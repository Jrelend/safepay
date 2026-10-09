import { mn } from "@/lib/i18n/mn";

export function SimulationBanner() {
  return (
    <div
      role="note"
      className="bg-warning-soft text-warning-foreground px-4 py-2 text-center text-xs leading-snug font-medium"
    >
      {mn.simulationBanner}
    </div>
  );
}
