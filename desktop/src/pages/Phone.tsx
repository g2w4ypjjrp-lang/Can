import { CheckCircle2, CircleSlash, QrCode, RefreshCw, ShieldCheck, Smartphone } from "lucide-react";
import { toDataURL } from "qrcode";
import { useEffect, useRef, useState } from "react";
import { useAction, usePoll } from "../api/hooks";
import { Badge, Card, DataTable, ErrorBox } from "../components/ui";
import { time } from "../lib/format";

export interface RemoteDevice {
  id: string;
  name: string;
  protection: string;
  paired_at: number;
  last_seen: number | null;
  revoked: boolean;
  online: boolean;
  /** Kilit ekranı bildirimleri (Web Push) bu telefonda açık mı. */
  push?: boolean;
}

export interface RemoteStatus {
  enabled: boolean;
  relay_url: string | null;
  connected: boolean;
  engine_id: string;
  pairing_active: boolean;
  devices: RemoteDevice[];
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

interface Pairing {
  qr: string;
  expires_ms: number;
  started_ms: number;
  image: string;
  known: string[];
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

const COMMANDS: Record<string, string> = {
  engage_kill_switch: "Acil durdurma",
  release_kill_switch: "Acil durdurmayı kaldır",
  pause_autotrade: "Botu durdur",
  resume_autotrade: "Botu başlat",
  close_position: "Pozisyon kapat",
  close_all: "Tüm pozisyonları kapat",
  request_snapshot: "Durum isteği",
  pair_request: "Eşleştirme",
};

/** Kenar çubuğu ve üst çubuk için kısa telefon durumu. */
export function phoneSummary(s: RemoteStatus | undefined): { tone: "ok" | "warn" | "neutral"; label: string; short: string } {
  if (!s || !s.enabled) return { tone: "neutral", label: "Kapalı — açmak için dokunun", short: "Telefon kapalı" };
  if (!s.connected) return { tone: "warn", label: "Bağlanıyor…", short: "Bağlanıyor…" };
  const active = s.devices.filter((d) => !d.revoked);
  const online = active.filter((d) => d.online).length;
  if (active.length === 0) return { tone: "ok", label: "Açık · telefon eşleştirin", short: "Telefon: eşleştirin" };
  return {
    tone: "ok",
    label: `${active.length} telefon eşli · ${online} çevrim içi`,
    short: online > 0 ? `${online} telefon bağlı` : `${active.length} telefon eşli`,
  };
}

function remainingSeconds(pairing: Pairing | null, now: number): number {
  return pairing ? Math.max(0, Math.round((pairing.expires_ms - now) / 1000)) : 0;
}

/** Telefondan kontrol: aç/kapat, QR ile eşleştirme, eşli cihazlar ve uzaktan komut kaydı. */
export function Phone() {
  const status = usePoll((c) => c.get<RemoteStatus>("/v1/remote/status"), 2000);
  const commands = usePoll((c) => c.get<RemoteCommand[]>("/v1/remote/commands", { limit: 50 }), 5000);
  const toggle = useAction((c, enabled: boolean) => c.post<RemoteStatus>("/v1/remote/enabled", { enabled }));
  const start = useAction((c) => c.post<{ qr: string; expires_ms: number }>("/v1/remote/pairing"));
  const revoke = useAction((c, id: string) => c.post("/v1/remote/devices/revoke", undefined, { device_id: id }));
  const [pairing, setPairing] = useState<Pairing | null>(null);
  const [paired, setPaired] = useState<RemoteDevice | null>(null);
  const [now, setNow] = useState(Date.now());
  const qrRef = useRef<HTMLDivElement>(null);

  const s = status.data;
  const remaining = remainingSeconds(pairing, now);

  useEffect(() => {
    if (!pairing) return;
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [pairing]);

  // QR gösterilirken yeni bir telefon eşleşirse kod kaldırılır ve başarı gösterilir.
  useEffect(() => {
    if (!pairing || !s) return;
    const fresh = s.devices.find((d) => !d.revoked && !pairing.known.includes(d.id));
    if (fresh) {
      setPaired(fresh);
      setPairing(null);
    }
  }, [s, pairing]);

  // Kapatılınca ekrandaki kod da kalkar (motor tarafında da geçersizleşir).
  useEffect(() => {
    if (s && !s.enabled) setPairing(null);
  }, [s]);

  async function showQr() {
    setPaired(null);
    const result = await start.execute();
    if (!result) return;
    const image = await toDataURL(result.qr, { margin: 1, width: 560, errorCorrectionLevel: "M" });
    setNow(Date.now());
    setPairing({
      ...result,
      image,
      started_ms: Date.now(),
      known: (s?.devices ?? []).map((d) => d.id),
    });
    requestAnimationFrame(() => qrRef.current?.focus());
  }

  async function setEnabled(enabled: boolean) {
    await toggle.execute(enabled);
    await status.refresh();
  }

  const enabled = s?.enabled ?? false;
  const ready = enabled && (s?.connected ?? false);
  const total = pairing ? Math.max(1, (pairing.expires_ms - pairing.started_ms) / 1000) : 1;
  const activeDevices = (s?.devices ?? []).filter((d) => !d.revoked);

  return (
    <div className="page" data-testid="page-phone">
      <section className="phone-hero" data-testid="phone">
        <div>
          <h2>Bilgisayarınızı telefondan kontrol edin</h2>
          <p>
            iPhone uygulaması bu bilgisayardaki motora QR kodla eşleşir. Dışarıdayken durumu görebilir, acil
            durdurabilir, botu durdurup başlatabilir ve pozisyon kapatabilirsiniz. Telefondan yeni işlem açılamaz,
            para çekilemez.
          </p>
          <div className="row">
            {!s ? (
              <Badge testId="relay-state">Yükleniyor…</Badge>
            ) : !enabled ? (
              <Badge testId="relay-state">Kapalı</Badge>
            ) : s.connected ? (
              <Badge tone="ok" testId="relay-state">
                Bağlı
              </Badge>
            ) : (
              <Badge tone="warn" testId="relay-state">
                Bağlanıyor…
              </Badge>
            )}
            {s && (
              <span className="muted small">
                Motor kimliği: <code>{s.engine_id.slice(0, 12)}…</code>
              </span>
            )}
          </div>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          className="switch"
          disabled={!s || toggle.pending}
          onClick={() => void setEnabled(!enabled)}
          data-testid="remote-toggle"
        >
          <span className="track" aria-hidden="true" />
          <span data-testid="remote-state">{enabled ? "Telefondan kontrol açık" : "Telefondan kontrol kapalı"}</span>
        </button>
      </section>

      <ErrorBox error={status.error} what="Telefondan kontrol" />
      <ErrorBox error={toggle.error ?? start.error ?? revoke.error} />

      <div className="grid-main">
        <Card title="Telefon ekle">
          <div className="pair-layout">
            <div>
              {pairing && remaining > 0 ? (
                <div data-testid="pair-qr">
                  <div className="qr-frame" ref={qrRef} tabIndex={-1}>
                    <img src={pairing.image} alt="Eşleştirme QR kodu" width={272} height={272} />
                  </div>
                  <div className="countdown" aria-hidden="true">
                    <progress max={total} value={remaining} />
                  </div>
                  <p className="muted small" style={{ width: 300, margin: "8px 0 0" }} data-testid="pair-remaining">
                    Kod {Math.floor(remaining / 60)}:{String(remaining % 60).padStart(2, "0")} dakika geçerli ve tek
                    kullanımlık. Kimseyle paylaşmayın.
                  </p>
                </div>
              ) : (
                <div className="qr-placeholder">
                  {paired ? <CheckCircle2 aria-hidden="true" style={{ color: "var(--up)" }} /> : <QrCode aria-hidden="true" />}
                  <span>
                    {paired
                      ? "Telefon eşleşti"
                      : pairing
                        ? "Kodun süresi doldu"
                        : enabled
                          ? "QR kod burada görünecek"
                          : "Önce telefondan kontrolü açın"}
                  </span>
                </div>
              )}
            </div>
            <div className="stack">
              {paired && (
                <div className="success-banner" role="status" data-testid="pair-success">
                  <CheckCircle2 aria-hidden="true" />
                  <div>
                    <b>{paired.name} eşleşti</b>
                    <div className="muted small">Telefon artık bu bilgisayarı kontrol edebilir.</div>
                  </div>
                </div>
              )}
              <ol className="steps">
                <li>
                  <div>
                    <b>Telefondan kontrolü açın</b>
                    <span>Sağ üstteki anahtarla. Bilgisayar, şifreli aktarma servisine bağlanır.</span>
                  </div>
                </li>
                <li>
                  <div>
                    <b>QR kodu gösterin</b>
                    <span>Aşağıdaki düğmeyle. Kod 5 dakika geçerlidir ve yalnızca bir kez kullanılır.</span>
                  </div>
                </li>
                <li>
                  <div>
                    <b>Telefonun kamerasıyla okutun</b>
                    <span>
                      Telefonda tarayıcıda izleme sayfası açılır ve birkaç saniyede eşleşir (uygulama gerekmez). Durumu,
                      botu, pozisyonları ve fırsatları görür; acil durdurabilirsiniz. Bağlantı uçtan uca şifrelidir.
                    </span>
                  </div>
                </li>
              </ol>
              <div className="row">
                <button
                  type="button"
                  className="primary big"
                  disabled={!ready || start.pending}
                  onClick={() => void showQr()}
                  data-testid="pair-start"
                >
                  {pairing && remaining > 0 ? <RefreshCw aria-hidden="true" size={17} /> : <QrCode aria-hidden="true" size={17} />}
                  {pairing && remaining > 0 ? "Yeni kod üret" : "QR kodu göster"}
                </button>
                {pairing && remaining > 0 && (
                  <button type="button" onClick={() => setPairing(null)}>
                    Gizle
                  </button>
                )}
              </div>
              {enabled && !s?.connected && (
                <span className="muted small">Aktarma servisine bağlanılıyor; internet bağlantınızı kontrol edin.</span>
              )}
            </div>
          </div>
        </Card>

        <Card title="Telefondan neler yapılabilir?">
          <ul className="allow-list">
            <li className="yes">
              <CheckCircle2 aria-hidden="true" />
              <span>
                Durumu ve pozisyonları görme, bildirim alma
                <small>Motor durumu, açık pozisyonlar, kâr/zarar</small>
              </span>
            </li>
            <li className="yes">
              <CheckCircle2 aria-hidden="true" />
              <span>
                Kilit ekranına bildirim (uygulama indirmeden)
                <small>
                  Telefondaki sayfada "Bildirimleri aç". iPhone'da önce Safari → Paylaş → Ana Ekrana Ekle; simgeden açıp QR'ı
                  uygulamanın içinden okutun. Bu bilgisayar açıkken gelir.
                </small>
              </span>
            </li>
            <li className="yes">
              <CheckCircle2 aria-hidden="true" />
              <span>
                Acil durdurma ve botu durdurma
                <small>Her zaman, tek dokunuşla</small>
              </span>
            </li>
            <li className="yes">
              <CheckCircle2 aria-hidden="true" />
              <span>
                Botu başlatma, pozisyon kapatma, acil durdurmayı kaldırma
                <small>Face ID onayıyla</small>
              </span>
            </li>
            <li className="no">
              <CircleSlash aria-hidden="true" />
              <span>
                Yeni işlem açma, ayar değiştirme, para çekme
                <small>Telefondan yapılamaz; yalnızca bu bilgisayardan</small>
              </span>
            </li>
          </ul>
          <hr />
          <div className="row small muted" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
            <ShieldCheck aria-hidden="true" size={18} style={{ color: "var(--accent)", flexShrink: 0 }} />
            <span>
              Her komut telefonun güvenli donanımındaki anahtarla imzalanır ve uçtan uca şifrelenir; motor imzayı
              doğrulamadan hiçbir komutu uygulamaz. Aktarma servisi mesajları okuyamaz ve komut üretemez.
            </span>
          </div>
        </Card>
      </div>

      <Card
        title={
          <span className="row">
            <Smartphone aria-hidden="true" size={16} /> Eşli telefonlar ({activeDevices.length})
          </span>
        }
      >
        <DataTable
          testId="devices"
          rows={s?.devices}
          rowKey={(d) => d.id}
          empty="Henüz eşli telefon yok"
          columns={[
            { key: "n", label: "Cihaz", render: (d) => <b>{d.name}</b> },
            {
              key: "p",
              label: "Anahtar",
              render: (d) =>
                d.protection === "secure_enclave" ? (
                  <Badge tone="ok">Secure Enclave</Badge>
                ) : d.protection === "browser" ? (
                  <Badge tone="info">Tarayıcı</Badge>
                ) : (
                  <Badge tone="warn">Yazılım</Badge>
                ),
            },
            {
              key: "b",
              label: "Bildirim",
              render: (d) => (d.push ? <Badge tone="ok">Açık</Badge> : <Badge>Kapalı</Badge>),
            },
            {
              key: "o",
              label: "Durum",
              render: (d) =>
                d.revoked ? <Badge tone="bad">Kaldırıldı</Badge> : d.online ? <Badge tone="ok">Çevrim içi</Badge> : <Badge>Çevrim dışı</Badge>,
            },
            { key: "t", label: "Eşleşme", render: (d) => time(d.paired_at) },
            { key: "l", label: "Son komut", render: (d) => time(d.last_seen) },
            {
              key: "a",
              label: "",
              align: "right",
              render: (d) =>
                d.revoked ? null : (
                  <button
                    type="button"
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
      </Card>

      <Card title="Uzaktan komut kaydı">
        <DataTable
          testId="remote-commands"
          rows={commands.data}
          rowKey={(r, i) => `${r.ts_ms}-${i}`}
          empty="Telefondan henüz komut gelmedi"
          columns={[
            { key: "t", label: "Zaman", render: (r) => time(r.ts_ms) },
            { key: "c", label: "Komut", render: (r) => COMMANDS[r.command] ?? (r.command || "—") },
            {
              key: "a",
              label: "Sonuç",
              render: (r) => <Badge tone={r.accepted && r.reason === "ok" ? "ok" : "bad"}>{REASONS[r.reason] ?? r.reason}</Badge>,
            },
            { key: "r", label: "Ayrıntı", render: (r) => <span className="small muted">{r.result}</span> },
          ]}
        />
      </Card>
    </div>
  );
}
