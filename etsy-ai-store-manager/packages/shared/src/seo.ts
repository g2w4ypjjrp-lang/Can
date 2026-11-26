/**
 * Deterministic Etsy listing-content checks (no AI). The character rules come from the
 * Etsy Open API v3 schema for createDraftListing / updateListing:
 *  - title:  /[^\p{L}\p{Nd}\p{P}\p{Sm}\p{Zs}™©®]/u is invalid; %, :, & and + at most once each
 *  - tags:   /[^\p{L}\p{Nd}\p{Zs}\-'™©®]/u is invalid
 *  - materials: /[^\p{L}\p{Nd}\p{Zs}]/u is invalid
 * Length limits (title 140, 13 tags, 20 characters per tag) are Etsy's published listing
 * limits and are also enforced by the listings table constraints.
 * The spam checks implement Etsy's guidance against keyword stuffing / repetition.
 */
export const ETSY_SEO_LIMITS = {
  titleMax: 140,
  tagsMax: 13,
  tagMax: 20,
  materialsMax: 13,
  materialMax: 45,
} as const;

const TITLE_INVALID = /[^\p{L}\p{Nd}\p{P}\p{Sm}\p{Zs}™©®]/gu;
const TAG_INVALID = /[^\p{L}\p{Nd}\p{Zs}\-'™©®]/gu;
const MATERIAL_INVALID = /[^\p{L}\p{Nd}\p{Zs}]/gu;
const ONCE_ONLY = ['%', ':', '&', '+'] as const;

export type SeoSeverity = 'error' | 'warning' | 'info';
export interface SeoIssue {
  field: 'title' | 'description' | 'tags' | 'materials';
  code: string;
  severity: SeoSeverity;
  message: string;
}
export interface SeoInput {
  title: string;
  description?: string | null;
  tags: string[];
  materials?: string[];
  /** Primary search phrase the listing targets (optional; improves the checks). */
  primaryKeyword?: string | null;
}
export interface SeoReport {
  /** 0-100; errors make the content unpublishable regardless of score. */
  score: number;
  publishable: boolean;
  issues: SeoIssue[];
}

/** Words that carry no search value when repeated (English + main store languages). */
const STOPWORDS = new Set(
  'a an and the for of with in on to by or & + - für und mit der die das le la les et pour de des el los las y para con il e per di een het voor met en z na i dla do'.split(
    ' ',
  ),
);
/** Superlatives / claims Etsy shoppers and policies treat as spam or unverifiable. */
const SPAM_PHRASES = [
  'best seller',
  'bestseller',
  'best gift ever',
  '100% guaranteed',
  'free shipping',
  'sale',
  'cheap',
  'limited time',
  'hot item',
  'trending now',
  'top rated',
  'number 1',
  '#1',
];

const words = (s: string) =>
  s
    .toLocaleLowerCase()
    .split(/[^\p{L}\p{Nd}']+/u)
    .filter((w) => w.length > 1 && !STOPWORDS.has(w));

/** Cleans a tag to Etsy's allowed character set and length (never invents content). */
export function normalizeTag(tag: string): string {
  return tag
    .replace(TAG_INVALID, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLocaleLowerCase()
    .slice(0, ETSY_SEO_LIMITS.tagMax)
    .trim();
}

export function validateListingSeo(input: SeoInput): SeoReport {
  const issues: SeoIssue[] = [];
  const add = (field: SeoIssue['field'], code: string, severity: SeoSeverity, message: string) =>
    issues.push({ field, code, severity, message });
  const title = input.title ?? '';
  const desc = input.description ?? '';
  const tags = input.tags ?? [];
  const materials = input.materials ?? [];
  const kw = input.primaryKeyword?.trim().toLocaleLowerCase() || null;

  // ---- title
  if (!title.trim()) add('title', 'title_empty', 'error', 'Başlık boş olamaz');
  if (title.length > ETSY_SEO_LIMITS.titleMax)
    add('title', 'title_too_long', 'error', `Başlık ${title.length}/140 karakter`);
  const badTitle = [...new Set(title.match(TITLE_INVALID) ?? [])];
  if (badTitle.length)
    add(
      'title',
      'title_invalid_chars',
      'error',
      `Etsy’nin kabul etmediği karakterler: ${badTitle.join(' ')}`,
    );
  for (const ch of ONCE_ONLY) {
    if (title.split(ch).length - 1 > 1)
      add(
        'title',
        'title_char_repeat',
        'error',
        `"${ch}" başlıkta yalnızca bir kez kullanılabilir`,
      );
  }
  const tw = words(title);
  const counts = new Map<string, number>();
  for (const w of tw) counts.set(w, (counts.get(w) ?? 0) + 1);
  const stuffed = [...counts].filter(([, n]) => n > 2).map(([w]) => w);
  if (stuffed.length)
    add(
      'title',
      'title_keyword_stuffing',
      'error',
      `Aynı kelime 2’den fazla tekrar ediyor: ${stuffed.join(', ')}`,
    );
  else if ([...counts.values()].some((n) => n === 2))
    add(
      'title',
      'title_repetition',
      'warning',
      'Başlıkta tekrar eden kelime var; tek kullanım yeterli',
    );
  const upperWords = title
    .split(/\s+/)
    .filter((w) => w.length > 3 && w === w.toLocaleUpperCase() && /\p{Lu}/u.test(w));
  if (upperWords.length >= 3)
    add(
      'title',
      'title_all_caps',
      'warning',
      'Çok sayıda TAMAMI BÜYÜK HARF kelime (spam gibi görünür)',
    );
  if (title.length > 0 && title.length < 40)
    add('title', 'title_short', 'info', 'Başlık kısa; ürünü tanımlayan 1-2 ifade daha eklenebilir');
  if (kw && !title.toLocaleLowerCase().slice(0, 70).includes(kw))
    add('title', 'title_keyword_position', 'warning', 'Ana anahtar kelime başlığın başında değil');

  // ---- tags
  if (tags.length > ETSY_SEO_LIMITS.tagsMax)
    add('tags', 'tags_too_many', 'error', `${tags.length} etiket; en fazla 13`);
  if (tags.length < ETSY_SEO_LIMITS.tagsMax)
    add('tags', 'tags_unused_slots', 'warning', `${13 - tags.length} boş etiket hakkı`);
  const seen = new Set<string>();
  for (const t of tags) {
    if (t.length > ETSY_SEO_LIMITS.tagMax)
      add('tags', 'tag_too_long', 'error', `"${t}" ${t.length}/20 karakter`);
    const bad = [...new Set(t.match(TAG_INVALID) ?? [])];
    if (bad.length)
      add('tags', 'tag_invalid_chars', 'error', `"${t}" geçersiz karakter: ${bad.join(' ')}`);
    const k = t.trim().toLocaleLowerCase();
    if (!k) add('tags', 'tag_empty', 'error', 'Boş etiket');
    if (seen.has(k)) add('tags', 'tag_duplicate', 'error', `"${t}" tekrar ediyor`);
    seen.add(k);
  }
  const tagWordCounts = new Map<string, number>();
  for (const t of seen)
    for (const w of new Set(words(t))) tagWordCounts.set(w, (tagWordCounts.get(w) ?? 0) + 1);
  const overused = [...tagWordCounts].filter(([, n]) => n > 4).map(([w]) => w);
  if (overused.length)
    add(
      'tags',
      'tags_word_overuse',
      'warning',
      `Şu kelime 4’ten fazla etikette: ${overused.join(', ')} (çeşitlilik görünürlüğü artırır)`,
    );
  const singleWord = [...seen].filter((t) => !/\s/.test(t)).length;
  if (seen.size >= 6 && singleWord > seen.size / 2)
    add(
      'tags',
      'tags_single_words',
      'info',
      'Etiketlerin çoğu tek kelime; çok kelimeli ifadeler (long-tail) daha isabetli eşleşir',
    );

  // ---- spam phrases anywhere
  const all = `${title}\n${tags.join('\n')}`.toLocaleLowerCase();
  const spam = SPAM_PHRASES.filter((p) =>
    new RegExp(`(^|[^\\p{L}])${p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}([^\\p{L}]|$)`, 'u').test(
      all,
    ),
  );
  if (spam.length)
    add('title', 'spam_phrases', 'warning', `Kanıtlanamayan / spam ifadeler: ${spam.join(', ')}`);

  // ---- description
  if (!desc.trim()) add('description', 'description_empty', 'error', 'Açıklama boş olamaz');
  else {
    if (desc.length < 300)
      add(
        'description',
        'description_short',
        'warning',
        'Açıklama kısa (300+ karakter; malzeme, ölçü, bakım, kişiselleştirme önerilir)',
      );
    if (kw && !desc.slice(0, 160).toLocaleLowerCase().includes(kw))
      add(
        'description',
        'description_keyword_intro',
        'info',
        'Ana anahtar kelime ilk cümlede geçmiyor',
      );
    const dw = words(desc);
    if (dw.length > 40) {
      const dc = new Map<string, number>();
      for (const w of dw) dc.set(w, (dc.get(w) ?? 0) + 1);
      const top = [...dc].sort((a, b) => b[1] - a[1])[0];
      if (top && top[1] / dw.length > 0.08 && top[1] > 6)
        add(
          'description',
          'description_stuffing',
          'warning',
          `"${top[0]}" açıklamada aşırı tekrar ediyor`,
        );
    }
  }

  // ---- materials
  if (materials.length > ETSY_SEO_LIMITS.materialsMax)
    add('materials', 'materials_too_many', 'error', 'En fazla 13 malzeme');
  for (const m of materials) {
    if ((m.match(MATERIAL_INVALID) ?? []).length)
      add(
        'materials',
        'material_invalid_chars',
        'error',
        `"${m}" yalnızca harf, rakam ve boşluk içerebilir`,
      );
    if (m.length > ETSY_SEO_LIMITS.materialMax)
      add('materials', 'material_too_long', 'error', `"${m}" çok uzun`);
  }

  const penalty = issues.reduce(
    (s, i) => s + (i.severity === 'error' ? 25 : i.severity === 'warning' ? 8 : 2),
    0,
  );
  const unused = Math.max(0, 13 - tags.length);
  return {
    score: Math.max(0, Math.min(100, 100 - penalty - unused * 1)),
    publishable: !issues.some((i) => i.severity === 'error'),
    issues,
  };
}
