import { PricingTable } from "@/components/pricing-table";

export const metadata = { title: "Pricing" };

export default function PricingPage() {
  return (
    <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6">
      <h1 className="font-[family-name:var(--font-display)] text-4xl font-extrabold tracking-tight">Plans & pricing</h1>
      <p className="mb-10 mt-3 max-w-2xl text-muted">
        Every plan is checked on the server. Upgrading unlocks features immediately after payment confirmation.
      </p>
      <PricingTable />
    </section>
  );
}
