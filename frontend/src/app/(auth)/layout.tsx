import Link from "next/link";
import { Lock, Scale, ShieldCheck } from "lucide-react";
import { KickoffDial } from "@/components/marketing/kickoff-dial";
import { Logo } from "@/components/brand/logo";
import { ResponsibleNote } from "@/components/layout/marketing";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      <aside className="bg-stadium pitch-lines relative hidden flex-col justify-between overflow-hidden border-r border-border p-12 lg:flex">
        <Link href="/" aria-label="First5Minute home"><Logo /></Link>
        <div>
          <span className="eyebrow">Match-day intelligence</span>
          <h2 className="mt-5 font-[family-name:var(--font-display)] text-[68px] font-bold uppercase leading-[0.95] tracking-wide">
            The first<br />five minutes.<br /><span className="text-brand-500">Decoded.</span>
          </h2>
          <div className="mt-10 flex items-center gap-8">
            <KickoffDial size={150} />
            <ul className="space-y-3 text-sm text-muted">
              {[[Lock, "Predictions locked before kick-off"], [ShieldCheck, "Every estimate shows its data quality"], [Scale, "We never place bets or hold money"]].map(([Icon, t]) => {
                const I = Icon as typeof Lock;
                return <li key={t as string} className="flex items-center gap-2.5"><I className="h-4 w-4 shrink-0 text-brand-400" aria-hidden />{t as string}</li>;
              })}
            </ul>
          </div>
        </div>
        <p className="text-xs text-subtle">18+ only. Statistical estimates, never guarantees.</p>
      </aside>
      <div className="flex flex-col items-center justify-center px-4 py-12 sm:px-8">
        <Link href="/" className="mb-8 lg:hidden" aria-label="First5Minute home"><Logo /></Link>
        <div className="w-full max-w-md">
          {children}
          <ResponsibleNote className="mt-10" />
        </div>
      </div>
    </div>
  );
}
