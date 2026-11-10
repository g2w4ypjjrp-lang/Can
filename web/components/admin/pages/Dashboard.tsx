"use client";

import {
  ArrowUpRight,
  CircleDollarSign,
  Download,
  KeyRound,
  Laptop,
  Mail,
  ShoppingCart,
  Smartphone,
  Tags,
  Users,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { useAdmin } from "@/components/admin/AdminSession";
import { AreaTrend, BarList, Sparkline } from "@/components/admin/charts";
import { AdminCard, AdminPage, EmptyState, Feedback, KpiCard, Skeleton, StatusPill, cell, orderTone, useAdminQuery } from "@/components/admin/kit";
import { can, dateTime } from "@/lib/admin";
import { formatPrice, licenseStatusLabel, orderStatusLabel } from "@/lib/format";

interface Stats {
  licenses: Record<string, number>;
  usage: { platform: string; devices: number; customers: number }[];
  customers: { total: number; new_30d: number; blocked: number };
  new_messages: number;
}

interface SalesRow {
  day: string;
  currency: string;
  order_count: number;
  revenue_minor: number;
}

interface OrderRow {
  id: string;
  order_no: number;
  status: string;
  currency: string;
  total_minor: number;
  review_reason: string | null;
  created_at: string;
  customer_email: string;
  plan_name: string | null;
}

interface AuditRow {
  id: number;
  occurred_at: string;
  actor_type: string;
  action: string;
  target_type: string | null;
}

const ACTIONS: Record<string, string> = {
  "admin.login": "Yönetici girişi",
  "admin.login_failed": "Başarısız yönetici girişi",
  "admin.logout": "Yönetici çıkışı",
  "admin.activated": "Yönetici hesabı etkinleştirildi",
  "admin.admin_invited": "Yönetici davet edildi",
  "admin.plan_updated": "Paket güncellendi",
  "admin.release_created": "Sürüm taslağı eklendi",
  "admin.release_published": "Sürüm yayınlandı",
  "admin.release_withdrawn": "Sürüm geri çekildi",
  "admin.license_generated": "Lisans üretildi",
  "admin.license_frozen": "Lisans donduruldu",
  "admin.license_revealed": "Tam lisans anahtarı görüntülendi",
  "admin.settings_updated": "Ayarlar güncellendi",
  "customer.registered": "Yeni müşteri kaydı",
  "customer.login": "Müşteri girişi",
  "order.created": "Sipariş oluşturuldu",
  "order.fulfilled": "Sipariş tamamlandı",
  "payment.succeeded": "Ödeme alındı",
};

const ACTORS: Record<string, string> = {
  admin: "Yönetici",
  customer: "Müşteri",
  system: "Sistem",
  payment_webhook: "Ödeme bildirimi",
  engine: "Masaüstü motoru",
};

function greeting(): string {
  const hour = Number(new Intl.DateTimeFormat("tr-TR", { hour: "numeric", hour12: false, timeZone: "Europe/Istanbul" }).format(new Date()));
  if (hour >= 5 && hour < 11) return "Günaydın";
  if (hour >= 11 && hour < 18) return "İyi günler";
  if (hour >= 18 && hour < 23) return "İyi akşamlar";
  return "İyi geceler";
}

function ago(iso: string): string {
  const seconds = (new Date(iso).getTime() - Date.now()) / 1000;
  const rtf = new Intl.RelativeTimeFormat("tr", { numeric: "auto" });
  const steps: [number, Intl.RelativeTimeFormatUnit][] = [
    [60, "second"],
    [3600, "minute"],
    [86400, "hour"],
    [604800, "day"],
  ];
  for (const [limit, unit] of steps) {
    if (Math.abs(seconds) < limit) {
      const divisor = unit === "second" ? 1 : unit === "minute" ? 60 : unit === "hour" ? 3600 : 86400;
      return rtf.format(Math.round(seconds / divisor), unit);
    }
  }
  return dateTime(iso);
}

/** Son 30 gün (UTC gün sınırı, veritabanı görünümüyle aynı), boş günler 0. */
function lastDays(rows: SalesRow[], currency: string, days = 30) {
  const byDay = new Map<string, { revenue: number; orders: number }>();
  for (const row of rows) {
    if (row.currency !== currency) continue;
    const key = row.day.slice(0, 10);
    const entry = byDay.get(key) ?? { revenue: 0, orders: 0 };
    entry.revenue += Number(row.revenue_minor);
    entry.orders += Number(row.order_count);
    byDay.set(key, entry);
  }
  const label = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short", timeZone: "UTC" });
  const out: { key: string; label: string; revenue: number; orders: number }[] = [];
  const today = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - i));
    const key = d.toISOString().slice(0, 10);
    const entry = byDay.get(key) ?? { revenue: 0, orders: 0 };
    out.push({ key, label: label.format(d), ...entry });
  }
  return out;
}

