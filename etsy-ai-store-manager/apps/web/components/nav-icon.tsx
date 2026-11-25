import {
  Bell,
  Bot,
  FileBarChart,
  Globe,
  LayoutDashboard,
  Lightbulb,
  Megaphone,
  Package,
  Palette,
  Printer,
  Search,
  Settings,
  ShoppingBag,
  Store,
  Users,
  Wallet,
  Workflow,
  type LucideIcon,
} from 'lucide-react';

const ICONS: Record<string, LucideIcon> = {
  Bell,
  Bot,
  FileBarChart,
  Globe,
  LayoutDashboard,
  Lightbulb,
  Megaphone,
  Package,
  Palette,
  Printer,
  Search,
  Settings,
  ShoppingBag,
  Store,
  Users,
  Wallet,
  Workflow,
};

export function NavIcon({ name, className }: { name: string; className?: string }) {
  const Icon = ICONS[name] ?? LayoutDashboard;
  return <Icon aria-hidden className={className} />;
}
