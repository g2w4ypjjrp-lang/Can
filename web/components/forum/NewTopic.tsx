"use client";

import { CheckCircle2, Clock3, EyeOff, Send, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { LoginPrompt } from "@/components/forum/LoginPrompt";
import { rememberName, rememberedName, useForumAccount, type MyPosts } from "@/components/forum/useForumAccount";
import { RankPill } from "@/components/forum/Ranks";
import { CATEGORY_META, CoinToken } from "@/components/forum/Visuals";
import { Button, Field, Notice, inputBase } from "@/components/ui";
import { NETWORK_ERROR } from "@/lib/api";
import type { ForumCategory } from "@/lib/forum";

const CUSTOMER_CATEGORIES: ForumCategory[] = ["genel", "strateji", "soru", "yeni-coin"];

const STATUS = {
  pending: { label: "Onay bekliyor", icon: Clock3, box: "border-warn-border bg-warn-bg text-warn-fg" },
  approved: { label: "Yayında", icon: CheckCircle2, box: "border-success-border bg-success-bg text-success-fg" },
  rejected: { label: "Reddedildi", icon: XCircle, box: "border-danger-border bg-danger-bg text-danger-fg" },
  hidden: { label: "Gizlendi", icon: EyeOff, box: "border-border bg-surface-2 text-fg" },
} as const;

function StatusTag({ status }: { status: keyof typeof STATUS }) {
  const { label, icon: Icon, box } = STATUS[status];
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-semibold ${box}`}>
      <Icon aria-hidden="true" className="h-3 w-3" /> {label}
    </span>
  );
}

function MyPostsList({ mine }: { mine: MyPosts }) {
  if (!mine.topics.length && !mine.replies.length) {
    return <p className="text-sm text-muted">Henüz gönderiniz yok.</p>;
  }
  return (
    <div className="space-y-6">
      {mine.topics.length ? (
        <ul className="space-y-2" aria-label="Konularım">
          {mine.topics.map((t) => (
            <li key={t.number} className="rounded-lg border border-border bg-surface-2 px-3.5 py-2.5" data-testid={`my-topic-${t.number}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                {t.status === "approved" ? (
                  <Link href={`/forum/${t.number}`} prefetch={false} className="font-semibold text-fg underline-offset-4 hover:underline">
                    {t.title}
                  </Link>
                ) : (
                  <span className="font-semibold text-fg">{t.title}</span>
                )}
                <StatusTag status={t.status} />
              </div>
              {t.moderation_note && t.status !== "approved" ? (
                <p className="mt-1 text-sm text-muted">Yönetici notu: {t.moderation_note}</p>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {mine.replies.length ? (
        <div>
          <h3 className="text-sm font-semibold text-fg">Yanıtlarım</h3>
          <ul className="mt-2 space-y-2" aria-label="Yanıtlarım">
            {mine.replies.map((r, i) => (
              <li key={i} className="rounded-lg border border-border bg-surface-2 px-3.5 py-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-muted">
                    “{r.title}” konusuna: <span className="text-fg">{r.body}</span>
                  </span>
                  <StatusTag status={r.status} />
                </div>
                {r.moderation_note && r.status !== "approved" ? <p className="mt-1 text-muted">Yönetici notu: {r.moderation_note}</p> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/** Yeni konu: yönetici onayına gider; kişi kendi gönderilerinin durumunu altta görür. */
export function NewTopic() {
  const api = useApi();
  const account = useForumAccount();
  const [category, setCategory] = useState<ForumCategory>("genel");
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [coin, setCoin] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const nickname = account.mine?.profile?.nickname ?? null;
  useEffect(() => setName(rememberedName()), []);
  useEffect(() => {
    if (nickname) setName(nickname);
  }, [nickname]);

  if (account.state === "loading") return <p className="text-sm text-muted">Yükleniyor…</p>;
  if (account.state === "anon") return <LoginPrompt next="/forum/yeni" action="Konu açmak" />;
  if (account.state === "error")
    return (
      <Notice tone="warning" title="Forum şu anda yüklenemedi" role="status">
        Lütfen biraz sonra tekrar deneyin.
      </Notice>
    );

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    setDone(null);
    try {
      const result = await api.post<{ message: string }>("/v1/forum/me/topics", {
        author_name: name.trim(),
        category,
        title: title.trim(),
        body,
        coin_symbol: coin.trim() || null,
      });
      rememberName(name.trim());
      setTitle("");
      setBody("");
      setCoin("");
      setDone(result.message);
      account.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : NETWORK_ERROR);
    } finally {
      setPending(false);
    }
  }

  const symbol = coin.trim().toUpperCase().replace(/USDT$/, "");

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_17rem]">
      <form onSubmit={(e) => void submit(e)} className="fb-box" data-testid="topic-form">
        <h2 className="fb-thead">Konu bilgileri</h2>
        <div className="space-y-4 p-4 text-[13px] sm:p-5">
        <fieldset>
          <legend className="text-sm font-medium text-fg">Kategori</legend>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {CUSTOMER_CATEGORIES.map((code) => {
              const meta = CATEGORY_META[code];
              const Icon = meta.icon;
              const active = category === code;
              return (
                <label
                  key={code}
                  className={`flex cursor-pointer items-center gap-2.5 rounded-lg border p-2.5 transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent-text ${
                    active ? "border-accent-text bg-surface-2" : "border-border hover:bg-surface-2"
                  }`}
                >
                  <input type="radio" name="kategori" value={code} checked={active} onChange={() => setCategory(code)} className="visually-hidden" />
                  <span aria-hidden="true" className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br text-white ${meta.gradient}`}>
                    <Icon className="h-4 w-4" />
                  </span>
                  <span>
                    <span className="block text-[13px] font-semibold text-fg">{meta.label}</span>
                    <span className="block text-xs text-muted">{meta.hint}</span>
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            id="konu-ad"
            label="Forumda görünecek adınız"
            hint={
              nickname
                ? "Forum adınız kalıcıdır (profil ve rütbeniz bu adla)."
                : "Gerçek adınızı yazmak zorunda değilsiniz. İlk gönderinizdeki ad kalıcı forum adınız olur."
            }
            readOnly={Boolean(nickname)}
            required
            minLength={2}
            maxLength={40}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Field
            id="konu-coin"
            label="İlgili coin"
            hint="Örn. BTC, SOL"
            maxLength={16}
            value={coin}
            onChange={(e) => setCoin(e.target.value)}
          />
        </div>
        <Field id="konu-baslik" label="Başlık" required minLength={5} maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} />
        <div>
          <label htmlFor="konu-metin" className="block text-sm font-medium text-fg">
            Metin
          </label>
          <textarea
            id="konu-metin"
            required
            minLength={10}
            maxLength={5000}
            rows={8}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            className={`mt-1.5 ${inputBase}`}
            aria-describedby="konu-metin-ipucu"
          />
          <p id="konu-metin-ipucu" className="mt-1 flex justify-between gap-3 text-xs text-muted">
            <span>Paragraf için boş satır bırakın. Bağlantılar tıklanabilir gösterilmez.</span>
            <span>{body.length} / 5000</span>
          </p>
        </div>
        {error ? (
          <Notice tone="danger" role="alert">
            {error}
          </Notice>
        ) : null}
        {done ? (
          <Notice tone="success" role="status">
            {done}
          </Notice>
        ) : null}
        <Button type="submit" size="sm" disabled={pending}>
          <Send aria-hidden="true" className="h-4 w-4" /> Onaya gönder
        </Button>
        </div>
      </form>

      <aside className="space-y-4 text-[13px]">
        {account.mine?.profile ? (
          <div className="fb-box" data-testid="my-profile">
            <p className="fb-thead">Forum profiliniz</p>
            <div className="p-3">
            <p className="mt-2 flex flex-wrap items-center gap-2 font-semibold text-fg">
              {account.mine.profile.nickname} <RankPill posts={account.mine.profile.posts} team={false} />
            </p>
            <p className="mt-1 text-xs text-muted">
              {account.mine.profile.posts} yayımlanmış mesaj · {account.mine.profile.likes} faydalı
            </p>
            <Link
              href={`/forum/uye/${encodeURIComponent(account.mine.profile.nickname)}`}
              className="mt-3 inline-block text-sm font-semibold text-accent-text underline-offset-4 hover:underline"
            >
              Profilim ve rütbem →
            </Link>
            </div>
          </div>
        ) : null}
        <div className="fb-box">
          <p className="fb-thead">Önizleme</p>
          <div className="flex items-start gap-3 p-3">
            {symbol.length >= 2 ? (
              <CoinToken symbol={symbol} />
            ) : (
              <span aria-hidden="true" className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-gradient-to-br text-white ${CATEGORY_META[category].gradient}`}>
                {(() => {
                  const Icon = CATEGORY_META[category].icon;
                  return <Icon className="h-5 w-5" />;
                })()}
              </span>
            )}
            <div className="min-w-0">
              <p className="break-words font-semibold text-fg">{title.trim() || "Konu başlığınız"}</p>
              <p className="text-xs text-muted">
                {CATEGORY_META[category].label} · {name.trim() || "Adınız"}
              </p>
            </div>
          </div>
        </div>
        <div className="fb-box">
          <p className="fb-thead">Yayın kuralları</p>
          <ul className="list-disc space-y-1 p-3 pl-7 text-muted">
            <li>Konular ekip onayından sonra yayımlanır (genelde aynı gün).</li>
            <li>Kazanç vaadi, reklam ve yönlendirme bağlantısı içeren gönderiler yayımlanmaz.</li>
            <li>Telefon, e-posta gibi kişisel bilgilerinizi paylaşmayın.</li>
            <li>Paylaşımlar yatırım tavsiyesi değildir.</li>
          </ul>
        </div>
      </aside>

      <section aria-labelledby="gonderilerim-baslik" className="lg:col-span-2" id="gonderilerim">
        <div className="fb-box">
          <h2 id="gonderilerim-baslik" className="fb-thead">
            Gönderilerim
          </h2>
          <div className="p-4 text-[13px]">{account.mine ? <MyPostsList mine={account.mine} /> : null}</div>
        </div>
      </section>
    </div>
  );
}
