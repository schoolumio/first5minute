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

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/scanner", label: "Match scanner", icon: Radar },
  { href: "/odds", label: "Odds comparison", icon: Scale },
  { href: "/booking-code-converter", label: "Convert Booking Code", icon: ArrowLeftRight },
  { href: "/predictions", label: "Prediction history", icon: History },
  { href: "/account", label: "Account", icon: CircleUser },
];

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { user } = useAuth();
  const items = user?.role === "admin" ? [...NAV, { href: "/admin", label: "Admin", icon: ShieldCheck }] : NAV;
  return (
    <nav className="flex flex-col gap-1 p-3" aria-label="Main">
      {items.map(({ href, label, icon: Icon }) => {
        const active = pathname === href || pathname.startsWith(href + "/");
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            className={cn(
              "flex items-center gap-3 rounded-[var(--radius-md)] px-3 py-2 text-sm font-medium transition-colors",
              active ? "bg-brand-500/10 text-brand-400" : "text-muted hover:bg-surface-2 hover:text-fg",
            )}
          >
            <Icon className="h-4 w-4" aria-hidden />
            {label}
          </Link>
        );
      })}
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
      <div className="flex items-center justify-center gap-2 border-b border-demo/30 bg-demo/10 px-4 py-1.5 text-center text-xs text-demo">
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

  return (
    <div className="flex min-h-screen flex-col">
      <div className="flex flex-1">
        <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-border bg-surface/60 lg:flex">
          <Link href="/" className="flex h-16 items-center border-b border-border px-5">
            <Logo />
          </Link>
          <Sidebar />
          <div className="mt-auto border-t border-border p-4 text-xs text-muted">
            <p className="flex items-center justify-between">
              Plan <Badge tone="brand">{user.entitlements?.plan_name ?? "Free"}</Badge>
            </p>
            <p className="mt-2 flex items-center justify-between">
              Data <Badge tone={status?.data_mode === "live" ? "brand" : "demo"}>{status?.data_mode ?? "unknown"}</Badge>
            </p>
          </div>
        </aside>

        {mobileOpen && (
          <div className="fixed inset-0 z-50 lg:hidden">
            <div className="absolute inset-0 bg-black/60" onClick={() => setMobileOpen(false)} />
            <aside className="absolute inset-y-0 left-0 w-64 border-r border-border bg-surface">
              <div className="flex h-16 items-center justify-between border-b border-border px-4">
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
          <header className="sticky top-0 z-30 flex h-16 items-center justify-between gap-3 border-b border-border bg-bg/85 px-4 backdrop-blur sm:px-6">
            <button className="cursor-pointer p-1 text-muted lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open menu">
              <Menu className="h-5 w-5" />
            </button>
            <div className="hidden text-xs text-muted sm:block">
              {status?.last_runs?.scanner ? <>Scanner ran {relative(status.last_runs.scanner.at)}</> : "Scanner has not run yet"}
            </div>
            <div className="flex items-center gap-1">
              <Notifications />
              <span className="mx-2 hidden text-sm text-muted sm:inline">{user.full_name || user.email}</span>
              <Button variant="ghost" size="sm" onClick={signOut}>
                <LogOut className="h-4 w-4" /> <span className="hidden sm:inline">Sign out</span>
              </Button>
            </div>
          </header>
          {!user.email_verified && (
            <div className="px-4 pt-4 sm:px-6">
              <Alert tone="warn" title="Verify your email address">
                Check your inbox for the verification link to unlock the scanner.{" "}
                <button className="cursor-pointer font-semibold underline" onClick={() => api("/auth/resend-verification", { method: "POST" })}>
                  Resend link
                </button>
              </Alert>
            </div>
          )}
          <main className="mx-auto w-full max-w-7xl flex-1 animate-fade-in px-4 py-6 sm:px-6">{children}</main>
        </div>
      </div>
    </div>
  );
}

export function PageHeader({ title, description, action }: { title: string; description?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
      </div>
      {action}
    </div>
  );
}
