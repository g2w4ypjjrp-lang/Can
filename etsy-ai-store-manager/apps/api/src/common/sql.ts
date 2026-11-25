import type { Queryable } from '../database/database.service.js';

/**
 * Builds and runs `update <table> set ... where <key> = $n` from a camelCase patch,
 * using a fixed whitelist of columns (never interpolates user-provided names).
 * Returns the number of updated rows (null when there was nothing to update).
 */
export async function updateFromPatch(
  db: Queryable,
  table: string,
  keyColumn: string,
  keyValue: string,
  patch: Record<string, unknown>,
  columns: Record<string, string>,
): Promise<number | null> {
  const sets: string[] = [];
  const params: unknown[] = [];
  for (const [field, column] of Object.entries(columns)) {
    if (patch[field] !== undefined) {
      params.push(patch[field]);
      sets.push(`${column} = $${params.length}`);
    }
  }
  if (!sets.length) return null;
  params.push(keyValue);
  const r = await db.query(
    `update ${table} set ${sets.join(', ')} where ${keyColumn} = $${params.length}`,
    params,
  );
  return r.rowCount ?? 0;
}
