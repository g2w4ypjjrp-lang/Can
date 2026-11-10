import type { LucideIcon } from "lucide-react";

import { IconTile } from "@/components/ui";

export function IconBox({ icon, tone = "accent" }: { icon: LucideIcon; tone?: "accent" | "violet" | "cyan" | "success" | "danger" }) {
  return <IconTile icon={icon} tone={tone} />;
}
