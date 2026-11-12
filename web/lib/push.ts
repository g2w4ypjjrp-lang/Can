// Telefon bildirimleri (Web Push) — tarayıcı tarafı. Abonelik bilgisi (bildirim servisi adresi +
// tarayıcının açık anahtarları) uçtan uca şifreli aktarma kanalıyla bilgisayardaki motora gider;
// motor bildirimi bu anahtara şifreleyip doğrudan bildirim servisine gönderir.
//
// iPhone: yalnızca ana ekrana eklenmiş web uygulamasında çalışır (iOS 16.4+, Safari → Paylaş →
// Ana Ekrana Ekle). Android: Chrome'da doğrudan çalışır.

export type PushSupport = "ok" | "ios_home_screen" | "unsupported" | "denied";

export interface PushArgs {
  endpoint: string;
  p256dh: string;
  auth: string;
}

const SCOPE = "/telefon";

export function isIos(): boolean {
  if (typeof navigator === "undefined") return false;
  return /iPhone|iPad|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
}

/** Ana ekrandan (uygulama gibi) açılmış mı? */
export function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  const nav = navigator as Navigator & { standalone?: boolean };
  return nav.standalone === true || window.matchMedia?.("(display-mode: standalone)").matches === true;
}

export function pushSupport(): PushSupport {
  if (typeof window === "undefined") return "unsupported";
  if (isIos() && !isStandalone()) return "ios_home_screen";
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  return "ok";
}

function toBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const padded = base64url.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (base64url.length % 4)) % 4);
  const raw = atob(padded);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function toB64url(buffer: ArrayBuffer | null): string {
  if (!buffer) return "";
  let text = "";
  for (const b of new Uint8Array(buffer)) text += String.fromCharCode(b);
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function subscriptionArgs(sub: PushSubscription): PushArgs {
  return { endpoint: sub.endpoint, p256dh: toB64url(sub.getKey("p256dh")), auth: toB64url(sub.getKey("auth")) };
}

async function registration(): Promise<ServiceWorkerRegistration> {
  const existing = await navigator.serviceWorker.getRegistration(SCOPE);
  if (existing) return existing;
  await navigator.serviceWorker.register("/sw.js", { scope: SCOPE });
  return navigator.serviceWorker.ready;
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (pushSupport() !== "ok") return null;
  const reg = await navigator.serviceWorker.getRegistration(SCOPE);
  return reg ? reg.pushManager.getSubscription() : null;
}

/** İzin ister ve abone olur (kullanıcı dokunuşuyla çağrılmalı; iPhone bunu şart koşar). */
export async function enablePush(vapidKey: string): Promise<PushArgs> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error(
      permission === "denied"
        ? "Bildirim izni verilmedi. Telefon Ayarları → Bildirimler bölümünden bu uygulamaya izin verin."
        : "Bildirim izni verilmedi.",
    );
  }
  const reg = await registration();
  const key = toBytes(vapidKey);
  let sub = await reg.pushManager.getSubscription();
  // Motorun anahtarı değiştiyse (yeniden kurulum) eski abonelik kaldırılır.
  if (sub && toB64url(sub.options.applicationServerKey) !== vapidKey) {
    await sub.unsubscribe();
    sub = null;
  }
  sub ??= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
  return subscriptionArgs(sub);
}

export async function disablePush(): Promise<void> {
  const sub = await currentSubscription();
  await sub?.unsubscribe();
}
