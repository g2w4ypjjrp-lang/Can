import { describe, expect, it } from 'vitest';
import sharp from 'sharp';
import {
  assertSafeSvg,
  evaluatePrintFit,
  inspectImage,
  normalizeUpload,
  prepareForPrintArea,
  removeUniformBackground,
  scanProtectedTerms,
  svgToPng,
} from '@esm/design-tools';

const SAFE =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 120"><circle cx="50" cy="50" r="40" fill="#f00"/><text x="50" y="110" font-family="sans-serif">HI</text></svg>';

describe('SVG safety (librsvg must never read files/URLs)', () => {
  it('accepts plain vector art', () => expect(() => assertSafeSvg(SAFE)).not.toThrow());
  it.each([
    ['<svg xmlns="http://www.w3.org/2000/svg"><image href="file:///etc/passwd"/></svg>', 'görsel'],
    ['<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', 'script'],
    [
      '<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg>&x;</svg>',
      'DOCTYPE',
    ],
    ['<svg xmlns="http://www.w3.org/2000/svg"><rect fill="url(http://evil/x)"/></svg>', 'url'],
    ['<svg xmlns="http://www.w3.org/2000/svg"><use href="other.svg#a"/></svg>', 'use'],
    ['<svg xmlns="http://www.w3.org/2000/svg" onload="x()"></svg>', 'olay'],
    ['<svg xmlns="http://www.w3.org/2000/svg"><foreignObject/></svg>', 'foreignObject'],
    ['<svg xmlns="http://www.w3.org/2000/svg"><style>@import url(x.css);</style></svg>', 'import'],
    ['<html><svg/></html>', 'SVG değil'],
  ])('rejects %s', (svg, msg) => expect(() => assertSafeSvg(svg)).toThrow(new RegExp(msg)));
  it('allows internal #references (gradients)', () => {
    expect(() =>
      assertSafeSvg(
        '<svg xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="g"/></defs><rect fill="url(#g)"/></svg>',
      ),
    ).not.toThrow();
  });
});

describe('rasterisation and print preparation', () => {
  it('renders SVG to a transparent PNG at print width with 300 DPI metadata', async () => {
    const png = await svgToPng(SAFE, 1500);
    const info = await inspectImage(png);
    expect(info).toMatchObject({
      format: 'png',
      width: 1500,
      height: 1800,
      hasAlpha: true,
      density: 300,
    });
  });
  it('evaluates print fit: ok / low resolution / too low', () => {
    expect(
      evaluatePrintFit({ width: 4500, height: 5400 }, { width: 4500, height: 5400 }),
    ).toMatchObject({ status: 'ok', scale: 1, coverage: 1 });
    expect(
      evaluatePrintFit({ width: 2250, height: 2700 }, { width: 4500, height: 5400 }),
    ).toMatchObject({ status: 'low_resolution', effectiveDpi: 150, upscaled: true });
    expect(
      evaluatePrintFit({ width: 900, height: 1080 }, { width: 4500, height: 5400 }),
    ).toMatchObject({ status: 'too_low', effectiveDpi: 60 });
    expect(
      evaluatePrintFit({ width: 5400, height: 5400 }, { width: 4500, height: 5400 }).coverage,
    ).toBeCloseTo(0.833, 2);
  });
  it('prepares an exact-size print file with transparent padding', async () => {
    const src = await sharp({
      create: {
        width: 1000,
        height: 500,
        channels: 4,
        background: { r: 255, g: 0, b: 0, alpha: 1 },
      },
    })
      .png()
      .toBuffer();
    const { png, fit } = await prepareForPrintArea(src, { width: 2700, height: 1200 });
    const info = await inspectImage(png);
    expect([info.width, info.height, info.density]).toEqual([2700, 1200, 300]);
    expect(fit).toMatchObject({ status: 'too_low', effectiveDpi: 125 }); // scale 2.4 → 300/2.4
    const { data } = await sharp(png).raw().toBuffer({ resolveWithObject: true });
    expect(data[3]).toBe(0); // left padding is transparent
  });
});

describe('background removal', () => {
  it('removes the edge-connected background but keeps enclosed areas of the same colour', async () => {
    // white canvas, red ring, white inside the ring
    const svg =
      '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect width="200" height="200" fill="#fff"/><circle cx="100" cy="100" r="60" fill="none" stroke="#f00" stroke-width="20"/></svg>';
    const src = await sharp(Buffer.from(svg)).png().toBuffer();
    const { png, removedRatio, background } = await removeUniformBackground(src);
    expect(background).toEqual([255, 255, 255]);
    expect(removedRatio).toBeGreaterThan(0.5);
    const { data, info } = await sharp(png).raw().toBuffer({ resolveWithObject: true });
    const alpha = (x: number, y: number) => data[(y * info.width + x) * 4 + 3];
    expect(alpha(2, 2)).toBe(0); // corner removed
    expect(alpha(100, 100)).toBe(255); // inside the ring kept
    expect(alpha(100, 40)).toBe(255); // the ring itself kept
  });
});

describe('uploads and IP pre-check', () => {
  it('normalises JPEG/SVG uploads to PNG and rejects non-images', async () => {
    const jpg = await sharp({ create: { width: 10, height: 10, channels: 3, background: '#0f0' } })
      .jpeg()
      .toBuffer();
    expect((await inspectImage(await normalizeUpload(jpg))).format).toBe('png');
    expect((await inspectImage(await normalizeUpload(Buffer.from(SAFE), 600))).width).toBe(600);
    await expect(normalizeUpload(Buffer.from('not an image at all'))).rejects.toThrow();
  });
  it('flags obvious protected names (pre-check only)', () => {
    expect(scanProtectedTerms('Cute Pikachu birthday shirt')).toEqual(['pikachu']);
    expect(scanProtectedTerms('Retro Star Wars style mug')).toContain('star wars');
    expect(scanProtectedTerms('Plant mom botanical line art')).toEqual([]);
    expect(scanProtectedTerms('marionette puppet')).toEqual([]); // no partial-word false positive for "mario"
  });
});
