import sharp from 'sharp';
import { createHash } from 'node:crypto';

/** Hard limits protect the server from decompression bombs and huge uploads. */
export const MAX_INPUT_PIXELS = 8000 * 8000;
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
export const PRINT_DPI = 300;

export interface ImageInfo {
  format: string;
  width: number;
  height: number;
  hasAlpha: boolean;
  density: number | null;
  bytes: number;
  sha256: string;
}

export async function inspectImage(buf: Buffer): Promise<ImageInfo> {
  if (buf.length > MAX_UPLOAD_BYTES) throw new Error('Dosya 25 MB sınırını aşıyor');
  const meta = await sharp(buf, { limitInputPixels: MAX_INPUT_PIXELS }).metadata();
  if (!meta.width || !meta.height || !meta.format) throw new Error('Görüntü okunamadı');
  if (!['png', 'jpeg', 'webp', 'svg'].includes(meta.format))
    throw new Error(`Desteklenmeyen biçim: ${meta.format}`);
  return {
    format: meta.format,
    width: meta.width,
    height: meta.height,
    hasAlpha: Boolean(meta.hasAlpha),
    density: meta.density ?? null,
    bytes: buf.length,
    sha256: createHash('sha256').update(buf).digest('hex'),
  };
}

/**
 * SVG safety check (model output or upload). librsvg can resolve external
 * resources, so anything that could reference files/URLs or run script is rejected.
 */
