import { cn } from "@/lib/cn";

/**
 * First5Minute mark: a bold "5" whose top bar is the brand green, set inside a
 * stopwatch dial with the opening five minutes highlighted.
 */
export function LogoMark({ className, title = "Project Five" }: { className?: string; title?: string }) {
  const ticks = Array.from({ length: 12 }, (_, i) => i);
  return (
    <svg viewBox="0 0 64 64" className={cn("h-8 w-8", className)} role="img" aria-label={title}>
      {/* dial arc */}
      <path d="M32 6 A26 26 0 1 1 13.6 13.6" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" opacity="0.95" />
      {/* first-five-minute segment */}
      <path d="M32 6 A26 26 0 0 1 45 9.5" fill="none" stroke="var(--color-brand-500)" strokeWidth="4.5" strokeLinecap="round" />
      {ticks.map((i) => {
        const a = (i / 12) * Math.PI * 2 - Math.PI / 2;
        if (i >= 9) return null;
        const r1 = 20.5, r2 = i % 3 === 0 ? 16.5 : 18.5;
        return (
          <line key={i} x1={32 + r1 * Math.cos(a)} y1={32 + r1 * Math.sin(a)} x2={32 + r2 * Math.cos(a)} y2={32 + r2 * Math.sin(a)}
            stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" opacity="0.7" />
        );
      })}
      {/* the 5 */}
      <path d="M19 15 h20 l-3.2 7 H26.5 l-1 5.2 c1.6-.8 3.4-1.2 5.4-1.2 6.4 0 10.6 4.3 10.6 10.4 0 6.6-5 11.1-12.4 11.1-4.6 0-8.4-1.7-10.8-4.5l4.4-4.8c1.6 1.8 3.8 2.9 6.2 2.9 3.4 0 5.6-2 5.6-4.9 0-2.8-2.1-4.7-5.3-4.7-1.9 0-3.6.6-4.9 1.6l-5.4-2.2z"
        fill="currentColor" />
      <path d="M19 15 h20 l-3.2 7 H17.6z" fill="var(--color-brand-500)" />
    </svg>
  );
}

export function Logo({ className, compact }: { className?: string; compact?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark className="h-8 w-8 text-fg" />
      {!compact && (
        <span className="leading-none">
          <span className="block font-[family-name:var(--font-display)] text-[15px] font-extrabold tracking-tight">
            PROJECT <span className="text-brand-500">FIVE</span>
          </span>
          <span className="mt-0.5 block text-[9px] font-semibold uppercase tracking-[0.2em] text-muted">First five minutes. Decoded.</span>
        </span>
      )}
    </span>
  );
}
