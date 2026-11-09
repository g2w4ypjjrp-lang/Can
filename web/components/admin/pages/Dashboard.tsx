"use client";

import Link from "next/link";

import { AdminPage, Feedback, useAdminQuery } from "@/components/admin/kit";
import { useAdmin } from "@/components/admin/AdminSession";
import { Card } from "@/components/ui";
import { can } from "@/lib/admin";
import { licenseStatusLabel } from "@/lib/format";

interface Stats {
  licenses: Record<string, number>;
  usage: { platform: string; devices: number; customers: number }[];
  customers: { total: number; new_30d: number; blocked: number };
  new_messages: number;
}

function Tile({ label, value, testId }: { label: string; value: number | string; testId?: string }) {
  return (
    <Card className="p-5">
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-fg" data-testid={testId}>
        {value}
      </p>
    </Card>
  );
}

export function Dashboard() {
  const { me } = useAdmin();
  const allowed = can(me, "report.usage");
  const stats = useAdminQuery<Stats>(allowed ? "/admin/v1/stats" : null);
  if (!allowed) {
    return (
      <AdminPage title="Hoş geldiniz" lead="Yetkili olduğunuz bölümler soldaki menüdedir.">
        {null}
      </AdminPage>
    );
  }
  const s = stats.data;
  const windows = s?.usage.find((u) => u.platform === "windows");
  return (
    <AdminPage title="Özet" lead="Lisans, müşteri ve kullanım durumu.">
      <Feedback error={stats.error} />
      {s ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Tile label="Müşteri" value={s.customers.total} testId="stat-customers" />
            <Tile label="Son 30 günde yeni müşteri" value={s.customers.new_30d} />
            <Tile label="Etkin bilgisayar (7 gün)" value={windows?.devices ?? 0} />
            <Tile label="Yeni mesaj" value={s.new_messages} testId="stat-messages" />
          </div>
          <Card>
            <h2 className="font-semibold text-fg">Lisanslar</h2>
            <ul className="mt-3 flex flex-wrap gap-3 text-sm">
              {Object.entries(s.licenses).length === 0 ? <li className="text-muted">Henüz lisans yok.</li> : null}
              {Object.entries(s.licenses).map(([status, count]) => (
                <li key={status} className="rounded-full bg-surface-2 px-3 py-1 text-fg">
                  {licenseStatusLabel(status)}: <strong>{count}</strong>
                </li>
              ))}
            </ul>
            <Link href="/yonetim/lisanslar" className="mt-4 inline-block text-sm text-link underline underline-offset-2">
              Lisanslara git
            </Link>
          </Card>
        </>
      ) : null}
    </AdminPage>
  );
}
