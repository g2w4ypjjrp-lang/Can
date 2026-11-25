import type { Metadata } from 'next';
import type { NotificationDto } from '@esm/shared';
import { api } from '@/lib/api';
import { formatDate } from '@/lib/format';
import { Card, PageHeader } from '@/components/ui';
import { markAllNotificationsReadAction, markNotificationReadAction } from '../actions';

export const metadata: Metadata = { title: 'Bildirimler' };

const SEVERITY: Record<NotificationDto['severity'], string> = {
  info: 'bg-brand-100 text-brand-600',
  success: 'bg-emerald-100 text-emerald-800',
  warning: 'bg-amber-100 text-amber-800',
  critical: 'bg-red-100 text-red-800',
};

export default async function NotificationsPage() {
  const items = await api<NotificationDto[]>('/notifications');
  const unread = items.filter((n) => !n.readAt).length;
  return (
    <>
      <PageHeader title="Bildirimler" description={`${unread} okunmamış`}>
        {unread > 0 && (
          <form action={markAllNotificationsReadAction}>
            <button className="rounded-lg border border-line bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50">
              Tümünü okundu yap
            </button>
          </form>
        )}
      </PageHeader>
      <Card>
        {items.length === 0 ? (
          <p className="text-sm text-slate-500">Bildirim yok.</p>
        ) : (
          <ul className="divide-y divide-line">
            {items.map((n) => (
              <li key={n.id} className="flex items-start justify-between gap-4 py-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${SEVERITY[n.severity]}`}
                    >
                      {n.severity}
                    </span>
                    <p
                      className={`truncate text-sm ${n.readAt ? 'text-slate-600' : 'font-semibold text-navy-900'}`}
                    >
                      {n.title}
                    </p>
                  </div>
                  {n.body && <p className="mt-1 text-sm text-slate-600">{n.body}</p>}
                  <p className="mt-1 text-xs text-slate-400">{formatDate(n.createdAt)}</p>
                </div>
                {!n.readAt && (
                  <form action={markNotificationReadAction}>
                    <input type="hidden" name="id" value={n.id} />
                    <button className="shrink-0 text-xs text-brand-600 hover:underline">
                      Okundu
                    </button>
                  </form>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
