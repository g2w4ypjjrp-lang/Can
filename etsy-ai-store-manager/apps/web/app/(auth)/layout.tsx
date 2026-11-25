import { Store } from 'lucide-react';

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        <div className="mb-8 flex items-center justify-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-navy-900 text-white">
            <Store aria-hidden className="h-5 w-5" />
          </span>
          <span className="text-lg font-semibold text-navy-900">Etsy AI Store Manager</span>
        </div>
        <div className="rounded-2xl border border-line bg-white p-8 shadow-sm">{children}</div>
      </div>
    </main>
  );
}
