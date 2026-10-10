# SafePay Design System — "Modern Trustworthy Fintech"

This is the visual and interaction system for the SafePay web app (`apps/web`).
The source of truth is the code:

- Tokens: `src/app/globals.css`
- Primitives: `src/components/ui.tsx`
- Icons: `src/components/icons.tsx`
- Deal-flow components: `src/components/deal-flow-ui.tsx`
- Deal-flow logic: `src/lib/deal-flow.ts`

This document explains the decisions behind them.

## Principles

1. **Money state is never implicit.** Every deal screen answers three
   questions: where the money is, who acts next, and what happens if
   something is wrong.
2. **One primary action per screen.** Ways out (dispute, cancel, decline,
   refund) sit in a separate, quieter "Асуудал гарсан уу?" area. They are
   never placed next to the primary button with equal weight.
3. **Simulation is always visible.** The navy "Туршилтын орчин" strip appears
   on every page. The «ТУРШИЛТЫН ТӨЛБӨР — БОДИТ МӨНГӨ БИШ» notice appears on
   every screen that shows or moves money, including confirmation dialogs.
4. **Calm, not decorative.** No gradients, glassmorphism, stock imagery,
   testimonials or invented statistics. The landing page's example deal is
   labelled «Жишээ — бодит гүйлгээ биш».
5. **Accessible by construction.** Tokens meet WCAG 2.2 AA in both themes.
   State is never conveyed by colour alone.

## Colour tokens

Components use semantic tokens only. Raw Tailwind palette classes
(`bg-rose-600`, `dark:…`) are not used. The light and dark themes are both
defined in `globals.css`.

| Token | Light | Dark | Use |
|---|---|---|---|
| `background` | `#F7F9FC` | `#0B1220` | Page |
| `surface` | `#FFFFFF` | `#121A2B` | Cards, inputs, dialogs |
| `surface-muted` | `#EEF2F7` | `#1A2438` | Inset panels, segmented track |
| `foreground` | `#172033` | `#E6EAF2` | Body text |
| `muted` | `#5A6478` | `#9AA5BA` | Secondary text |
| `border` | `#E3E8F0` | `#243049` | Decorative dividers |
| `border-strong` | `#7B8597` | `#5F6B86` | Input and control boundaries (≥ 3:1) |
| `primary` | `#101D35` navy | `#2FD39E` emerald | Primary buttons, current step |
| `brand` | `#077553` | `#3DDBA8` | Links, active navigation, emerald text |
| `brand-soft` | `#E6F6EF` | `#0F2A22` | Active nav pill, unread rows |
| `mark` / `mark-foreground` | `#101D35` / `#12B886` | same | Logo, the "money held" seal, admin strip |
| `success` | `#0B7A55` | `#5EDBAE` | Completed steps, confirmations |
| `warning` | `#7A4F00` | `#F5C66B` | Test-payment notice, inspection ended |
| `danger` | `#B42318` | `#FF8F86` | Errors, dispute |
| `danger-solid` | `#B42318` | `#B42318` | Filled destructive button (white text) |
| `info` | `#1F4FB8` | `#8DB4FF` | Neutral notices |
| `focus` | `#101D35` | `#3DDBA8` | Focus ring |

Each status tone (`success`, `warning`, `danger`, `info`) has `-soft` (tinted
surface) and `-border` companions. `TONE_SOFT` in `ui.tsx` maps a tone to the
three classes, so badges, alerts and notices share one palette.

The reference palette was Navy `#101D35`, Emerald `#12B886`, background
`#F7F9FC` and text `#172033`. It was refined in two places:

- Emerald `#12B886` is only 2.55:1 on white, so it is used for marks and
  accents, never for text. Emerald text uses `brand` `#077553` (5.1:1 on
  `brand-soft`, 5.4:1 on `background`).
- In dark mode navy cannot carry a button on a navy page, so `primary`
  becomes emerald with near-black text (8.4:1).

### Measured contrast (WCAG relative luminance)

