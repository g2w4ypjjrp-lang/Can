import type Anthropic from '@anthropic-ai/sdk';
import { z } from 'zod';
import { zodOutputFormat } from '@anthropic-ai/sdk/helpers/zod';
import { addUsage, AI_MODEL, AiRefusalError, emptyUsage, type AiUsage } from './client.js';

export const ListingSeoSchema = z.object({
  primaryKeyword: z.string().describe('The main buyer search phrase this listing targets'),
  title: z.string().describe('Etsy title, max 140 characters'),
  description: z.string().describe('Full listing description, plain text with line breaks'),
  tags: z.array(z.string()).describe('Exactly 13 distinct tags, each max 20 characters'),
  materials: z.array(z.string()).describe('Materials, letters/digits/spaces only; may be empty'),
  rationale: z.string().describe('Turkish; why these keywords, which data supports them'),
});
export type ListingSeo = z.infer<typeof ListingSeoSchema>;

const SEO_SYSTEM = `You write Etsy listing content (title, description, 13 tags) that ranks in Etsy search AND converts.
Etsy rules you must follow:
- Title <= 140 characters, leads with the clearest buyer search phrase; natural language, not a list of keywords.
  Never repeat the same word more than twice. Use %, :, &, + at most once each. No emojis, no ALL CAPS.
- Exactly 13 tags, each <= 20 characters, only letters, digits, spaces, - and '. Multi-word long-tail phrases;
  no duplicates; do not repeat the same word in most tags; tags complement the title instead of copying it.
- Materials contain only letters, digits and spaces.
- No unverifiable claims ("best seller", "#1", "free shipping", "sale", "limited time"), no other brands,
  trademarks, franchises, characters or celebrities, no misleading statements.
- Description: first sentence describes the item with the primary phrase; then key details as short paragraphs or
  "- " bullet lines: design, material/product specifics given to you, sizing/care if provided, personalisation if
  offered, shipping/production note if provided. Never invent facts (sizes, materials, delivery times) that are
  not in the input. Include every disclosure line given in the input (translated into the listing language, same meaning).
- Write in the requested language for the target buyers.
Use the provided keyword data (real Etsy marketplace metrics where marked) to choose phrases; prefer phrases with
demand and moderate competition.`;

/** Generates SEO content for one listing in one language (structured output). */
export async function generateListingSeo(
  client: Anthropic,
  input: {
    language: string;
    product: {
      title: string;
      productType?: string | null;
      description?: string | null;
      currentTags?: string[];
      materials?: string[];
      personalization?: boolean;
      facts?: string[];
    };
    design?: {
      brief?: string | null;
      humanContribution?: string | null;
      textInDesign?: string[];
    } | null;
    keywords: Array<{
      keyword: string;
      activeListings?: number | null;
      avgFavorites?: number | null;
      source: string;
    }>;
    disclosures: string[];
    /** Issues from the deterministic checker on a previous attempt (repair round). */
    previousIssues?: string[];
  },
  usage: AiUsage = emptyUsage(),
): Promise<{ seo: ListingSeo; usage: AiUsage }> {
  const lines = [
    `Language: ${input.language}`,
    `Product: ${input.product.title}${input.product.productType ? ` (${input.product.productType})` : ''}`,
    input.product.description
      ? `Current description:\n${input.product.description.slice(0, 4000)}`
      : '',
    input.product.currentTags?.length
      ? `Current tags: ${input.product.currentTags.join(', ')}`
      : '',
    input.product.materials?.length ? `Materials: ${input.product.materials.join(', ')}` : '',
    input.product.facts?.length
      ? `Verified product facts:\n- ${input.product.facts.join('\n- ')}`
      : '',
    input.product.personalization ? 'Personalisation is offered.' : '',
    input.design?.brief ? `Design concept: ${input.design.brief}` : '',
    input.design?.humanContribution
      ? `Shop owner's creative direction: ${input.design.humanContribution}`
      : '',
    input.design?.textInDesign?.length
      ? `Text printed on the design: ${input.design.textInDesign.join(' / ')}`
      : '',
    input.keywords.length
      ? `Keyword data:\n${input.keywords
          .map(
            (k) =>
              `- "${k.keyword}"${k.activeListings != null ? ` active listings ${k.activeListings}` : ''}${
                k.avgFavorites != null ? `, avg favourites ${k.avgFavorites}` : ''
              } [${k.source}]`,
          )
          .join('\n')}`
      : 'No keyword data available; infer buyer phrases from the product.',
    input.disclosures.length ? `Disclosure lines to include:\n${input.disclosures.join('\n')}` : '',
    input.previousIssues?.length
      ? `Your previous attempt failed these checks; fix all of them:\n- ${input.previousIssues.join('\n- ')}`
      : '',
  ].filter(Boolean);
  const res = await client.messages.parse({
    model: AI_MODEL,
    max_tokens: 8000,
    output_config: { effort: 'medium', format: zodOutputFormat(ListingSeoSchema) },
    system: SEO_SYSTEM,
    messages: [{ role: 'user', content: lines.join('\n\n') }],
  });
  const acc = addUsage(usage, res.usage, AI_MODEL);
  if (res.stop_reason === 'refusal') throw new AiRefusalError(res.stop_details?.category ?? null);
  if (!res.parsed_output) throw new Error(`SEO çıktısı alınamadı (stop_reason=${res.stop_reason})`);
  return { seo: res.parsed_output, usage: acc };
}

