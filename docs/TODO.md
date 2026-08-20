# CarTrends CRM — open items

Living list. Nothing here is lost; each item says what's blocking it.

---

# ⭐ TASK ENGINE v2 — Sir's requirements (18 Aug meeting + Automate Tasks teardown)

Sources: the leadership meeting transcript and
`Automate_Tasks_Clone_Reference.docx` (screen-by-screen teardown of the live
Automate Tasks admin panel). Combined, deduplicated against what we already
have, and ordered so each phase builds on the previous one.

**Already covered — no work needed:** 6 KPI tiles, date-range presets,
Table/Bar toggle, My/Delegated/Subscribed lists, Templates, industry Task
Directory, Activities feed, Holidays, recurring tasks, follow ("In Loop" ≈ our
🔔 subscribe), My Team drill-down basics, WhatsApp/notification plumbing.

## Phase A — Core rules & schema (the foundation)

- [x] **A1 · Assignment hierarchy (level-based, NOT department-based).**
      Levels: Admin(3) → Manager(2: sales_manager, hr_manager) → Employee(1:
      everyone else). Rule: you may assign to your own level and below, never
      above. So: admin→anyone; manager→managers+employees (any department —
      inter-department explicitly allowed); **employee→fellow employees**
      (new — today employees can only self-assign). Self-assign always
      allowed. Enforced server-side in `can_assign_to(assigner, assignee)`;
      the assignee dropdown only shows people you're allowed to pick.
- [x] **A2 · Effort value.** `Task.effort_minutes` — set by the ASSIGNER
      (optional), entered as minutes or hours in the UI.
      Plus `assignee_estimate_minutes` — the assignee's one-time counter-
      estimate ("Amit says 1h, Bhavna says 4h"), logged to the activity feed,
      never overwriting the assigner's value. Both surface in reviews (D5).
