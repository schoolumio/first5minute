import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";
import { CATEGORY_LABEL, QUALITY_LABEL } from "@/lib/format";
import type { Category, Quality } from "@/lib/types";

const badge = cva("inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide", {
  variants: {
    tone: {
      neutral: "border-border-strong bg-surface-2 text-muted",
      brand: "border-brand-500/40 bg-brand-500/10 text-brand-400",
      info: "border-info/40 bg-info/10 text-info",
      warn: "border-warn/40 bg-warn/10 text-warn",
      danger: "border-danger/40 bg-danger/10 text-danger",
      demo: "border-demo/40 bg-demo/10 text-demo",
    },
  },
  defaultVariants: { tone: "neutral" },
});

export function Badge({ tone, className, ...props }: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badge>) {
  return <span className={cn(badge({ tone }), className)} {...props} />;
}

const CATEGORY_TONE: Record<Category, VariantProps<typeof badge>["tone"]> = {
  qualified: "brand",
  watchlist: "info",
  below_threshold: "neutral",
  excluded: "danger",
};

export function CategoryBadge({ category }: { category: Category }) {
  return <Badge tone={CATEGORY_TONE[category]}>{CATEGORY_LABEL[category]}</Badge>;
}

const QUALITY_BARS: Record<Quality, number> = { insufficient: 0, low: 1, medium: 2, high: 3 };

/** Data-quality indicator: three bars plus label. */
export function QualityIndicator({ quality, compact }: { quality: Quality; compact?: boolean }) {
  const n = QUALITY_BARS[quality];
  const color = n === 3 ? "bg-brand-500" : n === 2 ? "bg-info" : n === 1 ? "bg-warn" : "bg-danger";
  return (
    <span className="inline-flex items-center gap-1.5" title={`Data quality: ${QUALITY_LABEL[quality]}`}>
      <span className="flex items-end gap-0.5" aria-hidden>
        {[0, 1, 2].map((i) => (
          <span key={i} className={cn("w-1 rounded-sm", i < n ? color : "bg-border-strong")} style={{ height: 6 + i * 3 }} />
        ))}
      </span>
      {!compact && <span className="text-xs text-muted">{QUALITY_LABEL[quality]}</span>}
    </span>
  );
}

export function DemoBadge() {
  return (
    <Badge tone="demo" title="Synthetic development data - not real fixtures">
      Demo
    </Badge>
  );
}
