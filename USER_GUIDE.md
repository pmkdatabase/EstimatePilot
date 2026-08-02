# EstimatePilot — User Guide

EstimatePilot replaces the spreadsheet-based estimating workflow trades and construction companies often run on. It covers one continuous pipeline:

**Estimate/Quote Builder → Materials & Labor → Approved Job Setup → Schedule + Installer Sheets → Labor Hours + Material Usage → Job Costing → Profit Dashboard → Customer History/Reporting**

*(Lead Tracker — capturing a prospect before a formal quote exists — is planned but not yet built.)*

Three roles share the app, each seeing only what's relevant to their job:

| Role | Can do |
|---|---|
| **Owner** | Everything below, plus Profit Dashboard, Reports, and user management |
| **Estimator** | Customers, Materials/Labor, Estimates, Job Setup, Schedule (reschedule) |
| **Installer** | Their assigned Jobs, cost logging, Installer Sheets, Schedule (read-only, own jobs) |

---

## Getting started

```bash
cd K:\DB\EstimatePilot
.\venv\Scripts\Activate.ps1
python app.py
```

Visit `http://127.0.0.1:5000`. First run seeds demo data automatically. Demo logins:

| Role | Email | Password |
|---|---|---|
| Owner | owner@demo.com | Owner@2026! |
| Estimator | estimator@demo.com | Estimator@2026! |
| Installer | installer@demo.com | Installer@2026! |

---

## Walkthrough

### 1. Customers
**Nav → Customers.** Add a customer (name, email, phone, address) on the left; the list on the right is clickable — opens that customer's full history page (see §9).

### 2. Materials & Labor
**Nav → Materials.** Two independent catalogs:
- **Materials** — name, category, unit (sq ft, linear ft, each…), unit cost
- **Labor rates** — role/trade name + $/hr (no unit needed, it's always hourly)

Both feed into the estimate builder and job cost logging — set these up before building your first estimate.

### 3. Building an estimate
**Nav → Estimates → New estimate.** Pick a customer, give it a title, then you land on the quote builder:
- Pick a **material or labor rate** from the dropdown (grouped) — it auto-fills the unit cost and relabels the quantity field to "Hours worked" for labor, "Quantity (unit)" for materials
- Or leave it on "Custom line…" for something not in the catalog
- Set **Markup %** and **Tax %** — the summary panel (subtotal → revenue → tax → total) recalculates live as you type, before saving
- **Mark as sent** is optional (client-facing status only); **Approve → create job** is the real trigger — it locks the estimate and moves you into Job Setup

### 4. Job Setup
Triggered automatically after approving an estimate (or reachable anytime via **"Edit job setup"** on a job page). Set:
- **Crew size**
- **Target start date**
- **Site notes** (access instructions, safety requirements, equipment needed)

A job missing this info shows a **"needs setup"** badge on the Jobs list and a warning banner on its detail page until filled in.

### 5. Schedule + Installer Sheets
**Nav → Schedule.** Jobs grouped by target date; anything without a date sits in an "Unscheduled" section at the top. Owner/estimator can reschedule inline (date field + Save). Installers see the same page filtered to only their assigned jobs, read-only.

Every job has an **"Installer sheet"** button — a clean, printable work order (customer, address, phone, date, crew size, site notes, materials/labor checklist). No dollar figures appear on it; it's a field document, not a financial one.

### 6. Logging labor hours & material usage
On a job's detail page, **"Log a cost"**:
- Pick a **material or labor rate** → the field becomes "Quantity" or "Hours worked," and the dollar amount computes itself (quantity × rate) — no manual math
- Or pick **"Other (no catalog item)"** for one-off costs like permits or equipment rental → freeform description + manual amount

The **"Estimated vs. actual usage"** card compares what was priced into the quote against what's actually been logged, per material/labor line — the actual figure turns **red** if usage has exceeded the estimate.

### 7. Job costing
Automatic — no separate step. Every job's detail page shows Budget (the estimate's revenue), Actual cost (sum of all logged entries), Profit, and Margin %, updating live as costs are logged.

### 8. Profit Dashboard
**Nav → Profit Dashboard** (owner only). Aggregate revenue/cost/profit across every job, plus a per-job breakdown table, plus a count of estimates still open (draft/sent).

### 9. Customer History / Reporting
Click any customer name (Customers list, or from Reports) to see their full history: every estimate they've had, linked jobs, statuses, and lifetime revenue/cost/profit. **Export CSV** downloads that customer's full record.

**Nav → Reports** (owner only): every customer ranked by lifetime value, plus a one-click CSV export of every job company-wide (customer, status, dates, revenue, cost, profit, margin) — for accounting or spreadsheet analysis outside the app.

---

## Quick reference: where do I…

| I want to… | Go to |
|---|---|
| Add a customer | Customers |
| Add a material or labor rate | Materials |
| Build a quote | Estimates → New estimate |
| See if a job needs crew/date/notes set | Jobs (look for "needs setup" badge) |
| See what's scheduled this week | Schedule |
| Print a work order for a crew | Job detail → Installer sheet |
| Log what was actually used/worked | Job detail → Log a cost |
| Check if a job is over budget on materials | Job detail → Estimated vs. actual usage |
| See company-wide profit | Profit Dashboard (owner) |
| See one customer's full history | Click their name anywhere, or Reports |
| Export data for accounting | Customer detail → Export CSV, or Reports → Export all jobs |
| Add a team member | Users (owner) |

---

## Known gaps

- **Lead Tracker** (pre-quote pipeline stage) — not built by design decision, held for later.
- Scheduling is a grouped list by date, not a calendar grid.
- Jobs have one lead installer + a crew-size headcount, not named multi-person crew assignment.
- Not yet deployed publicly — runs locally only (see project files for PythonAnywhere deployment steps once ready).