- [x] **A3 · Task identity & time display.** Human task ID `T-00042` on rows
      and detail; relative due strings ("6 hours from now", "2 days overdue");
      recurring tasks get an optional **end date** (teardown has it, we don't).
- [x] **A4 · Soft delete.** Deleting a task (admin-only, unchanged) moves it
      to a **Deleted Tasks** bin (flag, not row removal) — recoverable and
      auditable, with admin restore. Matches teardown §2.

## Phase B — Edit lockdown + Modification Requests (the anti-manipulation core)

- [x] **B1 · Lock direct edits.** Assignee: status changes only. Creator:
      NO silent edits after creation (today they can — that's the score-
      manipulation hole Sir described). Admin/Super-Admin: full edit stays.
      Every field change that isn't a status move must go through B2.
- [x] **B2 · Modification Request workflow — inside the system, no separate
      form.** New model: task, requested_by, proposed changes (due date,
      effort, frequency, title/desc, "cancel this recurring task"…), reason,
      status. Routing (reconciled from the two versions discussed in the
      meeting — CONFIRM with Sir):
        * request raised by the **assignee** → approved by the **task creator**;
        * request raised by the **creator** (their own mistake, e.g. wrong
          midnight deadline, accidental daily-repeat) → approved by **Admin**
          (stops friendly-pairs score-boosting);
        * every request + approval is **logged and visible to Admin** either way.
      Approval applies the change atomically + activity log + notification to
      both parties. UI: "Request change" button on the task, an approvals
      inbox for creators/admin, badge counts.
- [x] **B3 · Completion evidence (fixes "he just keeps ticking it daily").**
      Org-level Task Settings (admin): mandatory **Remarks** / **Attachment** /
      **Image** on completion — same mechanism as teardown §6.2. Completing a
      task opens a small modal collecting the required proof; requires a task-
      attachments table (also used by E1).
- [x] **B4 · Assigner's recurring-task visibility.** "Recurring" quick filter
      on the Delegated tab ("how many daily tasks have I assigned?") so a
      forgotten accidental daily task is one click away — cancelling it goes
      through B2.

## Phase B+ — Review-meeting changes (19 Aug demo to manager) — DO BEFORE C

Corrections to claims made in the demo (for the next demo, say it right):
category IS saved & filterable (just free-text today); attachments ARE stored
permanently today; group field is a visibility tag, NOT per-member copies;
request routing already goes to the task creator (his ask "request should go
to whoever assigned" = ALREADY DONE — score that point).

- [x] **B5 · Category system v2** (pulls F1 forward, expanded):
      `Department` dropdown first on the task form → `Category` dropdown
      filtered by that department, with "+ Add Category" visible
      to managers/admin only (employees never create categories). Managed
      TaskCategory model (name, department, active), existing free-text values
      migrated, 33 defaults seeded per department. Deleting a category
      deactivates it (history intact); re-adding the name reactivates it.
- [x] **B6 · Effort mandatory** on task creation (was optional; both Prateek
      sir and the reviewer want it required — scoring depends on it).
      API-created tasks only; system-created (webforms/recurrence) exempt.
- [x] **B7 · In-Loop at creation**: colleague checkbox picker on the task
      form; picked colleagues are subscribed + notified ("You're in the
      loop: T-xxxxx") the moment the task is created.
- [ ] **B8 · Group fan-out assignment** *(ON HOLD — per boss, 19 Aug)*:
      assigning a task to a Group creates an INDIVIDUAL copy per member.
      Distinct from today's group-visibility tag — keep both when built.
- [x] **B9 · Escalate on requests**: the creator reviewing a Modification
      Request gets Approve / Reject / **Escalate ↑** — escalate hands the
      request to admin (chain logged, admins notified, creator loses the
      decision; admin cannot escalate — final approver).
- [ ] **B10 · Delegated filters** *(SKIPPED — out of context per boss)*:
      person dropdown on the Delegated tab.
- [x] **B11 · Attachment retention**: task attachments auto-delete
      **7 days after the task is completed** (sweep runs with the reminder
      ticker; `TASK_ATTACHMENT_RETENTION_DAYS` in .env, 0 = keep forever).
      Attachments stay optional by default (both evidence toggles OFF).
- [x] **B12 · Reporting-manager visibility**: the designated reporting
      manager (My Team hierarchy) sees ALL tasks assigned to their direct
      reports, regardless of who assigned them or which department.
- [~] **B13 · Render deployment for UAT** — prepped 19 Aug (see
      `docs/DEPLOY.md`): Neon migrated + local data copied over,
      render.yaml/build script/WhiteNoise/SPA-serving/security settings all
      in place, .env & db.sqlite3 untracked from git. REMAINING: Anuj
      pushes to GitHub + connects the repo as a Render Blueprint + pastes
      DATABASE_URL in the dashboard.
- [ ] *(parked)* "All Apps" ERP-style launcher — discussed, not committed.

## Phase C — Workload-aware assigning

- [x] **C1 · Assignee workload panel at assignment time.** When you pick an
      assignee in the task form: their open-task count, priority breakdown,
      and **pending effort hours** ("your pipeline shows 15 hours pending").
      Soft warning when they're overloaded (≥ 8h pending effort or ≥ 10 open
      tasks) — informs, never blocks. `GET /api/tasks/workload/?user=<id>`;
      visible to anyone who could assign to that person, their reporting
      manager, and dept/all viewers. Tasks without an effort value are
      counted separately ("+N with no effort value") so assigners learn.
- [x] **C2 · Same panel in the employee drill-down** — 📊 Workload button on
      every My Team row (both the read-only directory and the admin manage
      view), expands the same panel inline, fetch-on-click.

## Phase D — Time Earned, scoring & reports

- [ ] **D1 · Time Earned.** Completing a task credits its `effort_minutes` to
      the assignee for that day. An 18-hour task completed on day 3 credits
      all 18h that day — the weekly view balances it (exactly Speaker 4's
      design). Tasks with no effort value count toward task-count metrics but
      earn 0 time — visible, so assigners learn to set effort.
- [ ] **D2 · Score formula — transparent, shown in a tooltip** (the thing the
      teardown couldn't extract from Automate Tasks — ours will be visible).
      Proposal (CONFIRM weights): Score % = 60 × on-time-completion-rate +
      40 × effort-weighted completion (time earned ÷ time assigned), over the
      selected date range.
- [ ] **D3 · Dashboard v2.** Percentages on the six tiles; **tiles click
      through** to the filtered task list; new **Employees report tab**
      (per-person: total, score, overdue/pending/in-progress/in-time/delayed
      counts + %) for managers/admin with the per-person slide-over
      drill-down (stats + their tasks + attendance link — teardown §3.3);
      **Daily** grain tab; CSV export of the current view; **Custom date
      range** picker added to the presets.
- [ ] **D4 · Multitasker index.** Sir explicitly wants to identify
      multitaskers: measure days with ≥N parallel active tasks × on-time
      completion of those overlapping tasks; surfaced as a badge/column in
      the Employees report and fed to D5/E3 review output.
- [ ] **D5 · Effort-dispute report.** Side-by-side list of tasks where the
      assignee's estimate diverged from the assigner's effort value — the
      "Amit said 1 hour, Bhavna said 4" review ammunition, filterable for the
      15-day review meeting.

## Phase E — Task detail panel + creation & AI

- [ ] **E1 · Task detail slide-over** (teardown §6): ID pill, title,
      description, assigned to/by, dates, status, category, priority; action
      rows (In Progress / Complete / Comment / Request change); **Checklist**
      (tickable sub-items); **Sub-tasks**; **Comments**; **Task Updates**
      audit feed (we already log TaskActivity — this displays it per-task);
      attachments list.
- [ ] **E2 · Creation upgrades:** "In Loop" picker at creation (pre-subscribe
      colleagues); "Assign more" checkbox to fire several tasks in a row;
      effort input (A2) in minutes/hours.
- [ ] **E3 · AI layer** (Claude behind `AI_ENABLED`, deterministic fallback
      always works):
        * "Generate with AI Prompt" — natural language → drafted title /
          description / checklist;
        * per-task "AI Summarize";
        * **AI review summary per employee** — the categories Sir dictated:
          "slow — give one task at a time", "multitasker but below expected
          speed — train them", "next level — on time every time, make them a
          trainer/lead, promote", generated from D1–D4 stats so the fallback
          (no API key) still produces rule-based versions of the same
          sentences.

## Phase F — Managed categories & task settings

- [ ] **F1 · Category management** (teardown §6.3): admin CRUD list with task
      counts and reorder, replacing today's free-text category field
      (existing values migrated automatically). Tags: postponed — category
      covers the meeting's needs; revisit if asked.
- [ ] **F2 · Task Settings screen** housing B3's evidence toggles + future
      org-wide task policies.

## Phase P — Progress updates & Time Spent (20 Aug requirements doc, part 1)

- [x] **P1 · In-Progress status update pop-up**: picking "In Progress —
      Status Update" opens a form — % work done, effort spent so far,
      comments (ALL optional, send at least one). Repeatable ("+ update"
      button); every update logs to the activity history + notifies the
      creator. Task stores `progress_percent`; rows show ▰ % and ⏲ spent
      chips (Delegated view included). `POST /api/tasks/{id}/progress/`.
- [x] **P2 · Done flow v2**: completion description now MANDATORY on every
      completion (plain status-PATCH answers 400 so the UI opens the
      modal); modal shows the assigner's Task Time read-only + requires
      actual **Total Effort Spent** → `actual_minutes` on Task,
      progress set to 100.
- [x] **P3 · Time Report tab**: Time Earned (assigned effort credited on
      completion) vs Time Spent (actual minutes) per person with range
      presets; tasks with no effort value shown separately (earn 0).
      `GET /api/tasks/time_report/?range=` — employee sees self, manager
      dept + reports, admin all. (Merges into D1 scoring later.)
- [x] **P4 · Edit request with new time + reason** — already live (B2/B9:
      TaskChangeRequest with effort_minutes + escalate).

## Phase M — Mistake Register & Accountability Engine (20 Aug doc, part 2)

Sir's spec: convert the app into Mistake + Accountability + Escalation +
Performance management. Employee owns the mistake → Manager owns the
correction → Dept Head owns repeats → Founder sees only serious escalations.

- [ ] **M1 · Register core** (~3-4 days): `Mistake` model (employee, dept,
      manager, linked task/lead, category, severity, classification —
      Human/Process/System/Management/External, impact + financial loss,
      root cause, corrective + preventive action, due date, evidence file,
      explanation, manager remarks, status) + `MistakeEvent` full audit
      trail + CRUD APIs with role-scoped visibility + auto-create
      correction/audit task (completing it updates the mistake) + notify()
      fan-out + employee/manager list views.
- [ ] **M2 · Repeat detection + 3-level flow + SLA escalation** (~2-3 days):
      occurrence levels (1: explain+correct, manager reviews; 2: Repeat
      Error — root cause + CAPA mandatory, manager accountable; 3:
      Performance Escalation to dept head; discipline stays human-approved).
      Rule-based similarity first (same employee + category + process/SKU
      keywords) with MANAGER CONFIRMATION before marking repeat; escalation
      path = reporting_manager chain (employee → TL/manager → dept head →
      admin/founder). SLA deadlines by severity (Low 72h / Med 48h / High
      24h / Critical 4h) checked by the existing reminder ticker; missed
      SLA auto-escalates one level up.
- [ ] **M3 · AI layer + founder view** (~2 days): Claude (env-gated,
      existing AI_ENABLED pattern, rule-based fallback) classifies mistake
      type, spots cross-employee patterns ("5 people made this → question
      the process, not the people"), suggests CAPA; Founder dashboard =
      Action Required only (critical, big financial impact, overdue
      escalations, recurring failures) + concise weekly digest; managers
      get a daily accountability summary.
- [ ] **M4 · Scoring** (~2 days, merges with Phase D): employee score adds
      mistake frequency/repeats/severity/action completion/improvement;
      department accountability score (repeats, SLA compliance, financial
      impact, improvement).
- **Blocked on Sir:** who are the Department Heads (needed for the
  escalation chain) + the mistake category list + confirm SLA hours.

## Decisions to confirm with Sir before/while building
1. **Modification-request approver routing** — the reconciled rule in B2
   (assignee→creator approves; creator→admin approves; admin sees all).
   The meeting contained both "creator approves" and "only Super Admin".
2. **Score weights** in D2 (proposed 60/40 on-time vs effort-weighted).
3. Effort value stays **optional** (per Speaker 4) — confirm it shouldn't be
   mandatory for managers.
4. Multi-assignee tasks (Automate Tasks supports; the meeting never asked) —
   proposed SKIP for now, one task = one owner keeps scoring honest.


## Build order for "one go"
A → B → C → D → E → F. A+B are the foundation (rules), C is small, D is the
analytics payoff, E is the biggest UI lift, F is cleanup. Each phase lands
with API tests + browser verification + README update before the next starts.

---

## 1. Waiting on the founder / CRM team

### 1.1 SalaryBox parity check  ⏳ BLOCKED — Anuj to review the SalaryBox admin portal first
Payroll is built (salary structures, monthly runs from attendance, LWP,
PF / professional tax / other deductions, advances, payslips, CSV export).
**Not built yet because we don't know if CarTrends uses them.** Confirm each:

- [ ] **Overtime** — extra hours × a rate? Which rate, and who approves it?
- [ ] **Shifts** — multiple office timings per employee (morning/evening)?
- [ ] **Bonuses / incentives** — sales incentive, festival bonus, performance pay
- [ ] **Arrears** — back-pay when a salary revision is applied late
- [ ] **ESI / gratuity** — statutory deductions beyond PF and professional tax
- [ ] **Payslip PDF** — a downloadable/printable slip per employee (today it's an
      on-screen breakdown + a monthly CSV)
- [ ] **Salary revision workflow** — approval before a new structure takes effect?

> Decision rule: only build what SalaryBox actually gets used for. Everything
> here is additive to the existing payroll module — no rework needed.

### 1.2 Old CRM app (Google Apps Script) integration

**⚠️ 20 Aug finding — this changes the plan, needs founder decision before
building anything:** a live walkthrough of the old CRM (logged in as a Sales
Executive) showed it is NOT a simple lead form — it's a full field-sales
operations system already in daily use:
- **9,580 customers** (row-level security hides ~99.97% of them from a
  non-admin login — real export needs admin/founder access or direct
  access to the backing Google Sheet, not the UI).
- Per-customer **Owner + Joint Owner (field agent)**, a **Call Log** (Order /
  Collection / Feedback / Complaint calls, each with their own fields —
  order amount, amount collected, payment mode, complaint type/amount),
  **Visit Requests** assigned to field agents, **GPS/mileage tracking**
  (distance traveled, conveyance, visits/day), a computed multi-condition
  **Stage** tag (Open Complaint / Balance Overdue / Unassigned / Never
  Contacted / Needs Follow-up / Healthy / Missing Info — not a stored
  field), and complaint emails to the founder + accounts team with a
  resolution/SLA state.
- "Tasks" in this system are really 3 separate things unioned together:
  follow-up-flagged call logs, open Visit Requests, and unresolved
  Complaint assignments — there's no single tasks table.
- **Estimated value** and **created date** have no clean equivalent —
  needs a decision (map to Order Amount? ERP Balance? skip it?).

**What this means for "integrate vs remove the old CRM":**
- **Full replace + retire is a multi-week build**, not a quick add-on — it
  would mean rebuilding order/collection logging, GPS visit tracking, and
  complaint SLA workflows inside CarTrends before 9,580 active customers
  and several field reps could safely move over. Not something to decide
  without the founder explicitly signing up for that scope.
- **Recommended default (matches the original positioning below) is to
  keep both systems running**: old CRM stays the field-sales/customer
  system (proven, in daily use, don't touch); CarTrends stays the
  **internal ops layer** (tasks, attendance, payroll, internal enquiries).
  Under this plan, a *live* API-key push may not even be needed — a
  periodic **one-time-style export** (direct Google Sheet access →
  CSV, not the scraped UI) covers reporting/backup needs without the
  security surface of a standing integration endpoint.
- **[ ] BLOCKED on founder:** confirm which of the two paths above —
  before building the `IntegrationKey`/API-key system below, since it may
  turn out to be unnecessary.
- [ ] Needs the CarTrends backend on a **public URL** first (see §3) —
      only relevant if a live push integration is actually chosen.
- [ ] Decide the positioning to the team: this system is the **operations layer**
      (tasks, attendance, payroll, internal enquiries); the old app stays the
      sales CRM until we decide otherwise. **Avoid double data entry.**
- [ ] **Auth for the incoming push (20 Aug, Anuj asked "how do apps like
      Flipkart/Odoo issue API keys" — same pattern, we build our own):**
      a script has no login session, so JWT doesn't fit — it needs a
      long-lived shared secret, exactly like Odoo's per-user "API key" or a
      payment gateway's secret key.
      * **Works today, zero new code:** the existing Forms module already
        has this shape — a published form's `public_token` is effectively
        an API key, and `POST /api/public/forms/<token>/submit/` already
        creates a Lead unauthenticated-but-keyed. Good enough to start
        immediately once we know the old CRM's lead fields (§1.4). Limits:
        payload keys are the form's internal numeric field IDs (awkward for
        someone else's script to hand-code), source is hardcoded `"web"`,
        and only 5 lead fields are mappable (name/phone/email/company/
        requirement) — fine for a quick start, not a clean external contract.
      * **Cleaner long-term (build when we're ready to formalize):** a
        proper `IntegrationKey` model (label, generated key via
        `secrets.token_urlsafe`, active, created_by, last_used_at) managed
        from Settings (admin generates/revokes, like Odoo's API key
        screen), plus one stable endpoint `POST /api/integrations/leads/`
        authenticated by `Authorization: Api-Key <key>` header, accepting
        clean named JSON (`customer_name, phone, email, company,
        requirement, department, source`) — no numeric field IDs, easy for
        any external script (or its AI) to generate against, reusable for
        future integrations beyond just this one script.

### 1.3 Website enquiry form
- [ ] Does the website already have an enquiry form? Where do those enquiries go
      today (email / sheet / nowhere)?
- [ ] Option A: put the CarTrends form link on the website — **works today, zero
      work**. Option B: keep the site's own form design → build the incoming
      webhook.

### 1.4 CSV import (see the shared note "Data In, Data Out")
- [ ] Which data first? Need **one real sample file** with actual column names.
- [ ] Duplicate rule: skip / update / create new when a phone already exists.
- [ ] Owner of imported leads: unassigned / round-robin / from a column.

### 1.5 Marketplace leads
- [ ] Does CarTrends actually sell on **IndiaMART / TradeIndia**? If no → skip
      those adapters entirely. If yes → their API is a **paid add-on** on the
      seller account.

---

## 2. Build queue (no blockers — just not done yet)

- [x] **Face check-in** — DONE. `@vladmandic/face-api` + 6.8 MB of model weights
      in `frontend/public/models`, lazy-loaded camera UI, admin enrolment in
      HR Settings. **Still needs one real-world test with an actual face and
      camera** (the dev environment has no webcam), and
      `FACE_RECOGNITION_ENABLED=true` in `backend/.env` to switch it on.
- [ ] **Offline attendance** — the app installs as a PWA and opens offline, but
      every action still needs the server. What CAN be built: queue check-in/out
      punches locally (with the device timestamp + GPS) and sync automatically
      when the network returns, shown as "pending sync" in the UI. Edge cases to
      solve before building: device clock tampering (server should record both
      timestamps), duplicate punches after sync, geofence can only be validated
      at sync time, and face verification needs the models pre-cached. Leads /
      tasks / payroll stay online-only — stale business data is worse than an
      error.
- [ ] **Face liveness** — current matching compares the camera capture to the
      enrolled descriptor; it does NOT detect a printed photo held to the
      camera (no liveness check). Geofence + HR notifications mitigate this.
      If buddy-punching with photos becomes a real problem, add a
      blink/turn-your-head liveness step.
- [ ] **Spare-parts form templates** — ready-made forms for this business:
      quotation request, bulk/fleet order, warranty claim, service booking,
      vendor registration, customer complaint.
- [ ] **Outgoing webhooks** — only once a receiving system is named.
- [ ] **Google Calendar / Sheets sync** — needs a Google Cloud project.
- [ ] **Field-sales app features** — not scoped yet.

---

## 3. Deployment (Phase 10)

- [ ] New **Neon Postgres** database → `DATABASE_URL` (never reuse another
      project's DB).
- [ ] `render.yaml`, `DEBUG=false`, `ALLOWED_HOSTS`, CORS, media storage.
- [ ] Then, and only then, these can go live:
  - [ ] **WhatsApp Cloud API** — access token, phone number ID, app secret,
        webhook verify token. Business-initiated messages need Meta-approved
        templates (`lead_assigned`, `follow_up_reminder`, `crm_update`).
  - [ ] **Gmail API** — OAuth client + refresh token + sender address.
  - [ ] **Claude API** — `ANTHROPIC_API_KEY` (classification falls back to
        keyword rules until then).

---

## 4. Verify before promising to the team

- [ ] **WhatsApp groups.** It was said in the demo that the Cloud API can create
      groups of 8 members — **this needs checking in Meta's official docs**. To
      current knowledge the Cloud API is **1-to-1 only** and does not support
      groups at all. The alternative is a WhatsApp **Web session** bridge (which
      is how `cartrends-contacts` reads groups today) — unofficial, ban risk,
      needs a phone session running 24×7. Confirm before anyone creates new
      groups on this promise.
- [ ] **Don't cancel SalaryBox yet.** Face check-in isn't finished, payroll has
      had no parallel run, and there's no mobile app in the staff's hands. Run
      both for one full month before switching off.
