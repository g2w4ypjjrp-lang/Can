import type pg from 'pg';
import {
  createAnthropic,
  emptyUsage,
  generateListingSeo,
  translateListing,
  type AiUsage,
} from '@esm/ai-engine';
import { normalizeTag, validateListingSeo, type SeoIssue } from '@esm/shared';
import { scanProtectedTerms } from '@esm/design-tools';
import { finishTask, startTask } from '../designs/jobs.js';
import { notifyAdmins } from '../etsy/sync.js';

export interface SeoDeps {
  anthropic: { apiKey: string; baseURL?: string | undefined } | null;
}

const LANG_NAMES: Record<string, string> = {
  en: 'English',
  de: 'German',
  fr: 'French',
  es: 'Spanish',
  it: 'Italian',
  pt: 'Portuguese',
  nl: 'Dutch',
  pl: 'Polish',
  ja: 'Japanese',
};

/** Tags: Etsy character set, ≤20 chars, unique, at most 13 (never invents tags). */
export function cleanTags(tags: string[]): string[] {
  const out: string[] = [];
  for (const t of tags) {
    const n = normalizeTag(t);
    if (n && !out.includes(n)) out.push(n);
    if (out.length === 13) break;
  }
  return out;
}

function ipIssues(text: string): SeoIssue[] {
  const hits = scanProtectedTerms(text);
  return hits.length
    ? [
        {
          field: 'title',
          code: 'protected_terms',
          severity: 'error',
          message: `Korumalı olabilecek ifadeler: ${hits.join(', ')}`,
        },
      ]
    : [];
}

interface Target {
  storeId: string;
  title: string;
  description: string | null;
  tags: string[];
  materials: string[];
  productType: string | null;
  designId: string | null;
  isPrintify: boolean;
}

async function loadTarget(
  pool: pg.Pool,
  draft: { listing_id: string | null; product_id: string | null },
): Promise<Target> {
  if (draft.listing_id) {
    const r = await pool.query(
      `select l.store_id, l.title, l.description, l.tags, l.materials, p.product_type, p.design_id,
              (p.printify_product_id is not null) as is_printify
         from public.listings l left join public.products p on p.id = l.product_id
        where l.id = $1`,
      [draft.listing_id],
    );
    const l = r.rows[0];
    if (!l) throw new Error('listing not found');
    return {
      storeId: l.store_id,
      title: l.title,
      description: l.description,
      tags: l.tags ?? [],
      materials: l.materials ?? [],
      productType: l.product_type,
      designId: l.design_id,
      isPrintify: Boolean(l.is_printify),
    };
  }
  const r = await pool.query(`select * from public.products where id = $1`, [draft.product_id]);
  const p = r.rows[0];
  if (!p) throw new Error('product not found');
  return {
    storeId: p.store_id,
    title: p.title,
    description: (p.metadata?.description as string | undefined) ?? null,
    tags: Array.isArray(p.metadata?.tags) ? (p.metadata.tags as string[]) : [],
    materials: [],
    productType: p.product_type,
    designId: p.design_id,
    isPrintify: Boolean(p.printify_product_id),
  };
}

/**
 * Generates an SEO draft: Claude proposes title/description/13 tags using the store's
 * real Etsy keyword data; the deterministic checker validates it and one repair round
 * is run when Etsy rules are broken. The draft is stored only — never sent anywhere.
 */
