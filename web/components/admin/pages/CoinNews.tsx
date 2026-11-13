"use client";

import { Bot, Clock3, ExternalLink, EyeOff, Newspaper, RefreshCw, Rocket, Share2, Undo2 } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { AdminCard, AdminPage, EmptyState, Feedback, inputClass, smallButton, useAdminAction, useAdminQuery } from "@/components/admin/kit";
import { CoinToken } from "@/components/forum/Visuals";
import { Button } from "@/components/ui";
import { dateTime } from "@/lib/admin";
import { timeAgo } from "@/lib/forum";

interface NewsItem {
  id: string;
  source: string;
  source_name: string;
  kind: "listing" | "news";
  title: string;
  summary: string;
  url: string;
  symbols: string[];
  published_at: string;
  status: "new" | "drafted" | "shared" | "dismissed";
  topic_number: number | null;
}

interface SourceState {
  key: string;
  name: string;
  enabled: boolean;
  ok: boolean | null;
  count: number;
  error: string | null;
}

interface NewsData {
  items: NewsItem[];
  new_counts: { listing: number; news: number };
  pending_drafts: number;
  auto_draft: boolean;
  last_run: string | null;
  interval_s: number;
  sources: SourceState[];
}

type Tab = "listing" | "all" | "drafted" | "shared" | "dismissed";

function shortTitle(text: string): string {
  if (text.length <= 120) return text;
  return `${text.slice(0, 118).replace(/\s+\S*$/, "")}…`;
}

function defaultBody(item: NewsItem): string {
  const parts = [`“${item.title}”`];
  if (item.summary && item.summary !== item.title) parts.push(item.summary);
  parts.push(
    `Kaynak: ${item.source_name}. Ayrıntılar için kaynak bağlantısına bakın. Bu paylaşım bilgilendirme amaçlıdır; yatırım tavsiyesi değildir.`,
  );
  return parts.join("\n\n");
}

function ShareForm({ item, onShared }: { item: NewsItem; onShared: (number: number) => void }) {
  const api = useApi();
  const action = useAdminAction();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const result = await action.run(() =>
      api.post<{ number: number }>(`/admin/v1/news/${item.id}/share`, {
        category: data.get("category"),
        title: String(data.get("title") ?? "").trim(),
        body: String(data.get("body") ?? ""),
        coin_symbol: String(data.get("coin") ?? "").trim() || null,
        pinned: data.get("pinned") === "on",
      }),
    );
    if (result) onShared(result.number);
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="mt-4 space-y-3 rounded-2xl border border-accent-text/30 bg-surface p-4" data-testid="share-form">
      <p className="text-sm text-muted">Forumda ekip konusu olarak hemen yayımlanır; kaynak bağlantısı konuya eklenir. Metni düzenleyebilirsiniz.</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-sm text-fg">
          Kategori
          <select name="category" defaultValue={item.kind === "listing" ? "yeni-coin" : "haber"} className={`mt-1 ${inputClass}`}>
            <option value="yeni-coin">Yeni coinler</option>
            <option value="haber">Haberler</option>
          </select>
        </label>
        <label className="text-sm text-fg">
          Coin
          <input name="coin" maxLength={16} defaultValue={item.symbols[0] ?? ""} className={`mt-1 ${inputClass}`} />
        </label>
        <label className="flex items-center gap-2 self-end pb-2 text-sm text-fg">
          <input type="checkbox" name="pinned" className="h-4 w-4" /> Üstte sabitle
        </label>
      </div>
      <label className="block text-sm text-fg">
        Başlık
        <input name="title" required minLength={5} maxLength={120} defaultValue={shortTitle(item.title)} className={`mt-1 ${inputClass}`} />
      </label>
      <label className="block text-sm text-fg">
        Metin
        <textarea name="body" required minLength={10} maxLength={5000} rows={5} defaultValue={defaultBody(item)} className={`mt-1 ${inputClass}`} />
      </label>
      <Button type="submit" size="sm" disabled={action.pending}>
        <Share2 aria-hidden="true" className="h-4 w-4" /> Forumda paylaş
      </Button>
      <Feedback error={action.error} />
    </form>
  );
}

