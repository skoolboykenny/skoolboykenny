# Maru Quick operations dashboard

`ops-dashboard.html` is the operations dashboard, rebuilt from `dashboard.html` (the original template, kept for reference). Open it in a browser; it is self-contained and runs on sample data.

## What changed, and why

A five-advisor review checked the template against the vending use case. All five agreed on the outcome below.

- **The screen answers four questions, in order:**
  1. Is any customer's money in limbo?
  2. Can we still vend?
  3. Is the business flowing?
  4. For a BPC evaluator: can the books be trusted?
- **Integrity strip at the top:** "0 lost · 0 double tokens", tokens issued = sales succeeded, the time of the last reconciliation with BPC, and how fresh the data is (it turns to "Stale" after 60 s).
- **KPI row:**
  - Float available is the yellow hero, because vending stops when float runs out. It shows the low-float threshold marker and the amount held for sales in flight.
  - Sales today.
  - Sales in flight.
  - Exceptions: recovering, manual review and failed.
- **One primary action:** "Review exceptions". The reconciliation CSV is the secondary action.
- **Card mapping:**

  | Template card | Becomes |
  |---|---|
  | Project analytics | Sales by channel: stacked web, app, POS and USSD bars for today, 7 days or 30 days |
  | Time tracker (dark card) | BPC link: endpoint, protocol, active site, terminals, rate, and the measured timings |
  | Progress gauge | Sale-state funnel, with plain-English labels |
  | Projects list | Needs attention, oldest first |
  | Workload meters | Workers: one XMLVend terminal each |
  | Latest activity | Audit log, plus Float movements |

- **Added:** Districts (live and planned), and a BPC viewer mode (the eye icon) that hides operator-only actions and shows a read-only badge.
- **Dropped:** the splash loader, meetings, team collaboration, the time tracker, the mobile-app promo and the staggered entrance animations. There is one short fade, and it is turned off under reduced motion.
- **Honesty rules:**
  - Measured timings say where and when they were measured.
  - The page is marked "Sample data".
  - No status relies on colour alone: every state chip has an icon and a word.

## Logos

- **Maru Quick logo:** once, in the sidebar brand slot (`.brand`). It shows the mark only when the rail is collapsed. It also goes in the favicon and on exports.
  - Supply two transparent files: `logo.svg` for light mode and `logo-dark.svg` for dark mode. One file cannot meet contrast on both backgrounds.
  - Never on a KPI card (yellow on yellow fails contrast), never as a watermark, never repeated.
- **BPC:** shown as text only ("BPC link"). A BPC logo would imply an endorsement the tender has not given. Add one only with BPC's written permission, small, inside the BPC link card, and never beside the Maru Quick logo.

## Wiring it up

Replace the `D` object in the script with a JSON endpoint (e.g. `GET /bpc/api/overview`). Every figure on the page comes from that object. Amounts are in thebe.