export async function generateSeoDraft(
  pool: pg.Pool,
  deps: SeoDeps,
  draftId: string,
  userId: string | null,
) {
  const draft = (await pool.query(`select * from public.seo_drafts where id = $1`, [draftId]))
    .rows[0];
  if (!draft) throw new Error('seo draft not found');
  if (draft.status !== 'generating') return { skipped: true, status: draft.status };
  if (!deps.anthropic) {
    await pool.query(`update public.seo_drafts set status = 'failed', error = $2 where id = $1`, [
      draftId,
      'ANTHROPIC_API_KEY tanımlı değil',
    ]);
    return { failed: true };
  }
  const t = await loadTarget(pool, draft);
  const design = t.designId
    ? (
        await pool.query(
          `select d.prompt, d.human_contribution,
                  exists (select 1 from public.design_versions v where v.design_id = d.id and v.operation = 'ai_generate') as ai_used,
                  (select v.generation_params->'textInDesign' from public.design_versions v
                    where v.design_id = d.id and v.operation = 'ai_generate' order by v.version desc limit 1) as text_in_design
             from public.designs d where d.id = $1`,
          [t.designId],
        )
      ).rows[0]
    : null;
  // real marketplace data first (Etsy API), then estimates; matched to the product words
  const words = `${t.title} ${t.productType ?? ''}`
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((w) => w.length > 2);
  const kw = (
    await pool.query(
      `select keyword, active_listings, avg_favorers, is_estimate from public.keywords
        where store_id = $1 and language = $2
          and ($3::text[] = '{}' or exists (select 1 from unnest($3::text[]) w where lower(keyword) like '%' || w || '%'))
        order by is_estimate asc, avg_favorers desc nulls last limit 15`,
      [t.storeId, draft.language, words],
    )
  ).rows;
  const disclosures: string[] = [];
  if (design?.ai_used)
    disclosures.push(
      'Design note: this artwork was created by our shop from our own concept, with the help of AI tools.',
    );
  if (t.isPrintify)
    disclosures.push('Made to order: printed and shipped by our production partner.');

  const taskId = await startTask(
    pool,
    t.storeId,
    'seo_generate',
    `seo_generate:${draftId}`,
    { draftId, language: draft.language },
    userId,
  );
  let usage: AiUsage = emptyUsage();
  try {
    const client = createAnthropic(deps.anthropic);
    let previousIssues: string[] | undefined;
    let result: {
      title: string;
      description: string;
      tags: string[];
      materials: string[];
      primaryKeyword: string;
      rationale: string;
    } | null = null;
    let report = validateListingSeo({ title: '', tags: [] });
    let issues: SeoIssue[] = [];
    for (let round = 0; round < 2; round++) {
      const out = await generateListingSeo(
        client,
        {
          language: LANG_NAMES[draft.language] ?? draft.language,
          product: {
            title: t.title,
            productType: t.productType,
            description: t.description,
            currentTags: t.tags,
            materials: t.materials,
          },
          design: design
            ? {
                brief: design.prompt,
                humanContribution: design.human_contribution,
                textInDesign: Array.isArray(design.text_in_design) ? design.text_in_design : [],
              }
            : null,
          keywords: kw.map((k) => ({
            keyword: k.keyword,
            activeListings: k.active_listings,
            avgFavorites: k.avg_favorers === null ? null : Number(k.avg_favorers),
            source: k.is_estimate ? 'estimate' : 'Etsy API data',
          })),
          disclosures,
          previousIssues,
        },
        usage,
      );
      usage = out.usage;
      result = {
        ...out.seo,
        title: out.seo.title.replace(/\s+/g, ' ').trim(),
        tags: cleanTags(out.seo.tags),
        materials: out.seo.materials
          .map((m) => m.trim())
          .filter(Boolean)
          .slice(0, 13),
      };
      report = validateListingSeo({ ...result, primaryKeyword: result.primaryKeyword });
      issues = [...report.issues, ...ipIssues(`${result.title} ${result.tags.join(' ')}`)];
      const errors = issues.filter((i) => i.severity === 'error');
      if (!errors.length) break;
      previousIssues = errors.map((e) => `${e.field}: ${e.message}`);
    }
    if (!result) throw new Error('no result');
    const blocking = issues.some((i) => i.severity === 'error');
    await pool.query(
      `update public.seo_drafts set status = 'draft', primary_keyword = $2, title = $3, description = $4, tags = $5,
              materials = $6, rationale = $7, seo_score = $8, issues = $9, baseline = $10, ai_task_id = $11, error = $12
        where id = $1`,
      [
        draftId,
        result.primaryKeyword,
        result.title.slice(0, 140),
        result.description,
        result.tags,
        result.materials,
        result.rationale,
        blocking ? Math.min(report.score, 49) : report.score,
        JSON.stringify(issues),
        JSON.stringify({
          title: t.title,
          description: t.description,
          tags: t.tags,
          materials: t.materials,
        }),
        taskId,
        blocking ? 'Etsy kurallarına uymayan alanlar var; düzenlemeden uygulanamaz.' : null,
      ],
    );
    await finishTask(pool, taskId, 'succeeded', usage, { draftId, score: report.score });
    await notifyAdmins(
      pool,
      t.storeId,
      'seo.generated',
      blocking ? 'warning' : 'success',
      'SEO önerisi hazır',
      `${t.title.slice(0, 80)} (${draft.language}) — puan ${report.score}`,
      draft.listing_id
        ? `/dashboard/etsy/listings/${draft.listing_id}`
        : `/dashboard/products/${draft.product_id}`,
    );
    return { draftId, score: report.score, issues: issues.length };
  } catch (err) {
    const message = err instanceof Error ? err.message.slice(0, 500) : String(err);
    await finishTask(pool, taskId, 'failed', usage, null, message);
    await pool.query(
      `update public.seo_drafts set status = 'failed', error = $2, ai_task_id = $3 where id = $1`,
      [draftId, message, taskId],
    );
    return { failed: true, error: message };
  }
}

const NUM = /\d+(?:[.,]\d+)?/g;

/** Facts that must survive translation: numbers and the printed design text. */
export function translationFactIssues(
  source: { description: string },
  translated: { title: string; description: string },
  printedText: string[],
): SeoIssue[] {
  const issues: SeoIssue[] = [];
  const norm = (s: string) => s.replace(',', '.');
  const srcNums = new Set((source.description.match(NUM) ?? []).map(norm));
  const dstNums = new Set((translated.description.match(NUM) ?? []).map(norm));
  const missing = [...srcNums].filter((n) => !dstNums.has(n));
  if (missing.length)
    issues.push({
      field: 'description',
      code: 'numbers_changed',
      severity: 'error',
      message: `Kaynaktaki sayılar çeviride yok: ${missing.slice(0, 6).join(', ')} (ölçü/adet bilgisi değişmiş olabilir)`,
    });
  const ratio = translated.description.length / Math.max(1, source.description.length);
  if (source.description.length > 100 && (ratio < 0.5 || ratio > 2))
    issues.push({
      field: 'description',
      code: 'length_mismatch',
      severity: 'warning',
      message: `Çeviri uzunluğu kaynağın ${ratio.toFixed(1)} katı; eksik veya eklenmiş içerik olabilir`,
    });
  const body = `${translated.title}\n${translated.description}`.toLowerCase();
  const lost = printedText.filter((p) => p.trim() && !body.includes(p.trim().toLowerCase()));
  if (lost.length)
    issues.push({
      field: 'description',
      code: 'printed_text_changed',
      severity: 'warning',
      message: `Ürün üzerindeki metin çeviride aynen geçmiyor: ${lost.join(', ')}`,
    });
  return issues;
}

