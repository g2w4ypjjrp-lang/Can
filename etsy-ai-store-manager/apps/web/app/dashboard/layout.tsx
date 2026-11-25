import { LogOut } from 'lucide-react';
import { Sidebar } from '@/components/sidebar';
import { loadStores } from '@/lib/current-store';
import { api } from '@/lib/api';
import type { MeResponse } from '@esm/shared';
import { signOutAction } from '../(auth)/actions';
import { selectStoreAction } from './actions';

export const dynamic = 'force-dynamic';

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const [me, { stores, current }] = await Promise.all([api<MeResponse>('/me'), loadStores()]);

  return (
    <div className="min-h-screen">
      <Sidebar />
      <div className="lg:pl-64">
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between gap-4 border-b border-line bg-white/90 px-4 pl-16 backdrop-blur lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            {stores.length > 0 ? (
              <form action={selectStoreAction} className="flex items-center gap-2">
                <label htmlFor="store-switcher" className="sr-only">
                  Mağaza
                </label>
                <select
                  id="store-switcher"
                  name="storeId"
                  defaultValue={current?.id}
                  className="max-w-[220px] rounded-lg border border-line bg-white px-3 py-1.5 text-sm"
                >
                  {stores.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
                <button
                  type="submit"
                  className="rounded-lg border border-line px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
                >
                  Seç
                </button>
              </form>
            ) : (
              <span className="text-sm text-slate-500">Henüz mağaza yok</span>
            )}
            {current && (
              <ConnectionBadge status={current.status} demo={current.dataOrigin === 'demo'} />
            )}
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden text-sm text-slate-600 sm:inline" data-testid="user-email">
              {me.fullName ?? me.email}
            </span>
            <form action={signOutAction}>
              <button
                type="submit"
                className="flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
              >
                <LogOut className="h-4 w-4" aria-hidden />
                <span className="hidden sm:inline">Çıkış</span>
              </button>
            </form>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6 lg:px-8 lg:py-8">{children}</main>
      </div>
    </div>
  );
}

function ConnectionBadge({ status, demo }: { status: string; demo: boolean }) {
  if (demo)
    return (
      <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800">
        DEMO
      </span>
    );
  const map: Record<string, [string, string]> = {
    connected: ['Etsy bağlı', 'bg-emerald-100 text-emerald-800'],
    not_connected: ['Etsy bağlı değil', 'bg-slate-100 text-slate-600'],
    disconnected: ['Bağlantı koptu', 'bg-red-100 text-red-800'],
    suspended: ['Askıda', 'bg-red-100 text-red-800'],
  };
  const [label, cls] = map[status] ?? ['Bilinmiyor', 'bg-slate-100 text-slate-600'];
  return (
    <span className={`hidden rounded-full px-2.5 py-0.5 text-xs font-medium sm:inline ${cls}`}>
      {label}
    </span>
  );
}
