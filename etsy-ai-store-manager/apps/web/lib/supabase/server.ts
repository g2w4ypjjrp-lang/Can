import 'server-only';
import { createServerClient } from '@supabase/ssr';
import { cookies } from 'next/headers';
import { webConfig } from '../config';

/** Supabase client bound to the request cookies (Server Components, Actions, Route Handlers). */
export async function createSupabaseServerClient() {
  const { supabaseUrl, supabaseKey } = webConfig();
  const cookieStore = await cookies();
  return createServerClient(supabaseUrl, supabaseKey, {
    cookies: {
      getAll: () => cookieStore.getAll(),
      setAll: (toSet) => {
        try {
          for (const { name, value, options } of toSet) cookieStore.set(name, value, options);
        } catch {
          // Called from a Server Component: cookies are refreshed by proxy.ts instead.
        }
      },
    },
  });
}

/**
 * Returns the verified user and an access token for calling the API.
 * getUser() validates the session with Supabase Auth (not just the cookie).
 */
export async function getSessionUser() {
  const supabase = await createSupabaseServerClient();
  const { data: userData, error } = await supabase.auth.getUser();
  if (error || !userData.user) return null;
  const { data: sessionData } = await supabase.auth.getSession();
  const accessToken = sessionData.session?.access_token;
  if (!accessToken) return null;
  return { user: userData.user, accessToken };
}
