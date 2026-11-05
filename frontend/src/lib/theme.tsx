"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";

export type Theme = "dark" | "light";
const KEY = "f5m-theme";

/** Runs before first paint (inlined in <head>) so there is no flash of the wrong theme. */
export const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem("${KEY}");if(t!=="light"&&t!=="dark")t="dark";document.documentElement.dataset.theme=t;var m=document.querySelector('meta[name="theme-color"]');if(m)m.setAttribute("content",t==="light"?"#ffffff":"#050b17");}catch(e){document.documentElement.dataset.theme="dark";}})();`;

export function useTheme() {
  const [theme, setTheme] = useState<Theme | null>(null);
  useEffect(() => { setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark"); }, []);
  const apply = (t: Theme) => {
    document.documentElement.dataset.theme = t;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", t === "light" ? "#ffffff" : "#050b17");
    try { localStorage.setItem(KEY, t); } catch { /* private mode: the choice just will not persist */ }
    setTheme(t);
  };
  return { theme, setTheme: apply, toggle: () => apply(theme === "light" ? "dark" : "light") };
}

/** Sun/moon switch. `labelled` shows the words, for menus. */
export function ThemeToggle({ className, labelled }: { className?: string; labelled?: boolean }) {
  const { theme, toggle } = useTheme();
  const light = theme === "light";
  const next = light ? "dark" : "light";
  return (
    <button type="button" onClick={toggle} aria-label={`Switch to ${next} mode`} title={`Switch to ${next} mode`} data-testid="theme-toggle"
      className={cn("inline-flex h-9 cursor-pointer items-center justify-center gap-2 rounded-[var(--radius-md)] px-2.5 text-muted transition-colors hover:bg-surface-2 hover:text-fg", className)}>
      {theme === null ? <span className="h-4 w-4" /> : light ? <Moon className="h-4 w-4" aria-hidden /> : <Sun className="h-4 w-4" aria-hidden />}
      {labelled && <span className="text-sm font-medium">{light ? "Dark mode" : "Light mode"}</span>}
    </button>
  );
}
