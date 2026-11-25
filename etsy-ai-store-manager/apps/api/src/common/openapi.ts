import { z, type ZodType } from 'zod';

/** Converts a zod schema to an OpenAPI-compatible JSON schema for @ApiBody. */
export function zodToOpenApi(schema: ZodType): Record<string, unknown> {
  const json = z.toJSONSchema(schema, { target: 'openapi-3.0', unrepresentable: 'any' }) as Record<
    string,
    unknown
  >;
  const { $schema: _ignored, ...rest } = json;
  return rest;
}
