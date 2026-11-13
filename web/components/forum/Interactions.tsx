"use client";

// Konu sayfasındaki etkileşimler: beğeni, alıntılama ve coin için yükseliş/düşüş oyu. Giriş
// yapılmamışsa düğmeler giriş sayfasına yönlendirir. Sayılar sunucudan gelir; tıklayınca güncellenir.

import { Quote, ThumbsUp, TrendingDown, TrendingUp } from "lucide-react";
import Link from "next/link";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { useApi } from "@/components/ApiContext";
import { ApiError, NETWORK_ERROR } from "@/lib/api";

interface TopicState {
  ready: boolean;
  anon: boolean;
  liked: Set<string>;
  vote: "bull" | "bear" | null;
  setLiked: (key: string, on: boolean) => void;
  setVote: (vote: "bull" | "bear") => void;
}

const StateContext = createContext<TopicState>({
  ready: false,
  anon: true,
  liked: new Set(),
  vote: null,
  setLiked: () => undefined,
  setVote: () => undefined,
});

export function TopicStateProvider({ number, children }: { number: number; children: ReactNode }) {
  const api = useApi();
  const [ready, setReady] = useState(false);
  const [anon, setAnon] = useState(true);
  const [liked, setLikedSet] = useState<Set<string>>(new Set());
  const [vote, setVote] = useState<"bull" | "bear" | null>(null);

  useEffect(() => {
    api
      .get<{ liked: string[]; vote: "bull" | "bear" | null }>(`/v1/forum/me/topics/${number}/state`)
      .then((state) => {
        setLikedSet(new Set(state.liked));
        setVote(state.vote);
        setAnon(false);
      })
      .catch(() => setAnon(true))
      .finally(() => setReady(true));
  }, [api, number]);

  const setLiked = (key: string, on: boolean) =>
    setLikedSet((current) => {
      const next = new Set(current);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });

  return <StateContext.Provider value={{ ready, anon, liked, vote, setLiked, setVote }}>{children}</StateContext.Provider>;
}

function LoginHint({ number, text }: { number: number; text: string }) {
  return (
    <Link href={`/giris?sonra=${encodeURIComponent(`/forum/${number}`)}`} className="text-xs font-semibold text-accent-text underline-offset-4 hover:underline">
      {text}
    </Link>
  );
}