function compactMoney(minor: number, currency: string): string {
  const value = minor / 100;
  const symbol = currency === "TRY" ? "₺" : currency === "USD" ? "$" : currency === "EUR" ? "€" : "";
  if (value >= 1_000_000) return `${symbol}${(value / 1_000_000).toLocaleString("tr-TR", { maximumFractionDigits: 1 })} mn`;
  if (value >= 1_000) return `${symbol}${(value / 1_000).toLocaleString("tr-TR", { maximumFractionDigits: 1 })} bin`;
  return `${symbol}${value.toLocaleString("tr-TR", { maximumFractionDigits: 0 })}`;
}

function QuickLink({ href, icon: Icon, label }: { href: string; icon: LucideIcon; label: string }) {
  return (
    <Link
      href={href}
      className="group flex items-center gap-3 rounded-2xl border border-border bg-surface px-4 py-3 text-sm font-medium text-fg shadow-sm transition-colors hover:border-border-strong hover:bg-surface-2"
    >
      <span className="inline-flex h-8 w-8 items-center justify-center rounded-xl bg-surface-2 text-accent-text">
        <Icon aria-hidden="true" className="h-4 w-4" />
      </span>
      {label}
      <ArrowUpRight aria-hidden="true" className="ml-auto h-4 w-4 text-muted transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
    </Link>
  );
}

