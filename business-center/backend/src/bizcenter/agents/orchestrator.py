"""CEO Agent orkestrasyonu: plan -> uzman ajanlar -> kalite kontrol -> birleşik rapor.

Çalışan (worker) tarafında, servis bağlantısıyla çalışır. Her model çağrısı `agent_runs`
tablosuna maliyetiyle kaydedilir; görev bütçesi aşılırsa görev durdurulur.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from ..db import Database
from .llm import LLM, LLMError, LLMResult
from .registry import COMMON, SPECS

log = logging.getLogger("bizcenter.orchestrator")

MAX_STEPS = 8

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "steps"],
    "properties": {
        "summary": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["agent_code", "instruction"],
                "properties": {"agent_code": {"type": "string"}, "instruction": {"type": "string"}},
            },
        },
    },
}

QC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "issues", "needs_human_review", "report"],
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
        "issues": {"type": "array", "items": {"type": "string"}},
        "needs_human_review": {"type": "boolean"},
        "report": {"type": "string"},
    },
}
MAX_REVISIONS = 1

CEO_ROLE = """CEO Agent. Kullanıcının komutunu anla ve işi uzman ajanlara dağıt.
- Yalnızca listedeki ajan kodlarını kullan. En fazla {max_steps} adım planla; gereksiz adım ekleme.
- Adımlar sırayla çalışır; her ajan önceki adımların çıktısını görür.
- İçerik, tasarım, SEO veya finans üreten planların sonuna uygun kalite kontrol ajanını (qc_*) ekle.
- Platformlara yazma (yayın, fiyat, silme, iade, reklam) hiçbir ajanın yetkisinde değildir; bunlar
  onaya sunulacak öneri olarak kalır."""


class BudgetExceeded(Exception):
    pass


PROFILE_FIELDS = {
    "brand_name": "Marka", "language": "İçerik dili", "youtube_channel_url": "YouTube kanalı",
    "youtube_niche": "YouTube nişi", "youtube_audience": "YouTube hedef kitlesi",
    "etsy_shop_name": "Etsy mağazası", "etsy_shop_url": "Etsy mağaza adresi", "etsy_niche": "Etsy nişi",
    "etsy_products": "Ürün tipleri", "price_range": "Fiyat aralığı", "currency": "Para birimi",
    "target_markets": "Hedef pazarlar", "goals": "Hedefler", "tone": "Marka dili / ton", "avoid": "Kaçınılacaklar",
}


def profile_block(profile: dict[str, Any] | None) -> str:
    """İşletme profilini sistem talimatına eklenecek blok olarak verir (yoksa ajan bunu bilir)."""
    if not profile:
        return ("\n\n<business_profile>Henüz doldurulmadı. Genel varsayımlar yap ve bunu belirt; "
                "kullanıcıya profili doldurmasını öner.</business_profile>")
    lines = [f"{label}: {str(profile[k]).strip()[:500]}" for k, label in PROFILE_FIELDS.items()
             if str(profile.get(k) or "").strip()]
    body = "\n".join(lines).replace("</business_profile>", "")
    return f"\n\n<business_profile>\n{body}\n</business_profile>"


def _untrusted(label: str, text: str) -> str:
    safe = text.replace("</untrusted_data>", "</untrusted_data_>")
    return f'<untrusted_data source="{label}">\n{safe}\n</untrusted_data>'


class Orchestrator:
    def __init__(self, db: Database, llm: LLM, model: str, max_task_cost_usd: Decimal) -> None:
        self.db = db
        self.llm = llm
        self.model = model
        self.max_cost = max_task_cost_usd

    async def _exec(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        async with self.db.pool.connection() as conn:
            cur = await conn.execute(sql, args)
            rows = await cur.fetchall() if cur.description else []
            await conn.commit()
            return rows

    async def _status(self, task_id: UUID) -> str | None:
        rows = await self._exec("select status from tasks where id = %s", task_id)
        return rows[0]["status"] if rows else None

    async def _call(self, task: dict[str, Any], agent: dict[str, Any], spent: list[Decimal],
                    **kw: Any) -> LLMResult:
        """Bir ajan çağrısı: agent_runs kaydı + bütçe kontrolü."""
        if spent[0] >= self.max_cost:
            raise BudgetExceeded
        run = (await self._exec(
            "insert into agent_runs(organization_id, agent_id, task_id, status, model)"
            " values (%s,%s,%s,'running',%s) returning id",
            task["organization_id"], agent["id"], task["id"], self.model))[0]["id"]
        try:
            res = await self.llm.complete(**kw)
        except Exception as exc:
            msg = str(exc) if isinstance(exc, LLMError) else "Beklenmeyen hata"
            await self._exec("update agent_runs set status='failed', error=%s, finished_at=now() where id=%s",
                             msg, run)
            raise
        spent[0] += res.cost_usd
        await self._exec(
            "update agent_runs set status='succeeded', model=%s, input_tokens=%s, output_tokens=%s,"
            " cost_usd=%s, finished_at=now() where id=%s",
            res.model, res.input_tokens, res.output_tokens, res.cost_usd, run)
        if spent[0] > self.max_cost:
            raise BudgetExceeded
        return res

    async def run(self, task_id: UUID) -> None:
        rows = await self._exec(
            "update tasks set status='running', updated_at=now() where id=%s and status='queued'"
            " returning id, organization_id, command, title, created_by, result", task_id)
        if not rows:
            log.info("task %s not queued; skipping", task_id)
            return
        task = rows[0]
        prof = await self._exec("select value from system_settings where organization_id=%s and key='business_profile'",
                                task["organization_id"])
        task["profile"] = profile_block(prof[0]["value"] if prof else None)
        spent = [Decimal(0)]
        try:
            agents = {a["code"]: a for a in await self._exec(
                "select id, code, name, description from agents where organization_id=%s and enabled",
                task["organization_id"])}
            ceo = agents.get("ceo")
            if ceo is None:
                raise LLMError("CEO Agent devre dışı")
            roster = {c: a for c, a in agents.items() if c in SPECS}
            await self._exec("update tasks set assigned_agent_id=%s where id=%s", ceo["id"], task_id)

            direct = (task.get("result") or {}).get("direct_agent")
            if direct:
                if direct not in roster:
                    raise LLMError("Seçilen ajan kullanılamıyor")
                plan: dict[str, Any] = {"summary": "Doğrudan atanan görev",
                                        "steps": [{"agent_code": direct, "instruction": task["command"]}]}
                await self._run_steps(task, plan, roster, ceo, spent, report=False)
                return
            # 1) Plan
            roster_txt = "\n".join(f"- {c}: {a['description']}" for c, a in roster.items())
            plan_res = await self._call(
                task, ceo, spent, effort="high", schema=PLAN_SCHEMA,
                system=f"{COMMON}\n\nRolün: {CEO_ROLE.format(max_steps=MAX_STEPS)}\n\nAjanlar:\n{roster_txt}{task['profile']}",
                user=_untrusted("user_command", task["command"]))
            plan = plan_res.data or {}
            await self._run_steps(task, plan, roster, ceo, spent, report=True)
        except BudgetExceeded:
            await self._fail(task_id, f"Görev bütçesi aşıldı (üst sınır {self.max_cost} USD)", spent)
        except LLMError as exc:
            await self._fail(task_id, str(exc), spent)
        except Exception:
            log.exception("task %s crashed", task_id)
            await self._fail(task_id, "Beklenmeyen sistem hatası", spent)

    async def _run_steps(self, task: dict[str, Any], plan: dict[str, Any], roster: dict[str, dict[str, Any]],
                         ceo: dict[str, Any], spent: list[Decimal], report: bool) -> None:
        task_id = task["id"]
        steps = [s for s in plan.get("steps", []) if s.get("agent_code") in roster][:MAX_STEPS]
        if not steps:
            raise LLMError("CEO geçerli bir plan oluşturamadı")
        for i, s in enumerate(steps, 1):
            await self._exec(
                "insert into task_steps(task_id, position, agent_id, description) values (%s,%s,%s,%s)",
                task_id, i, roster[s["agent_code"]]["id"], s["instruction"][:4000])

        # 2) Uzmanlar sırayla; qc_* adımları önceki üretimi denetler, gerekirse düzeltme ister.
        outputs: list[tuple[str, str]] = []
        last_producer: tuple[dict[str, Any], int, str] | None = None  # (ajan, outputs sırası, talimat)
        qc_results: list[dict[str, Any]] = []
        for i, s in enumerate(steps, 1):
            if await self._status(task_id) == "cancelled":
                await self._exec("update task_steps set status='skipped' where task_id=%s and status='pending'",
                                 task_id)
                return
            code = s["agent_code"]
            agent, spec = roster[code], SPECS[code]
            step_id = (await self._exec(
                "update task_steps set status='running', updated_at=now() where task_id=%s and position=%s"
                " returning id", task_id, i))[0]["id"]
            is_qc = code.startswith("qc_")
            await self._exec("update tasks set assigned_agent_id=%s, status=%s where id=%s and status not in"
                             " ('cancelled')", agent["id"], "waiting_qc" if is_qc else "running", task_id)
            if not is_qc:
                res = await self._produce(task, agent, spec, s["instruction"], outputs, spent)
                outputs.append((agent["name"], res.text))
                last_producer = (agent, len(outputs) - 1, s["instruction"])
                out = {"text": res.text, "sources": res.sources, "cost_usd": str(res.cost_usd)}
            else:
                verdict, revisions = await self._qc(task, agent, spec, s["instruction"], outputs, spent), 0
                while verdict["verdict"] == "fail" and last_producer and revisions < MAX_REVISIONS:
                    revisions += 1
                    p_agent, p_idx, p_instr = last_producer
                    fix = (f"{p_instr}\n\nKalite kontrol bu sorunları buldu, düzelterek çıktını YENİDEN yaz:\n- "
                           + "\n- ".join(verdict["issues"]))
                    res = await self._produce(task, p_agent, SPECS[p_agent["code"]], fix, outputs[:p_idx], spent)
                    outputs[p_idx] = (p_agent["name"], res.text)
                    verdict = await self._qc(task, agent, spec, s["instruction"], outputs, spent)
                verdict["revisions"] = revisions
                qc_results.append({"agent": agent["name"], **verdict})
                outputs.append((agent["name"], verdict["report"]))
                out = {"text": verdict["report"], "sources": [], "qc": verdict}
                await self._exec("update tasks set status='running' where id=%s and status='waiting_qc'", task_id)
            await self._exec("update task_steps set status=%s, output=%s, updated_at=now() where id=%s",
                             "failed" if is_qc and out["qc"]["verdict"] == "fail" else "done", Jsonb(out), step_id)
            step_id = None

        # 3) CEO birleşik rapor (doğrudan atanan görevde ajanın çıktısı rapordur)
        if not report:
            final_text, final_agent = outputs[0][1] if outputs else "", roster[steps[0]["agent_code"]]["id"]
        else:
            final_agent = ceo["id"]
            final_text = (await self._call(
            task, ceo, spent, effort="medium", system=f"{COMMON}\n\nRolün: CEO Agent. Ekibin çıktılarını "
            "kullanıcıya tek, kısa ve uygulanabilir bir rapor olarak birleştir: Özet, Bulgular, "
            "Onaya sunulacak öneriler, Eksik veriler ve sonraki adımlar." + task["profile"],
            user=_untrusted("user_command", task["command"]) + "\n\n" + "\n\n".join(
                _untrusted(name, out) for name, out in outputs))).text
        await self._exec(
            "update tasks set status='completed', completed_at=now(), assigned_agent_id=%s, result=%s"
            " where id=%s and status in ('running','waiting_qc')",
            final_agent, Jsonb({"plan_summary": plan.get("summary", ""), "report": final_text,
                              "total_cost_usd": str(spent[0]), "qc": qc_results,
                              "qc_passed": all(q["verdict"] == "pass" for q in qc_results),
                              "needs_human_review": any(q["needs_human_review"] for q in qc_results)}), task_id)
        review = any(q["needs_human_review"] for q in qc_results)
        await self._notify(task, "task_completed", f"Görev tamamlandı: {task['title']}",
                           "İnsan incelemesi gerekiyor." if review else "Rapor hazır.")

    async def _produce(self, task: dict[str, Any], agent: dict[str, Any], spec: Any, instruction: str,
                       outputs: list[tuple[str, str]], spent: list[Decimal]) -> LLMResult:
        context = "\n\n".join(_untrusted(f"step_{n}:{name}", out) for n, (name, out) in enumerate(outputs, 1))
        return await self._call(
            task, agent, spent, system=spec.system + task["profile"], web_search=spec.web_search, effort="medium",
            user=f"{_untrusted('user_command', task['command'])}\n\n"
                 f"Önceki adımların çıktıları:\n{context or '(yok)'}\n\nSenin görevin: {instruction}")

    async def _qc(self, task: dict[str, Any], agent: dict[str, Any], spec: Any, instruction: str,
                  outputs: list[tuple[str, str]], spent: list[Decimal]) -> dict[str, Any]:
        context = "\n\n".join(_untrusted(f"step_{n}:{name}", out) for n, (name, out) in enumerate(outputs, 1))
        res = await self._call(
            task, agent, spent, system=spec.system + task["profile"] + "\nSonucu şemaya göre ver: verdict (pass/fail), issues "
            "(somut sorunlar), needs_human_review (telif/marka/hukuki/finansal risk varsa true), report.",
            effort="medium", schema=QC_SCHEMA,
            user=f"{_untrusted('user_command', task['command'])}\n\nDenetlenecek çıktılar:\n{context or '(yok)'}"
                 f"\n\nDenetim görevin: {instruction}")
        data = res.data if isinstance(res.data, dict) else {}
        verdict = data.get("verdict") if data.get("verdict") in ("pass", "fail") else "fail"
        return {"verdict": verdict, "issues": [str(x) for x in data.get("issues", [])][:20],
                "needs_human_review": bool(data.get("needs_human_review")) or (
                    agent["code"] == "qc_copyright" and verdict == "fail"), "report": str(data.get("report", ""))}

    async def _notify(self, task: dict[str, Any], kind: str, title: str, body: str) -> None:
        await self._exec(
            "insert into notifications(organization_id, user_id, kind, title, body, link) values (%s,%s,%s,%s,%s,%s)",
            task["organization_id"], task.get("created_by"), kind, title[:200], body, f"/tasks/{task['id']}")

    async def _fail(self, task_id: UUID, msg: str, spent: list[Decimal]) -> None:
        await self._exec("update task_steps set status='failed', updated_at=now()"
                         " where task_id=%s and status='running'", task_id)
        await self._exec("update task_steps set status='skipped' where task_id=%s and status='pending'", task_id)
        rows = await self._exec(
            "update tasks set status='failed', error=%s, result=%s, updated_at=now()"
            " where id=%s and status in ('queued','running','waiting_qc')"
            " returning id, organization_id, title, created_by",
            msg, Jsonb({"total_cost_usd": str(spent[0])}), task_id)
        if rows:
            await self._notify(rows[0], "task_failed", f"Görev başarısız: {rows[0]['title']}", msg)



