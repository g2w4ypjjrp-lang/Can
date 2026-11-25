/**
 * Left menu of the admin panel. `phase` = development phase in which the module
 * becomes functional; `status` is the honest implementation state shown in the UI.
 */
export type ModuleStatus = 'ready' | 'partial' | 'planned';

export interface NavItem {
  slug: string;
  href: string;
  label: string;
  icon: string;
  phase: number;
  status: ModuleStatus;
  description: string;
}

export const NAV_ITEMS: readonly NavItem[] = [
  {
    slug: 'overview',
    href: '/dashboard',
    label: 'Genel Bakış',
    icon: 'LayoutDashboard',
    phase: 1,
    status: 'ready',
    description: 'Satış, kâr, reklam, sipariş ve AI önerileri özeti',
  },
  {
    slug: 'ai-manager',
    href: '/dashboard/ai-manager',
    label: 'AI Store Manager',
    icon: 'Bot',
    phase: 10,
    status: 'planned',
    description: 'Gerçek verilere bağlı araçlarla çalışan AI operasyon yöneticisi',
  },
  {
    slug: 'market-research',
    href: '/dashboard/market-research',
    label: 'Pazar Araştırma',
    icon: 'Globe',
    phase: 5,
    status: 'ready',
    description: 'Trend, anahtar kelime ve rakip analizi',
  },
  {
    slug: 'opportunities',
    href: '/dashboard/opportunities',
    label: 'Ürün Fırsatları',
    icon: 'Lightbulb',
    phase: 5,
    status: 'ready',
    description: 'Talep/rekabet puanlı ürün fırsatları ve kârlılık simülasyonu',
  },
  {
    slug: 'design-studio',
    href: '/dashboard/design-studio',
    label: 'Tasarım Stüdyosu',
    icon: 'Palette',
    phase: 6,
    status: 'planned',
    description: 'Özgün tasarım, baskı dosyası, mockup ve IP risk kontrolü',
  },
  {
    slug: 'products',
    href: '/dashboard/products',
    label: 'Ürünler',
    icon: 'Package',
    phase: 3,
    status: 'ready',
    description: 'Ürünler, varyantlar ve maliyetler',
  },
  {
    slug: 'etsy',
    href: '/dashboard/etsy',
    label: 'Etsy Mağazam',
    icon: 'Store',
    phase: 2,
    status: 'ready',
    description: 'Etsy OAuth, mağaza verisi ve ilan yönetimi',
  },
  {
    slug: 'printify',
    href: '/dashboard/printify',
    label: 'Printify',
    icon: 'Printer',
    phase: 3,
    status: 'ready',
    description: 'Katalog, baskı sağlayıcıları, üretim maliyeti ve siparişler',
  },
  {
    slug: 'ads',
    href: '/dashboard/ads',
    label: 'Reklam Yönetimi',
    icon: 'Megaphone',
    phase: 8,
    status: 'planned',
    description: 'Kampanyalar, bütçe sınırı, ROAS ve reklam sonrası katkı',
  },
  {
    slug: 'orders',
    href: '/dashboard/orders',
    label: 'Siparişler',
    icon: 'ShoppingBag',
    phase: 9,
    status: 'planned',
    description: 'Sipariş, üretim, kargo ve iade takibi',
  },
  {
    slug: 'customers',
    href: '/dashboard/customers',
    label: 'Müşteriler',
    icon: 'Users',
    phase: 9,
    status: 'planned',
    description: 'Müşteri mesajları ve AI yanıt taslakları',
  },
  {
    slug: 'seo',
    href: '/dashboard/seo',
    label: 'SEO Merkezi',
    icon: 'Search',
    phase: 7,
    status: 'planned',
    description: 'Çok dilli başlık, açıklama ve etiket optimizasyonu',
  },
  {
    slug: 'finance',
    href: '/dashboard/finance',
    label: 'Finans ve Kâr',
    icon: 'Wallet',
    phase: 4,
    status: 'ready',
    description: 'Profit Engine: ürün başına gerçek katkı ve fiyat önerisi',
  },
  {
    slug: 'automation',
    href: '/dashboard/automation',
    label: 'Otomasyon',
    icon: 'Workflow',
    phase: 10,
    status: 'partial',
    description: 'Zamanlanmış görevler, retry ve iş geçmişi',
  },
  {
    slug: 'notifications',
    href: '/dashboard/notifications',
    label: 'Bildirimler',
    icon: 'Bell',
    phase: 1,
    status: 'ready',
    description: 'Sistem ve AI bildirimleri',
  },
  {
    slug: 'reports',
    href: '/dashboard/reports',
    label: 'Raporlar',
    icon: 'FileBarChart',
    phase: 10,
    status: 'planned',
    description: 'Günlük, haftalık ve aylık raporlar',
  },
  {
    slug: 'settings',
    href: '/dashboard/settings',
    label: 'Ayarlar',
    icon: 'Settings',
    phase: 1,
    status: 'ready',
    description: 'Hesap, mağaza, kâr politikası ve reklam bütçesi',
  },
] as const;
