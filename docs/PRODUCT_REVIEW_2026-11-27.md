# Product review implementation — 27 November 2026

Source: the user's two-page **Nutrilift Product Changes.pdf**. The attachment was treated as product requirements. Repository/account and release instructions remain governed by `AGENTS.md`: this change goes to the development fork's `Staging` branch; production promotion is separate. The raw PDF is excluded from Git.

## Delivered behavior

| Review area | Implementation |
| --- | --- |
| Mobile interface | Black text, light surfaces, compact role navigation, large touch controls and responsive record cards. The main action is visible at 360 × 640. Screening saves remain accessible at the bottom of the viewport. |
| Login and privacy | Show/Hide password; the requested roll-number/privacy statement; no local-preview, outbox or CSV-export links on dashboards. |
| Teacher dashboard | Selected class at the top, Start screening a student, guide/video popup, full academic-year roll list, Flagged students and Re-screenings due filters. Flagged results include red and yellow, with current pending messages first. |
| Roll check | Normalised roll lookup before questions. Existing results show the last date, View record, Edit responses and Re-screen when due. New students and re-screenings start with blank answers. Screen next student keeps the class and focuses an empty roll field. |
| Parent notification | Only parent name and WhatsApp number, with a register-check instruction. Both 10-digit and +91 Indian numbers work. No in-app message preview. Approved Marathi template and relevant video open in WhatsApp; private inputs clear and the teacher returns to the same report. |
| Message status | Pending until a browser handoff succeeds. Cancellation or blocked opening does not record an event. Reopening retains the first timestamp, counts once and leaves the screening due date unchanged. Superseded forms remain in history but do not create current pending tasks. |
| Principal | Share link with class teachers is the main action. Copy invitation and Share via WhatsApp both include the school join link and guide. Class reports retain the two quick filters and metric drilldowns. |
| Programme | Maharashtra totals first, six metrics, district → school (with district) → class → roll → dated form. School-name search remains available. Initial state view contains aggregates. |
| Report state | Return links carry scope, dates, metric, search and page. Only the internal dashboard route is accepted. Invalid dates show inline errors and retain the last valid report for the signed-in user. |
| Record integrity | Corrections preserve original dates, audit snapshots and opened-message history. Re-screening creates a new dated form; current flag and due date use the latest form. No model migration or database replacement. |

## Verification

- 142 automated tests passed, including 17 new review regressions; the existing re-screening expectation was updated to the newly requested current-record behavior.
- Django system checks, migration-drift check and JavaScript syntax check passed.
- Chromium browser checks used an isolated SQLite database, separate from `var/nutrilift.sqlite3`.
- At 360 × 640, login, teacher/principal/programme dashboards, roll lookup, screening form, saved result, parent notification and invitation had no horizontal document overflow and their main actions were visible. Programme reporting was also checked at 1280 × 900.
- Browser flows covered Show/Hide, guide popup, existing-roll detection, complete new screening, Screen next student and autofocus, Indian-number validation, blocked popup/cancel, successful mocked WhatsApp handoff, cleared private inputs, same-class return, clipboard invitation, programme drilldowns and date errors.
- The successful notification request body was `{}`. Synthetic Marathi content and example.org URLs were installed only in the isolated QA database. No WhatsApp message was sent and no real recipient was contacted.

## Configuration and limits

Approved guide/video resources and Marathi messages remain configurable at `/settings/` for authorised programme users; this operator screen is hidden from reporting navigation. Parent sharing is disabled until the relevant message and video are configured and approved. No approved resources were fabricated for the user's working database.

“Opened in WhatsApp” records a successful browser window/navigation handoff. Browsers cannot confirm delivery, reading, video views or successful loading of an external app.

The existing local email backend and restricted outbox endpoint remain available to operators; removing pilot navigation does not configure external email delivery. The CSV endpoint retains its existing access controls but is no longer linked from dashboards.
