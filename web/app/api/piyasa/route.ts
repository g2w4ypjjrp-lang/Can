// Canlı fiyat bandının tarayıcıdan yenilenmesi (aynı köken; dış adrese tarayıcı bağlanmaz).
import { NextResponse } from "next/server";

import { fetchQuotes } from "@/lib/market";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const raw = new URL(request.url).searchParams.get("c") ?? "";
  const extra = raw
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter((s) => /^[A-Z0-9]{2,12}$/.test(s))
    .slice(0, 8);
  const quotes = await fetchQuotes();
  const more = extra.length ? (await fetchQuotes(extra)).filter((q) => !quotes.some((x) => x.base === q.base)) : [];
  return NextResponse.json({ quotes: [...quotes, ...more] }, { headers: { "Cache-Control": "public, max-age=5" } });
}
