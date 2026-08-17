
- **Phase 6 — Leave & Attendance** (check-in/out, geo-fencing, optional face recognition, leave approvals).
- **Phase 7 — Industry template directory** (JSON/CSV-seeded template marketplace).
- **Phase 8 — External integrations**: IndiaMART / TradeIndia adapters (need their paid API keys; new sources create inbound records and reuse the existing pipeline + `auto_assign`), Google Calendar/Sheets, outbound webhooks, CSV import.
- **Phase 9 — Support ecosystem**: tickets, events, tutorials, help center, setup checklist, KAM/CS profiles, Achievers Club.
- **Phase 10 — Production**: Neon `DATABASE_URL`, `render.yaml` + `DEBUG=false`/`ALLOWED_HOSTS` pass, then live WhatsApp/Gmail/Claude verification.
- Live credential wiring: WhatsApp send/receive, Gmail send/poll and Claude classification are fully coded but run in `skipped`/fallback mode until keys are pasted into `backend/.env`.

Phase 8: Integrations 🔴

Ye remaining integrations:

Lead Sources
IndiaMART
TradeIndia
Productivity
Google Calendar
Google Sheets
Developer/API
Webhooks
General API
Data
CSV Import

IndiaMART/TradeIndia ka flow ideally:

External Lead → InboundMessage → AI → Existing Lead check → New/Existing Lead → Auto Assignment → Notification

hona chahiye.

Phase 9: Support & Customer Success 🔴

Ye Automate Business ka support ecosystem hai:

Support Tickets
Events
Tutorials
Help Center
Setup Checklist
KAM
Customer Success Head
Achievers Club

Ye CRM ke core se alag ek customer-success layer hai.

Phase 10: Production 🔴

Last mein system ko actual production mein le jaana:

Database

SQLite → Neon PostgreSQL

Hosting

Render deployment

Production config
DEBUG=false
ALLOWED_HOSTS
CORS
production secrets
migrations
logging
health checks
Live integrations
WhatsApp credentials
Gmail credentials
Claude API key

Aur:

IndiaMART credentials
TradeIndia credentials

jab available hon.