export function Dashboard() {
  const { me } = useAdmin();
  const allowed = can(me, "report.usage");
  const stats = useAdminQuery<Stats>(allowed ? "/admin/v1/stats" : null);
  const sales = useAdminQuery<SalesRow[]>(can(me, "report.sales") ? "/admin/v1/reports/sales?days=30" : null);
  const orders = useAdminQuery<OrderRow[]>(can(me, "order.read") ? "/admin/v1/orders?limit=6" : null);
  const audit = useAdminQuery<AuditRow[]>(can(me, "audit.read") ? "/admin/v1/audit?limit=8" : null);

  const currency = useMemo(() => {
    const totals = new Map<string, number>();
    for (const row of sales.data ?? []) totals.set(row.currency, (totals.get(row.currency) ?? 0) + Number(row.revenue_minor));
    return [...totals.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? "TRY";
  }, [sales.data]);
  const series = useMemo(() => lastDays(sales.data ?? [], currency), [sales.data, currency]);
  const revenue = series.reduce((sum, d) => sum + d.revenue, 0);
  const orderCount = series.reduce((sum, d) => sum + d.orders, 0);
  const otherCurrencies = new Set((sales.data ?? []).map((r) => r.currency).filter((c) => c !== currency));

  const firstName = (me?.full_name || "").trim().split(/\s+/)[0] ?? "";
  const today = new Intl.DateTimeFormat("tr-TR", { dateStyle: "full", timeZone: "Europe/Istanbul" }).format(new Date());

  if (!allowed) {
    return (
      <AdminPage eyebrow={`${greeting()}${firstName ? `, ${firstName}` : ""}`} title="Hoş geldiniz" lead="Yetkili olduğunuz bölümler soldaki menüdedir.">
        {null}
      </AdminPage>
    );
  }

  const s = stats.data;
  const windows = s?.usage.find((u) => u.platform === "windows");
  const ios = s?.usage.find((u) => u.platform === "ios");
  const licenseItems = s ? Object.entries(s.licenses).map(([status, value]) => ({ key: status, label: licenseStatusLabel(status), value })) : [];

  return (
    <AdminPage
      eyebrow={`${greeting()}${firstName ? `, ${firstName}` : ""}`}
      title="Özet"
      lead={`${today} · satış, lisans ve kullanım durumu`}
      actions={
        <Link href="/yonetim/raporlar" className="inline-flex items-center gap-1.5 rounded-xl border border-border bg-surface px-3.5 py-2 text-sm font-medium text-fg shadow-sm hover:bg-surface-2">
          Raporlar <ArrowUpRight aria-hidden="true" className="h-4 w-4" />
        </Link>
      }
    >
      <Feedback error={stats.error} />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {can(me, "report.sales") ? (
          <KpiCard
            label="Gelir · son 30 gün"
            icon={CircleDollarSign}
            value={sales.data ? formatPrice(revenue, currency) : <Skeleton className="h-8 w-32" />}
            hint={otherCurrencies.size ? `Yalnızca ${currency}; diğer para birimleri raporlarda` : `${orderCount} ödenmiş sipariş`}
            chart={sales.data ? <Sparkline values={series.map((d) => d.revenue)} className="h-10 w-full" /> : null}
          />
        ) : null}
        {can(me, "report.sales") ? (
          <KpiCard
            label="Sipariş · son 30 gün"
            icon={ShoppingCart}
            value={sales.data ? orderCount.toLocaleString("tr-TR") : <Skeleton className="h-8 w-16" />}
            hint={`Günde ortalama ${(orderCount / 30).toLocaleString("tr-TR", { maximumFractionDigits: 1 })}`}
            chart={sales.data ? <Sparkline values={series.map((d) => d.orders)} className="h-10 w-full" /> : null}
          />
        ) : null}
        <KpiCard
          label="Etkin lisans"
          icon={KeyRound}
          value={s ? (s.licenses.active ?? 0).toLocaleString("tr-TR") : <Skeleton className="h-8 w-16" />}
          hint={s ? `${(s.licenses.sold ?? 0).toLocaleString("tr-TR")} etkinleştirme bekliyor` : undefined}
        />
        <KpiCard
          label="Müşteri"
          icon={Users}
          testId="stat-customers"
          value={s ? s.customers.total.toLocaleString("tr-TR") : <Skeleton className="h-8 w-16" />}
          hint={s ? `Son 30 günde +${s.customers.new_30d}` : undefined}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        {can(me, "report.sales") ? (
          <AdminCard title="Günlük gelir" description={`Son 30 gün · ${currency} · ödemesi alınmış siparişler`} className="xl:col-span-2">
            {sales.data ? (
              <AreaTrend
                title="Günlük gelir, son 30 gün"
                points={series.map((d) => ({
                  key: d.key,
                  label: d.label,
                  value: d.revenue,
                  detail: `${d.orders} sipariş`,
                }))}
                format={(v) => formatPrice(v, currency)}
                compact={(v) => compactMoney(v, currency)}
                emptyText="Son 30 günde ödemesi alınmış sipariş yok."
              />
            ) : (
              <Skeleton className="h-[260px] w-full" />
            )}
            <Feedback error={sales.error} />
          </AdminCard>
        ) : null}
        <AdminCard title="Lisans durumları" description="Tüm lisanslar">
          {s ? <BarList title="Lisans durumlarına göre sayılar" items={licenseItems} /> : <Skeleton className="h-40 w-full" />}
          <Link href="/yonetim/lisanslar" className="mt-5 inline-flex items-center gap-1 text-sm font-medium text-link hover:underline">
            Lisanslara git <ArrowUpRight aria-hidden="true" className="h-4 w-4" />
          </Link>
        </AdminCard>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        {can(me, "order.read") ? (
          <AdminCard
            title="Son siparişler"
            className="xl:col-span-2"
            actions={
              <Link href="/yonetim/siparisler" className="text-sm font-medium text-link hover:underline">
                Tümü
              </Link>
            }
          >
            {orders.data === null ? (
              <div className="space-y-3">
                {[0, 1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : orders.data.length === 0 ? (
              <EmptyState icon={ShoppingCart} title="Henüz sipariş yok">
                Satış başladığında son siparişler burada görünür.
              </EmptyState>
            ) : (
              <div className="-mx-5 overflow-x-auto sm:-mx-6">
                <table className="w-full min-w-[560px] text-left text-sm">
                  <caption className="visually-hidden">Son siparişler</caption>
                  <thead className="text-xs uppercase tracking-wide text-muted">
                    <tr>
                      {["Sipariş", "Müşteri", "Tutar", "Durum", "Tarih"].map((h) => (
                        <th key={h} scope="col" className="px-5 pb-2 font-semibold sm:px-6">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {orders.data.map((o) => (
                      <tr key={o.id} className="transition-colors hover:bg-surface-2/50">
                        <td className={`${cell} pl-5 font-semibold text-fg sm:pl-6`}>#{o.order_no}</td>
                        <td className={cell}>
                          <p className="max-w-56 truncate text-fg">{o.customer_email}</p>
                          <p className="text-xs text-muted">{o.plan_name ?? "—"}</p>
                        </td>
                        <td className={`${cell} tabular text-fg`}>{formatPrice(o.total_minor, o.currency)}</td>
                        <td className={cell}>
                          <StatusPill tone={orderTone(o.status)}>{orderStatusLabel(o.status, Boolean(o.review_reason))}</StatusPill>
                        </td>
                        <td className={`${cell} pr-5 text-muted sm:pr-6`}>{dateTime(o.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </AdminCard>
        ) : null}

        <div className="space-y-4">
          <AdminCard title="Kullanım" description="Son 7 günde lisansı doğrulanan cihazlar">
            <ul className="grid grid-cols-2 gap-3">
              <li className="rounded-2xl border border-border bg-bg/60 p-4">
                <Laptop aria-hidden="true" className="h-4 w-4 text-accent-text" />
                <p className="tabular mt-2 text-2xl font-semibold text-fg">{s ? (windows?.devices ?? 0) : "—"}</p>
                <p className="text-xs text-muted">Windows bilgisayar</p>
              </li>
              <li className="rounded-2xl border border-border bg-bg/60 p-4">
                <Smartphone aria-hidden="true" className="h-4 w-4 text-accent-text" />
                <p className="tabular mt-2 text-2xl font-semibold text-fg">{s ? (ios?.devices ?? 0) : "—"}</p>
                <p className="text-xs text-muted">iPhone</p>
              </li>
            </ul>
            {s ? (
              <Link href="/yonetim/mesajlar" className="mt-3 flex items-center justify-between rounded-2xl border border-border px-4 py-3 text-sm hover:bg-surface-2">
                <span className="flex items-center gap-2 text-fg">
                  <Mail aria-hidden="true" className="h-4 w-4 text-accent-text" /> Yeni mesaj
                </span>
                <StatusPill tone={s.new_messages ? "info" : "neutral"} testId="stat-messages">
                  {s.new_messages}
                </StatusPill>
              </Link>
            ) : null}
          </AdminCard>
          <AdminCard title="Hızlı işlemler">
            <div className="space-y-2">
              {can(me, "license.generate") ? <QuickLink href="/yonetim/lisanslar" icon={KeyRound} label="Lisans üret" /> : null}
              {can(me, "plan.manage") ? <QuickLink href="/yonetim/paketler" icon={Tags} label="Paket ve fiyatlar" /> : null}
              {can(me, "release.manage") ? <QuickLink href="/yonetim/surumler" icon={Download} label="Sürüm yayınla" /> : null}
            </div>
          </AdminCard>
        </div>
      </div>

      {can(me, "audit.read") ? (
        <AdminCard
          title="Son etkinlikler"
          description="Denetim kaydından"
          actions={
            <Link href="/yonetim/denetim" className="text-sm font-medium text-link hover:underline">
              Denetim kaydı
            </Link>
          }
        >
          {audit.data === null ? (
            <Skeleton className="h-32 w-full" />
          ) : audit.data.length === 0 ? (
            <p className="text-sm text-muted">Henüz kayıt yok.</p>
          ) : (
            <ol className="relative space-y-4 before:absolute before:inset-y-1 before:left-[7px] before:w-px before:bg-border">
              {audit.data.map((row) => (
                <li key={row.id} className="relative flex items-start gap-4 pl-7">
                  <span aria-hidden="true" className="absolute left-0 top-1 h-[15px] w-[15px] rounded-full border-2 border-surface bg-chart-1" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-fg">{ACTIONS[row.action] ?? row.action}</p>
                    <p className="text-xs text-muted">
                      {ACTORS[row.actor_type] ?? row.actor_type}
                      {row.target_type ? ` · ${row.target_type}` : ""}
                    </p>
                  </div>
                  <time dateTime={row.occurred_at} className="shrink-0 text-xs text-muted" title={dateTime(row.occurred_at)}>
                    {ago(row.occurred_at)}
                  </time>
                </li>
              ))}
            </ol>
          )}
        </AdminCard>
      ) : null}
    </AdminPage>
  );
}

