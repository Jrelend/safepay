import { StatusBadge } from "@/components/status-badge";
import { DEAL_STATUSES, DEAL_STATUS_META } from "@/lib/deal-status";
import { mn } from "@/lib/i18n/mn";
import { formatMnt } from "@/lib/money";

export default function HomePage() {
  return (
    <div className="space-y-8">
      <section className="space-y-4">
        <h1 className="text-2xl leading-tight font-bold">{mn.hero.title}</h1>
        <p className="text-muted">{mn.hero.body}</p>
        <div className="bg-surface border-border rounded-2xl border p-4 shadow-sm">
          <div className="text-muted text-xs">Жишээ гүйлгээ</div>
          <div className="mt-1 flex items-center justify-between gap-3">
            <div className="font-medium">iPhone 13, 128GB</div>
            <StatusBadge status="FUNDED" />
          </div>
          <div className="mt-3 text-2xl font-semibold tabular-nums">{formatMnt(1_250_000)}</div>
        </div>
        <button
          type="button"
          disabled
          aria-describedby="cta-note"
          className="bg-brand text-brand-foreground min-h-12 w-full rounded-xl px-4 font-semibold opacity-60"
        >
          {mn.hero.primaryCta}
        </button>
        <p id="cta-note" className="text-muted text-center text-xs">
          {mn.hero.comingSoon}
        </p>
      </section>

      <section aria-labelledby="steps-title" className="space-y-3">
        <h2 id="steps-title" className="text-lg font-semibold">
          {mn.steps.title}
        </h2>
        <ol className="space-y-3">
          {mn.steps.items.map((step, i) => (
            <li key={step.title} className="bg-surface border-border flex gap-3 rounded-2xl border p-4">
              <span className="bg-brand-soft text-brand grid size-8 shrink-0 place-items-center rounded-full text-sm font-bold">
                {i + 1}
              </span>
              <div>
                <div className="font-medium">{step.title}</div>
                <p className="text-muted text-sm">{step.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="statuses-title" className="space-y-3">
        <h2 id="statuses-title" className="text-lg font-semibold">
          {mn.statuses.title}
        </h2>
        <ul className="bg-surface border-border divide-border divide-y rounded-2xl border">
          {DEAL_STATUSES.map((status) => (
            <li key={status} className="flex flex-col items-start gap-1 p-4">
              <StatusBadge status={status} />
              <p className="text-muted text-sm">{DEAL_STATUS_META[status].description}</p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
