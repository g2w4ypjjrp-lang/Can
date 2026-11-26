import type Anthropic from '@anthropic-ai/sdk';
import { z } from 'zod';
import { zodOutputFormat } from '@anthropic-ai/sdk/helpers/zod';
import { addUsage, AI_MODEL, AiRefusalError, emptyUsage, type AiUsage } from './client.js';

export const TriageSchema = z.object({
  category: z.enum(['question', 'complaint', 'return', 'shipping', 'personalization', 'other']),
  sentiment: z.enum(['positive', 'neutral', 'negative']),
  urgency: z
    .enum(['low', 'normal', 'high', 'critical'])
    .describe('critical = legal threat, chargeback, safety; high = angry or time-sensitive'),
  issues: z
    .array(
      z.enum([
        'late_delivery',
        'damaged',
        'wrong_item',
        'quality',
        'size_fit',
        'personalization_error',
        'missing_item',
        'tracking',
        'refund_request',
        'cancel_request',
        'other',
      ]),
    )
    .max(5),
  suggestedAction: z.enum([
    'reply',
    'refund',
    'replacement',
    'shipping_check',
    'personalization_fix',
    'none',
  ]),
  language: z.string().describe('ISO 639-1 code of the customer message'),
  replyDraft: z
    .string()
    .describe("Reply in the customer's language, ready for the seller to review"),
  internalNote: z
    .string()
    .describe('Turkish; what happened, what the seller should check or decide'),
});
export type Triage = z.infer<typeof TriageSchema>;

const SYSTEM = `You help an Etsy print-on-demand seller handle customer messages and reviews.
Classify the message and draft a reply for the SELLER TO REVIEW (it is never sent automatically).
Rules for the reply draft:
- Write in the customer's language, warm, short and specific; thank them and acknowledge the issue.
- Use ONLY the order facts provided. Never invent tracking numbers, dates, delivery promises or policies.
- Never promise a refund, replacement, discount or cancellation — say the seller will check and come back,
  unless the facts say it was already done. Refunds and replacements need the seller's approval.
- Do not ask for personal data beyond the order details Etsy already has; never ask the buyer to contact off Etsy.
- For a public review reply: polite, no blame, no private order details, invite them to message the shop.
- No legal admissions; if there is a legal threat or chargeback mention set urgency=critical.`;

export async function triageCustomerMessage(
  client: Anthropic,
  input: { shopName: string; message: string; facts: string[]; isPublicReview: boolean },
  usage: AiUsage = emptyUsage(),
): Promise<{ triage: Triage; usage: AiUsage }> {
  const res = await client.messages.parse({
    model: AI_MODEL,
    max_tokens: 4000,
    output_config: { effort: 'medium', format: zodOutputFormat(TriageSchema) },
    system: SYSTEM,
    messages: [
      {
        role: 'user',
        content: [
          `Shop: ${input.shopName}`,
          input.isPublicReview ? 'Type: public Etsy review' : 'Type: private customer message',
          `Order facts:\n- ${input.facts.join('\n- ') || 'none'}`,
          `Customer text:\n"""${input.message.slice(0, 6000)}"""`,
        ].join('\n\n'),
      },
    ],
  });
  const acc = addUsage(usage, res.usage, AI_MODEL);
  if (res.stop_reason === 'refusal') throw new AiRefusalError(res.stop_details?.category ?? null);
  if (!res.parsed_output)
    throw new Error(`Sınıflandırma çıktısı alınamadı (stop_reason=${res.stop_reason})`);
  return { triage: res.parsed_output, usage: acc };
}
