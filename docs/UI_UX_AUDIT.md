# SafePay Beta v0.1 — UI/UX Audit

**Scope:** every page in `apps/web` (Next.js App Router), user and admin.
**Method:** Playwright screenshots at 390 px and 1440 px in light and dark mode
(64 captures, `e2e/ui-review.spec.ts`, kept in `docs/screenshots/ui-review/before/`),
a code read of every page and shared component, and computed WCAG contrast
ratios for the colour tokens.
**Baseline:** `main` at `a04f17c`.
**Standard:** WCAG 2.2 AA for accessibility.

Severity:

- 🔴 **Critical** — can cause a wrong financial action, hides where the money
  is, or fails a WCAG AA criterion that blocks a task.
- 🟡 **Major** — causes confusion, extra work or a measurable accessibility
  gap. The task can still be finished.
- 🟢 **Minor** — polish, consistency or copy.

## Summary

| Area | 🔴 | 🟡 | 🟢 |
|---|---|---|---|
| Transaction flow and money clarity | 3 | 4 | 2 |
| Navigation and information architecture | 1 | 3 | 2 |
| Visual design and consistency | 0 | 4 | 4 |
| Forms, errors and feedback | 0 | 4 | 2 |
| Accessibility (WCAG 2.2 AA) | 2 | 5 | 2 |
| Mongolian copy | 0 | 2 | 4 |
| Admin | 0 | 3 | 1 |

What already works, and must be kept:

- Every screen that shows or moves money carries the
  «ТУРШИЛТЫН ТӨЛБӨР — БОДИТ МӨНГӨ БИШ» notice.
- Nothing overflows horizontally at 390 px or 1440 px, in either theme.
- Mongolian Cyrillic (Ө, Ү) renders correctly with system fonts.
- Confirmation dialogs use one idempotency key per opening, so a double tap
  cannot repeat an action.
- Form fields have real `<label>`s, errors are linked with
  `aria-describedby`, and there is a skip link.
- Body text in both themes passes AA contrast (5.5:1 or better).

## 1. Transaction flow and money clarity

| # | Finding | Severity | Where | Recommendation |
|---|---|---|---|---|
| F1 | **«Маргаан нээх» has the same visual weight as the primary action.** It is a full-width bright red button directly under «Хүлээн авснаа батлах». A buyer about to confirm can tap the wrong one, and two equal buttons give no hint which is the normal path. | 🔴 | Deal detail (DELIVERED, FUNDED) | One primary action. Move destructive and escape actions (dispute, cancel, decline) into a separate "Асуудал гарсан уу?" area with an outlined danger style. |
| F2 | **No "who acts next" indicator.** The status badge says what happened (for example «Хүргэгдсэн»), but not whose turn it is or what the user must do. The dashboard "Таны хариу хүлээж буй" list covers only 3 of the 10 states. | 🔴 | Deal detail, dashboard, deal cards | Add a "next step" panel to every deal: who needs to act, what to do, and what happens after. Derive "your turn" from the actions the API allows (`deal.actions`), not from a hand-kept map. |
| F3 | **Where the simulated money is is never stated.** Users must infer it from the status label («Барьцаанд байршсан») or from the escrow postings card at the bottom of the page. | 🔴 | Deal detail | Add a "Мөнгө хаана байна" line: not paid yet, held by SafePay, released to the seller, or refunded to the buyer. |
| F4 | No overview of the whole process. Users cannot see how many steps remain. | 🟡 | Deal detail | Add a 5-step progress stepper (agree, pay, deliver, confirm, done), with a distinct branch for dispute, cancelled or refunded deals. |
| F5 | The inspection notice is a long paragraph that mixes the deadline, the no-auto-release rule and role-specific advice. | 🟡 | Deal detail (DELIVERED) | Split it into a short title, the deadline, and a role-specific next step. |
| F6 | The history (timeline) is the last card on the page; on mobile it sits below about 3 screens of terms. | 🟡 | Deal detail | Order the page: next step, then money, then progress, then terms, then history. |
| F7 | The escrow posting row wraps the amount onto a second line at 390 px («Барьцаанд байршсан · 2026-10-10 13:41» plus the amount). | 🟡 | Deal detail | Use a two-line list item: label and date on the left, amount on the right with no wrapping. |
| F8 | After an action the confirmation is only a green alert at the top. If the user had scrolled down, the change is invisible. | 🟢 | Deal detail | Move focus to the success message (`tabIndex=-1` and `focus()`), which also scrolls it into view and announces it. |
| F9 | «Нөхцөл засах» (edit terms) appears below the action buttons, separated from the draft context. | 🟢 | Deal detail (DRAFT) | Group it with the draft's next step. |

