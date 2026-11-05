import { cn } from "@/lib/cn";

/** Circular probability gauge: the model's estimate at a glance. */
export function ProbabilityRing({ value, size = 60, className }: { value: number; size?: number; className?: string }) {
  const r = (size - 8) / 2;
  const c = 2 * Math.PI * r;
  const lo = 0.5;                                    // the scale starts at 50%: these markets live in the 70-99% band
  const frac = Math.max(0, Math.min(1, (value - lo) / (1 - lo)));
  return (
    <div className={cn("relative shrink-0", className)} style={{ width: size, height: size }} role="img" aria-label={`Model estimate ${(value * 100).toFixed(1)} percent`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={4} className="stroke-surface-3" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={4} strokeLinecap="round" strokeDasharray={`${c * frac} ${c}`} className="stroke-brand-500" />
      </svg>
      <span className="tabular absolute inset-0 flex items-center justify-center font-[family-name:var(--font-mono)] text-[13px] font-bold">{(value * 100).toFixed(0)}<span className="text-[9px] font-medium text-muted">%</span></span>
    </div>
  );
}