/**
 * Localises a listing into one language with quality checks: Etsy rules, numbers/facts
 * preserved, printed text kept, and an English back-translation for human review.
 */
export async function generateTranslation(
  pool: pg.Pool,
  deps: SeoDeps,
  translationId: string,
  userId: string | null,
) {
  const tr = (
    await pool.query(`select * from public.listing_translations where id = $1`, [translationId])
  ).rows[0];
  if (!tr) throw new Error('translation not found');
  if (tr.status !== 'generating') return { skipped: true, status: tr.status };
  if (!deps.anthropic) {
    await pool.query(
      `update public.listing_translations set status = 'failed', error = $2 where id = $1`,
      [translationId, 'ANTHROPIC_API_KEY tanımlı değil'],
    );
    return { failed: true };
  }
  const l = (
    await pool.query(
      `select l.*, s.default_language,
              (select v.generation_params->'textInDesign' from public.design_versions v
                 join public.products p on p.design_id = v.design_id
                where p.id = l.product_id and v.operation = 'ai_generate' order by v.version desc limit 1) as printed
         from public.listings l join public.store_settings s on s.store_id = l.store_id
        where l.id = $1`,
      [tr.listing_id],
    )
  ).rows[0];
  if (!l) throw new Error('listing not found');
  const printed: string[] = Array.isArray(l.printed) ? l.printed : [];
  const source = {
    language: LANG_NAMES[l.default_language] ?? l.default_language,
    title: l.title,
    description: l.description ?? '',
    tags: l.tags ?? [],
  };
  const taskId = await startTask(
    pool,
    l.store_id,
    'seo_translate',
    `seo_translate:${translationId}`,
    { translationId, language: tr.language },
    userId,
  );
  let usage: AiUsage = emptyUsage();
  try {
    const client = createAnthropic(deps.anthropic);
    let previousIssues: string[] | undefined;
    let out: Awaited<ReturnType<typeof translateListing>>['translation'] | null = null;
    let tags: string[] = [];
    let issues: SeoIssue[] = [];
    let score = 0;
    for (let round = 0; round < 2; round++) {
      const r = await translateListing(
        client,
        {
          targetLanguage: LANG_NAMES[tr.language] ?? tr.language,
          source,
          printedText: printed,
          previousIssues,
        },
        usage,
      );
      usage = r.usage;
      out = r.translation;
      tags = cleanTags(out.tags);
      const rep = validateListingSeo({
        title: out.title.trim(),
        description: out.description,
        tags,
      });
      issues = [
        ...rep.issues,
        ...translationFactIssues(source, out, printed),
        ...ipIssues(`${out.title} ${tags.join(' ')}`),
      ];
      score =
        rep.score -
        issues
          .filter((i) => !rep.issues.includes(i))
          .reduce((s, i) => s + (i.severity === 'error' ? 25 : 8), 0);
      const errors = issues.filter((i) => i.severity === 'error');
      if (!errors.length) break;
      previousIssues = errors.map((e) => `${e.field}: ${e.message}`);
    }
    if (!out) throw new Error('no result');
    const blocking = issues.some((i) => i.severity === 'error');
    await pool.query(
      `update public.listing_translations set status = 'draft', title = $2, description = $3, tags = $4,
              quality_score = $5, quality_notes = $6, back_translation = $7, localization_notes = $8,
              ai_task_id = $9, source = 'ai', error = $10
        where id = $1`,
      [
        translationId,
        out.title.trim().slice(0, 140),
        out.description,
        tags,
        Math.max(0, Math.min(100, blocking ? Math.min(score, 49) : score)),
        JSON.stringify(issues),
        JSON.stringify(out.backTranslation),
        JSON.stringify(out.localizationNotes),
        taskId,
        blocking ? 'Kalite kontrolünden geçmeyen alanlar var; düzenleyin.' : null,
      ],
    );
    await finishTask(pool, taskId, 'succeeded', usage, { translationId, score });
    return { translationId, score, issues: issues.length };
  } catch (err) {
    const message = err instanceof Error ? err.message.slice(0, 500) : String(err);
    await finishTask(pool, taskId, 'failed', usage, null, message);
    await pool.query(
      `update public.listing_translations set status = 'failed', error = $2, ai_task_id = $3 where id = $1`,
      [translationId, message, taskId],
    );
    return { failed: true, error: message };
  }
}
