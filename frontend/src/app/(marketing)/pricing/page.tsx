import { PricingTable } from "@/components/pricing-table";

export const metadata = { title: "Pricing" };

export default function PricingPage() {
  return (
    <section className="bg-stadium mx-auto max-w-none px-4 py-20 sm:px-6">
      <div className="mx-auto max-w-7xl">
        <span className="eyebrow">Pricing</span>
        <h1 className="mt-4 font-[family-name:var(--font-display)] text-5xl font-bold uppercase leading-none tracking-wide sm:text-7xl">Plans &amp; pricing</h1>
        <p className="mb-12 mt-5 max-w-2xl text-muted">
          Every plan is checked on the server. Upgrading unlocks features immediately after payment confirmation.
        </p>
      <PricingTable />
      </div>
    </section>
  );
}