## 2. Navigation and information architecture

| # | Finding | Severity | Where | Recommendation |
|---|---|---|---|---|
| N1 | **Desktop uses the mobile bottom tab bar.** At 1440 px the whole app is a 672 px column with a phone tab bar fixed to the bottom of a wide screen. There is no desktop navigation. | 🔴 | All authenticated pages | From `md` and up, show the main navigation in the header and hide the bottom bar. Widen the content column to about 960 px and use two columns on deal detail. |
| N2 | The admin console shows the consumer bottom navigation («Шинэ», «Мэдэгдэл»…). This mixes two security contexts: the admin session is separate. | 🟡 | `/admin/*` | Hide the consumer navigation under `/admin`. The admin area gets its own header strip and navigation. |
| N3 | The admin section links (Маргаан / Хэрэглэгч / Аудит) have no current-page state, visual or `aria-current`. | 🟡 | Admin | Add active styling and `aria-current="page"`. |
| N4 | The dashboard's top card is the "Туршилтын хэтэвч" balance. It shows 0 ₮ for most users and does not explain what it is. Deals are the main object of the app, not a wallet. | 🟡 | Dashboard | Lead with "Таны ээлж" (deals that need you). Move the simulated balance to a small, explained stat. |
| N5 | «Бүх гэрээ» and «Буцах» links on deal detail duplicate the bottom navigation. | 🟢 | Deal detail | Keep only the back link. |
| N6 | The «Шинэ» tab label is vague. | 🟢 | Bottom nav | Use «Шинэ гэрээ» in the desktop navigation and keep «Шинэ» in the mobile bar, where space is tight. |

## 3. Visual design and consistency

| # | Finding | Severity | Where | Recommendation |
|---|---|---|---|---|
| V1 | The colours come from Tailwind defaults (sky, rose, amber, emerald) mixed with three custom tokens. Status, alert and notice colours are not one system, so the same "warning" looks different on a badge, an alert and a notice. | 🟡 | Global | Replace them with semantic tokens (`success`, `warning`, `danger`, `info`, each with `soft`, `fg` and `border`) for both themes. |
| V2 | In dark mode the notices are heavy: a saturated brown/orange test notice and a bright blue info alert. They dominate the page more than the content does. | 🟡 | Dark mode | Use desaturated tinted surfaces with a coloured border and a coloured title. |
| V3 | The simulation banner is 12 px text across the full width, two lines on mobile. It is the most important trust message and the least readable. | 🟡 | Global | Use a compact, high-contrast strip: a short label ("Туршилтын орчин") plus a one-line explanation. |
| V4 | The type scale is ad hoc (text-2xl, text-3xl, text-lg mixed freely). Headings and amounts compete. | 🟡 | Global | Define a fixed scale (display / title / heading / body / caption) and one amount style. |
| V5 | Cards have no elevation, and the light border (1.25:1) makes the card edges almost invisible on the light background. | 🟢 | Global | Use a slightly stronger border and a subtle shadow. |
| V6 | The landing page has a "Жишээ гүйлгээ (бодит биш)" card and lists all 10 statuses. This is noise for a first-time visitor. | 🟢 | Landing | Keep the hero, 3 steps and safety points. Remove the status list. Present the example as a labelled illustration of the deal stepper. |
| V7 | "SP" lettermark plus a "Beta" pill. The pill border is very faint. | 🟢 | Header | Use a refined mark and a clearer Beta tag. |
| V8 | The emoji "📎" and "✓" glyphs are used as icons. They render differently on each OS. | 🟢 | Evidence list, terms, landing | Use inline SVG icons. |

