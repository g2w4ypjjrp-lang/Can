import { toDataURL } from "qrcode";
import { useEffect, useState } from "react";
import { useAction, usePoll } from "../api/hooks";
import { Badge, Card, DataTable, ErrorBox } from "../components/ui";
import { time } from "../lib/format";

interface RemoteStatus {
  enabled: boolean;
  relay_url: string | null;
  connected: boolean;
  engine_id: string;
  pairing_active: boolean;
  devices: { id: string; name: string; protection: string; paired_at: number; last_seen: number | null; revoked: boolean; online: boolean }[];
  stats: Record<string, number>;
}

interface RemoteCommand {
  ts_ms: number;
  device_id: string;
  seq: number | null;
  command: string;
  accepted: boolean;
  reason: string;
  result: string;
}

const REASONS: Record<string, string> = {
  ok: "Uygulandı",
  malformed: "Biçim geçersiz / imzasız",
  wrong_engine: "Başka motora ait",
  unknown_device: "Eşleşmemiş cihaz",
  revoked_device: "Eşleştirmesi kaldırılmış cihaz",
  bad_signature: "İmza geçersiz",
  stale: "Eski komut",
  replay: "Tekrar oynatma",
  not_allowed: "İzin verilmeyen komut",
  biometric_required: "Face ID gerekli",
  bad_proof: "Eşleştirme kodu yanlış",
  no_session: "Eşleştirme oturumu yok",
  failed: "Uygulanamadı",
};

/** Telefon eşleştirme ve uzaktan komut kaydı (Ayarlar ekranının bir bölümü). */
export function PhoneSection() {
  const status = usePoll((c) => c.get<RemoteStatus>("/v1/remote/status"), 3000);
  const commands = usePoll((c) => c.get<RemoteCommand[]>("/v1/remote/commands", { limit: 50 }), 5000);
  const [pairing, setPairing] = useState<{ qr: string; expires_ms: number; image: string } | null>(null);
  const [now, setNow] = useState(Date.now());
  const start = useAction((c) => c.post<{ qr: string; expires_ms: number }>("/v1/remote/pairing"));
  const revoke = useAction((c, id: string) => c.post("/v1/remote/devices/revoke", undefined, { device_id: id }));

  useEffect(() => {
    if (!pairing) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [pairing]);

  const remaining = pairing ? Math.max(0, Math.round((pairing.expires_ms - now) / 1000)) : 0;
  const s = status.data;

  return (
    <Card title="Telefon (iOS) eşleştirme" testId="phone">
      <ErrorBox error={status.error} what="Uzaktan kontrol" />
      {s && (
        <div className="stack">
          <div className="row">
            <span>Aktarma servisi:</span>
            {s.enabled ? (
              <Badge tone={s.connected ? "ok" : "warn"} testId="relay-state">
                {s.connected ? "Bağlı" : "Bağlanıyor…"}
              </Badge>
            ) : (
              <Badge testId="relay-state">Ayarlanmamış</Badge>
            )}
            <span className="muted small">Motor kimliği: <code>{s.engine_id}</code></span>
          </div>
          <p className="muted small">
            Telefon, bilgisayarınıza buluttaki aktarma servisi üzerinden bağlanır. Her komut telefonun güvenli
            donanımındaki anahtarla imzalanır; motor imzayı doğrulamadan hiçbir komutu uygulamaz. Bulut komut üretemez.
            Uzaktan yalnızca acil durdurma, bot durdur/başlat ve pozisyon kapatma yapılabilir; yeni işlem açma ve para
            çekme yoktur.
          </p>
          {!s.enabled && (
            <div className="notice">
              Aktarma servisi adresi henüz ayarlanmadı. Bulut dağıtımı onayınızla (G5) birlikte etkinleşecek.
            </div>
          )}
          {s.enabled && (
            <div className="row">
              <button
                className="primary"
                disabled={!s.connected || start.pending}
                onClick={async () => {
                  const result = await start.execute();
                  if (result) setPairing({ ...result, image: await toDataURL(result.qr, { margin: 1, width: 260 }) });
                }}
                data-testid="pair-start"
              >
                Yeni telefon eşleştir
              </button>
            </div>
          )}
          {pairing && remaining > 0 && (
            <div className="pairing" data-testid="pair-qr">
              <img src={pairing.image} alt="Eşleştirme QR kodu" width={260} height={260} />
              <div className="stack">
                <b>iPhone uygulamasında "Bilgisayarı eşleştir" ile bu kodu okutun.</b>
                <span className="muted">Kod {remaining} sn geçerli ve tek kullanımlık.</span>
                <span className="muted small">Kodu kimseyle paylaşmayın; ekran görüntüsü almayın.</span>
              </div>
            </div>
          )}
          <ErrorBox error={start.error ?? revoke.error} />
          <DataTable
            testId="devices"
            rows={s.devices}
            rowKey={(d) => d.id}
            empty="Eşleştirilmiş telefon yok"
            columns={[
              { key: "n", label: "Cihaz", render: (d) => <b>{d.name}</b> },
              {
                key: "p",
                label: "Anahtar",
                render: (d) => (d.protection === "secure_enclave" ? <Badge tone="ok">Secure Enclave</Badge> : <Badge tone="warn">Yazılım</Badge>),
              },
              { key: "o", label: "Durum", render: (d) => (d.revoked ? <Badge tone="bad">Kaldırıldı</Badge> : d.online ? <Badge tone="ok">Çevrim içi</Badge> : "Çevrim dışı") },
              { key: "t", label: "Eşleşme", render: (d) => time(d.paired_at) },
              { key: "l", label: "Son komut", render: (d) => time(d.last_seen) },
              {
                key: "a",
                label: "",
                render: (d) =>
                  d.revoked ? null : (
                    <button
                      onClick={async () => {
                        await revoke.execute(d.id);
                        await status.refresh();
                      }}
                    >
                      Eşleştirmeyi kaldır
                    </button>
                  ),
              },
            ]}
          />
          <h4>Uzaktan komut kaydı</h4>
          <DataTable
            testId="remote-commands"
            rows={commands.data}
            rowKey={(r, i) => `${r.ts_ms}-${i}`}
            empty="Komut yok"
            columns={[
              { key: "t", label: "Zaman", render: (r) => time(r.ts_ms) },
              { key: "c", label: "Komut", render: (r) => <code>{r.command || "—"}</code> },
              { key: "a", label: "Sonuç", render: (r) => <Badge tone={r.accepted && r.reason === "ok" ? "ok" : "bad"}>{REASONS[r.reason] ?? r.reason}</Badge> },
              { key: "r", label: "Ayrıntı", render: (r) => <span className="small muted">{r.result}</span> },
            ]}
          />
        </div>
      )}
    </Card>
  );
}
