"use client";

import Link from "next/link";
import { useState } from "react";
import { Menu, X } from "lucide-react";
import { Logo } from "@/components/brand/logo";
import { ButtonLink } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";

const NAV = [
  { href: "/#how-it-works", label: "How it works" },
  { href: "/#markets", label: "Markets" },
  { href: "/#features", label: "Features" },
  { href: "/pricing", label: "Pricing" },
  { href: "/#faq", label: "FAQ" },
];

export function MarketingHeader() {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  return (
    <header className="sticky top-0 z-40 border-b border-border/70 bg-bg/85 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6">
        <Link href="/" aria-label="Project Five home">
          <Logo />
        </Link>
        <nav className="hidden items-center gap-7 text-sm text-muted md:flex">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} className="hover:text-fg">
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="hidden items-center gap-2 md:flex">
          {user ? (
            <ButtonLink href="/dashboard" size="sm">
              Open dashboard
            </ButtonLink>
          ) : (
            <>
              <ButtonLink href="/login" variant="ghost" size="sm">
                Sign in
              </ButtonLink>
              <ButtonLink href="/register" size="sm">
                Start free
              </ButtonLink>
            </>
          )}
        </div>
        <button className="cursor-pointer p-2 text-muted md:hidden" onClick={() => setOpen(!open)} aria-label="Toggle menu" aria-expanded={open}>
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>
      {open && (
        <div className="border-t border-border px-4 pb-4 md:hidden">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} onClick={() => setOpen(false)} className="block py-2.5 text-sm text-muted">
              {n.label}
            </Link>
          ))}
          <div className="mt-2 flex gap-2">
            <ButtonLink href={user ? "/dashboard" : "/login"} variant="outline" size="sm" className="flex-1">
              {user ? "Dashboard" : "Sign in"}
            </ButtonLink>
            {!user && (
              <ButtonLink href="/register" size="sm" className="flex-1">
                Start free
              </ButtonLink>
            )}
          </div>
        </div>
      )}
    </header>
  );
}

export function ResponsibleNote({ className = "" }: { className?: string }) {
  return (
    <p className={`text-xs leading-relaxed text-subtle ${className}`}>
      18+ only. Project Five provides statistical analysis, not betting advice. Model estimates can be wrong and past performance
      does not guarantee future results. Never stake more than you can afford to lose. If gambling stops being fun, seek support
      from a local responsible-gambling service.
    </p>
  );
}

export function MarketingFooter() {
  return (
    <footer className="border-t border-border bg-surface/40">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-12 sm:px-6 md:grid-cols-4">
        <div className="md:col-span-2">
          <Logo />
          <p className="mt-4 max-w-sm text-sm text-muted">
            Global football intelligence for the opening five minutes. Built on event timelines, transparent models and honest
            uncertainty.
          </p>
          <ResponsibleNote className="mt-4 max-w-md" />
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-subtle">Product</p>
          <ul className="mt-3 space-y-2 text-sm text-muted">
            <li><Link href="/#how-it-works" className="hover:text-fg">How it works</Link></li>
            <li><Link href="/pricing" className="hover:text-fg">Pricing</Link></li>
            <li><Link href="/dashboard" className="hover:text-fg">Dashboard</Link></li>
          </ul>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-subtle">Account</p>
          <ul className="mt-3 space-y-2 text-sm text-muted">
            <li><Link href="/login" className="hover:text-fg">Sign in</Link></li>
            <li><Link href="/register" className="hover:text-fg">Create account</Link></li>
            <li><Link href="/account" className="hover:text-fg">Responsible gambling tools</Link></li>
          </ul>
        </div>
      </div>
      <div className="border-t border-border py-5 text-center text-xs text-subtle">© {new Date().getFullYear()} Project Five · First5Minute</div>
    </footer>
  );
}
