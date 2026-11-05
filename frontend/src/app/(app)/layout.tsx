import { AppShell } from "@/components/layout/app-shell";
import { TicketBar } from "@/components/ticket/ticket-bar";
import { TicketProvider } from "@/lib/ticket";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <TicketProvider>
      <AppShell>{children}</AppShell>
      <TicketBar />
    </TicketProvider>
  );
}
