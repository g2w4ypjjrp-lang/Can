import { type FormEvent, useEffect, useState } from "react";
import { useAction, usePoll } from "../api/hooks";
import { Badge, Card, ErrorBox, Field } from "../components/ui";
import { time } from "../lib/format";

interface TelegramStatus {
  configured: boolean;
  enabled: boolean;
  token_hint: string | null;
  chat_id: string | null;
  categories: string[];
  available_categories: { key: string; label: string }[];
  last_error: string | null;
  last_sent_ms: number | null;
  dropped: number;
}

/** Telegram bildirimleri: kullanıcının kendi botu ve sohbeti (Ayarlar ekranının bir bölümü). */
export function TelegramSection() {
  const status = usePoll((c) => c.get<TelegramStatus>("/v1/notifications/telegram"), 10_000);
  const save = useAction((c, body: unknown) => c.post<TelegramStatus>("/v1/notifications/telegram", body));
  const test = useAction((c) => c.post<TelegramStatus>("/v1/notifications/telegram/test"));
  const discover = useAction((c, token: string) =>
    c.post<{ chat_id: string; name: string }[]>("/v1/notifications/telegram/discover", { bot_token: token || null }),
  );
  const remove = useAction((c) => c.post<TelegramStatus>("/v1/notifications/telegram/remove"));
  const [token, setToken] = useState("");
  const [chat, setChat] = useState("");
  const [chats, setChats] = useState<{ chat_id: string; name: string }[]>([]);
  const [categories, setCategories] = useState<string[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const s = status.data;

  useEffect(() => {
    if (s && categories === null) setCategories(s.categories);
    if (s?.chat_id && !chat) setChat(s.chat_id);
  }, [s, categories, chat]);

  async function submit(event: FormEvent, enabled: boolean) {
    event.preventDefault();
    setMessage(null);
    const result = await save.execute({ bot_token: token || null, chat_id: chat || null, enabled, categories: categories ?? [] });
    if (result) {
      setToken("");
      setMessage(enabled ? "Kaydedildi; bildirimler açık." : "Kaydedildi; bildirimler kapalı.");
      await status.refresh();
    }
  }

  return (
    <Card
      title="Telegram bildirimleri"
      testId="telegram"
      actions={
        s ? (
          <Badge tone={s.enabled ? "ok" : "neutral"} testId="telegram-state">
            {s.enabled ? "Açık" : "Kapalı"}
          </Badge>
        ) : null
      }
    >
      <ErrorBox error={status.error} what="Bildirimler" />
      <ol className="steps small" style={{ marginBottom: 14 }}>
        <li>
          <div>
            <b>Telegram'da @BotFather'a /newbot yazın</b>
            <span>Bota bir ad verin; size verilen bot anahtarını kopyalayın.</span>
          </div>
        </li>
        <li>
          <div>
            <b>Kendi botunuzu açıp /start yazın</b>
            <span>Bot yalnızca kendisine yazan sohbete mesaj gönderebilir.</span>
          </div>
        </li>
        <li>
          <div>
            <b>Anahtarı yapıştırın, "Sohbeti bul"a basın, kaydedip açın</b>
            <span>Sonra "Deneme mesajı" ile kontrol edin.</span>
          </div>
        </li>
      </ol>
      <form className="form" onSubmit={(e) => void submit(e, true)}>
        <div className="grid-2">
          <Field label={s?.token_hint ? `Bot anahtarı (kayıtlı …${s.token_hint}; değiştirmek için yeni anahtar girin)` : "Bot anahtarı"}>
            <input
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="123456789:AA…"
              autoComplete="off"
              spellCheck={false}
              data-testid="telegram-token"
            />
          </Field>
          <Field label="Sohbet kimliği">
            <div className="row" style={{ flexWrap: "nowrap" }}>
              <input value={chat} onChange={(e) => setChat(e.target.value)} placeholder="ör. 987654321" data-testid="telegram-chat" />
              <button
                type="button"
                disabled={discover.pending}
                onClick={async () => {
                  const found = await discover.execute(token);
                  setSearched(found !== undefined);
                  if (found) {
                    setChats(found);
                    if (found.length === 1) setChat(found[0]!.chat_id);
                  }
                }}
                data-testid="telegram-discover"
              >
                Sohbeti bul
              </button>
            </div>
          </Field>
        </div>
        {chats.length > 1 && (
          <div className="row small">
            Bulunan sohbetler:
            {chats.map((c) => (
              <button key={c.chat_id} type="button" onClick={() => setChat(c.chat_id)}>
                {c.name} ({c.chat_id})
              </button>
            ))}
          </div>
        )}
        <ErrorBox error={discover.error} />
        {searched && chats.length === 0 && (
          <div className="notice">Sohbet bulunamadı: önce Telegram'da botunuza /start yazın, sonra yeniden deneyin.</div>
        )}
        <fieldset className="row" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="small muted" style={{ marginBottom: 6 }}>
            Hangi bildirimler gelsin?
          </legend>
          {(s?.available_categories ?? []).map((c) => (
            <label key={c.key} className="row small" style={{ marginRight: 14 }}>
              <input
                type="checkbox"
                checked={(categories ?? []).includes(c.key)}
                onChange={(e) =>
                  setCategories((prev) => (e.target.checked ? [...(prev ?? []), c.key] : (prev ?? []).filter((k) => k !== c.key)))
                }
              />
              {c.label}
            </label>
          ))}
        </fieldset>
        <div className="row">
          <button className="primary" type="submit" disabled={save.pending} data-testid="telegram-save">
            Kaydet ve aç
          </button>
          <button type="button" disabled={save.pending || !s?.enabled} onClick={(e) => void submit(e, false)}>
            Kapat
          </button>
          <button
            type="button"
            disabled={test.pending || !s?.configured}
            onClick={async () => {
              setMessage(null);
              if (await test.execute()) setMessage("Deneme mesajı gönderildi; Telegram'ı kontrol edin.");
              await status.refresh();
            }}
            data-testid="telegram-test"
          >
            Deneme mesajı
          </button>
          {s?.token_hint && (
            <button
              type="button"
              className="ghost"
              onClick={async () => {
                await remove.execute();
                setChat("");
                await status.refresh();
              }}
            >
              Bot anahtarını sil
            </button>
          )}
        </div>
      </form>
      {message && (
        <div className="ok" role="status" data-testid="telegram-message">
          {message}
        </div>
      )}
      <ErrorBox error={save.error ?? test.error ?? remove.error} />
      {s?.last_error && <div className="notice">Son gönderim hatası: {s.last_error}</div>}
      <p className="muted small">
        Bot anahtarı bu bilgisayarda şifreli saklanır. Mesajlar kısa özetlerdir; API anahtarı, bakiye ayrıntısı içermez.
        {s?.last_sent_ms ? ` Son mesaj: ${time(s.last_sent_ms)}.` : ""}
        {s?.dropped ? ` Hız sınırı nedeniyle atlanan: ${s.dropped}.` : ""}
      </p>
    </Card>
  );
}
