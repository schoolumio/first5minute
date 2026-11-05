"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  ArrowLeftRight,
  Bell,
  CircleUser,
  FlaskConical,
  History,
  LayoutDashboard,
  LogOut,
  Menu,
  Radar,
  Scale,
  ShieldCheck,
  Ticket,
  X,
} from "lucide-react";
import { Logo } from "@/components/brand/logo";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert, Skeleton } from "@/components/ui/feedback";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { relative } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useTicket } from "@/lib/ticket";

const GROUPS = [
  { label: "Intelligence", items: [
    { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
    { href: "/scanner", label: "Match scanner", icon: Radar },
    { href: "/odds", label: "Odds comparison", icon: Scale },
    { href: "/predictions", label: "Track record", icon: History },
  ] },
  { label: "Betslip tools", items: [
    { href: "/ticket", label: "My ticket", icon: Ticket },
    { href: "/booking-code-converter", label: "Convert Booking Code", icon: ArrowLeftRight },
  ] },
  { label: "You", items: [{ href: "/account", label: "Account", icon: CircleUser }] },
];

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { user } = useAuth();
  const { items: ticket } = useTicket();
  const groups = user?.role === "admin" ? [...GROUPS, { label: "Operations", items: [{ href: "/admin", label: "Admin", icon: ShieldCheck }] }] : GROUPS;
  return (
    <nav className="flex flex-col gap-5 overflow-y-auto p-3" aria-label="Main">
      {groups.map((g) => (
        <div key={g.label}>
          <p className="mb-1.5 px-3 font-[family-name:var(--font-mono)] text-[10px] font-semibold uppercase tracking-[0.2em] text-subtle">{g.label}</p>
          <div className="flex flex-col gap-0.5">
            {g.items.map(({ href, label, icon: Icon }) => {
              const active = pathname === href || pathname.startsWith(href + "/");
              return (
                <Link key={href} href={href} onClick={onNavigate} aria-current={active ? "page" : undefined}
                  className={cn("group relative flex items-center gap-3 rounded-[var(--radius-md)] px-3 py-2 text-[13px] font-medium transition-colors",
                    active ? "bg-gradient-to-r from-brand-500/15 to-transparent text-fg" : "text-muted hover:bg-surface-2/70 hover:text-fg")}>
                  {active && <span className="absolute inset-y-1.5 left-0 w-[3px] rounded-r bg-brand-500 shadow-[0_0_12px_rgb(108_194_46/0.8)]" aria-hidden />}
                  <Icon className={cn("h-4 w-4 shrink-0", active ? "text-brand-400" : "text-subtle group-hover:text-muted")} aria-hidden />
                  {label}
                  {href === "/ticket" && ticket.length > 0 && <span className="numeral ml-auto flex h-5 min-w-5 items-center justify-center rounded-[4px] bg-brand-500 px-1 text-xs text-[#06110a]">{ticket.length}</span>}
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );
}

interface NotificationList {
  items: { id: number; title: string; body: string; link: string | null; read: boolean; created_at: string }[];
  unread: number;
}

function Notifications() {
  const [open, setOpen] = useState(false);
  const { data, reload } = useApi<NotificationList>("/notifications", { page_size: 8 });
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const markAll = async () => {
    await api("/notifications/read-all", { method: "POST" });
    reload();
  };
  return (
    <div className="relative" ref={ref}>
      <button className="relative cursor-pointer rounded-full p-2 text-muted hover:bg-surface-2 hover:text-fg" onClick={() => setOpen(!open)}
        aria-label={`Notifications${data?.unread ? ` (${data.unread} unread)` : ""}`}>
        <Bell className="h-4.5 w-4.5" />
        {!!data?.unread && <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-brand-500" />}
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-2 w-80 overflow-hidden rounded-[var(--radius-lg)] border border-border bg-surface shadow-2xl">
          <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
            <p className="text-sm font-semibold">Notifications</p>
            {!!data?.unread && (
              <button className="cursor-pointer text-xs text-brand-400 hover:underline" onClick={markAll}>
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-96 overflow-y-auto">
            {!data?.items.length && <p className="px-4 py-6 text-center text-sm text-muted">No notifications yet.</p>}
            {data?.items.map((n) => (
              <Link key={n.id} href={n.link ?? "#"} onClick={() => setOpen(false)}
                className={cn("block border-b border-border/60 px-4 py-3 hover:bg-surface-2", !n.read && "bg-brand-500/5")}>
                <p className="text-sm font-medium">{n.title}</p>
                <p className="mt-0.5 line-clamp-2 text-xs text-muted">{n.body}</p>
                <p className="mt-1 text-[11px] text-subtle">{relative(n.created_at)}</p>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function DataModeBanner() {
  const { status } = useAuth();
  if (!status) return null;
  if (status.data_mode === "demo") {
    return (
      <div className="flex items-center justify-center gap-2 border-b border-demo/30 bg-[repeating-linear-gradient(135deg,rgb(192_132_252/0.12)_0_10px,rgb(192_132_252/0.06)_10px_20px)] px-4 py-1.5 text-center text-[11px] text-demo">
        <FlaskConical className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span>
          <strong>Demo environment.</strong> Fixtures, teams, results and predictions are synthetic development data - no live
          football provider is connected.
        </span>
      </div>
    );
  }
  return null;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading, logout, status } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const signingOut = useRef(false);

  useEffect(() => {
    if (!loading && !user && !signingOut.current) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [loading, user, router, pathname]);

  const signOut = async () => {
    signingOut.current = true;
    await logout();
    router.replace("/");
  };

  if (loading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Skeleton className="h-8 w-40" />
      </div>
    );
  }

  const initials = (user.full_name || user.email).split(/[\s@.]+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("");
  const today = new Date().toLocaleDateString(undefined, { weekday: "short", day: "2-digit", month: "short" }).replace(",", "");
  const scannerAt = status?.last_runs?.scanner?.at;

  return (
    <div className="bg-stadium flex min-h-screen flex-col">
      <div className="flex flex-1">
        <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-border/80 bg-surface/50 backdrop-blur lg:flex">
          <Link href="/" className="flex h-16 items-center px-5" aria-label="First5Minute home">
            <Logo />
          </Link>
          <span className="ribbon ribbon-dim mx-5 mb-2" aria-hidden />
          <Sidebar />
          <div className="mt-auto space-y-3 border-t border-border/80 p-4">
            <div className="flex items-center gap-2 text-[11px] text-muted">
              <span className={cn("h-2 w-2 rounded-full", scannerAt ? "animate-pulse-dot bg-brand-500" : "bg-subtle")} aria-hidden />
              {scannerAt ? <>Scanner live · ran {relative(scannerAt)}</> : "Scanner has not run yet"}
            </div>
            <div className="flex items-center justify-between text-[11px] text-muted">
              <span>Plan</span><Badge tone="brand">{user.entitlements?.plan_name ?? "Free"}</Badge>
            </div>
            <div className="flex items-center justify-between text-[11px] text-muted">
              <span>Data</span><Badge tone={status?.data_mode === "live" ? "brand" : "demo"}>{status?.data_mode ?? "unknown"}</Badge>
            </div>
          </div>
        </aside>

        {mobileOpen && (
          <div className="fixed inset-0 z-50 lg:hidden">
            <div className="absolute inset-0 bg-black/70" onClick={() => setMobileOpen(false)} />
            <aside className="absolute inset-y-0 left-0 w-72 border-r border-border bg-surface">
              <div className="flex h-16 items-center justify-between px-4">
                <Logo />
                <button className="cursor-pointer p-1 text-muted" onClick={() => setMobileOpen(false)} aria-label="Close menu">
                  <X className="h-5 w-5" />
                </button>
              </div>
              <Sidebar onNavigate={() => setMobileOpen(false)} />
            </aside>
          </div>
        )}

        <div className="flex min-w-0 flex-1 flex-col">
          <DataModeBanner />
          <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-border/80 bg-bg/80 px-4 backdrop-blur sm:px-8">
            <button className="cursor-pointer p-1 text-muted lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open menu">
              <Menu className="h-5 w-5" />
            </button>
            <div className="hidden items-center gap-3 sm:flex">
              <span className="numeral rounded-[4px] border border-border-strong px-2 py-1 text-[11px] uppercase tracking-widest text-muted">{today}</span>
              <span className="text-xs text-subtle">Match-day view · all times local</span>
            </div>
            <div className="flex items-center gap-1.5">
              <Notifications />
              <span className="mx-1 hidden h-6 w-px bg-border sm:block" />
              <span className="hidden max-w-40 truncate text-sm text-muted md:inline">{user.full_name || user.email}</span>
              <span className="numeral flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-brand-500 to-brand-700 text-xs text-[#06110a]" aria-hidden>{initials}</span>
              <Button variant="ghost" size="icon" onClick={signOut} aria-label="Sign out" title="Sign out">
                <LogOut className="h-4 w-4" />
              </Button>
            </div>
          </header>
          {!user.email_verified && (
            <div className="px-4 pt-4 sm:px-8">
              <Alert tone="warn" title="Verify your email address">
                Check your inbox for the verification link to unlock the scanner.{" "}
                <button className="cursor-pointer font-semibold underline" onClick={() => api("/auth/resend-verification", { method: "POST" })}>
                  Resend link
                </button>
              </Alert>
            </div>
          )}
          <main className="mx-auto w-full max-w-[1400px] flex-1 animate-fade-in px-4 py-8 sm:px-8">{children}</main>
        </div>
      </div>
    </div>
  );
}

export function PageHeader({ title, description, action, eyebrow }: { title: string; description?: React.ReactNode; action?: React.ReactNode; eyebrow?: string }) {
  return (
    <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1 className="mt-3 break-words font-[family-name:var(--font-display)] text-[30px] font-semibold uppercase leading-[1.05] tracking-wide sm:text-[40px]">{title}</h1>
        {description && <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted">{description}</p>}
        <span className="ribbon mt-4" aria-hidden />
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
