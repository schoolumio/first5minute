"use client";

import { X } from "lucide-react";
import { useEffect, useRef } from "react";

/** Minimal accessible modal: Esc / backdrop closes, focus moves into the dialog. */
export function Dialog({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70" onClick={onClose} />
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title}
        className="relative w-full max-w-lg rounded-[var(--radius-xl)] border border-border-strong bg-surface p-6 shadow-2xl outline-none">
        <button className="absolute right-4 top-4 cursor-pointer text-muted hover:text-fg" onClick={onClose} aria-label="Close"><X className="h-5 w-5" /></button>
        <h2 className="pr-8 text-lg font-bold">{title}</h2>
        <div className="mt-3">{children}</div>
      </div>
    </div>
  );
}
