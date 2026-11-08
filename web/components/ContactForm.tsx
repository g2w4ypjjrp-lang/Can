"use client";

import Link from "next/link";
import type { FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { ErrorBox } from "@/components/auth/ErrorBox";
import { formValue, useSubmit } from "@/components/auth/useSubmit";
import { Button, Field, Notice } from "@/components/ui";
import type { Message } from "@/lib/api";

export const TOPICS = [
  { value: "support", label: "Teknik destek" },
  { value: "license", label: "Lisans ve cihazlar" },
  { value: "sales", label: "Satış ve paketler" },
  { value: "privacy", label: "Kişisel veriler (KVKK)" },
  { value: "other", label: "Diğer" },
] as const;

const inputClass =
  "mt-1.5 block w-full rounded-lg border border-border-strong bg-bg px-3 py-2.5 text-fg focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent";

export function ContactForm() {
  const api = useApi();
  const submit = useSubmit();

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    void submit.run(async () => {
      const result = await api.post<Message>("/v1/contact", {
        name: formValue(form, "name"),
        email: formValue(form, "email"),
        topic: formValue(form, "topic"),
        message: formValue(form, "message"),
        website: formValue(form, "website"),
      });
      return result.message ?? "Mesajınız alındı.";
    });
  }

  if (submit.done) {
    return (
      <Notice tone="success" role="status">
        {submit.done}
      </Notice>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5">
      <Field id="name" name="name" label="Adınız" autoComplete="name" maxLength={120} required />
      <Field id="email" name="email" type="email" label="E-posta" autoComplete="email" required />
      <div>
        <label htmlFor="topic" className="block text-sm font-medium text-fg">
          Konu
        </label>
        <select id="topic" name="topic" required defaultValue="support" className={inputClass}>
          {TOPICS.map((topic) => (
            <option key={topic.value} value={topic.value}>
              {topic.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor="message" className="block text-sm font-medium text-fg">
          Mesajınız
        </label>
        <textarea
          id="message"
          name="message"
          required
          minLength={10}
          maxLength={5000}
          rows={6}
          aria-describedby="message-ipucu"
          className={inputClass}
        />
        <p id="message-ipucu" className="mt-1.5 text-sm text-muted">
          API anahtarınızı, parolanızı veya lisans anahtarınızın tamamını asla yazmayın.
        </p>
      </div>
      {/* Bot tuzağı: kullanıcılar görmez ve doldurmaz. */}
      <div className="visually-hidden" aria-hidden="true">
        <label htmlFor="website">Web siteniz</label>
        <input id="website" name="website" type="text" tabIndex={-1} autoComplete="off" />
      </div>
      <p className="text-sm text-muted">
        Bilgileriniz yalnızca talebinizi yanıtlamak için kullanılır. Ayrıntılar:{" "}
        <Link href="/yasal/gizlilik" className="text-link underline underline-offset-2">
          Gizlilik ve KVKK aydınlatma metni
        </Link>
        .
      </p>
      <ErrorBox error={submit.error} />
      <Button type="submit" disabled={submit.pending}>
        {submit.pending ? "Gönderiliyor…" : "Gönder"}
      </Button>
    </form>
  );
}
