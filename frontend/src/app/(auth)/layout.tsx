import Link from "next/link";
import { Logo } from "@/components/brand/logo";
import { ResponsibleNote } from "@/components/layout/marketing";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="pitch-grid flex min-h-screen flex-col items-center justify-center px-4 py-12">
      <Link href="/" className="mb-8" aria-label="Project Five home">
        <Logo />
      </Link>
      <div className="w-full max-w-md rounded-[var(--radius-xl)] border border-border bg-surface p-6 shadow-[var(--shadow-card)] sm:p-8">
        {children}
      </div>
      <ResponsibleNote className="mt-8 max-w-md text-center" />
    </div>
  );
}
