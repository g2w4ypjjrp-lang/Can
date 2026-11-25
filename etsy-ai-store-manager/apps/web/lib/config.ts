/**
 * Runtime configuration. NEXT_PUBLIC_* values are safe for the browser (Supabase
 * URL + publishable/anon key only). API_INTERNAL_URL is used server-side to reach
 * the NestJS API inside the Docker network.
 */
export function webConfig() {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!supabaseUrl || !supabaseKey) {
    throw new Error(
      'NEXT_PUBLIC_SUPABASE_URL ve NEXT_PUBLIC_SUPABASE_ANON_KEY tanımlı olmalı (.env)',
    );
  }
  return {
    supabaseUrl,
    supabaseKey,
    apiUrl: (
      process.env.API_INTERNAL_URL ??
      process.env.NEXT_PUBLIC_API_URL ??
      'http://localhost:4000'
    ).replace(/\/+$/, ''),
    siteUrl: (process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000').replace(/\/+$/, ''),
  };
}
