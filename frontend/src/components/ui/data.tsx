"use client";

import { cn } from "@/lib/cn";
import { pct } from "@/lib/format";

export function Stat({
  label,
  value,
  sub,
  icon: Icon,
  tone = "default",
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  icon?: React.ElementType;
  tone?: "default" | "brand" | "info" | "warn";
}) {
  const toneCls = { default: "text-muted", brand: "text-brand-400", info: "text-info", warn: "text-warn" }[tone];
  return (
    <div className="rounded-[var(--radius-lg)] border border-border bg-surface p-4 shadow-[var(--shadow-card)]">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wider text-muted">{label}</p>
        {Icon && <Icon className={cn("h-4 w-4", toneCls)} aria-hidden />}
      </div>
      <p className="tabular mt-2 font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight">{value}</p>
      {sub && <p className="mt-1 text-xs text-subtle">{sub}</p>}
    </div>
  );
}

/** Horizontal probability bar with optional threshold marker. */
export function ProbabilityBar({ value, threshold, className }: { value: number; threshold?: number; className?: string }) {
  // Probabilities in these markets live roughly in 0.70-1.00; scale the bar to that band for legibility.
  const lo = 0.7;
  const scaled = (v: number) => Math.max(0, Math.min(1, (v - lo) / (1 - lo)));
  return (
    <div className={cn("relative h-1.5 w-full overflow-hidden rounded-full bg-surface-3", className)} aria-hidden>
      <div className="h-full rounded-full bg-gradient-to-r from-brand-700 to-brand-400" style={{ width: `${scaled(value) * 100}%` }} />
      {threshold !== undefined && <div className="absolute inset-y-0 w-px bg-fg/60" style={{ left: `${scaled(threshold) * 100}%` }} />}
    </div>
  );
}

export function ProbabilityValue({ value, className }: { value: number; className?: string }) {
  return <span className={cn("tabular font-[family-name:var(--font-mono)] font-semibold", className)}>{pct(value, 1)}</span>;
}

export function Tabs<T extends string>({
  value,
  onChange,
  options,
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: React.ReactNode }[];
  className?: string;
}) {
  return (
    <div role="tablist" className={cn("inline-flex rounded-[var(--radius-md)] border border-border bg-surface-2 p-0.5", className)}>
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "cursor-pointer rounded-[8px] px-3 py-1.5 text-xs font-semibold transition-colors",
            value === o.value ? "bg-surface-3 text-fg shadow-sm" : "text-muted hover:text-fg",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Table({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn("w-full border-collapse text-sm", className)} {...props} />
    </div>
  );
}
export function Th({ className, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn("whitespace-nowrap border-b border-border px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-subtle", className)}
      {...props}
    />
  );
}
export function Td({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("border-b border-border/60 px-4 py-3 align-middle", className)} {...props} />;
}

export function Pager({ page, pages, onPage }: { page: number; pages: number; onPage: (p: number) => void }) {
  if (pages <= 1) return null;
  return (
    <div className="flex items-center justify-end gap-2 px-4 py-3 text-xs text-muted">
      <button className="cursor-pointer rounded px-2 py-1 hover:bg-surface-2 disabled:opacity-40" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <span className="tabular">
        Page {page} of {pages}
      </span>
      <button className="cursor-pointer rounded px-2 py-1 hover:bg-surface-2 disabled:opacity-40" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </div>
  );
}
