"use client";

import { Send } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { LoginPrompt } from "@/components/forum/LoginPrompt";
import { rememberName, rememberedName, useForumAccount } from "@/components/forum/useForumAccount";
import { Button, Field, Notice, inputBase } from "@/components/ui";
import { NETWORK_ERROR } from "@/lib/api";

/** Konuya yanıt: yönetici onayından sonra görünür. */
export function ReplyForm({ number }: { number: number }) {
  const api = useApi();
  const account = useForumAccount();
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const area = useRef<HTMLTextAreaElement>(null);
  const nickname = account.mine?.profile?.nickname ?? null;

  useEffect(() => setName(rememberedName()), []);
  useEffect(() => {
    if (nickname) setName(nickname);
  }, [nickname]);
  // "Alıntıla" düğmesi alıntıyı buraya ekler.
  useEffect(() => {
    function onQuote(event: Event) {
      const text = (event as CustomEvent<string>).detail;
      setBody((current) => `${current}${current && !current.endsWith("\n") ? "\n\n" : ""}${text}`);
      requestAnimationFrame(() => {
        area.current?.scrollIntoView({ behavior: "smooth", block: "center" });
        area.current?.focus();
      });
    }
    window.addEventListener("forum-quote", onQuote);
    return () => window.removeEventListener("forum-quote", onQuote);
  }, []);

  if (account.state === "loading") return <p className="text-sm text-muted">Yükleniyor…</p>;
  if (account.state === "anon") return <LoginPrompt next={`/forum/${number}`} action="Yanıt yazmak" />;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    setDone(null);
    try {
      const result = await api.post<{ message: string }>(`/v1/forum/me/topics/${number}/replies`, { author_name: name.trim(), body });
      rememberName(name.trim());
      setBody("");
      setDone(result.message);
      account.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : NETWORK_ERROR);
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-4 rounded-3xl border border-border bg-surface p-5 shadow-sm" data-testid="reply-form">
      <h2 className="font-semibold text-fg">Hızlı yanıt</h2>
      <Field
        id="yanit-ad"
        label="Forumda görünecek adınız"
        hint={nickname ? "Forum adınız kalıcıdır (profil ve rütbeniz bu adla)." : "İlk gönderinizde seçtiğiniz ad kalıcı forum adınız olur."}
        required
        minLength={2}
        maxLength={40}
        value={name}
        readOnly={Boolean(nickname)}
        onChange={(e) => setName(e.target.value)}
      />
      <div>
        <label htmlFor="yanit-metin" className="block text-sm font-medium text-fg">
          Yanıtınız
        </label>
        <textarea
          ref={area}
          id="yanit-metin"
          required
          minLength={2}
          maxLength={3000}
          rows={4}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          className={`mt-1.5 ${inputBase}`}
        />
        <p className="mt-1 text-right text-xs text-muted">{body.length} / 3000</p>
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
      <Button type="submit" disabled={pending}>
        <Send aria-hidden="true" className="h-4 w-4" /> Onaya gönder
      </Button>
    </form>
  );
}
