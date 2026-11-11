"use client";

// Telefon tarayıcısının aktarma servisi bağlantısı: eşleştirme, imzalı komut, şifreli özet.
// Eşleşme kaydı (dışa aktarılamayan anahtarlar dahil) yalnızca bu tarayıcının IndexedDB'sinde
// durur; sunucuya hiçbir anahtar gönderilmez.

import {
  type DeviceKeys,
  type PairingCode,
  type Signed,
  deviceHello,
  generateDeviceKeys,
  openFromEngine,
  pairRequest,
  REASONS,
  RemoteError,
  sealForEngine,
  signedCommand,
  unb64,
} from "./remote";

export interface StoredDevice {
  engineId: string;
  engineKey: Uint8Array;
  engineKx: Uint8Array;
  relay: string;
  name: string;
  keys: DeviceKeys;
  lastSeq: number;
  pairedAt: number;
}

const DB = "ati-telefon";
const STORE = "cihaz";
const KEY = "eslesme";

function idb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function tx<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const req = run(db.transaction(STORE, mode).objectStore(STORE));
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  }).finally(() => db.close()) as Promise<T>;
}

export const deviceStore = {
  load: () => tx<StoredDevice | undefined>("readonly", (s) => s.get(KEY) as IDBRequest<StoredDevice | undefined>),
  save: (device: StoredDevice) => tx("readwrite", (s) => s.put(device, KEY)),
  clear: () => tx("readwrite", (s) => s.delete(KEY)),
};

export type Phase = "connecting" | "pairing" | "online" | "engine_offline" | "offline" | "rejected";

export interface EngineEvent {
  ts_ms: number;
  kind: string;
  title: string;
  body: string;
}

export interface Listener {
  phase(phase: Phase, detail?: string): void;
  snapshot(data: Record<string, unknown>, events: EngineEvent[], ts: number): void;
  event(event: EngineEvent): void;
  result(ok: boolean, message: string, command: string | null): void;
  paired(device: StoredDevice): void;
}

/** Tek bir motora bağlantı. Kopunca artan beklemeyle yeniden bağlanır. */
export class RemoteClient {
  private ws: WebSocket | null = null;
  private closed = false;
  private retry = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private device: StoredDevice,
    private readonly listener: Listener,
    private readonly pairing: PairingCode | null = null,
  ) {}

  static async pair(code: PairingCode, name: string, listener: Listener): Promise<RemoteClient> {
    const keys = await generateDeviceKeys();
    const device: StoredDevice = {
      engineId: code.engine_id,
      engineKey: unb64(code.engine_key),
      engineKx: unb64(code.engine_kx),
      relay: code.relay.replace(/\/+$/, ""),
      name,
      keys,
      lastSeq: 0,
      pairedAt: 0,
    };
    return new RemoteClient(device, listener, code);
  }

  get deviceId(): string {
    return this.device.keys.deviceId;
  }

  start(): void {
    this.closed = false;
    this.connect();
  }

  stop(): void {
    this.closed = true;
    if (this.timer) clearTimeout(this.timer);
    this.ws?.close();
    this.ws = null;
  }

  private connect(): void {
    this.listener.phase(this.pairing && !this.device.pairedAt ? "pairing" : "connecting");
    const ws = new WebSocket(`${this.device.relay}/v1/relay/device`);
    this.ws = ws;
    ws.onopen = async () => {
      ws.send(JSON.stringify(await deviceHello(this.device.keys, this.device.engineId)));
    };
    ws.onmessage = (event) => void this.onFrame(String(event.data));
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      if (this.closed) return;
      this.listener.phase("offline", "Bağlantı koptu; yeniden bağlanılıyor…");
      const wait = Math.min(30_000, 1000 * 2 ** this.retry++);
      this.timer = setTimeout(() => this.connect(), wait);
    };
  }

  private async onFrame(raw: string): Promise<void> {
    let frame: Record<string, unknown>;
    try {
      frame = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return;
    }
    switch (frame.type) {
      case "welcome":
        this.retry = 0;
        if (!frame.engine_online) {
          this.listener.phase("engine_offline");
          return;
        }
        await this.afterConnect();
        return;
      case "engine_offline":
        this.listener.phase("engine_offline");
        return;
      case "device_online":
      case "engine_online":
        await this.afterConnect();
        return;
      case "error":
        this.listener.phase("offline", frame.reason === "rate_limited" ? "Çok sık istek; biraz bekleyin" : String(frame.reason));
        return;
      case "from_engine":
        await this.onEngineMessage(frame.msg);
        return;
      default:
        return;
    }
  }

  private async afterConnect(): Promise<void> {
    if (this.pairing && !this.device.pairedAt) {
      await this.send(await pairRequest(this.pairing, this.device.keys, this.device.name));
      return;
    }
    this.listener.phase("online");
    await this.command("request_snapshot");
  }

  private async onEngineMessage(envelope: unknown): Promise<void> {
    let payload: Record<string, unknown>;
    try {
      payload = await openFromEngine(envelope, this.device.keys, this.device.engineId, this.device.engineKey);
    } catch {
      return; // çözülemeyen ya da imzası geçersiz mesaj yok sayılır
    }
    switch (payload.type) {
      case "pair_result":
        if (payload.ok) {
          this.device = { ...this.device, pairedAt: Date.now() };
          await deviceStore.save(this.device);
          this.listener.paired(this.device);
          this.listener.phase("online");
          await this.command("request_snapshot");
        } else {
          const reason = String(payload.reason ?? "");
          this.listener.phase("rejected", REASONS[reason] ?? "Eşleştirme reddedildi");
          this.stop();
        }
        return;
      case "snapshot":
        this.listener.snapshot(
          (payload.data ?? {}) as Record<string, unknown>,
          (payload.events ?? []) as EngineEvent[],
          Number(payload.ts_ms ?? Date.now()),
        );
        this.listener.phase("online");
        return;
      case "event":
        this.listener.event(payload as unknown as EngineEvent);
        return;
      case "result": {
        const reason = String(payload.reason ?? "");
        if (reason === "revoked_device") {
          this.listener.phase("rejected", REASONS.revoked_device);
          return;
        }
        const command = typeof payload.command === "string" ? payload.command : null;
        if (command !== "request_snapshot" || !payload.ok) {
          this.listener.result(Boolean(payload.ok), String(payload.message ?? REASONS[reason] ?? reason), command);
        }
        return;
      }
      default:
        return;
    }
  }

  private async send(message: Signed): Promise<void> {
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN) throw new RemoteError("Bağlantı yok");
    const envelope = await sealForEngine(message, this.device.engineKx, this.device.engineId, this.device.keys.deviceId);
    ws.send(JSON.stringify({ type: "to_engine", msg: envelope }));
  }

  /** İmza anahtarlı komut (izleme, acil durdurma, botu durdurma). Sıra numarası geri gitmez. */
  async command(command: string, args: Record<string, unknown> = {}): Promise<void> {
    const seq = Math.max(this.device.lastSeq + 1, Date.now());
    this.device = { ...this.device, lastSeq: seq };
    if (this.device.pairedAt) await deviceStore.save(this.device);
    await this.send(await signedCommand(this.device.keys, this.device.engineId, seq, command, args));
  }
}