| Pair | Ratio | Requirement |
|---|---|---|
| foreground / background (light) | 15.4 | 4.5 |
| muted / background (light) | 5.64 | 4.5 |
| muted / surface-muted (light) | 5.29 | 4.5 |
| white / primary (light) | 16.8 | 4.5 |
| brand / brand-soft (light) | 5.11 | 4.5 |
| success / success-soft (light) | 4.83 | 4.5 |
| warning / warning-soft (light) | 6.57 | 4.5 |
| danger / danger-soft (light) | 5.75 | 4.5 |
| white / danger-solid | 6.57 | 4.5 |
| info / info-soft (light) | 6.46 | 4.5 |
| border-strong / surface (light) | 3.72 | 3.0 (non-text) |
| foreground / background (dark) | 15.5 | 4.5 |
| muted / surface (dark) | 7.01 | 4.5 |
| primary-foreground / primary (dark) | 8.41 | 4.5 |
| border-strong / surface (dark) | 3.26 | 3.0 (non-text) |
| focus ring / background (dark) | 10.6 | 3.0 |

### Theme

- The app follows `prefers-color-scheme` by default.
- Profile → «Харагдах байдал» offers Төхөөрөмжөөр / Цайвар / Бараан. The
  choice sets `data-theme` on `<html>` and is stored only in the browser
  (`localStorage`).
- A small inline script in `layout.tsx` applies it before paint, so the page
  does not flash the wrong theme.

## Typography

System fonts with full Mongolian Cyrillic coverage (Ө, Ү). No web-font
download.

| Role | Size / weight | Where |
|---|---|---|
| Display | 32–40 px / 700, tight tracking | Landing h1 |
| Page title | 24 px (28 px ≥ sm) / 700 | `PageTitle` h1 |
| Amount | 28–32 px / 700, tabular numbers | Deal and invite amount (`Money`) |
| Section title | 18 px / 700 | Next-step panel h2 |
| Card title | 16 px / 600 | `CardTitle` h2 |
| Body | 14–16 px / 400–500 | Text; inputs are 16 px to avoid iOS zoom |
| Caption | 12–13 px | Hints, timestamps, metadata |

The minimum is 11 px, used only for the progress-step labels and mobile tab
labels, both of which also have full text alternatives.

## Spacing, radius, elevation

- 4 px base grid. Cards use `p-4` (`sm:p-5`), stacks use `space-y-4`, and
  sections on the landing page use `space-y-14`.
- Radius: 12 px (`rounded-xl`) for controls, 16 px (`rounded-2xl`) for cards.
- Elevation: `shadow-card` (a 1–3 px soft shadow) on cards, and
  `shadow-raised` on dialogs and the landing example.

## Layout

- The main column is up to 1024 px (`max-w-5xl`). Each page picks its
  measure with `WIDTH`:
  - `narrow` (448 px): authentication and invite pages;
  - `form` (672 px): forms, lists, profile;
  - `wide`: dashboard, deal detail, admin.
- From `lg` (1024 px), the dashboard, deal detail and admin dispute pages use
  two columns: main content plus a 320–360 px side column.
- **Navigation:**
  - Below `md` (768 px): a fixed bottom tab bar with 5 items and 64 px
    targets.
  - From `md`: the same items in the header, with «Шинэ гэрээ» as a primary
    button.
  - `/admin/*` never shows the consumer navigation. It shows an «Админ горим»
    pill in the header and its own navy admin strip with section navigation.
- Safe areas: the bottom bar respects `env(safe-area-inset-bottom)`.
  `scroll-padding` keeps focused elements clear of the sticky header and the
  bottom bar.

## Components

### Button (`Button`, `ButtonLink`, `buttonClass`)

| Variant | Use |
|---|---|
| `primary` | The single forward action on a screen |
| `secondary` | Alternatives, navigation-like actions |
| `danger` | Confirming an irreversible destructive action inside a dialog or admin decision |
| `dangerOutline` | Offering a way out (dispute, cancel, decline, revoke) — never filled |
| `ghost` | Low-emphasis inline actions |

