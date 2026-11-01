import { MarketingFooter, MarketingHeader } from "@/components/layout/marketing";
import { DataModeBanner } from "@/components/layout/app-shell";

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <DataModeBanner />
      <MarketingHeader />
      <main>{children}</main>
      <MarketingFooter />
    </>
  );
}
