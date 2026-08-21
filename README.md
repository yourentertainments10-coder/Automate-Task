# CarTrends CRM

Internal CRM & business-automation system for CarTrends. **Fully independent
project** — no code, credentials, database, or deployment shared with any other
project. External services (WhatsApp Cloud API, Gmail API, Claude API, Neon
Postgres) are wired purely through environment variables and stay **OFF** until
their own new credentials are added to `backend/.env`.

**Status: CRM, workspace modules, Forms, Leave & Attendance, Payroll and the Template Directory are complete. 206 backend API tests, all passing.**

---

## Table of contents

1. [Feature overview](#1-feature-overview)
2. [Tech stack](#2-tech-stack)
3. [How to run](#3-how-to-run)
4. [Roles & permissions](#4-roles--permissions)
5. [Data model](#5-data-model)
6. [API endpoints](#6-api-endpoints)
7. [File-by-file reference — backend](#7-file-by-file-reference--backend)
8. [File-by-file reference — frontend](#8-file-by-file-reference--frontend)
9. [Environment variables (.env)](#9-environment-variables-env)
10. [Testing](#10-testing)
11. [How the automations work](#11-how-the-automations-work)
12. [Build history / phases](#12-build-history--phases)
13. [Not built yet](#13-not-built-yet)

---

## 1. Feature overview

| Area | What it does |
|---|---|
| **Authentication** | JWT login/logout/refresh with token blacklist; change password; sessions survive page reload; deactivated users cannot log in. |
| **Team management** | 7 roles (incl. a dedicated HR Manager), per-role capability matrix, `users.manage` user CRUD (Admin + HR Manager; only an Admin may grant the Admin role) , deactivate — never delete, reporting-manager hierarchy. **My Team** directory visible to every employee (Mobile / Reports To / role badges). |
| **Lead CRM** | Kanban pipeline New → Contacted → Quotation Sent → Negotiation → Won/Lost. Full lead profile (name, phone, email, company, requirement, source, department, priority, follow-up, value). Notes, document uploads, auto-numbered quotations, unified activity timeline. Role-scoped visibility. |
| **Auto-assignment** | Per-department rules: round-robin (Lead 1→Rahul, 2→Amit, 3→Priya, 4→Rahul) or fixed. Skips deactivated users; rotation resets when members change. Admin UI under **Automation**. |
| **Notifications** | One `notify()` entry point fans out to: in-app feed (always) + Gmail + WhatsApp (once credentials exist). Every channel attempt (sent/skipped/error) is recorded per notification. Unread badge, mark-read/read-all. |
| **Follow-up & task reminders** | Background ticker (every 5 min) + `manage.py send_reminders`. One ping per follow-up/due date; re-fires when the date is rescheduled. |
| **AI intake** | WhatsApp Cloud API webhook + Gmail inbox poller → Claude classification (keyword fallback when no key) → match existing lead by phone/email or create new → auto-assign → notify. Admin simulator to test the real pipeline without live credentials. |
| **Task Engine v2 (A+B)** | **Assignment hierarchy** — level-based, not department-based: Admin→anyone, Managers→managers+employees, Employees→fellow employees (cross-department fine, never upward); the assignee picker only offers allowed people. **Effort values** — the assigner sets effort (min/hr, optional); the assignee can record a one-time counter-estimate that never overwrites it (both logged for reviews). Task IDs (`T-00042`), relative due times ("6 hours from now"), recurrence end-dates. **Soft delete** — admin-only deletion moves tasks to a restorable Deleted bin. **Edit lockdown** — assignee: status only; creator: no direct edits; admin: full (logged). **Modification Requests** — in-system: assignee's request → creator approves; creator's own request → admin approves; every request/decision notified + logged to admin; approvable changes: due date, effort, priority, title, stop-recurrence, reassign, cancel. **Completion evidence** — admin toggles (Automation page) forcing remarks and/or a proof file on completion, collected by a modal and enforced server-side on every path. |
| **Tasks** | 7-tab area: Dashboard (6 tiles, date ranges, My/Delegated/Group scopes, category table, bar chart), My Tasks, Delegated, Subscribed (follow via 🔔), Templates, Activities audit feed, Holidays calendar. Category + frequency; recurring tasks auto-create the next occurrence on completion. Lead-linked tasks write into the lead timeline. |
| **Dashboard** | Tiles (total/new/active/won/lost/pipeline ₹/conversion %/pending follow-ups/overdue/assigned tasks/overdue tasks), leads-per-day chart, pipeline-by-stage bars, employee performance, lead-source performance, recent WhatsApp/Gmail feed, recent lead activity. Admin sees all; managers see their department automatically. |
| **Groups** | Team mini-workspaces: owner + members, category, archive (never hard-delete). Each group has Dashboard (task tiles + recent activity), Tasks, Ideas, Links and Members tabs. Tasks carry an optional group; **group members see the group's tasks** even when not assignee. Managers/admin create; owner/admin manage members. |
| **Notices** | Company notice board (separate from per-user Notifications): draft → publish (schedulable) → expire/archive, priority, category, attachment, and audience targeting — everyone / role / department / group / specific users. Per-user read tracking with All/Read/Unread filters + search. Admin manages. |
| **Links** | Shared bookmark manager: named collections ("Important Tools"), per-link description, group-scoped visibility, ★ favorites, search + filters. http/https-only URL validation. Anyone adds; edit/delete own (managers/admin any); managers manage collections. |
| **Idea Board** | My / Shared / Group idea boards with votes, comments, categories and a review workflow (New → Under Review → Approved/Rejected → Implemented). Authors edit their own ideas; only managers/admin change status. Group ideas require membership. |
| **Leave & Attendance** | **Attendance**: check-in/out with server-computed status (Present / Late / Half Day / Absent / Leave / Holiday / Week Off), working hours, late & early-checkout flags, missing-checkout detection, month view with per-status totals, correction requests with manager review that rewrites the day. **Leave**: types with annual quotas & document rules, apply with date range (working days only — skips holidays/week-offs), overlap guard, balances (quota/used/pending), cancel, manager approve/reject with remarks + notification; **approved leave writes LEAVE days into attendance** and blocks check-in. **Geo-fencing**: admin-defined office locations (lat/lng/radius); when `GEOFENCE_ENABLED=true` the server haversine-validates the GPS sent at check-in and rejects anything outside every fence. **Face recognition** (`FACE_RECOGNITION_ENABLED`): admin-only enrolment storing a numeric descriptor (never an image), euclidean matching against `FACE_MATCH_THRESHOLD`, and attendance is **never** marked on a below-threshold or unenrolled scan. |
| **Mobile / installable app** | Below 820px the sidebar becomes a slide-in drawer behind a top app bar (page title + notification bell); grids collapse to one column, tables scroll on their own, modals become bottom sheets, kanban columns become swipeable, tap targets grow, and notched phones get safe-area padding. Installs to a phone home screen as a **PWA** (manifest, 192/512/maskable icons, iOS meta tags, quick-action shortcuts) and a service worker caches the app shell for instant opening — but **never `/api` or `/media`**, so business data is always live. The app needs a connection to do anything beyond opening. |
| **Face attendance** | `@vladmandic/face-api` with the models served locally from `public/models` (no CDN). The library and its 6.8 MB of weights are a **lazy chunk** — downloaded only when someone opens the camera, so the main bundle stays ~460 KB. Camera modal with a mirrored preview and guide oval. **Self-enrolment** (`FACE_SELF_ENROLL`, on by default): like setting up a phone face lock, an unenrolled employee's first capture becomes their profile and marks their attendance in one step — HR/Admin get a "Face self-enrolled" notification and can **reset** any profile in HR Settings so the next capture re-enrols fresh. Admin enrolment also available (choose employee → capture → save). **HR override**: a "Mark present" button on the Team tab (`hr.manage`) records attendance manually with an audited note ("Marked present by Neha: face lock not working") for the day the camera refuses to cooperate. **Only a 128-number descriptor is sent — the photo never leaves the device.** Clear errors for denied permission, no camera, no face, more than one face; a different face is always rejected ("Face did not match"). No liveness detection yet (a printed photo is not detected) — mitigated by geofence + notifications, listed in TODO. |
| **Payroll** | Salary structures with history (monthly gross, optional basic, PF %, professional tax, other deduction, effective-from — a new entry never overwrites the old, so old payslips stay explainable). Monthly payroll runs computed **from the recorded attendance**: working days = calendar − week-offs − holidays; payable = present + late + half-days(×0.5) + *paid* leave; the rest is LWP. Advances are recovered automatically and settled on finalise. Draft runs can be recalculated freely; finalising locks the month. Per-employee payslip breakdown, CSV export, and a **My Salary** tab where every employee sees their own finalised payslips only. Guardrails: PF is charged on *earned* basic, and a payslip can never go below zero. |
| **Industry Template Directory** | A browsable library of ready-made task templates, kept **separate** from the company's own private Task Templates. Browse by industry (13 seeded: E-commerce, Distributor, Automotive & Spare Parts, Garment Manufacturing, Construction, Education, Financial Services, CA Firm, Travel, Photography, Health & Wellness, Service Provider, Hiring Agency) → category → template → preview its steps → **Create tasks** (steps become real tasks, spaced by `offset_days`, optionally assigned to a teammate or a group) or **Add to my Task Templates**. Content lives in JSON/CSV and loads via `manage.py load_directory` — never hand-written in code. |
| **Forms** | Real form builder: 10 field types (short/long text, number, email, phone, date, dropdown, radio, checkbox, file), required toggle, options, reorder/edit/delete, draft → publish → disable → reopen. Filled in-app by employees AND by customers via an unauthenticated **share link** (`/f/<token>`). Server-side validation, submissions list with answers + files, **CSV export**. Integrations: a submission can auto-create a **Lead** (field→attribute mapping, source=web, routed by the *existing* `auto_assign()` round-robin) and/or a **follow-up Task** assigned to the lead's assignee — both notified through the existing notification center. |

## 2. Tech stack

| Layer | Tech |
|---|---|
| Backend | Django 6 + Django REST Framework + SimpleJWT (Python 3.13) |
| Frontend | React 18 + Vite + react-router 6 + Chart.js (port 5174, proxies `/api` → backend) |
| Database | SQLite locally (zero setup); any `DATABASE_URL` postgres string (the new Neon DB) switches to Postgres |
| WhatsApp | Meta WhatsApp Cloud API, direct Graph v23 — **no BSP** |
| Email | Gmail API over REST (OAuth refresh-token flow — no Google SDK) |
| AI | Claude API (Anthropic Messages API over REST) with deterministic fallback |

## 3. How to run

```powershell
# Terminal 1 - backend (port 8000)
cd D:\Downloads\cartrends-crm
venv\Scripts\python backend\manage.py runserver 8000
```

```powershell
# Terminal 2 - frontend (port 5174)
cd D:\Downloads\cartrends-crm\frontend
npm run dev
```

First-time setup:

```powershell
cd D:\Downloads\cartrends-crm
python -m venv venv
venv\Scripts\python -m pip install -r backend\requirements.txt
cd frontend; npm install; cd ..
venv\Scripts\python backend\manage.py migrate
venv\Scripts\python backend\manage.py seed_users --demo-team
```

Open <http://localhost:5174>. Default admin: `admin` / `admin@12345` (change it).
Demo users: `rahul | amit | priya | meera | vikram | anita | karan`, password
`<username>@12345`. Django admin panel: <http://localhost:8000/admin/>.

## 4. Roles & permissions

One auditable matrix in `backend/accounts/permissions.py`:

| Capability | Admin | Sales Manager | Sales Executive | Purchase | Accounts | Support |
|---|---|---|---|---|---|---|
| Leads visible | all | own department | own leads only | department | **won** leads only | department |
| Edit leads | all | department | own | — (read-only) | — (read-only) | department |
| Assign / reassign leads | ✔ | ✔ | — | — | — | — |
| Tasks visible | all | department | own/created/followed | own | own | own |
| Assign tasks to others | ✔ | ✔ | — | — | — | — |
| Dashboard | all depts | own dept | — | — | — | — |
| AI Inbox | ✔ | ✔ | — | — | — | — |
| Team directory (read) | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| User management, Automation rules, Holidays, Simulator | ✔ | — | — | — | — | — |

## 5. Data model

```
User            username, email, password, first/last name, role, department,
                whatsapp_phone, reporting_manager -> User, is_active
Lead            customer_name, phone, email, company, requirement, source,
                department, status, priority, assigned_to, follow_up_at,
                reminded_at, estimated_value, ai_meta JSON, created_by
LeadEvent       lead, type (note|status_change|assignment|follow_up|document|
                quotation|call|email_in|email_out|wa_in|wa_out|created),
                body, actor, payload JSON            <- the communication history
LeadDocument    lead, file, filename, uploaded_by
Quotation       lead, number (QT-YYYY-NNNN), amount, status
                (draft|sent|accepted|rejected), notes, created_by
AssignmentRule  department (unique), strategy (round_robin|fixed),
                member_ids ordered JSON, rr_index, active
Task            title, description, category, frequency (one_time|daily|weekly|
                monthly), lead?, assigned_to, created_by, subscribers M2M,
                status (open|in_progress|done), priority, due_at, reminded_at,
                completed_at
TaskActivity    task, actor, text                     <- Activities feed
TaskTemplate    name, category, title, description, priority, frequency
Holiday         name, date
Notification    user, type, title, body, link, channels JSON
                (per-channel sent/skipped/error record), read_at
InboundMessage  channel (whatsapp|gmail), external_id (idempotency), sender,
                sender_name, subject, body, media JSON, ai_result JSON,
                lead?, status (pending|processed|ignored|failed), error
Group           name, description, category, owner, members M2M, active
Notice          title, content, author, category, priority, status (draft|
                published|archived), publish_at, expire_at, attachment,
                audience_type (everyone|role|department|group|users) +
                audience_value JSON
NoticeRead      notice, user, read_at (unique together)
LinkCollection  name, created_by
Link            collection, title, url, description, group?, added_by,
                favorites M2M
Idea            title, description, category, author, group?, status (new|
                under_review|approved|rejected|implemented), priority,
                votes M2M
IdeaComment     idea, author, body
Task (EXTENDED) + group? -> workspace.Group (group members see group tasks)
Form            name, description, status (draft|published|closed),
                public_token (share link), created_by, create_lead,
                lead_department, create_task, task_title
FormField       form, label, type (10 types), required, options JSON,
                lead_attr (maps answer -> Lead attribute), order
FormSubmission  form, submitted_by?, answers JSON, lead?, task?
SubmissionFile  submission, field_id, file, filename
OfficeLocation  name, latitude, longitude, radius_m, active (geo-fence)
Attendance      user+date (unique), check_in/out (+lat/lng each), location,
                status (present|absent|half_day|late|leave|holiday|week_off),
                working_minutes, is_late, is_early_checkout, face_verified,
                face_confidence, leave_request?, note
AttendanceCorrection  user, date, requested_check_in/out, reason,
                status (pending|approved|rejected), reviewed_by, remarks
LeaveType       name, annual_quota, paid, requires_document, active
LeaveRequest    user, leave_type, start_date, end_date, days, reason,
                document?, status (pending|approved|rejected|cancelled),
                reviewed_by, remarks, reviewed_at
FaceProfile     user (1:1), descriptor JSON (numeric only), enrolled_by
SalaryStructure user, monthly_gross, basic?, pf_percent, professional_tax,
                other_deduction, effective_from  (unique per user+date)
Advance         user, amount, given_on, reason, recovered, recovered_in
PayrollRun      year+month (unique), status (draft|finalised), working_days,
                total_net, finalised_at
Payslip         run+user (unique), monthly_gross, working/payable/lwp days,
                earned_gross, pf, professional_tax, advance_deduction,
                other_deduction, net_payable, breakdown JSON
Industry        name, slug, icon, description, order, active
DirectoryTemplate industry, category, name, description, priority,
                frequency, tags JSON, steps JSON [{title, description,
                offset_days}], active   (unique per industry+name)
```

## 6. API endpoints

All under `/api/`, JWT `Authorization: Bearer <token>` unless noted.

| Endpoint | Methods | Who | Purpose |
|---|---|---|---|
| `auth/login` | POST | public | username+password → access+refresh tokens |
| `auth/refresh` | POST | public | rotate refresh token |
| `auth/logout` | POST | any | blacklist refresh token |
| `auth/me` | GET | any | current user + capabilities |
| `auth/change-password` | POST | any | verify current, set new |
| `team/` | GET | any | read-only company directory |
| `users/` + `/{id}/` | CRUD | admin | user management (DELETE blocked) |
| `users/{id}/deactivate\|activate/` | POST | admin | soft on/off (self-deactivation blocked) |
| `leads/` + `/{id}/` | CRUD | scoped | filters: status, priority, source, assigned_to, department, overdue, search |
| `leads/{id}/events/` | GET | scoped | timeline |
| `leads/{id}/notes/` | POST | edit-scoped | add note |
| `leads/{id}/documents/` | GET/POST | scoped/edit | list / upload (10 MB cap) |
| `leads/{id}/quotations/` | GET/POST | scoped/edit | list / create (auto number) |
| `leads/summary/` | GET | scoped | per-status counts + overdue |
| `leads/assignees/` | GET | any | active users for dropdowns |
| `quotations/{id}/` | PATCH | edit-scoped | status/notes change (logged) |
| `assignment-rules/` + `/{id}/` | CRUD | admin | auto-assignment rules |
| `tasks/` + `/{id}/` | CRUD | scoped | filters: scope (my/delegated/subscribed), status, assigned_to, lead, category, frequency, overdue, search |
| `tasks/{id}/subscribe\|unsubscribe/` | POST | scoped | follow / unfollow |
| `tasks/categories/` | GET | scoped | distinct categories |
| `tasks/dashboard/` | GET | scoped | tiles + per-category table; params range, scope, category, search |
| `task-templates/` | CRUD | read: any · write: admin/manager | reusable blueprints |
| `task-activities/` | GET | scoped | audit feed; filters actor, days |
| `holidays/` | CRUD | read: any · write: admin | company calendar |
| `notifications/` | GET | own only | own feed |
| `notifications/unread_count/` · `{id}/read/` · `read_all/` | GET/POST | own only | badge + mark read |
| `dashboard/` | GET | admin/manager | all dashboard aggregates |
| `groups/` + `/{id}/` | CRUD | member-scoped · create: admin/manager · DELETE archives | team workspaces |
| `groups/{id}/add_member\|remove_member/` | POST | owner/admin | membership management |
| `groups/{id}/dashboard/` | GET | member-scoped | group task tiles + members + recent activity |
| `notices/` + `/{id}/` | list: targeted feed (`?manage=true` = admin all) · write: admin | company notice board |
| `notices/{id}/publish\|archive\|read/` | POST | admin / admin / targeted user | lifecycle + read tracking |
| `link-collections/` | CRUD | read: any · write: admin/manager | bookmark collections |
| `links/` + `/{id}/` + `/{id}/favorite/` | CRUD + POST | visible-scoped; edit own | shared bookmarks (http/https only) |
| `ideas/` + `/{id}/` | CRUD | visible-scoped; status change admin/manager | idea board (`?scope=my\|shared\|group`) |
| `ideas/{id}/comments\|vote/` | GET/POST | visible-scoped | discussion + vote toggle |
| `forms/` + `/{id}/` | CRUD | list: published (fill) / `?manage=true` own+admin · create: admin/manager | form builder |
| `forms/{id}/add_field\|reorder_fields/` | POST | form owner/admin | builder field ops |
| `form-fields/{id}/` | PATCH/DELETE | form owner/admin | edit/delete one field |
| `forms/{id}/publish\|close\|reopen/` | POST | form owner/admin | lifecycle (publish needs ≥1 field) |
| `forms/{id}/submit/` | POST | any signed-in | in-app submission (validated) |
| `forms/{id}/submissions/` · `/export/` | GET | form owner/admin | submissions list · CSV download |
| `public/forms/{token}/` · `/submit/` | GET/POST | **anonymous** | share-link form + submission |
| `attendance/` | GET | own · `?scope=team` for approvers | attendance history (date/status filters) |
| `attendance/today/` | GET | any | today's record + can-check-in/out + feature flags |
| `attendance/check_in\|check_out/` | POST | any | mark attendance (GPS + optional face descriptor) |
| `attendance/monthly/` | GET | own · `?user=` scope-checked | day-by-day month report + totals |
| `attendance/team_today/` | GET | `hr.approve` | today's team roster + counts |
| `attendance-corrections/` + `/{id}/review/` | CRUD + POST | own · review `hr.approve` | correction requests (approval rewrites the day) |
| `leaves/` + `/{id}/cancel\|review/` | CRUD + POST | own · `?scope=team` + review `hr.approve` | leave workflow |
| `leaves/balances/` | GET | own · `?user=` scope-checked | quota / used / pending / balance |
| `leave-types/` · `office-locations/` | CRUD | read: any · write: `hr.manage` | HR configuration |
| `hr/face/{user_id}/` | POST/DELETE | `hr.manage` | face enrolment / removal (descriptor only) |
| `hr/config/` | GET | any | policy + feature flags + own capabilities |
| `salary-structures/` · `advances/` | CRUD | read own · write `hr.manage` | salary history, advances |
| `payroll-runs/` + `/{id}/generate\|finalise/` | CRUD + POST | `hr.manage` | monthly run; recalculate; lock + settle advances |
| `payroll-runs/{id}/payslips\|export/` | GET | `hr.manage` | month's payslips · CSV download |
| `payslips/` | GET | own **finalised** only · `hr.manage` sees all | employee payslip history |
| `tasks/assignees/` | GET | any | hierarchy-filtered assignee list (your level & below) |
| `tasks/workload/?user=<id>` | GET | can-assign-to target · reporting manager · dept/all viewers | C1/C2 pipeline panel: open count, priority breakdown, pending effort, overdue, soft `overloaded` flag (≥8h or ≥10 open) — informs, never blocks |
| `tasks/{id}/estimate/` | POST | assignee, once | counter-estimate in minutes |
| `tasks/{id}/progress/` | POST | assignee | repeatable status update: % done, effort spent so far, comment — logs to activity, notifies creator |
| `tasks/{id}/complete/` | POST | assignee | complete: description + actual effort spent MANDATORY, proof file per settings |
| `tasks/time_report/?range=` | GET | self · dept (manager) · all (admin) | Time Earned (assigned effort) vs Time Spent (actual) per person |
| `tasks/employees_report/?range=&grain=` | GET | self · dept (manager) · all (admin) | per-person counts+%, transparent score (60/40 formula), multitasker index; `grain=daily` = completion-day crediting; `range=custom&start&end` |
| `tasks/effort_disputes/?range=` | GET | self · dept (manager) · all (admin) | effort vs estimate vs actual, sorted by disagreement |
| `mistakes/` + `/{id}/` | CRUD | own · dept (manager) · all (admin) · `?important=true` founder filter | Mistake Register: category, severity (SLA), classification, SOP linking, financial loss |
| `mistakes/{id}/explain\|confirm_repeat\|review\|create_task\|events/` | POST/GET | employee · manager · manager · manager · visible | 3-level accountability: structured root cause; "Same/Different error"; review (can't just close); corrective task; audit trail |
| `mistake-categories/` | GET · CUD | read any · write `settings.manage` | 29 seeded configurable categories |
| `mistake-settings/` | GET · POST | any · `settings.manage` | SLA hours per severity (72/48/24/4 defaults) |
| `tasks/{id}/request_change/` | GET/POST | assignee/creator/admin | raise a Modification Request |
| `tasks/{id}/restore/` · `?scope=deleted` | POST · GET | admin | Deleted-bin restore · listing |
| `tasks/{id}/files/` | GET | visible | task attachments |
| `task-change-requests/` + `/{id}/review/` | GET + POST | inbox/mine/all scopes · approver rules | Modification Request workflow; review decisions: approved / rejected / **escalated** (creator hands the call to admin) |
| `task-categories/` | GET · CUD | read any (`?department=` filter) · write `tasks.assign` | managed category dropdown; DELETE deactivates, re-add reactivates |
| `task-settings/` | GET · POST | any · `settings.manage` | completion-evidence policy |
| `directory/industries/` | GET | any | industries + template counts + categories |
| `directory/templates/` | GET · CUD | read any · write `settings.manage` | library (filters: industry, slug, category, tag, search) |
| `directory/templates/{id}/create_tasks/` | POST | any (assigning to others needs `tasks.assign`) | steps → real tasks with due-date offsets |
| `directory/templates/{id}/add_to_my_templates/` | POST | `tasks.assign` | copy steps into private Task Templates |
| `intake/` | GET | admin/manager | AI inbox listing |
| `intake/simulate/` | POST | admin | run any text through the real pipeline |
| `webhooks/whatsapp` | GET/POST | Meta (signature) | webhook verify handshake + message delivery |
| `/health` | GET | public | liveness check |

## 7. File-by-file reference — backend

### `backend/manage.py`
Standard Django entry point: `runserver`, `migrate`, `test`, and the custom
commands below all run through it.

### `backend/requirements.txt`
Python dependencies (Django, DRF, SimpleJWT, cors-headers, dotenv, requests).
`psycopg[binary]` is listed commented — install it when switching to Neon.

### `backend/.env.example`
Fully documented template for every environment variable, with step-by-step
instructions for obtaining each credential (Meta, Google OAuth, Anthropic,
Neon). Copy to `.env` and fill in what you have; blanks stay safely off.

### `backend/config/` — project wiring
| File | What it does |
|---|---|
| `settings.py` | All Django settings, env-driven. `env()` helper treats blank `.env` values as unset. `_database_from_env()` = SQLite fallback / Postgres when `DATABASE_URL` is set (parses the URL, forces SSL). JWT lifetimes (8h access / 7d refresh, rotation + blacklist), CORS origins, IST timezone, media root, custom pagination class. |
| `urls.py` | Root router: `/health`, `/admin/`, and mounts the four app URL files under `/api/`. Serves uploaded media in DEBUG. |
| `pagination.py` | `DefaultPagination` — page size 25, client can raise via `?page_size=` up to 300. |
| `asgi.py` / `wsgi.py` | Standard deployment entry points (Render will use wsgi/gunicorn). |

### `backend/accounts/` — users, auth, RBAC
| File | What it does |
|---|---|
| `models.py` | Custom `User` (extends AbstractUser): `role` (6-role enum), `department`, `whatsapp_phone`, `reporting_manager` (self-FK → "Reports To"). Admin role auto-sets `is_staff`. `ROLE_DEFAULT_DEPARTMENT` map used by seeding. |
| `permissions.py` | **The heart of RBAC.** `ROLE_CAPABILITIES` — one dict mapping each role to its capability strings (`leads.view_own`, `tasks.assign`, `dashboard.view`, …). Helpers `capabilities_for()` / `has_capability()`; DRF permission classes `IsAdmin` and `HasCapability.of("x")` used by every guarded view. The frontend receives the same strings via `/auth/me` and shows/hides UI from them. |
| `serializers.py` | `UserSerializer` (read; includes capabilities + reporting-manager name), `UserWriteSerializer` (admin create/update; password required on create, optional on update, Django password validation), `ChangePasswordSerializer`. |
| `views.py` | `me` (profile + capabilities), `change_password`, `logout` (blacklists the refresh token), `team_directory` (read-only company directory for every role), `UserViewSet` (admin CRUD; DELETE returns 405 — deactivate instead; `deactivate` blocks self). |
| `urls.py` | Routes: `auth/*`, `team/`, `users/` router. |
| `admin.py` | Django-admin registration of the custom user with CRM fields. |
| `management/commands/seed_users.py` | `python manage.py seed_users [--demo-team]` — idempotent seeding of the admin account and one demo user per role. |
| `tests.py` | 13 tests: login, wrong password, inactive-user block, me, refresh rotation + logout blacklist, admin-only user list, create with role, password rules, deactivate/activate, self-deactivation guard, delete blocked, role update keeps password. |
| `migrations/` | 0001 initial user schema; 0002 adds `reporting_manager`. |

### `backend/crm/` — leads, tasks, assignment, dashboard
| File | What it does |
|---|---|
| `models.py` | `Lead` (all CRM fields + `ai_meta` JSON + `reminded_at` + indexes), `LeadStatus`/`LeadSource`/`LeadPriority` enums, `OPEN_STATUSES`, `is_overdue` property; `AssignmentRule` (per-department, ordered `member_ids`, `rr_index` rotation pointer); `Task` (+ category, frequency, subscribers M2M, due/reminded/completed timestamps); `TaskActivity`; `TaskTemplate`; `Holiday`; `LeadEvent` (the unified timeline — every note/status/assignment/document/quotation/WhatsApp/email event); `LeadDocument` (files under `media/lead_docs/<lead>/`); `Quotation` (auto number `QT-YYYY-NNNN` on save). |
| `scoping.py` | **Who sees/edits what.** `visible_leads(user)` — all / department / won-only / own by capability. `can_edit_lead`, `can_assign`. `visible_tasks(user)` — all / department / own+created+subscribed. `can_edit_task`, `can_assign_tasks`. Every list view and object guard calls these. |
| `serializers.py` | `LeadSerializer` (display labels, assigned/creator briefs, `is_overdue`, per-request `can_edit`), `LeadEventSerializer`, `LeadDocumentSerializer` (download URL), `QuotationSerializer`, `NoteSerializer`, `TaskSerializer` (+ `subscribed` for current user), `TaskActivitySerializer`, `TaskTemplateSerializer`, `HolidaySerializer`, `AssignmentRuleSerializer` (validates member ids, resolves member details), `UserBriefSerializer`. |
| `views.py` | `LeadViewSet` — role-scoped queryset with all filters; `perform_create` (exec self-assign default, assign-permission check, created/assignment events, **auto-assign when unassigned**, notifications); `perform_update` (edit guard, reassign guard, auto events + notifications for status/assignee/follow-up changes); admin-only delete; sub-routes `events`, `notes`, `documents` (multipart upload, 10 MB cap), `quotations`, `summary`, `assignees`. `AssignmentRuleViewSet` (admin; member change resets rotation). `QuotationViewSet` (PATCH status/notes with lead-access guard + timeline log). |
| `task_views.py` | `TaskViewSet` — scope filters (my/delegated/subscribed), assign/edit/lead-visibility guards, activity logging, completion timestamps, lead-timeline writes, **`_spawn_next_occurrence`** (recurring tasks re-create themselves on completion: daily +1d, weekly +7d, monthly next month), `subscribe`/`unsubscribe`, `categories`, **`dashboard`** action (range chips → tile + per-category tallies: overdue/pending/in-progress/completed/in-time/delayed; group scope capability-gated). `TaskTemplateViewSet` (read: all, write: assigners). `TaskActivityViewSet` (scoped feed). `HolidayViewSet` (read: all, write: admin). |
| `assignment.py` | `auto_assign(lead)` — looks up the department's active rule, walks the ordered member list (round-robin advances `rr_index`, fixed takes first), skips deactivated users, saves, logs "Auto-assigned to …", notifies the assignee. Called from manual lead creation *and* the AI intake pipeline. |
| `reminders.py` | `send_followup_reminders()` — open leads with a passed `follow_up_at` get ONE notification per follow-up (`reminded_at` dedupe; rescheduling re-arms it), then chains `send_task_reminders()` which does the same for task due dates. |
| `dashboard.py` | `GET /api/dashboard/` — computes everything off `visible_leads`/`visible_tasks`: tiles, per-status distribution, leads-per-day (14 local dates), employee performance (+ open-task counts), source performance with conversion %, recent inbound WhatsApp/Gmail, recent lead events. |
| `urls.py` | Routers: leads, quotations, assignment-rules, tasks, task-templates, task-activities, holidays + `dashboard/`. |
| `admin.py` | Django-admin registrations for lead models. |
| `management/commands/send_reminders.py` | Manual/cron trigger for the reminder run. |
| `tests.py` | 19 tests — lead scoping per role, lifecycle events, permission denials, filters/summary, notes/documents/quotations. |
| `tests_assignment.py` | 12 tests — the exact round-robin sequence, skip-inactive, fixed, rotation reset, notifications, reminder dedupe + reschedule re-fire. |
| `tests_dashboard.py` | 5 tests — tile math, manager scoping, breakdowns, 14-day series, 403 for executives. |
| `tests_tasks.py` | 11 tests — task scoping, assign guards, completion, lead events, reminders, dashboard tile. |
| `tests_tasks_area.py` | 16 tests — my/delegated/subscribed scopes, auto-subscribe, dashboard tiles/categories/ranges, group-scope guard, recurrence, templates/holidays permissions, activities scoping, team directory. |
| `migrations/` | 0001 lead schema · 0002 assignment rule + `reminded_at` · 0003 task · 0004 holiday/template/activity + task category/frequency/subscribers. |

### `backend/workspace/` — Groups, Notices, Links, Idea Board
| File | What it does |
|---|---|
| `models.py` | `Group` (+members M2M, owner, active), `Notice`/`NoticeRead` (audience-targeted announcements with lifecycle + read tracking), `LinkCollection`/`Link` (bookmarks, group-scoped visibility, favorites), `Idea`/`IdeaComment` (boards with votes + review statuses). |
| `access.py` | Workspace visibility/permission helpers (mirrors `crm/scoping.py`): `visible_groups`, `can_create_group` (managers+), `can_manage_group` (owner/admin), `notice_targets` + `notices_for` (audience resolution), `visible_links`, `can_edit_link`, `visible_ideas`, `can_review_ideas`. |
| `serializers.py` | All workspace serializers, including notice audience validation (role/department/group/user-id checks) and http/https-only URL validation on links. |
| `views.py` | `GroupViewSet` (create=manager+, archive-on-delete, `add_member`/`remove_member`, `dashboard` action with task tiles + recent activity), `NoticeViewSet` (targeted feed vs `?manage=true` admin listing, `publish`/`archive`/`read` actions, read/unread/search filters), `LinkCollectionViewSet`, `LinkViewSet` (+`favorite` toggle), `IdeaViewSet` (scope filters, author-vs-reviewer edit rules, `comments`, `vote`). |
| `urls.py` / `admin.py` | Routers `groups`, `notices`, `link-collections`, `links`, `ideas`; Django-admin registrations. |
| `tests.py` | 21 tests — group create permission, membership visibility, member management guards, archive-not-delete, group-task visibility + foreign-group guard, group dashboard math, notice targeting (all 5 audience types), draft/scheduled/expired hiding, read flow, admin-only manage + publish/archive, audience validation, link URL-scheme rejection, group-link scoping, edit-own + favorites, idea scopes, membership guard, status-change capability, comments + votes. |
| `migrations/` | 0001 all workspace models. (Plus `crm/0005_task_group` for the Task→Group link.) |

### `backend/webforms/` — the form builder
| File | What it does |
|---|---|
| `models.py` | `Form` (status lifecycle, unguessable `public_token` share link, integration flags), `FormField` (10 types, options, `lead_attr` mapping, order), `FormSubmission` (answers JSON, links to created Lead/Task, `person()` resolution), `SubmissionFile`. |
| `services.py` | `validate_answers()` — full server-side validation (required, email, phone regex, number, ISO date, choice membership, 10 MB file cap). `create_submission()` — validate → store → `_run_integrations()`: builds a Lead from the `lead_attr`-mapped answers and hands it to the **existing** `crm.assignment.auto_assign` (no second pipeline), then creates the follow-up Task for the lead's assignee (falling back to the form creator) and notifies via `notifications.service.notify`. |
| `views.py` | `FormViewSet` — published list for filling vs `?manage=true` builder list; `get_object` lets owners reach their drafts; actions `publish` (needs ≥1 field) / `close` / `reopen`, `add_field`, `reorder_fields`, `submit` (in-app), `submissions`, `export` (CSV via `csv.writer`). `FormFieldViewSet` (PATCH/DELETE one field). Public endpoints `public_form` / `public_submit` (`AllowAny`, published-only, token-addressed). |
| `serializers.py` | Form/field/submission serializers; `PublicFormSerializer` strips tokens + integration config from what anonymous visitors see; choice-fields require options. |
| `urls.py` / `admin.py` | Router (`forms`, `form-fields`) + `public/forms/<token>/[submit/]`; admin with inline fields. |
| `tests.py` | 13 tests — builder permissions, field add/edit/reorder/delete + options validation, publish guard, foreign-manager blocked, public GET/submit + draft hidden, validation errors, closed-form rejection, employee attribution, file upload, **lead integration with round-robin rotation across two submissions**, task-for-lead-assignee, task-only fallback to creator, CSV export content, submissions listing. |
| `migrations/` | 0001 all webforms models. |

### `backend/hr/` — Leave & Attendance
| File | What it does |
|---|---|
| `models.py` | `OfficeLocation` (geo-fence), `Attendance` (one row per user/day, unique-constrained, with GPS + face metadata and a `missing_checkout` property), `AttendanceCorrection`, `LeaveType`, `LeaveRequest`, `FaceProfile` (descriptor only — never an image). |
| `services.py` | All the rules, server-side: `cfg()` reads the HR_* / GEOFENCE_ / FACE_ env vars; `haversine_m` + `validate_location` (rejects outside every active fence, refuses missing GPS when enforced); `face_distance` + `verify_face` (throws rather than marking on unenrolled / missing / mismatched scans); `check_in` / `check_out` (late-grace, working minutes, half-day/early-checkout classification); `leave_working_days` (skips week-offs + `crm.Holiday`), `apply_leave_to_attendance` / `revoke_leave_attendance`, `leave_balances`, `monthly_report` (classifies un-recorded days as holiday/week-off/absent and never marks future days absent), `today_summary`. |
| `views.py` | `AttendanceViewSet` (history scoping, `today`, `check_in`, `check_out`, `monthly`, `team_today`), `CorrectionViewSet` (+`review` that rewrites the attendance day; self-review blocked), `LeaveRequestViewSet` (apply with overlap/working-day validation, `cancel`, `review` + notification, `balances`), `LeaveTypeViewSet`, `OfficeLocationViewSet`, `face_enrolment` (admin-only, validated descriptor), `hr_config`. Scope helper `managed_users()`: admin = everyone, `hr.approve` = own department, else self. |
| `serializers.py` | Attendance/correction/leave/type/office serializers; `MarkSerializer` accepts only raw GPS + descriptor (never a client-computed status); coordinate and date-range validation, document requirement enforcement. |
| `tests.py` | 28 tests — haversine accuracy, fence on/off/missing-GPS, office CRUD permissions, face enrolment permissions + validation, unenrolled/mismatch never marks, matching records confidence, check-in/out duplicates, half-day, `today` flags, history scoping across 3 roles, cross-employee month blocked, month classification (present/holiday/week-off/absent), `team_today` capability, correction request→review→attendance rewrite + self-review block, leave working-day counting, invalid range/overlap/document guards, approval writes LEAVE + notifies, rejection doesn't, cancel + revoke, balances, scoping, leave-type admin-only, check-in blocked on approved leave, config flags. |
| `migrations/` | 0001 all HR models. |

### `backend/payroll/` — salary & payroll
| File | What it does |
|---|---|
| `models.py` | `SalaryStructure` (dated history so old payslips stay explainable), `Advance` (recovered from a payslip), `PayrollRun` (one per month, draft → finalised), `Payslip` (full figures + a `breakdown` JSON that explains every number). |
| `services.py` | The whole calculation: `working_days_in()` (calendar − week-offs − `crm.Holiday`), `structure_for()` (latest effective salary), `paid_leave_dates()`, `count_days()` (attendance → present / half / paid leave / unpaid), `build_payslip()` (earned gross, PF on *earned* basic, PT, advances, **never negative**), `generate_run()` (rebuild a draft), `finalise()` (lock + settle advances). |
| `views.py` | `SalaryStructureViewSet` and `AdvanceViewSet` (employees read their own, `hr.manage` writes), `PayrollRunViewSet` (create/regenerate/finalise/payslips/CSV export), `PayslipViewSet` (employees see only their own **finalised** slips). |
| `tests.py` | 19 tests — working-day maths incl. holidays, full/absent/half-day/paid-vs-unpaid-leave pay, PF + PT + other deductions, PF pro-rating, **zero-attendance never goes negative**, latest-structure-wins, employees without salary skipped (not zeroed), advance recovery + cap + no double recovery, HR-only run creation, duplicate/invalid month, finalise locking, employee sees only own finalised slip, salary/advance write permissions, CSV export. |

### `backend/directory/` — Industry Task Template Directory
| File | What it does |
|---|---|
| `models.py` | `Industry` (name/slug/icon/order) and `DirectoryTemplate` (category, priority, frequency, tags, `steps` JSON, unique per industry+name). |
| `views.py` | `IndustryViewSet` (annotated template counts + category list), `DirectoryTemplateViewSet` — browse/filter/search, admin-only content writes, and the two "use" actions: `add_to_my_templates` (copies each step into `crm.TaskTemplate`, auto-deduping names) and `create_tasks` (steps → `crm.Task`, due dates from `offset_days`, optional assignee/group with the same permission rules as the Tasks module, logs a `TaskActivity`, notifies the assignee). |
| `management/commands/load_directory.py` | The seed/import mechanism: reads **JSON or CSV**, upserts by (industry, name) so re-running is idempotent, validates enums (bad priority/frequency fall back to defaults), skips step-less rows with a count, `--replace` to wipe first. Defaults to the bundled starter pack. |
| `seeds/starter_pack.json` | 13 industries × 26 templates of real checklist content — data, not code, so the library grows by adding files. |
| `tests.py` | 14 tests — JSON idempotent load + enum fallback + skip rules, CSV load with grouping and tag splitting, `--replace`, bundled pack sanity, auth required, industry counts/categories, all filters, admin-only content writes, `add_to_my_templates` capability + name dedupe, `create_tasks` offsets/self/others/notification, foreign-group block, unknown assignee. |

### `backend/notifications/` — the notification center
| File | What it does |
|---|---|
| `models.py` | `Notification` — user, type, title, body, link, `channels` JSON (audit of every delivery attempt), `read_at`. |
| `service.py` | **The one entry point**: `notify(user, type, title, body, link)` — creates the in-app row and fans out to Gmail + WhatsApp, recording each result. Helpers `notify_lead_assigned` (skips self-assignment), `notify_status_change` (only when someone else changes your lead), `notify_follow_up_due`. |
| `channels/whatsapp.py` | Meta WhatsApp Cloud API sender over Graph v23 REST: `send_text` (24h-session messages) and `send_template` (approved-template messages for business-initiated pings). Fully written; returns `skipped` until `WHATSAPP_ENABLED` + token + phone-number id are set. |
| `channels/gmail.py` | Gmail API `users.messages.send` over REST with OAuth **refresh-token flow** (`_access_token()` caches the access token). MIME-builds the mail. Returns `skipped` until `GMAIL_ENABLED` + client id/secret/refresh token/sender are set. |
| `views.py` + `urls.py` | `NotificationViewSet` — own-feed only, `unread_count`, `read`, `read_all`. |
| `apps.py` | Starts the **5-minute reminder ticker thread** when the server runs (disable with `NOTIF_SCHEDULER=false`; never runs during migrate/test). |
| `tests.py` | 6 tests — in-app creation + skipped-channel audit, no-phone skip reason, own-feed isolation, unread/read/read-all, cross-user 404. |

### `backend/intake/` — WhatsApp/Gmail/AI intake
| File | What it does |
|---|---|
| `models.py` | `InboundMessage` — channel, `external_id` (unique per channel → idempotent against Meta/Gmail redelivery), sender, body, media metadata, `ai_result`, linked lead, status, error. |
| `ai.py` | `classify(text, sender_name)` → fixed-shape dict `{intent, customer_name, vehicle, items[{name,quantity}], priority, department, summary, provider}`. Claude path: Anthropic Messages API over REST with a strict-JSON system prompt, 20s timeout. Fallback path: deterministic keyword classifier (intent words, Indian commercial-vehicle list, item + quantity extraction, urgency detection). Any Claude failure silently falls back — the pipeline never blocks on AI. |
| `pipeline.py` | `process_message(msg)` — classify → spam ⇒ ignored; else find the most recent **open** lead by phone (WhatsApp) or email (Gmail): found ⇒ append `wa_in`/`email_in` timeline event + update `ai_meta` + notify assignee; not found ⇒ create a lead (name/requirement/department/priority from AI, source = channel) and run `auto_assign`. Poison messages are caught and marked `failed`, never crash the webhook. |
| `webhook.py` | `/api/webhooks/whatsapp` — GET: Meta's verify-token handshake; POST: `X-Hub-Signature-256` HMAC check against `WHATSAPP_APP_SECRET`, parses entries/contacts/messages (text + media captions), dedupes by message id, runs the pipeline, always answers 200 fast (Meta retries otherwise). |
| `gmail_poll.py` | `poll_inbox()` — Gmail REST: list unread by `GMAIL_POLL_QUERY`, fetch full message, decode headers + text body, create `InboundMessage`, run pipeline, mark read. Inert until Gmail is configured. |
| `views.py` | `IntakeViewSet` — AI-inbox listing (admin + sales managers) with channel/status filters; `simulate` action (admin) — runs any text through the **real** pipeline for testing/demos. |
| `apps.py` | Starts the Gmail poll thread (interval `GMAIL_POLL_SECONDS`) only when `GMAIL_ENABLED=true`. |
| `management/commands/poll_gmail.py` | One-shot poll for cron use. |
| `urls.py` / `admin.py` | Webhook path + intake router; admin registration. |
| `tests.py` | 18 tests — the spec's exact "brake pad and oil filter for Tata 407" extraction, urgency/support/accounts/spam classification, quantity parsing, Claude success + failure-fallback (mocked), lead create/append/dedupe by phone & email, webhook handshake, bad-signature rejection, redelivery idempotency, simulator permissions. |

## 8. File-by-file reference — frontend

| File | What it does |
|---|---|
| `index.html` | Single-page shell; loads Outfit + IBM Plex Mono fonts. |
| `vite.config.js` | Dev server on **5174**, proxies `/api` and `/health` to the Django backend on 8000 (so no CORS pain in dev). |
| `package.json` | React 18, react-router-dom 6, chart.js + react-chartjs-2, Vite 5. |
| `src/main.jsx` | React root; mounts `<App/>` with the stylesheet. |
| `src/api.js` | Tiny API client: JWT storage in localStorage, automatic **refresh-and-retry once** on 401, hard logout when the refresh token dies, `ApiError` + `errorText()` (flattens DRF field errors), `apiUpload()` for multipart file uploads, `login()`/`logout()`. |
| `src/auth.jsx` | `AuthProvider` context: session restore from stored token on load, `user`, `ready`, `can(capability)` — the single place the UI asks "is this allowed?". |
| `src/App.jsx` | Router + the app shell: dark sidebar with role-aware nav (Dashboard, Leads, Tasks, Notifications [unread badge, 30s poll], AI Inbox, My Team, Automation), `Protected` route wrapper (redirects to `/login`, enforces capability per route), sign-out. |
| `src/styles.css` | The whole design system: CSS variables (emerald/ivory palette), sidebar/shell, stat tiles, filter row, kanban board + cards, drawer, tabs, modal, tables, notification feed, AI-inbox chips, task rows, dashboard grid, charts. |
| `src/pages/Login.jsx` | Login card; error states for bad credentials / deactivated accounts; redirects when already signed in. |
| `src/pages/Home.jsx` | Role-splitting home: `dashboard.view` roles get the **Dashboard** (11 tiles, Chart.js leads-per-day bar chart, pipeline-by-stage bars, employee performance table incl. open tasks, lead-source table, recent WhatsApp/Gmail feed, recent lead activity); everyone else gets a personal welcome card listing their capabilities. |
| `src/pages/Leads.jsx` | The CRM board: stats strip, search + priority/source/assignee filters + overdue chip, 6-column **drag-and-drop kanban** (drop = status change via API), Add-Lead modal (role-aware assignee field), and the **Lead drawer** — editable status/priority/assignee/follow-up, plus Timeline (notes + all auto events), Documents (upload/download), Quotations (create, status flow) tabs. Read-only roles get disabled controls. |
| `src/pages/Tasks.jsx` | The 7-tab Tasks area: **TaskDashboard** (range chips Today→All Time, My Report/Delegated/Group scope switch, category filter, search, 6 tiles, per-category table ⇄ bar chart), **TaskList** (shared by My/Delegated/Subscribed: status tabs, overdue filter, checkbox complete, status dropdown, 🔔 follow toggle, add-task modal with category/frequency/lead/assignee/due), **Templates** (grouped by category; Use → prefilled task modal; manage for assigners), **Activities** (audit feed with day filters), **Holidays** (calendar; admin add/delete). |
| `src/pages/Notifications.jsx` | Notification feed: unread highlighting, per-channel delivery chips (✉/💬 sent/skipped/error with reason on hover), click-to-read, mark-all-read; updates the sidebar badge. |
| `src/pages/Intake.jsx` | AI Inbox (admin + managers): every inbound message with channel tag, status, classification chips (intent / vehicle / items / priority / department / provider) and the lead it became; **Simulator** (admin) posts any text through the real pipeline. |
| `src/pages/Users.jsx` | Two views in one route: **Directory** for all roles (search, role filter, Mobile / Reports To / Department / role badges — read-only) and **ManageTeam** for admins (same table + status, Edit/Deactivate/Activate, member-count, reporting-manager filter, and the add/edit modal incl. role, department, WhatsApp number, reports-to, password). |
| `src/pages/Settings.jsx` | Automation page (admin): per-department assignment-rule cards — active toggle, strategy select, ordered member pills with move-up/down/remove, add-member dropdown, "next in rotation" hint. |
| `src/pages/Groups.jsx` | Groups: card grid of your groups → detail view with **Dashboard / Tasks / Ideas / Links / Members** tabs; create/edit/archive for managers+owners, member add/remove, group task list with checkbox completion, quick group-idea input. |
| `src/pages/Notices.jsx` | Notice board: All/Read/Unread + search feed with expand-to-read (auto mark-read); admin **Manage** mode — draft/publish/archive/delete table + create/edit modal with the audience picker (everyone/role/department/group/users), scheduling and expiry. |
| `src/pages/Links.jsx` | Links: collections with grouped link lists, add-link modal (collection, optional group visibility), ★ favorite toggle + favorites filter, search, new-collection input for managers. |
| `src/pages/Ideas.jsx` | Idea Board: Shared/My/Group tabs, vote button, expandable comments thread, status pills, review dropdown for managers/admin, new-idea modal (shared or group board). |
| `src/pages/Forms.jsx` | Forms: Fill mode (published-form cards → in-app fill) and My Forms mode (create, builder, submissions). Builder: share-link card with copy, name/description, lead/task integration toggles (+ department, task title, field→lead mapping), field editor (add/edit-required/maps-to/reorder/delete), publish/disable/reopen. Submissions: table with person/lead/task, expandable answer detail + file links, **Export CSV** (authenticated blob download). |
| `src/pages/FormRenderer.jsx` | Shared renderer for all 10 field types — used by the in-app fill page and the public page; multipart submit (answers + `file_<id>` uploads), per-field server error display, loading/busy state. |
| `src/pages/PublicForm.jsx` | The `/f/<token>` share-link page — works **without login**, branded card, thank-you state, not-found handling. |
| `src/face.js` | Lazy loader for the face engine: dynamically imports `@vladmandic/face-api`, loads the three model nets from `/models`, and exposes `describeFace(video)` → a 128-number descriptor (throws user-facing messages for "no face" / "more than one face") plus `isSupported()`. |
| `src/pages/FaceCapture.jsx` | The camera modal used for both check-in and enrolment: `getUserMedia`, mirrored preview with a guide oval, progress status while models load, per-error messages (permission denied / no camera / no face), always stops the camera stream on close, and returns only the descriptor. |
| `src/pages/Payroll.jsx` | Two exports used by the HR page: **PayrollAdmin** (`hr.manage`) with Monthly-payroll / Salaries / Advances sub-tabs — run a month, recalculate a draft, finalise, per-employee payslip table, CSV download; and **MySalary** (everyone) — current salary, payslip history, and a line-by-line payslip breakdown. |
| `src/pages/Directory.jsx` | The **Template Directory** tab inside Tasks: industry cards → category filter / global search → template list with tags & step counts → expandable step preview → "Create N tasks" (assignee + group pickers) and "Add to my Task Templates". |
| `src/pages/HR.jsx` | Attendance & leave, role-aware tabs: **Today** (check-in/out with browser geolocation, live status tiles, policy/feature banner), **My Attendance** (month picker, per-status totals, day table with late/early/no-checkout flags, "Fix" → correction request), **My Leave** (balance tiles, apply modal with document upload when required, history, cancel), **Team** (today's roster + counts, drill into any member's month) and **Approvals** (pending leave + corrections with remarks, approve/reject) for `hr.approve`, plus **HR Settings** (office geo-fences with "use my current location", leave types, live policy readout) for `hr.manage`. |

## 9. Environment variables (.env)

Copy `backend/.env.example` → `backend/.env`. Everything blank = feature off,
app still fully works. Full instructions for obtaining each credential are in
the file itself.

| Block | Keys | Turns on |
|---|---|---|
| Core | `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CORS_ORIGINS` | — |
| Database | `DATABASE_URL` (+ `pip install "psycopg[binary]"`) | Neon Postgres instead of SQLite |
| WhatsApp | `WHATSAPP_ENABLED`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_WEBHOOK_VERIFY_TOKEN` | outbound WhatsApp notifications + webhook signature verification. Webhook URL for Meta: `https://<host>/api/webhooks/whatsapp` |
| Gmail | `GMAIL_ENABLED`, `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, `GMAIL_SENDER`, `GMAIL_POLL_SECONDS`, `GMAIL_POLL_QUERY` | email notifications + inbox polling |
| Claude | `AI_ENABLED`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `AI_TIMEOUT_SECONDS` | AI classification (falls back to keyword rules otherwise) |
| Jobs | `NOTIF_SCHEDULER` | the in-process 5-min reminder ticker |

## 10. Testing

```powershell
venv\Scripts\python backend\manage.py test            # all 99
venv\Scripts\python backend\manage.py test crm        # one app
```

133 tests across: `accounts/tests.py` (13), `crm/tests.py` (19),
`crm/tests_assignment.py` (12), `crm/tests_dashboard.py` (5),
`crm/tests_tasks.py` (11), `crm/tests_tasks_area.py` (16),
`notifications/tests.py` (6), `intake/tests.py` (18),
`workspace/tests.py` (21), `webforms/tests.py` (13), `hr/tests.py` (28), `hr/tests_hr_role.py` (12), `directory/tests.py` (14), `payroll/tests.py` (19) —
run the command for the authoritative count.
Every phase was additionally verified end-to-end in the browser (login flows,
drag-and-drop, uploads, round-robin, notifications, simulator, group
workspaces, notice targeting, favorites, votes).

## 11. How the automations work

**New lead (any source) →**
`auto_assign()` picks the employee from the department's rule (round-robin or
fixed) → `LeadEvent` logged → `notify()` → in-app + Gmail + WhatsApp.

**Customer WhatsApp message →**
Meta webhook → signature check → dedupe by message id → `classify()` (Claude
or rules) → existing open lead by phone? append to timeline + notify assignee
: create lead → auto-assign → notify. Spam is ignored.

**Customer email →**
Gmail poller (thread or cron) → same pipeline, matching by email address.

**Follow-up/task reminders →**
Every 5 minutes (`notifications/apps.py` ticker) or `manage.py send_reminders`:
open leads past `follow_up_at` and unfinished tasks past `due_at` each get one
notification per date; rescheduling re-arms them.

**Recurring tasks →**
Marking a daily/weekly/monthly task done auto-creates the next occurrence with
the advanced due date, same assignee/subscribers.

## 12. Build history / phases

- **Phase 0** — Auth + RBAC + team management (JWT, 6 roles, capability matrix, admin user CRUD, login UI).
- **Phase 1** — Lead CRM core (pipeline, timeline, notes, documents, quotations, role scoping, kanban UI).
- **Phase 2** — Auto-assignment (round-robin/fixed per department) + notification center (in-app/Gmail/WhatsApp fan-out, reminders).
- **Phase 3** — AI intake (WhatsApp webhook, Gmail poller, Claude classifier + rules fallback, simulator, `.env.example`).
- **Phase 4** — Admin dashboard (tiles, Chart.js, employee/source performance, activity feeds).
- **Tasks module** — assignment, lead links, due dates, dashboard tile.
- **Tasks area v2** — reference-app parity: task dashboard (6 tiles/ranges/scopes/category table/bar chart), My/Delegated/Subscribed, Templates, Activities, Holidays, recurring tasks, My Team directory for all roles + reporting managers.
- **Phase 5.1–5.4 — Workspace modules**: Groups (team workspaces with task
  integration + per-group dashboard), Notices (audience-targeted notice
  board with read tracking), Links (collections + favorites + group
  scoping), Idea Board (votes, comments, review workflow). 21 new API
  tests (120 total).
- **Phase 5.5 — Forms**: builder (10 field types, reorder, lifecycle),
  in-app + anonymous share-link submissions with server-side validation
  and file uploads, submissions view + CSV export, and the lead/task
  integrations that reuse `auto_assign()` and the notification center.
  13 new API tests (133 total).
- **Phase 6 — Leave & Attendance**: attendance check-in/out with
  server-side status rules, month reports, correction requests; leave
  types/balances/apply/cancel/approve with attendance integration;
  geo-fenced attendance (haversine, admin-managed offices); optional
  face-recognition attendance (admin enrolment, threshold matching,
  never marks on a weak match). 28 new API tests (161 total).
- **Separation of duties (HR)**: new **HR Manager** role — full company-wide
  leave/attendance powers + user onboarding, and **no access to the sales
  pipeline** (no Leads, dashboard, AI Inbox or Automation). **Nobody
  approves their own leave or attendance correction — the Admin included**;
  the error names who *can* review it, or tells you to add an HR Manager if
  no other approver exists. `/api/users/` moved from an admin-role check to
  the `users.manage` capability, with a guard so a non-Admin cannot grant
  the Admin role, edit an Admin, or change their own role. 12 new API tests.

## 13. Not built yet

- **Payroll**: salary structures with history, monthly runs computed from
  attendance (working days, LWP, paid-vs-unpaid leave), PF / professional tax /
  other deductions, advances recovered and settled on finalise, draft →
  finalised lifecycle, CSV export, employee "My Salary" payslip view.
  Two guardrails caught during the build: PF is charged on *earned* basic, and
  a payslip can never go below zero. 19 new API tests (206 total).
- **Phase 8 — External integrations**: IndiaMART / TradeIndia adapters (need their paid API keys; new sources create inbound records and reuse the existing pipeline + `auto_assign`), Google Calendar/Sheets, outbound webhooks, CSV import.
- **Phase 9 — Support ecosystem**: tickets, events, tutorials, help center, setup checklist, KAM/CS profiles, Achievers Club.
- **Phase 10 — Production**: Neon `DATABASE_URL`, `render.yaml` + `DEBUG=false`/`ALLOWED_HOSTS` pass, then live WhatsApp/Gmail/Claude verification.
- Live credential wiring: WhatsApp send/receive, Gmail send/poll and Claude classification are fully coded but run in `skipped`/fallback mode until keys are pasted into `backend/.env`.