- Sizes: `md` (48 px minimum height) and `sm` (40 px).
- `loading` shows a spinner, sets `aria-busy` and disables the button.
- Confirmation buttons keep the stable labels «Батлах» / «Болих». The dialog
  title and body name the specific action and its consequence.

### Form fields (`Field`, `TextArea`, `Select`)

- Always have a visible `<label>`.
- The hint or error is linked with `aria-describedby`.
- Errors use `role="alert"` with an icon and text, not colour alone.
- On submit, `focusFirstInvalid()` moves focus to the first invalid field.
- Boundaries use `border-strong` (3:1 or better).

### Alert

Tones: `info`, `success`, `warning`, `danger`, `neutral`. Each has an icon, an
optional title and a body in foreground colour. `danger` is
`role="alert"`; the others are `role="status"`. Pass `focusRef` to move focus
to it after an action (used for "<action>: амжилттай.").

### StatusBadge

A pill with a dot plus the status label. The tone comes from
`DEAL_STATUS_META`. The label is always text.

### SegmentedControl

Exclusive filters (deal scope, dispute status, theme). These are
`aria-pressed` buttons in a labelled group, not ARIA tabs, because they
filter one list.

### EmptyState

The pattern is: icon, then what this is, then why it is empty, then the next
action.

### Deal-flow components (`deal-flow-ui.tsx`)

- **`NextStepPanel`** shows who acts («Таны ээлж», «Нөгөө талын ээлж»,
  «SafePay шийдэж байна», «Хаагдсан»), a title, the consequence, and the
  primary action buttons. "Your turn" panels get a stronger border.
- **`MoneyLocation`** answers «Мөнгө хаана байна». The navy seal appears
  only while the money is held.
- **`DealProgress`** is a 5-step bar: Нөхцөл, Төлбөр, Хүлээлгэн өгөх,
  Шалгах, Дууссан.
  - The current step has `aria-current="step"`.
  - Each step has screen-reader text («дууссан» / «одоогийн алхам» /
    «хүлээгдэж буй»).
  - Dispute, refund, cancel and expiry show a "halted" label.
- **`TurnChip`** marks rows in lists that need the user.

The logic lives in `lib/deal-flow.ts` and is unit-tested against the backend
state machine:

- The money-held states equal `ESCROW_HELD_STATES`.
- Closed states equal `TERMINAL_STATES`.
- Primary and issue actions partition `PUBLIC_ACTIONS`.
- Turns match the backend's allowed actors.

### Dialog (`ActionDialog`)

- Native `<dialog>` with `showModal()`, so the browser handles focus trapping
  and Escape.
- `aria-labelledby` and `aria-describedby` point at the title and the
  consequence text.
- Focus returns to the button that opened it.
- One idempotency key per opening.

### Icons

24×24, 2 px stroke, in one set (`Icon`). They are decorative
(`aria-hidden`); meaning is always given in text. Emoji are not used as
icons.

## Motion

Only colour transitions and the loading spinner. `prefers-reduced-motion`
reduces all animations and transitions to effectively zero.

## Copy (Mongolian)

- Use «туршилтын» for user-facing labels and «симуляц» in explanations. The
  mandatory label «ТУРШИЛТЫН ТӨЛБӨР — БОДИТ МӨНГӨ БИШ» is fixed.
- Action labels are verbs and stay stable, because tests and users rely on
  them: «Төлбөр байршуулах», «Хүлээн авснаа батлах», «Маргаан нээх».
- Explain consequences in one sentence. State the no-auto-release rule once
  per screen.
- Never imply real banking: no bank logos, card imagery or "secure payment"
  claims.

## Do / Don't

| ✅ Do | ❌ Don't |
|---|---|
| One primary button per panel | Put «Маргаан нээх» as a filled red button next to «Хүлээн авснаа батлах» |
| Say where the money is in words | Rely on the badge colour to imply it |
| Use tokens (`text-danger`, `bg-success-soft`) | Use `text-rose-600` or `dark:` overrides |
| Give state as text plus colour | Use colour-only selection (role picker, steps) |
| Keep targets at 40–48 px (24 px minimum) | Use text-only links as primary targets |
