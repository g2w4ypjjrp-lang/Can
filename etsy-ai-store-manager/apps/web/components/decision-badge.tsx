const MAP: Record<string, [string, string]> = {
  excellent: ['Çok iyi', 'bg-emerald-100 text-emerald-800'],
  publishable: ['Yayınlanabilir', 'bg-brand-100 text-brand-600'],
  needs_approval: ['Onay bekler', 'bg-amber-100 text-amber-800'],
  not_recommended: ['Önerilmez', 'bg-orange-100 text-orange-800'],
  rejected: ['Reddedilir (zarar)', 'bg-red-100 text-red-800'],
};

export function DecisionBadge({ decision }: { decision: string | null }) {
  if (!decision) return <span className="text-xs text-slate-400">—</span>;
  const [text, cls] = MAP[decision] ?? [decision, 'bg-slate-100 text-slate-600'];
  return (
    <span
      className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}
      data-decision={decision}
    >
      {text}
    </span>
  );
}