## 4. Forms, errors and feedback

| # | Finding | Severity | Where | Recommendation |
|---|---|---|---|---|
| E1 | **The native file input shows English text** ("Choose File / No file chosen"), with no file name, size or type feedback before upload. | 🟡 | Dispute evidence | Use a localized file picker: a labelled button and the selected file's name and size. Validate type and size before upload. |
| E2 | The dispute page has two separate forms (statement, file), with one shared error message below both. The error can appear far from the form that caused it. | 🟡 | Dispute | Give each form its own inline error, and show a success message after sending. |
| E3 | The new-deal form is one long page with a submit button at the end. There is no summary of what the counterparty will see, and the role choice looks like a toggle without explanation. | 🟡 | Create deal | Group it into numbered sections (Role / What / Price and terms / Invite). Explain each role in one line. Show the fee-free total near submit. |
| E4 | Most errors only say «Алдаа гарлаа» or show the API message. Field-level errors exist but are not announced when they appear. | 🟡 | All forms | Add `role="alert"` to field errors and move focus to the first invalid field on submit. |
| E5 | The empty states are plain text («Мэдэгдэл алга»), with no explanation or next action. | 🟢 | Notifications, history, evidence | Use the pattern: what this is, why it is empty, how to start. |
| E6 | The «Хуулагдлаа ✓» confirmation on the invite link is not announced to screen readers. | 🟢 | Invite box | Use a polite live region. |

## 5. Accessibility (WCAG 2.2 AA)

Contrast was measured with the WCAG relative-luminance formula.

| Element | Foreground | Background | Ratio | Required | Result |
|---|---|---|---|---|---|
| Muted text (light) | `#5b6573` | `#f6f7f9` | 5.51 | 4.5 | ✅ |
| Brand link (light) | `#0b6e4f` | `#ffffff` | 6.25 | 4.5 | ✅ |
| Error text rose-600 | `#e11d48` | `#ffffff` | 4.70 | 4.5 | ✅ (barely) |
| White on danger button | `#ffffff` | `#e11d48` | 4.70 | 4.5 | ✅ (barely) |
| **Input border (light)** | `#e3e6eb` | `#ffffff` | **1.25** | 3.0 (1.4.11) | ❌ |
| **Input border (dark)** | `#2a313c` | `#161b22` | **1.32** | 3.0 (1.4.11) | ❌ |
| Muted text (dark) | `#9aa4b2` | `#0e1116` | 7.50 | 4.5 | ✅ |
| Brand (dark) | `#34c38f` | `#161b22` | 7.70 | 4.5 | ✅ |

