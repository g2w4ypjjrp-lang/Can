import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

/** Object storage for design files and print files. Paths: <store_id>/designs/<design_id>/v<N>.png */
export interface BlobStore {
  put(objectPath: string, data: Buffer, contentType: string): Promise<void>;
  get(objectPath: string): Promise<Buffer>;
  /** URL a third party (e.g. Printify) can download from for a limited time, or null if unsupported */
  signedUrl(objectPath: string, expiresInSeconds: number): Promise<string | null>;
}

function assertSafePath(p: string) {
  if (!/^[0-9a-f-]{36}\/[a-z_]+\/[0-9a-f-]{36}\/[\w.-]+$/i.test(p) || p.includes('..')) {
    throw new Error('Geçersiz nesne yolu');
  }
}

/** Filesystem store (local development / tests). */
export class LocalBlobStore implements BlobStore {
  constructor(private readonly root: string) {}
  async put(objectPath: string, data: Buffer) {
    assertSafePath(objectPath);
    const full = path.join(this.root, objectPath);
    await mkdir(path.dirname(full), { recursive: true });
    await writeFile(full, data);
  }
  async get(objectPath: string) {
    assertSafePath(objectPath);
    return readFile(path.join(this.root, objectPath));
  }
  async signedUrl() {
    return null;
  }
}

/**
 * Supabase Storage via its REST API using the service role key (server-side only).
 * Buckets are private; RLS on storage.objects is defined in migration 0011.
 */
export class SupabaseBlobStore implements BlobStore {
  constructor(
    private readonly url: string,
    private readonly serviceKey: string,
    private readonly bucket = 'designs',
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}
  private headers(extra: Record<string, string> = {}) {
    return { Authorization: `Bearer ${this.serviceKey}`, apikey: this.serviceKey, ...extra };
  }
  async put(objectPath: string, data: Buffer, contentType: string) {
    assertSafePath(objectPath);
    const res = await this.fetchImpl(`${this.url}/storage/v1/object/${this.bucket}/${objectPath}`, {
      method: 'POST',
      headers: this.headers({ 'Content-Type': contentType, 'x-upsert': 'true' }),
      body: new Uint8Array(data),
    });
    if (!res.ok) throw new Error(`Storage upload failed (${res.status})`);
  }
  async get(objectPath: string) {
    assertSafePath(objectPath);
    const res = await this.fetchImpl(
      `${this.url}/storage/v1/object/authenticated/${this.bucket}/${objectPath}`,
      { headers: this.headers() },
    );
    if (!res.ok) throw new Error(`Storage download failed (${res.status})`);
    return Buffer.from(await res.arrayBuffer());
  }
  async signedUrl(objectPath: string, expiresInSeconds: number) {
    assertSafePath(objectPath);
    const res = await this.fetchImpl(
      `${this.url}/storage/v1/object/sign/${this.bucket}/${objectPath}`,
      {
        method: 'POST',
        headers: this.headers({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ expiresIn: expiresInSeconds }),
      },
    );
    if (!res.ok) return null;
    const j = (await res.json()) as { signedURL?: string };
    return j.signedURL ? `${this.url}/storage/v1${j.signedURL}` : null;
  }
}

export function blobStoreFromEnv(env: {
  STORAGE_DRIVER?: string;
  STORAGE_LOCAL_DIR?: string;
  SUPABASE_URL?: string;
  SUPABASE_SERVICE_ROLE_KEY?: string;
}): BlobStore {
  if (env.STORAGE_DRIVER === 'supabase') {
    if (!env.SUPABASE_URL || !env.SUPABASE_SERVICE_ROLE_KEY)
      throw new Error('Supabase storage için SUPABASE_URL ve SUPABASE_SERVICE_ROLE_KEY gerekli');
    return new SupabaseBlobStore(
      env.SUPABASE_URL.replace(/\/+$/, ''),
      env.SUPABASE_SERVICE_ROLE_KEY,
    );
  }
  return new LocalBlobStore(env.STORAGE_LOCAL_DIR ?? './.data/storage');
}
