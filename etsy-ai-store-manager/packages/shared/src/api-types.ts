/** Response DTOs shared by API and web. Money is always a decimal string. */

export type StoreRole = 'owner' | 'admin' | 'analyst' | 'viewer';

export interface MeResponse {
  id: string;
  email: string;
  fullName: string | null;
  locale: string;
  timezone: string;
  settings: {
    uiLanguage: 'tr' | 'en';
    baseCurrency: string;
    notifyEmail: boolean;
    notifyPush: boolean;
    notifyDailyReport: boolean;
    requireReauthForSensitive: boolean;
  };
}

export interface StoreSummary {
  id: string;
  name: string;
  platform: 'etsy';
  status: 'not_connected' | 'connected' | 'disconnected' | 'suspended';
  currency: string;
  defaultLanguage: string;
  dataOrigin: 'live' | 'demo';
  role: StoreRole;
  externalShopId: string | null;
  createdAt: string;
}

export interface StoreSettingsDto {
  storeId: string;
  salesStrategy: 'growth' | 'balanced' | 'profit';
  automationLevel: 'manual' | 'controlled' | 'autonomous_limited';
  marketScope: string;
  defaultLanguage: string;
  languages: string[];
  targetMarkets: string[];
  dailyAdBudgetCap: string;
  adBudgetCurrency: string;
  sellerCountry: string | null;
  payoutCurrency: string | null;
  timezone: string;
  updatedAt: string;
}

export interface ProfitRulesDto {
  storeId: string;
  currency: string;
  targetContribution: string;
  excellentThreshold: string;
  publishThreshold: string;
  reviewThreshold: string;
  minThreshold: string;
  returnReserveRate: string;
  remakeReserveRate: string;
  otherVariableCostRate: string;
  otherVariableCostFixed: string;
  defaultAdCostPerOrder: string;
  taxRateOnProfit: string;
  vatOnFeesRate: string;
  offsiteAdsTier: '15' | '12';
  updatedAt: string;
}

export interface IntegrationStatus {
  platform: string;
  status: 'not_connected' | 'pending' | 'active' | 'expired' | 'revoked' | 'error';
  lastSyncedAt: string | null;
}

export interface DashboardOverview {
  storeId: string;
  currency: string;
  /** 'live' only when the store is connected and data came from Etsy. */
  dataOrigin: 'live' | 'demo' | 'none';
  period: { from: string; to: string };
  kpis: {
    revenueToday: string;
    revenueMonth: string;
    ordersMonth: number;
    averageOrderValue: string | null;
    adSpendMonth: string;
    roas: string | null;
    contributionMonth: string | null;
    refundRate: string | null;
  };
  dailyRevenue: Array<{ date: string; revenue: string; orders: number }>;
  topProducts: Array<{ title: string; units: number; revenue: string }>;
  countrySales: Array<{ country: string; orders: number; revenue: string }>;
  pendingApprovals: number;
  unreadNotifications: number;
  recentDecisions: Array<{ id: string; summary: string; confidence: string; createdAt: string }>;
  integrations: IntegrationStatus[];
  notes: string[];
}

export interface NotificationDto {
  id: string;
  type: string;
  severity: 'info' | 'success' | 'warning' | 'critical';
  title: string;
  body: string | null;
  link: string | null;
  readAt: string | null;
  createdAt: string;
}

export interface ApiErrorBody {
  statusCode: number;
  error: string;
  message: string;
  details?: unknown;
  requestId?: string;
}