| # | Finding | WCAG | Severity | Recommendation |
|---|---|---|---|---|
| A1 | **Form field boundaries are 1.25:1 (light) and 1.32:1 (dark).** Users with low vision cannot see where to type. | 1.4.11 Non-text Contrast | 🔴 | Use an input border token of at least 3:1 against the surface. |
| A2 | **The selected role in the new-deal form is shown by colour only** (green tint). The unselected radio has no visible state, and the focus ring is not shown on the visually hidden radio. | 1.4.1 Use of Color, 2.4.7 Focus Visible | 🔴 | Add a check icon and bold text to the selected option. Show a focus ring on the label through `has-[:focus-visible]`. |
| A3 | The deal-history and admin "tabs" use `role="tab"` without arrow-key handling, `aria-controls` or a labelled tabpanel. Screen readers announce tabs that do not behave like tabs. | 4.1.2 Name, Role, Value | 🟡 | Use a segmented control: buttons with `aria-pressed`. These are filters, not tabs. |
| A4 | The unread dot in notifications uses `aria-label` on a `<span>` with no role, so it is not announced. | 1.1.1, 4.1.2 | 🟡 | Add visually hidden text «Уншаагүй». |
| A5 | Several targets are below 24×24 CSS px or rely on text-only hit areas: the "Бүгдийг харах" link, the footer and back links (`min-h-8`), and the admin logout (`min-h-9` with `text-xs`). | 2.5.8 Target Size (Minimum) | 🟡 | Make every interactive target at least 24 px. The project standard is 44 px for primary targets. |
| A6 | Field errors appear without being announced, and focus is not moved to the first invalid field. | 3.3.1 Error Identification, 4.1.3 Status Messages | 🟡 | Add `role="alert"` and focus management. |
| A7 | The fixed bottom bar can cover focused elements near the bottom of the page (the main area has `pb-28`, but the sticky header and banner also take space at the top). | 2.4.11 Focus Not Obscured (Minimum) | 🟡 | Set `scroll-padding` on `html` for the header and bottom bar heights. |
| A8 | Timeline dots and status colours carry meaning without text alternatives in the stepper area (there is no stepper yet). | 1.3.1 | 🟢 | The new stepper must expose "completed / current / upcoming" as text. |
| A9 | Dark-mode `theme-color` is `#161b22`, which does not match the background. | — | 🟢 | Align it with the tokens. |

## 6. Mongolian copy

| # | Finding | Severity | Recommendation |
|---|---|---|---|
| C1 | The simulation term is inconsistent: «симуляц», «симуляци», «симуляцийн» and «туршилтын» are used for the same thing. | 🟡 | Standardize on «туршилтын» for user-facing labels and «симуляц» only in explanations. Keep the mandatory label unchanged. |
| C2 | The long helper texts on the inspection-days field (about 40 words) and the evidence notice repeat the no-auto-release rule in several places. | 🟡 | State the rule once per screen, in the next-step panel. |
| C3 | «Хүргэгдсэн» for DELIVERED is ambiguous: it reads as "delivered by courier", even for face-to-face deals. | 🟢 | «Хүлээлгэн өгсөн» matches the action name. Keep the badge and change only the description, to avoid breaking tests and the status sync. |
| C4 | The dialog confirm button is a generic «Батлах». | 🟢 | Keep «Батлах» (E2E contract), but show the action-specific consequence as the dialog title and lead text. |
| C5 | «Профайл» and «Профиль» are mixed. | 🟢 | Use «Профайл» everywhere. |
| C6 | «Түүх» (history) on deal detail and «Гэрээний түүх» in admin. | 🟢 | Use «Гэрээний түүх» in both places. |

## 7. Admin

| # | Finding | Severity | Recommendation |
|---|---|---|---|
| AD1 | The decision buttons («Худалдагчид шилжүүлэх» / «Худалдан авагчид буцаах») are styled as plain secondary toggles. The selected decision is shown only by a faint tint. | 🟡 | Use a radio card group with a clear selected state, and restate the outcome in the confirm button. |
| AD2 | The admin overview counts are tiny cards with 12 px labels. The deals-by-status list uses muted text. | 🟡 | Use stat tiles with readable labels. |
| AD3 | Party identities («Болормаа (user-…@example.com)») wrap awkwardly at 390 px. | 🟡 | Stack the name and email. |
| AD4 | The admin console looks the same as the consumer app. There is little visual cue that you are acting with elevated privileges. | 🟢 | Add an "Админ горим" strip in the navy brand colour. |

## Priority order for the redesign

1. Separate the dispute and cancel actions from the primary action. Add a next-step panel with the money location and a progress stepper (F1–F4).
2. Desktop navigation, a wider layout and admin navigation separation (N1–N3).
3. Semantic colour tokens with accessible input borders, light and dark (V1, V2, A1).
4. Accessible role picker, segmented filters, live-region errors and target sizes (A2–A7).
5. Localized evidence upload and a dispute case tracker (E1, E2).
6. Simplify the landing and dashboard, and make the copy consistent (V6, N4, C1–C6).
