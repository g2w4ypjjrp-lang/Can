"use client";

import { AlertTriangle, Bot, CheckCircle2, ExternalLink, MessagesSquare, Pencil, Pin, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import {
  AdminCard,
  AdminPage,
  EmptyState,
  Feedback,
  StatusPill,
  inputClass,
  smallButton,
  useAdminAction,
  useAdminQuery,
  type PillTone,
} from "@/components/admin/kit";
import { CATEGORY_META, CategoryChip, CoinToken } from "@/components/forum/Visuals";
import { Button } from "@/components/ui";
import { dateTime } from "@/lib/admin";
import type { ForumCategory } from "@/lib/forum";

interface QueueTopic {
  id: string;
  number: number;
  title: string;
  body: string;
  category: ForumCategory;
  coin_symbol: string | null;
  author_name: string;
  author_kind: "customer" | "team";
  flags: string[];
  created_at: string;
  source_name: string | null;
  source_url: string | null;
  customer_email: string | null;
  author_approved: number;
}

const AUTO_FLAG = "otomatik taslak";

interface QueueReply {
  id: string;
  body: string;
  author_name: string;
  flags: string[];
  created_at: string;
  number: number;
  topic_title: string;
  customer_email: string | null;
}

interface AdminTopic {
  id: string;
  number: number;
  title: string;
  category: ForumCategory;
  coin_symbol: string | null;
  author_name: string;
  author_kind: "customer" | "team";
  status: Status;
  pinned: boolean;
  locked: boolean;
  flags: string[];
  view_count: number;
  reply_count: number;
  moderation_note: string | null;
  created_at: string;
  published_at: string | null;
}

type Status = "pending" | "approved" | "rejected" | "hidden";

const STATUS: Record<Status, { label: string; tone: PillTone }> = {
  pending: { label: "Onay bekliyor", tone: "warn" },
  approved: { label: "Yayında", tone: "success" },
  rejected: { label: "Reddedildi", tone: "danger" },
  hidden: { label: "Gizli", tone: "neutral" },
};

function Flags({ flags }: { flags: string[] }) {
  if (!flags.length) return null;
  return (
    <span className="flex flex-wrap gap-1.5">
      {flags.map((flag) =>
        flag === AUTO_FLAG ? (
          <span key={flag} className="inline-flex items-center gap-1 rounded-full border border-info-border bg-info-bg px-2 py-0.5 text-xs font-semibold text-info-fg">
            <Bot aria-hidden="true" className="h-3 w-3" /> Otomatik taslak (yeni coin haberi)
          </span>
        ) : (
          <span key={flag} className="inline-flex items-center gap-1 rounded-full border border-warn-border bg-warn-bg px-2 py-0.5 text-xs font-semibold text-warn-fg">
            <AlertTriangle aria-hidden="true" className="h-3 w-3" /> {flag}
          </span>
        ),
      )}
    </span>
  );
}

/** Onay kartı (konu ya da yanıt): onayla, nedenli reddet, sil. */
function Decision({
  kind,
  id,
  label,
  onDone,
}: {
  kind: "topics" | "replies";
  id: string;
  label: string;
  onDone: (note: string) => void;
}) {
  const api = useApi();
  const action = useAdminAction();
  const [rejecting, setRejecting] = useState(false);

  async function act(name: "approve" | "reject" | "delete", note = "") {
    const ok = await action.run(() => api.post(`/admin/v1/forum/${kind}/${id}/moderate`, { action: name, note }));
    if (ok) onDone({ approve: "Onaylandı ve yayımlandı", reject: "Reddedildi", delete: "Silindi" }[name]);
  }

  async function reject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await act("reject", String(new FormData(event.currentTarget).get("note") ?? "").trim());
  }

  return (
    <div className="mt-4 space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" onClick={() => void act("approve")} disabled={action.pending} aria-label={`${label} onayla`}>
          <CheckCircle2 aria-hidden="true" className="h-4 w-4" /> Onayla
        </Button>
        <Button type="button" size="sm" variant="secondary" onClick={() => setRejecting((v) => !v)} aria-expanded={rejecting}>
          Reddet…
        </Button>
        <button type="button" className={smallButton} onClick={() => void act("delete")} disabled={action.pending} aria-label={`${label} sil`}>
          <Trash2 aria-hidden="true" className="h-3.5 w-3.5" /> Sil
        </button>
      </div>
      {rejecting ? (
        <form onSubmit={(e) => void reject(e)} className="flex flex-wrap items-end gap-2">
          <label className="min-w-60 flex-1 text-sm text-fg">
            Reddetme nedeni (müşteri görür)
            <input name="note" required minLength={3} maxLength={300} className={`mt-1 ${inputClass}`} />
          </label>
          <Button type="submit" size="sm" variant="danger" disabled={action.pending}>
            Reddet
          </Button>
        </form>
      ) : null}
      <Feedback error={action.error} />
    </div>
  );
}