/** "Faydalı" beğeni düğmesi (kendi mesajınızı beğenemezsiniz). */
export function LikeButton({ number, replyId, count }: { number: number; replyId?: string; count: number }) {
  const api = useApi();
  const state = useContext(StateContext);
  const key = replyId ?? "topic";
  const [value, setValue] = useState(count);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const on = state.liked.has(key);

  async function toggle() {
    setPending(true);
    setError(null);
    try {
      const result = await api.post<{ liked: boolean; count: number }>("/v1/forum/me/like", { number, reply_id: replyId ?? null });
      setValue(result.count);
      state.setLiked(key, result.liked);
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : NETWORK_ERROR);
    } finally {
      setPending(false);
    }
  }

  return (
    <span className="inline-flex items-center gap-2">
      {state.ready && state.anon ? (
        <span className="inline-flex items-center gap-1.5 text-xs text-muted">
          <ThumbsUp aria-hidden="true" className="h-3.5 w-3.5" /> {value} faydalı
        </span>
      ) : (
        <button
          type="button"
          onClick={() => void toggle()}
          disabled={pending || !state.ready}
          aria-pressed={on}
          className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-accent-text ${
            on ? "border-up/50 bg-up/15 text-fg" : "border-border bg-surface-2 text-fg hover:border-accent-text/50"
          }`}
          data-testid={replyId ? `like-reply-${replyId.slice(0, 8)}` : "like-topic"}
        >
          <ThumbsUp aria-hidden="true" className="h-3.5 w-3.5" /> Faydalı <span className="tabular">{value}</span>
        </button>
      )}
      {error ? (
        <span className="text-xs text-danger-fg" role="alert">
          {error}
        </span>
      ) : null}
    </span>
  );
}

/** Alıntıla: mesajı "> " satırlarıyla yanıt kutusuna ekler. */
export function QuoteButton({ author, body }: { author: string; body: string }) {
  function quote() {
    const lines = body.split("\n").filter((l) => !/^>\s?/.test(l)).slice(0, 12);
    const text = `> ${author} yazdı:\n${lines.map((l) => `> ${l}`).join("\n")}\n\n`;
    window.dispatchEvent(new CustomEvent("forum-quote", { detail: text }));
  }
  return (
    <button
      type="button"
      onClick={quote}
      className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-2.5 py-1 text-xs font-semibold text-fg hover:border-accent-text/50 focus-visible:outline-2 focus-visible:outline-accent-text"
    >
      <Quote aria-hidden="true" className="h-3.5 w-3.5" /> Alıntıla
    </button>
  );
}

/** Coin konusunda topluluk beklentisi: yükseliş (boğa) / düşüş (ayı). Kişi başı bir oy. */
export function SentimentPoll({ number, coin, initial }: { number: number; coin: string; initial: { bull: number; bear: number } }) {
  const api = useApi();
  const state = useContext(StateContext);
  const [counts, setCounts] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const total = counts.bull + counts.bear;
  const bullPct = total ? Math.round((counts.bull / total) * 100) : 50;

  async function vote(choice: "bull" | "bear") {
    setError(null);
    try {
      const result = await api.post<{ bull: number; bear: number }>(`/v1/forum/me/topics/${number}/sentiment`, { vote: choice });
      setCounts({ bull: result.bull, bear: result.bear });
      state.setVote(choice);
    } catch (err) {
      setError(err instanceof Error ? err.message : NETWORK_ERROR);
    }
  }

  const button = (choice: "bull" | "bear") => {
    const bull = choice === "bull";
    const active = state.vote === choice;
    const Icon = bull ? TrendingUp : TrendingDown;
    return (
      <button
        type="button"
        onClick={() => void vote(choice)}
        aria-pressed={active}
        disabled={!state.ready}
        className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[13px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-accent-text ${
          active ? (bull ? "border-up bg-up/20 text-fg" : "border-down bg-down/20 text-fg") : "border-border bg-surface-2 text-fg hover:border-accent-text/50"
        }`}
        data-testid={`vote-${choice}`}
      >
        <span aria-hidden="true">{bull ? "🐂" : "🐻"}</span>
        <Icon aria-hidden="true" className={`h-4 w-4 ${bull ? "text-up" : "text-down"}`} />
        {bull ? "Yükseliş" : "Düşüş"}
      </button>
    );
  };

  return (
    <section aria-labelledby="beklenti" className="fb-box" data-testid="sentiment">
      <h2 id="beklenti" className="fb-thead">
        Topluluk beklentisi: ${coin}
      </h2>
      <div className="p-3">
      <div className="flex h-2.5 overflow-hidden rounded-full bg-surface-3" aria-hidden="true">
        <div className={`bg-up ${WIDTHS[Math.round(bullPct / 10)] ?? "w-1/2"}`} />
        <div className="flex-1 bg-down" />
      </div>
      <p className="mt-2 flex justify-between text-xs font-semibold" data-testid="sentiment-counts">
        <span className="text-up">
          Yükseliş %{bullPct} ({counts.bull})
        </span>
        <span className="text-down">
          Düşüş %{total ? 100 - bullPct : 50} ({counts.bear})
        </span>
      </p>
      {state.ready && state.anon ? (
        <p className="mt-3 text-xs text-muted">
          Oy vermek için <LoginHint number={number} text="giriş yapın" />.
        </p>
      ) : (
        <div className="mt-3 flex gap-2">
          {button("bull")}
          {button("bear")}
        </div>
      )}
      {error ? (
        <p className="mt-2 text-xs text-danger-fg" role="alert">
          {error}
        </p>
      ) : null}
      <p className="mt-2 text-[11px] text-muted">Topluluk görüşüdür; yatırım tavsiyesi değildir.</p>
      </div>
    </section>
  );
}

// Satır içi stil kullanılamaz: oran onda bir adımlarla sınıf olarak verilir.
const WIDTHS = ["w-[3%]", "w-[10%]", "w-[20%]", "w-[30%]", "w-[40%]", "w-[50%]", "w-[60%]", "w-[70%]", "w-[80%]", "w-[90%]", "w-[97%]"];
