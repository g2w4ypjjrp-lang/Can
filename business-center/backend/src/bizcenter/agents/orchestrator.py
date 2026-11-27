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

CEO_ROLE = """CEO Agent. Kullanıcının komutunu anla ve işi uzman ajanlara dağıt.
- Yalnızca listedeki ajan kodlarını kullan. En fazla {max_steps} adım planla; gereksiz adım ekleme.
- Adımlar sırayla çalışır; her ajan önceki adımların çıktısını görür.
- İçerik, tasarım, SEO veya finans üreten planların sonuna uygun kalite kontrol ajanını (qc_*) ekle.
- Platformlara yazma (yayın, fiyat, silme, iade, reklam) hiçbir ajanın yetkisinde değildir; bunlar
  onaya sunulacak öneri olarak kalır."""


class BudgetExceeded(Exception):
    pass


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
            " returning id, organization_id, command, title", task_id)
        if not rows:
            log.info("task %s not queued; skipping", task_id)
            return
        task = rows[0]
        spent = [Decimal(0)]
        step_id: UUID | None = None
        try:
            agents = {a["code"]: a for a in await self._exec(
                "select id, code, name, description from agents where organization_id=%s and enabled",
                task["organization_id"])}
            ceo = agents.get("ceo")
            if ceo is None:
                raise LLMError("CEO Agent devre dışı")
            roster = {c: a for c, a in agents.items() if c in SPECS}
            await self._exec("update tasks set assigned_agent_id=%s where id=%s", ceo["id"], task_id)

            # 1) Plan
            roster_txt = "\n".join(f"- {c}: {a['description']}" for c, a in roster.items())
            plan_res = await self._call(
                task, ceo, spent, effort="high", schema=PLAN_SCHEMA,
                system=f"{COMMON}\n\nRolün: {CEO_ROLE.format(max_steps=MAX_STEPS)}\n\nAjanlar:\n{roster_txt}",
                user=_untrusted("user_command", task["command"]))
            plan = plan_res.data or {}
            steps = [s for s in plan.get("steps", []) if s.get("agent_code") in roster][:MAX_STEPS]
            if not steps:
                raise LLMError("CEO geçerli bir plan oluşturamadı")
            for i, s in enumerate(steps, 1):
                await self._exec(
                    "insert into task_steps(task_id, position, agent_id, description) values (%s,%s,%s,%s)",
                    task_id, i, roster[s["agent_code"]]["id"], s["instruction"][:4000])

            # 2) Uzmanlar sırayla
            outputs: list[tuple[str, str]] = []
            for i, s in enumerate(steps, 1):
                if await self._status(task_id) == "cancelled":
                    await self._exec("update task_steps set status='skipped' where task_id=%s and status='pending'",
                                     task_id)
                    return
                agent, spec = roster[s["agent_code"]], SPECS[s["agent_code"]]
                step_id = (await self._exec(
                    "update task_steps set status='running', updated_at=now() where task_id=%s and position=%s"
                    " returning id", task_id, i))[0]["id"]
                await self._exec("update tasks set assigned_agent_id=%s where id=%s", agent["id"], task_id)
                context = "\n\n".join(_untrusted(f"step_{n}:{name}", out) for n, (name, out) in enumerate(outputs, 1))
                res = await self._call(
                    task, agent, spent, system=spec.system, web_search=spec.web_search, effort="medium",
                    user=f"{_untrusted('user_command', task['command'])}\n\n"
                         f"Önceki adımların çıktıları:\n{context or '(yok)'}\n\nSenin görevin: {s['instruction']}")
                outputs.append((agent["name"], res.text))
                await self._exec(
                    "update task_steps set status='done', output=%s, updated_at=now() where id=%s",
                    Jsonb({"text": res.text, "sources": res.sources, "cost_usd": str(res.cost_usd)}), step_id)
                step_id = None

            # 3) CEO birleşik rapor
            report = await self._call(
                task, ceo, spent, effort="medium", system=f"{COMMON}\n\nRolün: CEO Agent. Ekibin çıktılarını "
                "kullanıcıya tek, kısa ve uygulanabilir bir rapor olarak birleştir: Özet, Bulgular, "
                "Onaya sunulacak öneriler, Eksik veriler ve sonraki adımlar.",
                user=_untrusted("user_command", task["command"]) + "\n\n" + "\n\n".join(
                    _untrusted(name, out) for name, out in outputs))
            await self._exec(
                "update tasks set status='completed', completed_at=now(), assigned_agent_id=%s, result=%s"
                " where id=%s and status='running'",
                ceo["id"], Jsonb({"plan_summary": plan.get("summary", ""), "report": report.text,
                                  "total_cost_usd": str(spent[0])}), task_id)
        except BudgetExceeded:
            await self._fail(task_id, step_id, f"Görev bütçesi aşıldı (üst sınır {self.max_cost} USD)", spent)
        except LLMError as exc:
            await self._fail(task_id, step_id, str(exc), spent)
        except Exception:
            log.exception("task %s crashed", task_id)
            await self._fail(task_id, step_id, "Beklenmeyen sistem hatası", spent)

    async def _fail(self, task_id: UUID, step_id: UUID | None, msg: str, spent: list[Decimal]) -> None:
        if step_id:
            await self._exec("update task_steps set status='failed', updated_at=now() where id=%s", step_id)
        await self._exec("update task_steps set status='skipped' where task_id=%s and status='pending'", task_id)
        await self._exec(
            "update tasks set status='failed', error=%s, result=%s, updated_at=now()"
            " where id=%s and status in ('queued','running')",
            msg, Jsonb({"total_cost_usd": str(spent[0])}), task_id)


