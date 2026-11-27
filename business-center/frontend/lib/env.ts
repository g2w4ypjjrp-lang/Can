// Yalnızca herkese açık değerler NEXT_PUBLIC_ ile tarayıcıya gider. API anahtarları burada YOK.
export const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
export const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const INTERNAL_API_URL = process.env.INTERNAL_API_URL ?? API_URL;
export const isConfigured = () => Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);
