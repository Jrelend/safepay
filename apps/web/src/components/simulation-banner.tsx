import { Icon } from "@/components/icons";
import { mn } from "@/lib/i18n/mn";

/** Shown on every page: Beta never touches real money. */
export function SimulationBanner() {
  return (
    <div role="note" className="bg-mark border-b border-white/10 px-4 py-1.5 text-xs leading-snug text-white">
      <div className="mx-auto flex max-w-5xl items-center justify-center gap-2 text-center">
        <Icon name="flask" className="hidden size-4 sm:block" />
        <span>
          <strong className="font-semibold">{mn.simulationBanner.label}</strong>
          <span aria-hidden> · </span>
          <span className="opacity-90">{mn.simulationBanner.body}</span>
        </span>
      </div>
    </div>
  );
}