function NewsCard({ item, onChanged }: { item: NewsItem; onChanged: (note?: string) => void }) {
  const api = useApi();
  const action = useAdminAction();
  const [sharing, setSharing] = useState(false);
  const listing = item.kind === "listing";

  async function setStatus(status: "new" | "dismissed") {
    const ok = await action.run(() => api.post(`/admin/v1/news/${item.id}/status`, { status }));
    if (ok) onChanged(status === "dismissed" ? "Haber gizlendi" : "Haber geri alındı");
  }

  return (
    <li className="card-lift rounded-3xl border border-border bg-surface p-5 shadow-sm" data-testid={`news-${item.id.slice(0, 8)}`}>
      <div className="flex gap-4">
        {item.symbols[0] ? (
          <CoinToken symbol={item.symbols[0]} />
        ) : (
          <span
            aria-hidden="true"
            className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-gradient-to-br text-white ${listing ? "from-[#be123c] to-[#a21caf]" : "from-[#047857] to-[#0f766e]"}`}
          >
            {listing ? <Rocket className="h-5 w-5" /> : <Newspaper className="h-5 w-5" />}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 text-xs">
            <span
              className={`rounded-full px-2 py-0.5 font-semibold text-white ${listing ? "bg-gradient-to-r from-[#be123c] to-[#a21caf]" : "bg-gradient-to-r from-[#047857] to-[#0f766e]"}`}
            >
              {listing ? "Yeni coin" : "Haber"}
            </span>
            <span className="font-semibold text-fg">{item.source_name}</span>
            <span className="text-muted" title={dateTime(item.published_at)}>
              {timeAgo(item.published_at)}
            </span>
            {item.symbols.slice(1).map((s) => (
              <span key={s} className="rounded-full border border-border bg-surface-2 px-2 py-0.5 font-mono text-fg">
                {s}
              </span>
            ))}
          </p>
          <h3 className="mt-2 font-semibold leading-snug text-fg">{item.title}</h3>
          {item.summary && item.summary !== item.title ? <p className="mt-1 text-sm leading-relaxed text-muted">{item.summary}</p> : null}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <a href={item.url} target="_blank" rel="noopener noreferrer nofollow" className={smallButton}>
              <ExternalLink aria-hidden="true" className="h-3.5 w-3.5" /> Kaynakta aç
            </a>
            {item.status === "new" ? (
              <>
                <Button type="button" size="sm" onClick={() => setSharing((v) => !v)} aria-expanded={sharing} aria-label={`${shortTitle(item.title)} paylaş`}>
                  <Share2 aria-hidden="true" className="h-4 w-4" /> Paylaş
                </Button>
                <button type="button" className={smallButton} onClick={() => void setStatus("dismissed")} disabled={action.pending}>
                  <EyeOff aria-hidden="true" className="h-3.5 w-3.5" /> Gizle
                </button>
              </>
            ) : null}
            {item.status === "dismissed" ? (
              <button type="button" className={smallButton} onClick={() => void setStatus("new")} disabled={action.pending}>
                <Undo2 aria-hidden="true" className="h-3.5 w-3.5" /> Geri al
              </button>
            ) : null}
            {item.status === "drafted" && item.topic_number ? (
              <Link href="/yonetim/forum" className="inline-flex items-center gap-1.5 text-sm font-semibold text-warn-fg underline-offset-4 hover:underline">
                <Clock3 aria-hidden="true" className="h-3.5 w-3.5" /> Otomatik taslak onay bekliyor: konu #{item.topic_number}
              </Link>
            ) : null}
            {item.status === "shared" && item.topic_number ? (
              <a href={`/forum/${item.topic_number}`} target="_blank" rel="noopener noreferrer" className="text-sm font-semibold text-success-fg underline-offset-4 hover:underline">
                Forumda: konu #{item.topic_number}
              </a>
            ) : null}
          </div>
          <Feedback error={action.error} />
          {sharing ? <ShareForm item={item} onShared={(number) => onChanged(`Paylaşıldı: forum konusu #${number}`)} /> : null}
        </div>
      </div>
    </li>
  );
}

/** Yeni coin haberinden otomatik konu taslağı: taslak forum onay kuyruğuna düşer. */
function AutoDraft({ data, onSaved }: { data: NewsData; onSaved: () => void }) {
  const api = useApi();
  const action = useAdminAction();

  async function toggle(enabled: boolean) {
    const ok = await action.run(
      () => api.put("/admin/v1/news/auto-draft", { enabled }),
      enabled ? "Otomatik taslak açıldı" : "Otomatik taslak kapatıldı",
    );
    if (ok) onSaved();
  }

  return (
    <AdminCard title="Otomatik konu taslağı" description="Yeni coin haberi gelince forumda konu taslağı hazırlanır ve onayınıza düşer.">
      <div className="space-y-3 text-sm" data-testid="auto-draft">
        <label className="flex items-center gap-2 font-medium text-fg">
          <input type="checkbox" checked={data.auto_draft} disabled={action.pending} onChange={(e) => void toggle(e.target.checked)} className="h-4 w-4" />
          Yeni coin haberlerinden otomatik taslak oluştur
        </label>
        <ul className="list-disc space-y-1 pl-5 text-muted">
          <li>Yalnızca coin sembolü belli, son 48 saatte yayımlanmış listeleme haberleri.</li>
          <li>Aynı coin için son 24 saatte konu varsa yeni taslak açılmaz.</li>
          <li>Taslak siz onaylamadan sitede görünmez; onaydan önce düzenleyebilirsiniz.</li>
        </ul>
        <p className="flex items-center gap-2 text-fg">
          <Bot aria-hidden="true" className="h-4 w-4 text-accent-text" />
          {data.pending_drafts ? (
            <Link href="/yonetim/forum" className="font-semibold underline-offset-4 hover:underline">
              {data.pending_drafts} taslak onay bekliyor → Forum onayları
            </Link>
          ) : (
            "Onay bekleyen taslak yok"
          )}
        </p>
        <Feedback error={action.error} message={action.message} />
      </div>
    </AdminCard>
  );
}

function Sources({ data, onSaved }: { data: NewsData; onSaved: () => void }) {
  const api = useApi();
  const action = useAdminAction();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const enabled = new FormData(event.currentTarget).getAll("source").map(String);
    const ok = await action.run(() => api.put("/admin/v1/news/sources", { enabled }), "Kaynaklar kaydedildi");
    if (ok) onSaved();
  }

  return (
    <AdminCard title="Kaynaklar" description="Yalnızca herkese açık kaynaklar; kimsenin hesabına erişilmez, başlık ve kısa özet saklanır.">
      <form onSubmit={(e) => void submit(e)} className="space-y-3" data-testid="news-sources">
        <ul className="space-y-2">
          {data.sources.map((s) => (
            <li key={s.key} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-bg/60 px-3 py-2">
              <label className="flex items-center gap-2 text-sm font-medium text-fg">
                <input type="checkbox" name="source" value={s.key} defaultChecked={s.enabled} className="h-4 w-4" /> {s.name}
              </label>
              <span className={`text-xs ${s.ok === false ? "text-danger-fg" : "text-muted"}`}>
                {s.ok === null ? "Henüz çekilmedi" : s.ok ? `Çalışıyor · son turda ${s.count} kayıt` : s.error}
              </span>
            </li>
          ))}
        </ul>
        <Button type="submit" size="sm" variant="secondary" disabled={action.pending}>
          Kaynakları kaydet
        </Button>
        <Feedback error={action.error} message={action.message} />
      </form>
    </AdminCard>
  );
}

export function CoinNews() {
  const api = useApi();
  const [tab, setTab] = useState<Tab>("listing");
  const [query, setQuery] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const params = {
    listing: "kind=listing&status=new",
    all: "status=new",
    drafted: "status=drafted",
    shared: "status=shared",
    dismissed: "status=dismissed",
  }[tab];
  const view = useAdminQuery<NewsData>(`/admin/v1/news?${params}${query ? `&q=${encodeURIComponent(query)}` : ""}`);
  const refresh = useAdminAction();
  const data = view.data;

  async function onRefresh() {
    setNote(null);
    const result = await refresh.run(() => api.post<{ added: number; drafted: number }>("/admin/v1/news/refresh"));
    if (result) {
      const drafted = result.drafted ? `, ${result.drafted} otomatik taslak onaya düştü` : "";
      setNote(result.added ? `${result.added} yeni haber eklendi${drafted}` : "Yeni haber yok");
      view.reload();
    }
  }

  const tabs: [Tab, string][] = [
    ["listing", `Yeni coinler${data ? ` (${data.new_counts.listing})` : ""}`],
    ["all", `Tüm yeni haberler${data ? ` (${data.new_counts.listing + data.new_counts.news})` : ""}`],
    ["drafted", `Onay bekleyen taslaklar${data ? ` (${data.pending_drafts})` : ""}`],
    ["shared", "Paylaşılanlar"],
    ["dismissed", "Gizlenenler"],
  ];

  return (
    <AdminPage
      eyebrow="Topluluk"
      title="Coin haberleri"
      lead="Yeni listelenen coinler ve güncel kripto haberleri herkese açık kaynaklardan düzenli çekilir. Beğendiğinizi “Paylaş” ile foruma ekleyin."
      actions={
        <Button type="button" onClick={() => void onRefresh()} disabled={refresh.pending}>
          <RefreshCw aria-hidden="true" className={`h-4 w-4 ${refresh.pending ? "animate-spin" : ""}`} /> Şimdi yenile
        </Button>
      }
    >
      <p className="text-sm text-muted" data-testid="news-last-run">
        {data?.last_run ? `Son çekim: ${dateTime(data.last_run)}` : "Henüz çekilmedi"} ·{" "}
        {data && data.interval_s > 0 ? `otomatik: her ${Math.round(data.interval_s / 60)} dakikada` : "otomatik çekme bu ortamda kapalı"}
      </p>
      <Feedback error={refresh.error ?? view.error} message={note} />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div role="tablist" aria-label="Haber listesi" className="flex flex-wrap gap-2">
              {tabs.map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={tab === key}
                  onClick={() => setTab(key)}
                  className={`rounded-full border px-4 py-2 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-accent-text ${
                    tab === key ? "border-transparent bg-brand text-white shadow-glow" : "border-border bg-surface text-fg hover:bg-surface-2"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <form
              role="search"
              onSubmit={(e) => {
                e.preventDefault();
                setQuery(String(new FormData(e.currentTarget).get("q") ?? "").trim());
              }}
              className="flex gap-2"
            >
              <label htmlFor="haber-ara" className="visually-hidden">
                Haberlerde ara
              </label>
              <input id="haber-ara" name="q" maxLength={80} placeholder="Coin ya da kelime" className={`${inputClass} w-48`} />
              <Button type="submit" size="sm" variant="secondary">
                Ara
              </Button>
            </form>
          </div>
          <div role="tabpanel" aria-label={tabs.find(([k]) => k === tab)?.[1]}>
            {data && data.items.length === 0 ? (
              <EmptyState icon={Newspaper} title="Bu listede haber yok">
                “Şimdi yenile” ile kaynakları hemen kontrol edebilirsiniz.
              </EmptyState>
            ) : null}
            <ul className="space-y-3">
              {data?.items.map((item) => (
                <NewsCard
                  key={item.id}
                  item={item}
                  onChanged={(text) => {
                    if (text) setNote(text);
                    view.reload();
                  }}
                />
              ))}
            </ul>
          </div>
        </div>
        {data ? (
          <div className="space-y-6">
            <AutoDraft data={data} onSaved={view.reload} />
            <Sources data={data} onSaved={view.reload} />
          </div>
        ) : null}
      </div>
    </AdminPage>
  );
}