export const TranslationSchema = z.object({
  title: z.string(),
  description: z.string(),
  tags: z.array(z.string()).describe('13 tags in the target language, each max 20 characters'),
  backTranslation: z
    .object({ title: z.string(), description: z.string() })
    .describe('Literal English back-translation of YOUR title and description, for quality review'),
  localizationNotes: z
    .array(z.string())
    .describe('Turkish; terms adapted for local buyers, units/sizes, anything uncertain'),
});
export type ListingTranslation = z.infer<typeof TranslationSchema>;

const TRANSLATE_SYSTEM = `You localise Etsy listings for buyers in another language. Translate meaning, not words:
use the phrases local buyers actually search for (tags are re-researched for the target language, not translated
literally). Keep all facts exactly as in the source: never add or drop materials, sizes, quantities, delivery or
personalisation details. Keep disclosure lines with the same meaning. Do not translate brand-like design text that is
printed on the product (quote it as is). Same Etsy rules as the source: title <= 140 characters, no word more than
twice, 13 tags <= 20 characters with only letters, digits, spaces, - and ', no unverifiable claims.`;

export async function translateListing(
  client: Anthropic,
  input: {
    targetLanguage: string;
    source: { language: string; title: string; description: string; tags: string[] };
    printedText?: string[];
    previousIssues?: string[];
  },
  usage: AiUsage = emptyUsage(),
): Promise<{ translation: ListingTranslation; usage: AiUsage }> {
  const content = [
    `Target language: ${input.targetLanguage}`,
    `Source (${input.source.language}) title: ${input.source.title}`,
    `Source description:\n${input.source.description.slice(0, 6000)}`,
    `Source tags: ${input.source.tags.join(', ')}`,
    input.printedText?.length
      ? `Text printed on the product (keep as is): ${input.printedText.join(' / ')}`
      : '',
    input.previousIssues?.length
      ? `Your previous attempt failed these checks; fix all of them:\n- ${input.previousIssues.join('\n- ')}`
      : '',
  ]
    .filter(Boolean)
    .join('\n\n');
  const res = await client.messages.parse({
    model: AI_MODEL,
    max_tokens: 8000,
    output_config: { effort: 'medium', format: zodOutputFormat(TranslationSchema) },
    system: TRANSLATE_SYSTEM,
    messages: [{ role: 'user', content }],
  });
  const acc = addUsage(usage, res.usage, AI_MODEL);
  if (res.stop_reason === 'refusal') throw new AiRefusalError(res.stop_details?.category ?? null);
  if (!res.parsed_output)
    throw new Error(`Çeviri çıktısı alınamadı (stop_reason=${res.stop_reason})`);
  return { translation: res.parsed_output, usage: acc };
}
