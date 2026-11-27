export type NavItem = { slug: string; label: string; phase: number; ready: boolean };

export const NAV: NavItem[] = [
  { slug: "dashboard", label: "Dashboard", phase: 1, ready: true },
  { slug: "ai-employees", label: "AI Employees", phase: 1, ready: true },
  { slug: "ceo", label: "CEO Command Center", phase: 2, ready: true },
  { slug: "youtube", label: "YouTube Management", phase: 3, ready: false },
  { slug: "etsy", label: "Etsy Management", phase: 4, ready: false },
  { slug: "product-research", label: "Product Research", phase: 4, ready: false },
  { slug: "video-production", label: "Video Production", phase: 3, ready: false },
  { slug: "tasks", label: "Task Management", phase: 2, ready: true },
  { slug: "approvals", label: "Approval Center", phase: 1, ready: true },
  { slug: "finance", label: "Financial Reports", phase: 4, ready: false },
  { slug: "analytics", label: "Analytics", phase: 3, ready: false },
  { slug: "calendar", label: "Content Calendar", phase: 3, ready: false },
  { slug: "automation", label: "Automation", phase: 6, ready: false },
  { slug: "integrations", label: "API Integrations", phase: 3, ready: false },
  { slug: "notifications", label: "Notifications", phase: 6, ready: false },
  { slug: "logs", label: "System Logs", phase: 2, ready: true },
  { slug: "settings", label: "Settings", phase: 1, ready: false },
];
