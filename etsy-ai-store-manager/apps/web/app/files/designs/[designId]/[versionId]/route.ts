import { NextResponse, type NextRequest } from 'next/server';
import { cookies } from 'next/headers';
import { webConfig } from '@/lib/config';
import { getSessionUser } from '@/lib/supabase/server';
import { STORE_COOKIE } from '@/lib/current-store';

const UUID = /^[0-9a-f-]{36}$/i;

/**
 * Authenticated image proxy: design files are private, so the browser fetches them
 * through this route, which forwards the user's session token to the API (RLS applies).
 */
export async function GET(
  _req: NextRequest,
  ctx: { params: Promise<{ designId: string; versionId: string }> },
) {
  const { designId, versionId } = await ctx.params;
  const storeId = (await cookies()).get(STORE_COOKIE)?.value;
  const session = await getSessionUser();
  if (!session) return new NextResponse('Unauthorized', { status: 401 });
  if (!UUID.test(designId) || !UUID.test(versionId) || !storeId || !UUID.test(storeId)) {
    return new NextResponse('Not found', { status: 404 });
  }
  const res = await fetch(
    `${webConfig().apiUrl}/api/v1/stores/${storeId}/designs/${designId}/versions/${versionId}/file`,
    {
      headers: { Authorization: `Bearer ${session.accessToken}` },
      cache: 'no-store',
    },
  );
  if (!res.ok) return new NextResponse('Not found', { status: res.status === 404 ? 404 : 502 });
  return new NextResponse(res.body, {
    headers: {
      'Content-Type': 'image/png',
      'Cache-Control': 'private, max-age=300',
      'X-Content-Type-Options': 'nosniff',
    },
  });
}
