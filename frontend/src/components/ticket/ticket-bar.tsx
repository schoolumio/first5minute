"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Ticket } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { useTicket } from "@/lib/ticket";

/** Floating shortcut to the ticket whenever it has games and you are on another page. */
export function TicketBar() {
  const { items } = useTicket();
  const path = usePathname();
  if (!items.length || path === "/ticket") return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-3 z-30 flex justify-center px-3">
      <div className="pointer-events-auto flex w-full max-w-md items-center justify-between gap-3 rounded-[var(--radius-lg)] border border-brand-500/40 bg-surface px-4 py-3 shadow-[var(--shadow-card)]">
        <p className="text-sm font-semibold"><Ticket className="mr-1.5 inline h-4 w-4 text-brand-400" aria-hidden />Ticket: {items.length} {items.length === 1 ? "game" : "games"}</p>
        <Link href="/ticket" className={cn(buttonVariants({ size: "sm" }))}>Review &amp; generate code</Link>
      </div>
    </div>
  );
}
