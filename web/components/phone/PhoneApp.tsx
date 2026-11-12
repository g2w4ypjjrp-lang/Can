"use client";

import { Camera, Lock, MonitorSmartphone, QrCode, ScanLine, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { LogoMark } from "@/components/Logo";
import { PhoneDashboard, totalBalance, type PushView, type Snap } from "@/components/phone/PhoneDashboard";
import { QrScanner } from "@/components/phone/QrScanner";
import { currentSubscription, disablePush, enablePush, isStandalone, pushSupport, subscriptionArgs, type PushSupport } from "@/lib/push";
import { parsePairing, RemoteError } from "@/lib/remote";
import { deviceStore, type EngineEvent, type Phase, RemoteClient, type StoredDevice } from "@/lib/remoteClient";

/** Bu oturumda tutulan bakiye noktası sayısı (5 sn'de bir → yaklaşık 10 dk). */
const SERIES_MAX = 120;

const STEPS = [
  { icon: MonitorSmartphone, text: "Bilgisayarda uygulamayı açın → Telefon ekranı → \"Telefondan kontrol\"ü açın." },
  { icon: QrCode, text: "\"QR kodu göster\"e basın." },
  { icon: ScanLine, text: "Telefonun kamerasıyla QR'ı okutun; bu sayfa açılır ve birkaç saniyede eşleşir." },
];
// Ana ekrana eklenmiş uygulamada telefonun kamera uygulaması QR'ı Safari'de açar; okutma uygulama
// içinden yapılır.
const STANDALONE_STEPS = [
  STEPS[0]!,
  STEPS[1]!,
  { icon: ScanLine, text: "Aşağıdaki \"QR kodu okut\" düğmesine basıp bilgisayardaki QR'ı okutun." },
];

function deviceName(): string {
  const home = isStandalone() ? "ana ekran" : "tarayıcı";
  if (/iPhone|iPad/.test(navigator.userAgent)) return `iPhone (${home})`;
  if (/Android/.test(navigator.userAgent)) return `Android (${home})`;
  return `Telefon (${home})`;
}

export function PhoneApp() {
  const [device, setDevice] = useState<StoredDevice | null | undefined>(undefined);
  const [phase, setPhase] = useState<Phase>("connecting");
  const [detail, setDetail] = useState<string | null>(null);
  const [snap, setSnap] = useState<Snap | null>(null);
  const [snapAt, setSnapAt] = useState<number | null>(null);
  const [events, setEvents] = useState<EngineEvent[]>([]);
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [series, setSeries] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [standalone, setStandalone] = useState(false);
  const [support, setSupport] = useState<PushSupport | "loading">("loading");
  const [browserPush, setBrowserPush] = useState(false);
  const [pushBusy, setPushBusy] = useState(false);
  const resynced = useRef(false);
  const client = useRef<RemoteClient | null>(null);
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 15_000);
    return () => clearInterval(id);
  }, []);

  const listener = useCallback(
    () => ({
      phase: (p: Phase, d?: string) => {
        setPhase(p);
        setDetail(d ?? null);
      },
      snapshot: (data: Record<string, unknown>, evs: EngineEvent[], ts: number) => {
        const next = data as Snap;
        const total = totalBalance(next);
        if (total !== null && Number.isFinite(total)) setSeries((list) => [...list, total].slice(-SERIES_MAX));
        setSnap(next);
        setSnapAt(ts);
        setEvents(evs.slice(0, 20));
      },
      event: (e: EngineEvent) => setEvents((list) => [e, ...list].slice(0, 20)),
      result: (ok: boolean, text: string) => {
        if (pending.current) clearTimeout(pending.current);
        setBusy(false);
        setToast({ ok, text });
        setTimeout(() => setToast(null), 5000);
      },
      paired: (d: StoredDevice) => setDevice(d),
    }),
    [],
  );

  const pairWith = useCallback(
    async (hash: string, isCancelled: () => boolean = () => false): Promise<boolean> => {
      try {
        const code = await parsePairing(hash);
        const c = await RemoteClient.pair(code, deviceName(), listener());
        if (isCancelled()) return true;
        client.current?.stop();
        client.current = c;
        setError(null);
        setDevice(null);
        c.start();
        return true;
      } catch (e) {
        setError(e instanceof RemoteError ? e.message : "QR kodu açılamadı");
        return false;
      }
    },
    [listener],
  );

  // Bildirim desteği ve bu tarayıcıdaki abonelik (yalnızca tarayıcıda bilinir).
  useEffect(() => {
    setStandalone(isStandalone());
    setSupport(pushSupport());
    currentSubscription()
      .then((sub) => setBrowserPush(sub !== null))
      .catch(() => setBrowserPush(false));
  }, []);

  // Açılış: adreste yeni QR varsa eşleş; yoksa kayıtlı eşleşmeyle bağlan.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const hash = window.location.hash;
      if (hash.includes("p=")) {
        // Gizli eşleştirme değeri tarayıcı geçmişinde kalmasın.
        history.replaceState(null, "", window.location.pathname);
        if (await pairWith(hash, () => cancelled)) return;
      }
      const stored = await deviceStore.load().catch(() => undefined);
      if (cancelled) return;
      setDevice(stored ?? null);
      if (stored?.pairedAt) {
        const c = new RemoteClient(stored, listener());
        client.current = c;
        c.start();
      }
    })();
    return () => {
      cancelled = true;
      client.current?.stop();
    };
  }, [listener, pairWith]);

  // Telefondaki abonelik var ama motor bilmiyorsa (yeniden kurulum, servis yeniledi) yeniden bildirilir.
  const enginePush = snap?.push;
  useEffect(() => {
    if (!enginePush || enginePush.subscribed || !browserPush || resynced.current || phase !== "online") return;
    resynced.current = true;
    (async () => {
      const sub = await currentSubscription();
      if (sub) await client.current?.command("push_subscribe", { ...subscriptionArgs(sub) });
    })().catch(() => undefined);
  }, [enginePush, browserPush, phase]);

  async function send(command: string, args: Record<string, unknown> = {}) {
    setBusy(true);
    if (pending.current) clearTimeout(pending.current);
    // Motor, eşleştirmesi kaldırılmış cihaza yanıt vermez; sonsuza dek beklenmez.
    pending.current = setTimeout(() => {
      setBusy(false);
      setToast({ ok: false, text: "Bilgisayardan yanıt gelmedi. Eşleştirme masaüstünden kaldırılmış olabilir." });
    }, 10_000);
    try {
      await client.current?.command(command, args);
    } catch (e) {
      if (pending.current) clearTimeout(pending.current);
      setBusy(false);
      setToast({ ok: false, text: e instanceof Error ? e.message : "Gönderilemedi" });
    }
  }

  async function pushOn() {
    if (!enginePush) return;
    setPushBusy(true);
    try {
      const args = await enablePush(enginePush.vapid_key);
      setBrowserPush(true);
      await send("push_subscribe", { ...args });
    } catch (e) {
      setToast({ ok: false, text: e instanceof Error ? e.message : "Bildirimler açılamadı" });
      setSupport(pushSupport());
    } finally {
      setPushBusy(false);
    }
  }

  async function pushOff() {
    setPushBusy(true);
    try {
      await disablePush();
      setBrowserPush(false);
      await send("push_unsubscribe");
    } finally {
      setPushBusy(false);
    }
  }

  async function forget() {
    await disablePush().catch(() => undefined);
    setBrowserPush(false);
    client.current?.stop();
    client.current = null;
    await deviceStore.clear();
    setDevice(null);
    setSnap(null);
    setSeries([]);
  }

  const paired = Boolean(device?.pairedAt) || phase === "online";
  // --- Eşleşme yok ---------------------------------------------------------------------------
  if (device === undefined && !error) {
    return (
      <div className="phone-neon">
        <main id="icerik" className="grid min-h-dvh place-items-center">
          <h1 className="sr-only">Telefondan izleme</h1>
          <p className="flex flex-col items-center gap-3 text-sm text-muted" role="status">
            <LogoMark className="ph-breathe h-16 w-16" />
            Yükleniyor…
          </p>
        </main>
      </div>
    );
  }
  if (!paired && !client.current) {
    return (
      <div className="phone-neon">
        <main id="icerik" className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-7 px-5 py-10" data-testid="phone-welcome">
          <div className="ph-rise flex flex-col items-center text-center">
            <span className="ph-orbit grid h-28 w-28 place-items-center">
              <LogoMark className="h-16 w-16" />
            </span>
            <h1 className="mt-5 text-2xl font-bold tracking-tight text-fg">
              Telefondan <span className="ph-gradient-text">izleme</span>
            </h1>
            <p className="mt-1 text-sm text-muted">AI Trading Intelligence · bakiye, bot, pozisyonlar ve kâr/zarar cebinizde</p>
          </div>
          {error && (
            <p role="alert" className="rounded-2xl border border-danger-border bg-danger-bg px-4 py-3 text-sm text-danger-fg" data-testid="phone-error">
              {error}
            </p>
          )}
          <ol className="space-y-3 text-sm text-fg">
            {(standalone ? STANDALONE_STEPS : STEPS).map(({ icon: Icon, text }, i) => (
              <li key={text} className="ph-card ph-rise flex items-center gap-3 p-3.5" style={{ animationDelay: `${(i + 1) * 80}ms` }}>
                <span className="ph-icon relative" aria-hidden="true">
                  <Icon size={18} />
                  <span className="absolute -right-1.5 -top-1.5 grid h-5 w-5 place-items-center rounded-full bg-[#3be8ff] text-[11px] font-extrabold text-[#0b1640]">
                    {i + 1}
                  </span>
                </span>
                <span>{text}</span>
              </li>
            ))}
          </ol>
          <button
            type="button"
            onClick={() => setScanning(true)}
            className="ph-tab-cta flex items-center justify-center gap-2 rounded-2xl py-3.5 text-sm font-bold"
            data-testid="phone-scan"
          >
            <Camera size={18} aria-hidden="true" /> QR kodu okut
          </button>
          <div className="ph-card flex items-start gap-3 p-3.5 text-xs text-muted">
            <ShieldCheck size={18} className="mt-0.5 shrink-0 text-up" aria-hidden="true" />
            <p>
              <Lock size={12} className="mr-1 inline" aria-hidden="true" />
              Bağlantı uçtan uca şifrelidir; anahtarlar yalnızca bu telefonda durur. Tarayıcıdan işlem açılamaz, para çekilemez.
            </p>
          </div>
        </main>
        {scanning && (
          <QrScanner
            onClose={() => setScanning(false)}
            onCode={(text) => {
              setScanning(false);
              let hash = text;
              try {
                hash = new URL(text).hash || text;
              } catch {
                /* adres değilse olduğu gibi denenir */
              }
              void pairWith(hash);
            }}
          />
        )}
      </div>
    );
  }

  const push: PushView = {
    support,
    engineReady: Boolean(enginePush),
    on: browserPush && Boolean(enginePush?.subscribed),
    busy: pushBusy || busy,
  };

  // --- Panel ---------------------------------------------------------------------------------
  return (
    <div className="phone-neon">
      <PhoneDashboard
        snap={snap}
        snapAt={snapAt}
        events={events}
        phase={phase}
        detail={detail}
        series={series}
        now={now}
        busy={busy}
        toast={toast}
        onRefresh={() => void send("request_snapshot")}
        onPause={() => void send("pause_autotrade")}
        onKill={() => void send("engage_kill_switch")}
        onForget={() => void forget()}
        push={push}
        onPushEnable={() => void pushOn()}
        onPushDisable={() => void pushOff()}
        onPushTest={() => void send("push_test")}
      />
    </div>
  );
}
