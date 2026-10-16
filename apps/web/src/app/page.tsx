import Link from "next/link";

import { Icon, type IconName } from "@/components/icons";
import { ButtonLink } from "@/components/ui";
import { mn } from "@/lib/i18n/mn";
import { formatMnt } from "@/lib/money";

const STEP_ICONS: IconName[] = ["file", "lock", "checkCircle"];

/** Illustration of a deal page (clearly labelled as an example, not real data). */
function ExampleDeal() {
  const steps = ["Нөхцөл", "Төлбөр", "Хүлээлгэн өгөх", "Шалгах", "Дууссан"];
  return (
    <figure
      aria-label="Жишээ гэрээний харагдах байдал"
      className="bg-surface border-border shadow-raised rounded-2xl border p-5"
    >
      <figcaption className="text-muted mb-3 text-xs font-medium">Жишээ — бодит гүйлгээ биш</figcaption>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-semibold">iPhone 13, 128GB</div>
          <div className="text-muted text-xs">Та: Худалдан авагч</div>
        </div>
        <span className="bg-mark text-mark-foreground grid size-9 place-items-center rounded-full">
          <Icon name="lock" className="size-[18px]" />
        </span>
      </div>
      <div className="mt-3 text-[28px] leading-tight font-bold tabular-nums">{formatMnt(1_250_000)}</div>
      <div className="bg-surface-muted mt-3 rounded-xl p-3 text-sm">
        <div className="text-muted text-xs">Мөнгө хаана байна</div>
        <div className="font-semibold">SafePay-ийн барьцаанд</div>
      </div>
      <div aria-hidden className="mt-4 grid grid-cols-5 gap-1.5">
        {steps.map((s, i) => (
          <div key={s}>
            <div className={`h-1.5 rounded-full ${i < 2 ? "bg-success" : i === 2 ? "bg-primary" : "bg-border"}`} />
            <div className={`mt-1.5 text-[10px] leading-tight ${i === 2 ? "font-semibold" : "text-muted"}`}>{s}</div>
          </div>
        ))}
      </div>
    </figure>
  );
}

export default function HomePage() {
  return (
    <div className="space-y-14 md:space-y-20">
      <section className="grid grid-cols-1 items-center gap-8 md:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] md:gap-12 md:pt-6">
        <div className="space-y-5">
          <span className="bg-brand-soft text-brand inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold">
            <Icon name="shieldCheck" className="size-4" />
            {mn.tagline}
          </span>
          <h1 className="text-[32px] leading-[1.15] font-bold tracking-tight sm:text-[40px]">{mn.hero.title}</h1>
          <p className="text-muted text-base leading-relaxed sm:text-lg">{mn.hero.body}</p>
          <div className="grid gap-2 sm:flex sm:flex-wrap">
            <ButtonLink href="/register" className="sm:px-6">
              {mn.hero.primaryCta}
              <Icon name="arrowRight" className="size-4" />
            </ButtonLink>
            <ButtonLink href="/login" variant="secondary" className="sm:px-6">
              {mn.hero.login}
            </ButtonLink>
          </div>
          <p className="text-muted flex items-start gap-2 text-[13px]">
            <Icon name="flask" className="mt-0.5 size-4" />
            {mn.hero.note}
          </p>
        </div>
        <ExampleDeal />
      </section>

      <section aria-labelledby="steps-title" className="space-y-5">
        <h2 id="steps-title" className="text-xl font-bold tracking-tight sm:text-2xl">
          {mn.steps.title}
        </h2>
        <ol className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {mn.steps.items.map((step, i) => (
            <li key={step.title} className="bg-surface border-border shadow-card rounded-2xl border p-5">
              <div className="flex items-center gap-3">
                <span className="bg-primary text-primary-foreground grid size-9 place-items-center rounded-xl">
                  <Icon name={STEP_ICONS[i]} className="size-[18px]" />
                </span>
                <span className="text-muted text-xs font-semibold">Алхам {i + 1}</span>
              </div>
              <div className="mt-3 font-semibold">{step.title}</div>
              <p className="text-muted mt-1 text-sm leading-relaxed">{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="safety-title" className="space-y-5">
        <h2 id="safety-title" className="text-xl font-bold tracking-tight sm:text-2xl">
          {mn.safety.title}
        </h2>
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {mn.safety.items.map((item) => (
            <li
              key={item}
              className="bg-surface border-border flex gap-3 rounded-2xl border p-4 text-sm leading-relaxed"
            >
              <span
                aria-hidden
                className="bg-success-soft text-success grid size-7 shrink-0 place-items-center rounded-full"
              >
                <Icon name="check" className="size-4" />
              </span>
              {item}
            </li>
          ))}
        </ul>
      </section>

      <section className="bg-mark rounded-2xl p-6 text-white sm:p-8">
        <h2 className="text-xl font-bold">Туршилтын орчинд туршаад үзээрэй</h2>
        <p className="mt-2 max-w-xl text-sm leading-relaxed text-white/85">
          Beta хувилбарт бүх төлбөр симуляц. Бодит банк, карт, QPay холбогдоогүй тул ямар ч мөнгө шилжихгүй.
        </p>
        <Link
          href="/register"
          className="text-mark mt-5 inline-flex min-h-12 w-full items-center justify-center rounded-xl bg-white px-6 text-[15px] font-semibold hover:bg-white/90 focus-visible:outline-white sm:w-auto"
        >
          {mn.hero.primaryCta}
        </Link>
      </section>
    </div>
  );
}
