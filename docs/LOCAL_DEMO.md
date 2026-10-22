# Local demo (presentations on one Windows PC)

A complete, clickable escrow demo with **simulated money only**. There is no bank,
card or QPay integration anywhere. Every page says
**"DEMO — SIMULATED MONEY — NO REAL PAYMENTS"**.

## Start, stop, reset

Requires Docker Desktop (running).

| | Double-click | or in PowerShell |
|---|---|---|
| Start (keeps data) | `scripts\demo-start.cmd` | `powershell -ExecutionPolicy Bypass -File scripts\demo-start.ps1` |
| Reset to a fresh demo | `scripts\demo-reset.cmd` | `powershell -ExecutionPolicy Bypass -File scripts\demo-reset.ps1 -Yes` |
| Stop | | `docker compose -f compose.yaml -f compose.demo.yaml stop` |

Then open **http://localhost:3000**.

- **Reset** deletes the local Docker database (the ledger is append-only, so the
  database is recreated rather than edited) and seeds it again. It takes about a
  minute.
- The first start builds the images, which takes a few minutes.

## Seeded accounts

| Role | Email | Password | Starts with |
|---|---|---|---|
| Buyer (Сараа) | `demo.buyer@example.com` | `SafePay-Demo-2026` | 10,000,000 ₮ simulated |
| Seller (Болд) | `demo.seller@example.com` | `SafePay-Demo-2026` | 0 ₮ |
| Admin | `demo.admin@example.com` | admin password `SafePay-Admin-Demo-2026` + 6-digit code | — |

You never need to type these:
- The yellow **"Демо"** bar at the top of every page switches between
  **Худалдан авагч / Худалдагч / Админ** with one click.
- The login page and the admin login page have one-click demo buttons.
- The admin's one-time code is filled in automatically.

## Presenter script (about 5 minutes)

1. **Buyer → Шинэ гэрээ.**
   - "Худалдан авагч" and the seller's email are pre-filled. Enter a title and a
     price, then click **Гэрээ үүсгэх**.
   - The seller is added to the deal at once.
   - Click **Нөхцөлийг батлаад илгээх**.
2. **Switch to Seller.** Open the deal, then click **Нөхцөлийг зөвшөөрөх** (accept).
3. **Switch to Buyer.** Open the deal and click **Төлбөр байршуулах**.
   - The dialog shows the wallet before and after paying. Confirm.
   - On the dashboard, the money has moved from **Боломжит** (available) to
     **Барьцаанд байгаа** (held in escrow).
4. **Switch to Seller.** Click **Хүлээлгэн өгсөн гэж тэмдэглэх** (mark delivered).
5. **Switch to Buyer.** Click **Хүлээн авснаа батлах** (confirm receipt).
   - The deal is **Амжилттай дууссан** (completed).
   - The seller's wallet shows the payment.

**Other flows:**
- **Cancel:** before payment, **Гэрээг цуцлах** (no money moves).
- **Refund:** after payment, the seller clicks **Мөнгийг буцаан олгох**. The money
  returns to the buyer's wallet.
- **Dispute:**
  1. After delivery, the buyer clicks **Маргаан нээх**.
  2. **Switch to Admin**, open the dispute and pick an outcome.
  3. Give a reason, then click **Шийдвэрийг батлах**.

Every deal page shows its status, timeline and escrow postings. The dashboard
wallet lists every movement.

## How the demo is isolated

Each demo behaviour needs both of these keys:
1. **`LOCAL_DEMO=true`** for the APIs (set only by `compose.demo.yaml`).
   - The APIs **refuse to start** with it in staging or production.
   - It mounts `/demo/*`: the account list and the demo admin's current code.
   - It lifts login rate limits **only for the three seeded emails**.
   - It adds a seeded counterparty to a new deal directly, through the normal join
     checks.
2. **`platform_policy.demo_wallets_enabled`** in the database (migration 0007).
   - It is off by default. Only the schema owner can set it, with
     `python -m app.cli demo-seed`, which refuses unless `APP_ENV` is local/test.
   - While it is on, funding a **demo** deal takes the money from the buyer's
     simulated wallet (refused when the wallet holds too little).

**Unchanged:**
- Non-demo deals are funded exactly as before, from the platform's
  simulated-cash account.
- Release, refund, dispute rules and the ledger invariants.
- CSRF and Origin checks, sessions.
- Admin password + TOTP: the demo admin has real credentials, and the page only
  fills them in.

Tests: `apps/api/tests/integration/test_local_demo.py` and
`apps/web/e2e/localdemo.spec.ts`.
