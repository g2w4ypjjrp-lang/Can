"use client";

import { useAdmin } from "@/components/admin/AdminSession";
import { AdminPage, Feedback, Table, cell, useAdminQuery } from "@/components/admin/kit";
import { Card } from "@/components/ui";
import { can, dateTime, formatMinor } from "@/lib/admin";
import { licenseStatusLabel } from "@/lib/format";

export function Reports() {
  const { me } = useAdmin();
  const sales = useAdminQuery<{ day: string; currency: string; order_count: number; revenue_minor: number }[]>(
    can(me, "report.sales") ? "/admin/v1/reports/sales?days=30" : null,
  );
  const payments = useAdminQuery<{ provider: string; status: string; currency: string; count: number; amount_minor: number }[]>(
    can(me, "report.payments") ? "/admin/v1/reports/payments?days=30" : null,
  );
  const usage = useAdminQuery<{ licenses: { plan_code: string; status: string; license_count: number }[] }>(
    can(me, "report.usage") ? "/admin/v1/reports/usage" : null,
  );
  return (
    <AdminPage title="Raporlar" lead="Son 30 gün. Satış ve ödeme verileri ödeme sistemi (Aşama 17) devreye girince dolar.">
      <Feedback error={sales.error ?? payments.error ?? usage.error} />
      {sales.data ? (
        <Card as="section">
          <h2 className="font-semibold text-fg">Satışlar</h2>
          {sales.data.length === 0 ? <p className="mt-2 text-sm text-muted">Henüz satış yok.</p> : (
            <div className="mt-3">
              <Table caption="Günlük satışlar" head={["Gün", "Para birimi", "Sipariş", "Gelir"]}>
                {sales.data.map((r) => (
                  <tr key={`${r.day}-${r.currency}`}>
                    <td className={cell}>{dateTime(r.day)}</td>
                    <td className={cell}>{r.currency}</td>
                    <td className={cell}>{r.order_count}</td>
                    <td className={cell}>{formatMinor(r.revenue_minor)}</td>
                  </tr>
                ))}
              </Table>
            </div>
          )}
        </Card>
      ) : null}
      {payments.data ? (
        <Card as="section">
          <h2 className="font-semibold text-fg">Ödemeler</h2>
          {payments.data.length === 0 ? <p className="mt-2 text-sm text-muted">Henüz ödeme yok.</p> : (
            <div className="mt-3">
              <Table caption="Ödemeler" head={["Sağlayıcı", "Durum", "Adet", "Tutar"]}>
                {payments.data.map((r) => (
                  <tr key={`${r.provider}-${r.status}-${r.currency}`}>
                    <td className={cell}>{r.provider}</td>
                    <td className={cell}>{r.status}</td>
                    <td className={cell}>{r.count}</td>
                    <td className={cell}>{formatMinor(r.amount_minor)} {r.currency}</td>
                  </tr>
                ))}
              </Table>
            </div>
          )}
        </Card>
      ) : null}
      {usage.data ? (
        <Card as="section">
          <h2 className="font-semibold text-fg">Lisanslar (paket ve duruma göre)</h2>
          <div className="mt-3">
            <Table caption="Paket ve duruma göre lisanslar" head={["Paket", "Durum", "Adet"]}>
              {usage.data.licenses.map((r) => (
                <tr key={`${r.plan_code}-${r.status}`}>
                  <td className={cell}>{r.plan_code}</td>
                  <td className={cell}>{licenseStatusLabel(r.status)}</td>
                  <td className={cell}>{r.license_count}</td>
                </tr>
              ))}
            </Table>
          </div>
        </Card>
      ) : null}
    </AdminPage>
  );
}