export function assertSafeSvg(svg: string): void {
  if (svg.length > 2_000_000) throw new Error('SVG çok büyük');
  const forbidden: Array<[RegExp, string]> = [
    [/<!DOCTYPE|<!ENTITY/i, 'DOCTYPE/ENTITY'],
    [/@import/i, '@import'],
    [/<script/i, 'script'],
    [/<foreignObject/i, 'foreignObject'],
    [/<image[\s>]/i, 'gömülü/dış görsel'],
    [/<(iframe|object|embed|use)[\s>]/i, 'dış içerik/use'],
    [/\son[a-z]+\s*=/i, 'olay işleyicisi'],
    [/(?:xlink:)?href\s*=\s*["'](?!#)/i, 'dış bağlantı'],
    [/url\(\s*["']?(?!#)/i, 'dış url()'],
  ];
  for (const [re, what] of forbidden)
    if (re.test(svg)) throw new Error(`SVG güvenlik denetimi: ${what} yasak`);
  if (!/^\s*(<\?xml[^>]*\?>\s*)?<svg[\s>]/i.test(svg)) throw new Error('Geçerli bir SVG değil');
}

/** Rasterises a (checked) SVG to a transparent PNG of the given width. */
export async function svgToPng(svg: string, width: number): Promise<Buffer> {
  assertSafeSvg(svg);
  const meta = await sharp(Buffer.from(svg), { limitInputPixels: MAX_INPUT_PIXELS }).metadata();
  const baseWidth = meta.width ?? 1000;
  const density = Math.min(2400, Math.max(72, Math.ceil((72 * width) / baseWidth)));
  return sharp(Buffer.from(svg), { density, limitInputPixels: MAX_INPUT_PIXELS })
    .resize({ width, fit: 'inside', withoutEnlargement: false })
    .png()
    .withMetadata({ density: PRINT_DPI })
    .toBuffer();
}

/**
 * Removes a uniform background by flood-filling from the image border:
 * pixels connected to the edge and within `tolerance` (RGB distance) of the
 * dominant corner colour become transparent. Interior areas of the same colour
 * (e.g. white inside letters) are preserved.
 */
export async function removeUniformBackground(
  buf: Buffer,
  tolerance = 28,
): Promise<{ png: Buffer; removedRatio: number; background: [number, number, number] }> {
  const { data, info } = await sharp(buf, { limitInputPixels: MAX_INPUT_PIXELS })
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });
  const { width: w, height: h } = info;
  const px = (x: number, y: number) => (y * w + x) * 4;
  const corners = [px(0, 0), px(w - 1, 0), px(0, h - 1), px(w - 1, h - 1)].map(
    (i) => [data[i]!, data[i + 1]!, data[i + 2]!] as const,
  );
  const bg = [0, 1, 2].map((c) => corners.map((k) => k[c]!).sort((a, b) => a - b)[1]!) as [
    number,
    number,
    number,
  ];
  const tol2 = tolerance * tolerance;
  const near = (i: number) => {
    const dr = data[i]! - bg[0];
    const dg = data[i + 1]! - bg[1];
    const db = data[i + 2]! - bg[2];
    return data[i + 3]! > 0 && dr * dr + dg * dg + db * db <= tol2;
  };
  const visited = new Uint8Array(w * h);
  const stack: number[] = [];
  for (let x = 0; x < w; x++) stack.push(x, (h - 1) * w + x);
  for (let y = 0; y < h; y++) stack.push(y * w, y * w + w - 1);
  let removed = 0;
  while (stack.length) {
    const p = stack.pop()!;
    if (visited[p]) continue;
    visited[p] = 1;
    const i = p * 4;
    if (!near(i)) continue;
    data[i + 3] = 0;
    removed++;
    const x = p % w;
    const y = (p - x) / w;
    if (x > 0) stack.push(p - 1);
    if (x < w - 1) stack.push(p + 1);
    if (y > 0) stack.push(p - w);
    if (y < h - 1) stack.push(p + w);
  }
  const png = await sharp(data, { raw: { width: w, height: h, channels: 4 } })
    .png()
    .toBuffer();
  return { png, removedRatio: removed / (w * h), background: bg };
}

export interface PrintFit {
  targetWidth: number;
  targetHeight: number;
  scale: number;
  effectiveDpi: number;
  coverage: number;
  upscaled: boolean;
  status: 'ok' | 'low_resolution' | 'too_low';
  message: string;
}

/** How the design maps onto a print area when fitted ("contain"). */
export function evaluatePrintFit(
  src: { width: number; height: number },
  area: { width: number; height: number },
  dpi = PRINT_DPI,
): PrintFit {
  const scale = Math.min(area.width / src.width, area.height / src.height);
  const effectiveDpi = Math.round(dpi / Math.max(scale, 1e-9));
  const coverage = (src.width * scale * src.height * scale) / (area.width * area.height);
  const status = scale <= 1 ? 'ok' : effectiveDpi >= 150 ? 'low_resolution' : 'too_low';
  return {
    targetWidth: area.width,
    targetHeight: area.height,
    scale: Math.round(scale * 1000) / 1000,
    effectiveDpi: scale <= 1 ? dpi : effectiveDpi,
    coverage: Math.round(coverage * 1000) / 1000,
    upscaled: scale > 1,
    status,
    message:
      status === 'ok'
        ? `Çözünürlük yeterli (${dpi} DPI). Baskı alanının %${Math.round(coverage * 100)}’i kaplanır.`
        : status === 'low_resolution'
          ? `Görsel ${scale.toFixed(2)}× büyütülecek; etkin çözünürlük ~${effectiveDpi} DPI (önerilen ${dpi}). Baskı yumuşak görünebilir.`
          : `Çözünürlük çok düşük (~${effectiveDpi} DPI). Daha büyük bir dosya gerekli.`,
  };
}

/** Produces the print file: exactly the print-area size, transparent padding, 300 DPI metadata. */
export async function prepareForPrintArea(
  buf: Buffer,
  area: { width: number; height: number },
  dpi = PRINT_DPI,
) {
  const info = await inspectImage(buf);
  const fit = evaluatePrintFit(info, area, dpi);
  const png = await sharp(buf, { limitInputPixels: MAX_INPUT_PIXELS })
    .resize({
      width: area.width,
      height: area.height,
      fit: 'contain',
      background: { r: 0, g: 0, b: 0, alpha: 0 },
      kernel: 'lanczos3',
    })
    .png()
    .withMetadata({ density: dpi })
    .toBuffer();
  return { png, fit };
}

/** Normalises any accepted upload to PNG (keeps alpha). SVG uploads are checked first. */
export async function normalizeUpload(buf: Buffer, svgWidth = 4500): Promise<Buffer> {
  const head = buf.subarray(0, 512).toString('utf8');
  if (/<svg[\s>]/i.test(head)) return svgToPng(buf.toString('utf8'), svgWidth);
  await inspectImage(buf);
  return sharp(buf, { limitInputPixels: MAX_INPUT_PIXELS }).png().toBuffer();
}