/** Ekip taslağını onaylamadan önce düzenleme (müşteri metinleri düzenlenmez). */
function EditDraft({ topic, onSaved }: { topic: QueueTopic; onSaved: () => void }) {
  const api = useApi();
  const action = useAdminAction();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const ok = await action.run(() =>
      api.post(`/admin/v1/forum/topics/${topic.id}/edit`, {
        category: data.get("category"),
        title: String(data.get("title") ?? "").trim(),
        body: String(data.get("body") ?? ""),
        coin_symbol: String(data.get("coin") ?? "").trim() || null,
      }),
    );
    if (ok) onSaved();
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="mt-3 space-y-3 rounded-2xl border border-accent-text/30 bg-surface p-4" data-testid="edit-draft">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm text-fg">
          Kategori
          <select name="category" defaultValue={topic.category} className={`mt-1 ${inputClass}`}>
            {(Object.keys(CATEGORY_META) as ForumCategory[]).map((c) => (
              <option key={c} value={c}>
                {CATEGORY_META[c].label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm text-fg">
          Coin
          <input name="coin" maxLength={16} defaultValue={topic.coin_symbol ?? ""} className={`mt-1 ${inputClass}`} />
        </label>
      </div>
      <label className="block text-sm text-fg">
        Başlık
        <input name="title" required minLength={5} maxLength={120} defaultValue={topic.title} className={`mt-1 ${inputClass}`} />
      </label>
      <label className="block text-sm text-fg">
        Metin
        <textarea name="body" required minLength={10} maxLength={5000} rows={6} defaultValue={topic.body} className={`mt-1 ${inputClass}`} />
      </label>
      <Button type="submit" size="sm" disabled={action.pending}>
        Değişiklikleri kaydet
      </Button>
      <Feedback error={action.error} />
    </form>
  );
}

function QueueTopicCard({ topic: t, onDone }: { topic: QueueTopic; onDone: (note: string) => void }) {
  const [editing, setEditing] = useState(false);
  const team = t.author_kind === "team";
  return (
    <li className="rounded-2xl border border-border bg-bg/60 p-4" data-testid={`queue-topic-${t.number}`}>
      <div className="flex flex-wrap items-center gap-2">
        <CategoryChip category={t.category} />
        {t.coin_symbol ? <CoinToken symbol={t.coin_symbol} size="sm" /> : null}
        <Flags flags={t.flags} />
        <span className="text-xs text-muted">
          {team ? "Ekip konusu" : t.author_approved ? `${t.author_approved} yayımlanmış konusu var` : "İlk konusu"}
        </span>
      </div>
      <h3 className="mt-3 text-lg font-semibold text-fg">{t.title}</h3>
      <p className="mt-2 max-h-72 overflow-y-auto whitespace-pre-line break-words rounded-xl bg-surface px-3 py-2 text-sm leading-relaxed text-fg">
        {t.body}
      </p>
      <p className="mt-2 flex flex-wrap items-center gap-x-2 text-xs text-muted">
        <span>
          {t.author_name} · {team ? "yönetim" : (t.customer_email ?? "silinmiş müşteri")} · {dateTime(t.created_at)}
        </span>
        {t.source_url ? (
          <a href={t.source_url} target="_blank" rel="noopener noreferrer nofollow" className="inline-flex items-center gap-1 font-semibold text-accent-text underline-offset-4 hover:underline">
            Kaynak: {t.source_name ?? "haber"} <ExternalLink aria-hidden="true" className="h-3 w-3" />
          </a>
        ) : null}
      </p>
      {team ? (
        <button type="button" className={`${smallButton} mt-3`} onClick={() => setEditing((v) => !v)} aria-expanded={editing}>
          <Pencil aria-hidden="true" className="h-3.5 w-3.5" /> Düzenle
        </button>
      ) : null}
      {editing ? (
        <EditDraft
          topic={t}
          onSaved={() => {
            setEditing(false);
            onDone("Taslak güncellendi");
          }}
        />
      ) : null}
      <Decision kind="topics" id={t.id} label={`“${t.title}”`} onDone={onDone} />
    </li>
  );
}

function Queue({ onChanged }: { onChanged: () => void }) {
  const queue = useAdminQuery<{ topics: QueueTopic[]; replies: QueueReply[] }>("/admin/v1/forum/queue");
  const [note, setNote] = useState<string | null>(null);
  const done = (text: string) => {
    setNote(text);
    queue.reload();
    onChanged();
    window.dispatchEvent(new Event("ati:forum-moderated"));
  };
  const data = queue.data;
  return (
    <div className="space-y-6">
      <Feedback error={queue.error} message={note} />
      {data && !data.topics.length && !data.replies.length ? (
        <EmptyState icon={CheckCircle2} title="Onay bekleyen gönderi yok">
          Müşteriler konu ya da yanıt gönderdiğinde burada görünür.
        </EmptyState>
      ) : null}
      {data?.topics.length ? (
        <AdminCard title={`Bekleyen konular (${data.topics.length})`}>
          <ul className="space-y-4">
            {data.topics.map((t) => (
              <QueueTopicCard key={`${t.id}-${t.title}-${t.body.length}`} topic={t} onDone={done} />
            ))}
          </ul>
        </AdminCard>
      ) : null}
      {data?.replies.length ? (
        <AdminCard title={`Bekleyen yanıtlar (${data.replies.length})`}>
          <ul className="space-y-4">
            {data.replies.map((r) => (
              <li key={r.id} className="rounded-2xl border border-border bg-bg/60 p-4" data-testid="queue-reply">
                <p className="flex flex-wrap items-center gap-2 text-sm text-muted">
                  <a href={`/forum/${r.number}`} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-semibold text-fg underline-offset-4 hover:underline">
                    #{r.number} {r.topic_title} <ExternalLink aria-hidden="true" className="h-3.5 w-3.5" />
                  </a>
                  konusuna yanıt
                  <Flags flags={r.flags} />
                </p>
                <p className="mt-2 whitespace-pre-line break-words rounded-xl bg-surface px-3 py-2 text-sm leading-relaxed text-fg">{r.body}</p>
                <p className="mt-2 text-xs text-muted">
                  {r.author_name} · {r.customer_email ?? "silinmiş müşteri"} · {dateTime(r.created_at)}
                </p>
                <Decision kind="replies" id={r.id} label={`${r.author_name} yanıtını`} onDone={done} />
              </li>
            ))}
          </ul>
        </AdminCard>
      ) : null}
    </div>
  );
}

function TopicRow({ topic, onChanged }: { topic: AdminTopic; onChanged: () => void }) {
  const api = useApi();
  const action = useAdminAction();
  const [confirm, setConfirm] = useState(false);
  const act = async (name: string) => {
    const ok = await action.run(() => api.post(`/admin/v1/forum/topics/${topic.id}/moderate`, { action: name }));
    if (ok) onChanged();
  };
  const buttons: [string, string][] = [];
  if (topic.status === "approved") {
    buttons.push(["hide", "Gizle"], [topic.pinned ? "unpin" : "pin", topic.pinned ? "Sabitlemeyi kaldır" : "Sabitle"]);
    buttons.push([topic.locked ? "unlock" : "lock", topic.locked ? "Yanıtlara aç" : "Yanıtlara kapat"]);
  } else if (topic.status === "pending") {
    buttons.push(["approve", "Onayla"]);
  } else {
    buttons.push(["restore", "Yayına al"]);
  }
  return (
    <li className="rounded-2xl border border-border bg-bg/60 p-4" data-testid={`admin-topic-${topic.number}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2">
            <StatusPill tone={STATUS[topic.status].tone}>{STATUS[topic.status].label}</StatusPill>
            <CategoryChip category={topic.category} />
            {topic.pinned ? (
              <span className="inline-flex items-center gap-1 text-xs font-semibold text-accent-text">
                <Pin aria-hidden="true" className="h-3 w-3" /> Sabit
              </span>
            ) : null}
            {topic.author_kind === "team" ? <span className="text-xs font-semibold text-success-fg">Ekip</span> : null}
          </p>
          <p className="mt-2 font-semibold text-fg">
            {topic.status === "approved" ? (
              <a href={`/forum/${topic.number}`} target="_blank" rel="noopener noreferrer" className="underline-offset-4 hover:underline">
                #{topic.number} {topic.title}
              </a>
            ) : (
              <>
                #{topic.number} {topic.title}
              </>
            )}
          </p>
          <p className="mt-1 text-xs text-muted">
            {topic.author_name} · {dateTime(topic.published_at ?? topic.created_at)} · {topic.reply_count} yanıt · {topic.view_count} görüntüleme
            {topic.moderation_note ? ` · not: ${topic.moderation_note}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {buttons.map(([name, text]) => (
            <button key={name} type="button" className={smallButton} disabled={action.pending} onClick={() => void act(name)} aria-label={`#${topic.number} ${text}`}>
              {text}
            </button>
          ))}
          {confirm ? (
            <button type="button" className={`${smallButton} border-danger-border text-danger-fg`} onClick={() => void act("delete")} aria-label={`#${topic.number} kalıcı olarak sil`}>
              Evet, kalıcı sil
            </button>
          ) : (
            <button type="button" className={smallButton} onClick={() => setConfirm(true)} aria-label={`#${topic.number} sil`}>
              Sil
            </button>
          )}
        </div>
      </div>
      <Feedback error={action.error} />
    </li>
  );
}

function AllTopics({ version, onChanged }: { version: number; onChanged: () => void }) {
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const list = useAdminQuery<AdminTopic[]>(
    `/admin/v1/forum/topics?v=${version}${status ? `&status=${status}` : ""}${query ? `&q=${encodeURIComponent(query)}` : ""}`,
  );
  return (
    <AdminCard title="Bütün konular" description="Yayındaki konuları gizleyin, sabitleyin, yanıtlara kapatın ya da silin.">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(String(new FormData(e.currentTarget).get("q") ?? "").trim());
        }}
        className="mb-4 flex flex-wrap items-end gap-3"
        role="search"
      >
        <label className="text-sm text-fg">
          Durum
          <select value={status} onChange={(e) => setStatus(e.target.value)} className={`mt-1 ${inputClass} w-44`} data-testid="forum-status-filter">
            <option value="">Tümü</option>
            {(Object.keys(STATUS) as Status[]).map((s) => (
              <option key={s} value={s}>
                {STATUS[s].label}
              </option>
            ))}
          </select>
        </label>
        <label className="min-w-56 flex-1 text-sm text-fg">
          Başlık ya da yazar
          <input name="q" maxLength={80} className={`mt-1 ${inputClass}`} />
        </label>
        <Button type="submit" variant="secondary" size="sm">
          Ara
        </Button>
      </form>
      <Feedback error={list.error} />
      {list.data?.length === 0 ? <p className="text-sm text-muted">Konu yok.</p> : null}
      <ul className="space-y-3">
        {list.data?.map((t) => (
          <TopicRow
            key={t.id}
            topic={t}
            onChanged={() => {
              list.reload();
              onChanged();
              window.dispatchEvent(new Event("ati:forum-moderated"));
            }}
          />
        ))}
      </ul>
    </AdminCard>
  );
}

function TeamTopicForm({ onCreated }: { onCreated: () => void }) {
  const api = useApi();
  const action = useAdminAction();
  const [created, setCreated] = useState<number | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const result = await action.run(() =>
      api.post<{ number: number }>("/admin/v1/forum/topics", {
        category: data.get("category"),
        title: String(data.get("title") ?? "").trim(),
        body: String(data.get("body") ?? ""),
        coin_symbol: String(data.get("coin") ?? "").trim() || null,
        pinned: data.get("pinned") === "on",
      }),
    );
    if (result) {
      setCreated(result.number);
      form.reset();
      onCreated();
    }
  }

  return (
    <AdminCard title="Ekip konusu aç" description="Ekip adına açılan konu onaysız, hemen yayımlanır (duyuru, rehber, haber).">
      <form onSubmit={(e) => void submit(e)} className="space-y-3" data-testid="team-topic-form">
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="text-sm text-fg">
            Kategori
            <select name="category" defaultValue="haber" className={`mt-1 ${inputClass}`}>
              {(Object.keys(CATEGORY_META) as ForumCategory[]).map((c) => (
                <option key={c} value={c}>
                  {CATEGORY_META[c].label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm text-fg">
            Coin (isteğe bağlı)
            <input name="coin" maxLength={16} className={`mt-1 ${inputClass}`} />
          </label>
          <label className="flex items-center gap-2 self-end pb-2 text-sm text-fg">
            <input type="checkbox" name="pinned" className="h-4 w-4" /> Üstte sabitle
          </label>
        </div>
        <label className="block text-sm text-fg">
          Başlık
          <input name="title" required minLength={5} maxLength={120} className={`mt-1 ${inputClass}`} />
        </label>
        <label className="block text-sm text-fg">
          Metin
          <textarea name="body" required minLength={10} maxLength={5000} rows={6} className={`mt-1 ${inputClass}`} />
        </label>
        <Button type="submit" disabled={action.pending}>
          Yayımla
        </Button>
        <Feedback error={action.error} />
        {created ? (
          <p className="text-sm text-success-fg" role="status">
            Yayımlandı:{" "}
            <a href={`/forum/${created}`} target="_blank" rel="noopener noreferrer" className="font-semibold underline">
              Forum konusu #{created}
            </a>
          </p>
        ) : null}
      </form>
    </AdminCard>
  );
}

export function ForumModeration() {
  const [tab, setTab] = useState<"queue" | "all" | "team">("queue");
  const [version, setVersion] = useState(0);
  const bump = () => setVersion((v) => v + 1);
  const tabs: [typeof tab, string][] = [
    ["queue", "Onay kuyruğu"],
    ["all", "Bütün konular"],
    ["team", "Ekip konusu aç"],
  ];
  return (
    <AdminPage
      eyebrow="Topluluk"
      title="Forum onayları"
      lead="Müşterilerin açtığı konular ve yanıtlar burada onaylanmadan sitede görünmez. Kazanç vaadi, bağlantı ve iletişim bilgisi içeren gönderiler otomatik işaretlenir."
      actions={
        <a href="/forum" target="_blank" rel="noopener noreferrer" className={smallButton}>
          <MessagesSquare aria-hidden="true" className="h-3.5 w-3.5" /> Forumu aç
        </a>
      }
    >
      <div role="tablist" aria-label="Forum yönetimi" className="flex flex-wrap gap-2">
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
      <div role="tabpanel" aria-label={tabs.find(([k]) => k === tab)?.[1]}>
        {tab === "queue" ? <Queue onChanged={bump} /> : null}
        {tab === "all" ? <AllTopics version={version} onChanged={bump} /> : null}
        {tab === "team" ? <TeamTopicForm onCreated={bump} /> : null}
      </div>
    </AdminPage>
  );
}
