"use client";

import { Send } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

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

  useEffect(() => setName(rememberedName()), []);

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
    } catch (err) {
      setError(err instanceof Error ? err.message : NETWORK_ERROR);
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-4 rounded-3xl border border-border bg-surface p-5 shadow-sm" data-testid="reply-form">
      <h2 className="font-semibold text-fg">Hızlı yanıt</h2>
      <Field id="yanit-ad" label="Forumda görünecek adınız" required minLength={2} maxLength={40} value={name} onChange={(e) => setName(e.target.value)} />
      <div>
        <label htmlFor="yanit-metin" className="block text-sm font-medium text-fg">
          Yanıtınız
        </label>
        <textarea
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
