"use client";

import { Eye, EyeOff } from "lucide-react";
import { forwardRef, useState } from "react";
import { cn } from "@/lib/cn";
import { Input } from "@/components/ui/form";

/** Password field with a show/hide toggle. Drop-in replacement for <Input type="password" />. */
export const PasswordInput = forwardRef<HTMLInputElement, Omit<React.InputHTMLAttributes<HTMLInputElement>, "type">>(
  function PasswordInput({ className, ...props }, ref) {
    const [visible, setVisible] = useState(false);
    return (
      <div className="relative">
        <Input ref={ref} type={visible ? "text" : "password"} className={cn("pr-10", className)} {...props} />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          aria-label={visible ? "Hide password" : "Show password"}
          aria-pressed={visible}
          className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-[var(--radius-md)] text-muted hover:text-fg"
        >
          {visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
    );
  },
);
