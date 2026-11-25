import { z } from 'zod';

/**
 * Listing edit proposal. Character rules come from the official Etsy OpenAPI
 * descriptions for updateListing (title / tags / materials regexes and the
 * "%, :, & and + only once" title rule). Count/length limits (140 title chars,
 * 13 tags, 20 chars per tag) follow Etsy's seller rules; Etsy remains the final
 * validator and its error is surfaced if it rejects a value.
 */
const TITLE_FORBIDDEN = /[^\p{L}\p{Nd}\p{P}\p{Sm}\p{Zs}™©®]/u;
const TAG_FORBIDDEN = /[^\p{L}\p{Nd}\p{Zs}\-'™©®]/u;
const MATERIAL_FORBIDDEN = /[^\p{L}\p{Nd}\p{Zs}]/u;

export const etsyTitleSchema = z
  .string()
  .trim()
  .min(1)
  .max(140, 'Başlık en fazla 140 karakter')
  .refine((t) => !TITLE_FORBIDDEN.test(t), 'Başlıkta izin verilmeyen karakter var')
  .refine(
    (t) => ['%', ':', '&', '+'].every((c) => t.split(c).length - 1 <= 1),
    '%, :, & ve + karakterleri en fazla birer kez kullanılabilir',
  );

export const etsyTagSchema = z
  .string()
  .trim()
  .min(1)
  .max(20, 'Etiket en fazla 20 karakter')
  .refine((t) => !TAG_FORBIDDEN.test(t), 'Etikette izin verilmeyen karakter var');

export const listingChangeRequestSchema = z
  .object({
    title: etsyTitleSchema.optional(),
    description: z.string().trim().min(1).max(50_000).optional(),
    tags: z
      .array(etsyTagSchema)
      .max(13, 'En fazla 13 etiket')
      .refine(
        (t) => new Set(t.map((x) => x.toLowerCase())).size === t.length,
        'Etiketler tekrar edemez',
      )
      .optional(),
    materials: z
      .array(
        z
          .string()
          .trim()
          .min(1)
          .max(45)
          .refine((m) => !MATERIAL_FORBIDDEN.test(m), 'Geçersiz malzeme'),
      )
      .max(13)
      .optional(),
    state: z.enum(['active', 'inactive']).optional(),
    reason: z.string().trim().min(3, 'Değişiklik gerekçesi yazın').max(1000),
  })
  .strict()
  .refine(
    (v) =>
      ['title', 'description', 'tags', 'materials', 'state'].some(
        (k) => v[k as keyof typeof v] !== undefined,
      ),
    'En az bir alan değişmeli',
  );
export type ListingChangeRequest = z.infer<typeof listingChangeRequestSchema>;

export interface ListingDto {
  id: string;
  etsyListingId: string | null;
  state: string;
  title: string;
  description: string | null;
  tags: string[];
  materials: string[];
  price: string | null;
  currency: string | null;
  quantity: number | null;
  numFavorers: number | null;
  etsyUrl: string | null;
  primaryImageUrl: string | null;
  dataOrigin: string;
  lastSyncedAt: string | null;
  etsyUpdatedAt: string | null;
}

export interface ApprovalDto {
  id: string;
  actionType: string;
  status: string;
  title: string;
  what: string;
  why: string;
  expectedBenefit: string | null;
  estimatedCost: string | null;
  costCurrency: string | null;
  profitImpact: string | null;
  apiOperation: string;
  riskLevel: string;
  requiresReauth: boolean;
  requestedByType: string;
  payload: Record<string, unknown>;
  createdAt: string;
  decidedAt: string | null;
  decisionNote: string | null;
  executedAt: string | null;
  executionResult: Record<string, unknown> | null;
  expiresAt: string | null;
}

export interface EtsyConnectionDto {
  configured: boolean;
  missingConfig: string[];
  status: 'not_connected' | 'pending' | 'active' | 'expired' | 'revoked' | 'error';
  shopId: string | null;
  shopName: string | null;
  shopUrl: string | null;
  scopes: string[];
  lastSyncedAt: string | null;
  lastError: string | null;
  tokenExpiresAt: string | null;
  counts: { listings: number; orders: number };
  unsupportedOperations: Record<string, string>;
}
