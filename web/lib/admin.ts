// Yönetim paneli istemci yardımcıları. Yetki yalnızca sunucuda denetlenir; buradaki izin
// kontrolleri yalnızca menü ve düğmeleri gizlemek içindir.

export interface AdminMe {
  id: string;
  email: string;
  full_name: string;
  roles: string[];
  permissions: string[];
  recovery_codes_left: number;
}

export interface NavEntry {
  href: string;
  label: string;
  permission: string | null;
  group: "Genel" | "Satış" | "Müşteriler" | "Sistem";
}

export const ADMIN_NAV: NavEntry[] = [
  { href: "/yonetim", label: "Özet", permission: "report.usage", group: "Genel" },
  { href: "/yonetim/siparisler", label: "Siparişler", permission: "order.read", group: "Satış" },
  { href: "/yonetim/paketler", label: "Paketler ve fiyatlar", permission: "plan.manage", group: "Satış" },
  { href: "/yonetim/raporlar", label: "Raporlar", permission: "report.sales", group: "Satış" },
  { href: "/yonetim/musteriler", label: "Müşteriler", permission: "customer.read", group: "Müşteriler" },
  { href: "/yonetim/lisanslar", label: "Lisanslar", permission: "license.read", group: "Müşteriler" },
  { href: "/yonetim/mesajlar", label: "Mesajlar", permission: "customer.read", group: "Müşteriler" },
  { href: "/yonetim/surumler", label: "Sürümler (indirme)", permission: "release.manage", group: "Sistem" },
  { href: "/yonetim/yoneticiler", label: "Yöneticiler", permission: "admin.manage", group: "Sistem" },
  { href: "/yonetim/denetim", label: "Denetim kaydı", permission: "audit.read", group: "Sistem" },
  { href: "/yonetim/ayarlar", label: "Ayarlar", permission: null, group: "Sistem" },
];

export const NAV_GROUPS = ["Genel", "Satış", "Müşteriler", "Sistem"] as const;

export function can(me: AdminMe | null, permission: string | null): boolean {
  return permission === null || Boolean(me?.permissions.includes(permission));
}

export const ROLE_LABELS: Record<string, string> = {
  super_admin: "Süper yönetici",
  license_manager: "Lisans yöneticisi",
  support: "Destek",
  finance: "Finans",
  auditor: "Denetçi",
};

/** "1.499,90" → 149990 (kuruş). Geçersizse null. */
export function parseMoney(text: string): number | null {
  const cleaned = text.trim().replace(/\s/g, "").replace(/\./g, "").replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null;
  return Math.round(Number(cleaned) * 100);
}

export function formatMinor(minor: number | null | undefined): string {
  if (minor === null || minor === undefined) return "";
  return (minor / 100).toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function toCsv(rows: Record<string, string>[]): string {
  if (rows.length === 0) return "";
  const headers = Object.keys(rows[0]!);
  const escape = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  return [headers.join(","), ...rows.map((r) => headers.map((h) => escape(r[h] ?? "")).join(","))].join("\n");
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("tr-TR", { dateStyle: "short", timeStyle: "short", timeZone: "Europe/Istanbul" }).format(d);
}
