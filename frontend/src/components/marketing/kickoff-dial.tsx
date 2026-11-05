/** The product's signature graphic: a 5-minute match clock, one segment per minute, with a sweeping hand. */
export function KickoffDial({ size = 220, label = "05:00" }: { size?: number; label?: string }) {
  const r = 86, c = 2 * Math.PI * r, seg = c / 5, gap = 7;
  return (
    <div className="relative" style={{ width: size, height: size }} role="img" aria-label="A five-minute match clock">
      <svg viewBox="0 0 220 220" width={size} height={size} className="-rotate-90" aria-hidden>
        <circle cx="110" cy="110" r="104" fill="none" className="dial-ring" strokeWidth="1" />
        {[0, 1, 2, 3, 4].map((i) => (
          <circle key={i} cx="110" cy="110" r={r} fill="none" strokeWidth="10" strokeLinecap="butt"
            stroke={i === 0 ? "var(--color-brand-500)" : "var(--color-surface-4)"}
            strokeDasharray={`${seg - gap} ${c - seg + gap}`} strokeDashoffset={-i * seg} />
        ))}
        <circle cx="110" cy="110" r={r} fill="none" strokeWidth="2" stroke="var(--color-brand-300)" strokeLinecap="round" className="dial-sweep"
          strokeDasharray={`${seg * 0.2} ${c}`} />
        {Array.from({ length: 60 }, (_, i) => {
          const a = (i / 60) * Math.PI * 2;
          const major = i % 12 === 0;
          const r1 = 98, r2 = major ? 92 : 95;
          return <line key={i} x1={110 + r1 * Math.cos(a)} y1={110 + r1 * Math.sin(a)} x2={110 + r2 * Math.cos(a)} y2={110 + r2 * Math.sin(a)} className="dial-tick" strokeWidth={major ? 1.5 : 0.8} />;
        })}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-[family-name:var(--font-mono)] text-[10px] font-semibold uppercase tracking-[0.3em] text-muted">cut-off</span>
        <span className="numeral text-5xl leading-none text-fg">{label}</span>
        <span className="mt-1 font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-[0.25em] text-brand-400">kick-off → 5&apos;</span>
      </div>
    </div>
  );
}
