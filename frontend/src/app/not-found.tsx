import { ButtonLink } from "@/components/ui/button";
import { LogoMark } from "@/components/brand/logo";

export default function NotFound() {
  return (
    <div className="pitch-grid flex min-h-screen flex-col items-center justify-center gap-4 px-4 text-center">
      <LogoMark className="h-14 w-14 text-fg" />
      <h1 className="font-[family-name:var(--font-display)] text-3xl font-bold">Offside.</h1>
      <p className="text-muted">That page doesn&apos;t exist.</p>
      <ButtonLink href="/">Back to home</ButtonLink>
    </div>
  );
}
