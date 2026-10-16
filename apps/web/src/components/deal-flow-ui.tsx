import type { ReactNode } from "react";

import { Icon, type IconName } from "@/components/icons";
import { FLOW_STEPS, MONEY_COPY, MONEY_LOCATION, TURN_LABEL, dealProgress, type NextStep } from "@/lib/deal-flow";
import type { DealStatus } from "@/lib/deal-status";

/**
 * Five-step progress. State is given in text (sr-only) as well as colour,
 * and the current step carries aria-current="step".
 */
export function DealProgress({ status }: { status: DealStatus }) {
  const { current, halted } = dealProgress(status);
  return (
    <div>
      <ol aria-label="Гэрээний явц" className="grid grid-cols-5 gap-1.5">
        {FLOW_STEPS.map((label, i) => {
          const done = i < current;
          const now = i === current && !halted;
          const stopped = i === current && halted;
          return (
            <li key={label} aria-current={now ? "step" : undefined} className="min-w-0">
              <span
                aria-hidden
                className={`block h-1.5 rounded-full ${
                  done
                    ? "bg-success"
                    : now
                      ? "bg-primary"
                      : stopped
                        ? halted.tone === "danger"
                          ? "bg-danger"
                          : "bg-border-strong"
                        : "bg-border"
                }`}
              />
              <span
                className={`mt-1.5 block text-[11px] leading-tight break-words sm:text-xs ${
                  now ? "text-foreground font-semibold" : done ? "text-foreground" : "text-muted"
                }`}
              >
                {label}
              </span>
              <span className="sr-only">
                {done ? " — дууссан" : now ? " — одоогийн алхам" : stopped ? ` — ${halted.label}` : " — хүлээгдэж буй"}
              </span>
            </li>
          );
        })}
      </ol>
      {halted ? (
        <p className={`mt-2 text-xs font-semibold ${halted.tone === "danger" ? "text-danger" : "text-muted"}`}>
          {halted.label}
        </p>
      ) : null}
    </div>
  );
}

const MONEY_ICON: Record<string, IconName> = {
  NOT_PAID: "clock",
  HELD: "lock",
  LOCKED: "lock",
  RELEASED: "checkCircle",
  REFUNDED: "undo",
  NEVER_PAID: "x",
};

/** "Where is the money?" — answered on every deal. */
export function MoneyLocation({ status }: { status: DealStatus }) {
  const location = MONEY_LOCATION[status];
  const copy = MONEY_COPY[location];
  const held = location === "HELD" || location === "LOCKED";
  return (
    <div className="bg-surface-muted flex gap-3 rounded-xl p-3">
      <span
        aria-hidden
        className={`grid size-9 shrink-0 place-items-center rounded-full ${
          held ? "bg-mark text-mark-foreground" : "bg-surface text-muted border-border border"
        }`}
      >
        <Icon name={MONEY_ICON[location]} className="size-[18px]" />
      </span>
      <div className="min-w-0 text-sm">
        <div className="text-muted text-xs font-medium">Мөнгө хаана байна</div>
        <div className="font-semibold">{copy.title}</div>
        <p className="text-muted mt-0.5 text-[13px] leading-snug">{copy.body}</p>
      </div>
    </div>
  );
}

const TURN_STYLE: Record<NextStep["turn"], { chip: string; icon: IconName; ring: string }> = {
  me: { chip: "bg-primary text-primary-foreground", icon: "arrowRight", ring: "border-primary/40" },
  counterparty: { chip: "bg-surface-muted text-muted", icon: "clock", ring: "border-border" },
  safepay: { chip: "bg-danger-soft text-danger", icon: "scale", ring: "border-danger-border" },
  nobody: { chip: "bg-surface-muted text-muted", icon: "check", ring: "border-border" },
};

/** What happens next, who has to do it, and the action buttons for it. */
export function NextStepPanel({ step, children }: { step: NextStep; children?: ReactNode }) {
  const style = TURN_STYLE[step.turn];
  return (
    <section
      aria-labelledby="next-step-title"
      className={`bg-surface shadow-card space-y-3 rounded-2xl border-2 p-4 sm:p-5 ${style.ring}`}
    >
      <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${style.chip}`}>
        <Icon name={style.icon} className="size-3.5" />
        {TURN_LABEL[step.turn]}
      </span>
      <div>
        <h2 id="next-step-title" className="text-lg leading-snug font-bold">
          {step.title}
        </h2>
        <p className="text-muted mt-1 text-sm">{step.body}</p>
      </div>
      {children}
    </section>
  );
}

/** Small "your turn" marker for list rows. */
export function TurnChip() {
  return (
    <span className="bg-primary text-primary-foreground inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold">
      <Icon name="arrowRight" className="size-3" />
      Таны ээлж
    </span>
  );
}
