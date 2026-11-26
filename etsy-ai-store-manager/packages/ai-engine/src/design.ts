import type Anthropic from '@anthropic-ai/sdk';
import { z } from 'zod';
import { zodOutputFormat } from '@anthropic-ai/sdk/helpers/zod';
import { addUsage, AI_MODEL, AiRefusalError, emptyUsage, type AiUsage } from './client.js';

export const SvgDesignSchema = z.object({
  svg: z.string().describe('A complete standalone SVG document'),
  title: z.string().describe('Short English design title'),
  description: z.string().describe('Turkish description of the design for the shop owner'),
  textInDesign: z.array(z.string()).describe('Every word/phrase rendered in the design'),
  palette: z.array(z.string()).describe('Hex colours used'),
});
export type SvgDesign = z.infer<typeof SvgDesignSchema>;

const DESIGN_SYSTEM = `You are a print-on-demand graphic designer producing ORIGINAL vector artwork as SVG.
Hard rules for the SVG (it is rendered by librsvg on a server):
- One standalone <svg> root with xmlns="http://www.w3.org/2000/svg" and a viewBox; transparent background (no full-canvas rect).
- Only shapes, paths, groups, gradients and <text>. No <image>, <script>, <foreignObject>, <use>, no external URLs, no href
  except "#id" references, no CSS @import, no event attributes, no DOCTYPE/ENTITY.
- Text: generic font families only (serif, sans-serif, monospace, cursive) or convert lettering to paths.
- Bold, print-friendly shapes; at most 6 colours; keep strokes >= 2% of the width so they survive printing.
Content rules:
- The design must be original. Never use or imitate brands, logos, trademarks, franchises, characters, sports teams,
  celebrities, song lyrics or other people's artwork.
- Follow the shop owner's creative direction precisely; it is the human contribution to this design.`;

/** Generates an original SVG design from a human creative brief (structured output). */
export async function generateSvgDesign(
  client: Anthropic,
  input: {
    brief: string;
    humanContribution: string;
    productType: string;
    aspect: { width: number; height: number };
    style?: string | null;
  },
  usage: AiUsage = emptyUsage(),
): Promise<{ design: SvgDesign; usage: AiUsage }> {
  const res = await client.messages.parse({
    model: AI_MODEL,
    max_tokens: 32000,
    output_config: { effort: 'high', format: zodOutputFormat(SvgDesignSchema) },
    system: DESIGN_SYSTEM,
    messages: [
      {
        role: 'user',
        content: [
          `Product: ${input.productType}. Print area aspect ratio ${input.aspect.width}:${input.aspect.height}; use viewBox "0 0 ${input.aspect.width} ${input.aspect.height}".`,
          `Design brief: ${input.brief}`,
          `Shop owner's creative direction (must be followed): ${input.humanContribution}`,
          input.style ? `Style: ${input.style}` : '',
        ]
          .filter(Boolean)
          .join('\n'),
      },
    ],
  });
  const acc = addUsage(usage, res.usage, AI_MODEL);
  if (res.stop_reason === 'refusal') throw new AiRefusalError(res.stop_details?.category ?? null);
  if (!res.parsed_output)
    throw new Error(`Tasarım çıktısı alınamadı (stop_reason=${res.stop_reason})`);
  return { design: res.parsed_output, usage: acc };
}

export const IpReviewSchema = z.object({
  riskLevel: z.enum(['low', 'medium', 'high']),
  findings: z
    .array(
      z.object({
        issue: z
          .string()
          .describe(
            'Turkish; what could infringe (trademark, logo, character, person, copied artwork, slogan)',
          ),
        severity: z.enum(['low', 'medium', 'high']),
      }),
    )
    .max(10),
  textDetected: z.array(z.string()),
  recommendation: z.string().describe('Turkish; what to change before selling'),
});
export type IpReview = z.infer<typeof IpReviewSchema>;

/**
 * Vision review of a design for trademark / copyright / personality-rights risk.
 * Advisory only — not legal advice; the owner decides.
 */
export async function reviewDesignIp(
  client: Anthropic,
  input: { pngBase64: string; title: string; prompt: string | null; localHits: string[] },
  usage: AiUsage = emptyUsage(),
): Promise<{ review: IpReview; usage: AiUsage }> {
  const res = await client.messages.parse({
    model: AI_MODEL,
    max_tokens: 8000,
    output_config: { effort: 'medium', format: zodOutputFormat(IpReviewSchema) },
    system:
      'You review print-on-demand designs before they are sold on Etsy. Identify anything that could infringe trademarks, ' +
      'copyrights or personality rights: brand names or logos, franchise characters or their recognisable traits, sports teams, ' +
      'real people, famous quotes or lyrics, or an obvious copy of a known artwork. Generic words, common phrases and generic ' +
      'motifs are low risk. Be specific; do not invent issues. Answer in Turkish.',
    messages: [
      {
        role: 'user',
        content: [
          {
            type: 'image',
            source: { type: 'base64', media_type: 'image/png', data: input.pngBase64 },
          },
          {
            type: 'text',
            text: `Design title: ${input.title}\nPrompt/brief: ${input.prompt ?? '-'}\nLocal keyword pre-check hits: ${input.localHits.join(', ') || 'none'}`,
          },
        ],
      },
    ],
  });
  const acc = addUsage(usage, res.usage, AI_MODEL);
  if (res.stop_reason === 'refusal') throw new AiRefusalError(res.stop_details?.category ?? null);
  if (!res.parsed_output)
    throw new Error(`IP incelemesi alınamadı (stop_reason=${res.stop_reason})`);
  return { review: res.parsed_output, usage: acc };
}
