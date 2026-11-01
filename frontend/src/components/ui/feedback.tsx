import { AlertTriangle, CheckCircle2, Info, Lock, XCircle } from "lucide-react";
import { cn } from "@/lib/cn";
import { ButtonLink } from "./button";

const ALERT = {
  info: { icon: Info, cls: "border-info/30 bg-info/5 text-info" },
  success: { icon: CheckCircle2, cls: "border-brand-500/30 bg-brand-500/5 text-brand-400" },
  warn: { icon: AlertTriangle, cls: "border-warn/30 bg-warn/5 text-warn" },
  danger: { icon: XCircle, cls: "border-danger/30 bg-danger/5 text-danger" },
  demo: { icon: Info, cls: "border-demo/30 bg-demo/5 text-demo" },
};

export function Alert({
  tone = "info",
  title,
  children,
  className,
}: {
  tone?: keyof typeof ALERT;
  title?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  const { icon: Icon, cls } = ALERT[tone];
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={cn("flex gap-3 rounded-[var(--radius-md)] border px-4 py-3 text-sm", cls, className)}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={cn("text-fg/80", title && "mt-0.5")}>{children}</div>}
      </div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-[var(--radius-sm)] bg-surface-3", className)} />;
}

export function EmptyState({ icon: Icon = Info, title, children }: { icon?: React.ElementType; title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      <div className="mb-3 rounded-full border border-border bg-surface-2 p-3">
        <Icon className="h-5 w-5 text-muted" aria-hidden />
      </div>
      <p className="text-sm font-semibold">{title}</p>
      {children && <div className="mt-1 max-w-md text-sm text-muted">{children}</div>}
    </div>
  );
}

export function UpgradeNotice({ plan = "pro", feature }: { plan?: string; feature: string }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-[var(--radius-md)] border border-dashed border-border-strong bg-surface-2/50 px-6 py-8 text-center">
      <Lock className="h-5 w-5 text-brand-400" aria-hidden />
      <p className="text-sm">
        <span className="font-semibold">{feature}</span> is included in the <span className="capitalize">{plan}</span> plan and above.
      </p>
      <ButtonLink href="/pricing" size="sm">
        View plans
      </ButtonLink>
    </div>
  );
}
