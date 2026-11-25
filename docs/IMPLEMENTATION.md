# NutriLift local implementation

The PDF specifies the release workflow. The workbook specifies the screening questions and scoring. Document content was treated as product input, not permission to contact anyone or deploy remotely.

## Scope and decisions

- Python/Django 5.2, SQLite, server-rendered HTML and local CSS/JavaScript. No runtime CDN dependencies or cloud database.
- English application navigation. Screening question labels and prompts are available in all eight source workbook languages; shared controls remain English, matching the PRD release scope. Marathi parent text is configurable.
- Student identity is school, academic year, class, section and normalised roll number. Numeric `0012` and `12` are the same roll. No student-name field exists, resolving the workbook's name field in favour of the PRD's explicit privacy rule.
- The user confirmed that **Yes** to sugary drinks/packaged snacks triggers red. The workbook's conflicting “If no” annotation is not used.
- Source diet options are lacto-vegetarian, lacto-ovo-vegetarian and non-vegetarian. Although annotations mention vegans, no vegan option exists in the supplied choices, so none was invented.
- Required questions must have explicit answers. Conditional answers are removed server-side when inapplicable. An approximate deworming date is optional because it may not be known; a known date cannot be before birth or after the screening.
- The highest-severity finding determines the overall flag: red, then yellow, then green. Each contributing finding remains visible.
- Academic year is one configured programme year. Local demo setup selects June–May based on local date. This is a configurable code/data assumption; multi-year promotion is outside the supplied release scope.
- Age is completed calendar months at the original screening date. Supported school screening range is 6 months through age 18 (before the 19th birthday). MUAC applies below 60 months. BMI is computed from 60 months. Date/weight/height sanity validation prevents invalid calculations.
- School days default to Monday–Friday, with configurable weekday numbers and holidays. Reminder worker runs every minute, creates the first pending-message reminder next school day, due reminders on their due date, and combined outstanding reminders after seven days on a school day. Each teacher receives at most one reminder per date.
- New registrations become active immediately and are signed in. A generated password and login URL are written to the account's local email outbox. Password changes and password reset links work locally; programme admins can inspect the outbox during testing.
- Principal invitations and parent messages open WhatsApp only on a deliberate button click. The app does not press Send. Popup blocks leave the status pending. A successful browser window/navigation launch records one opened event per screening. Cross-origin restrictions prevent proving WhatsApp delivery or successful loading, which is never claimed.
- Parent contact fields have no form names, are never submitted to the application, use no persistent browser storage, and are cleared after launch or departure. The opened endpoint accepts only an empty body or `{}`. The prepared message and recipient necessarily pass to WhatsApp when the teacher chooses to open it.
- The built-in PDF is a quick guide derived from the supplied workbook. Guide/video URLs and Marathi message templates can be configured by the programme admin. Draft content is labelled. No approved video assets were supplied or fabricated.
- The initial build was local-only. On 25 November 2026 the user authorised publishing to `admin-masters/nutrilift_v2` on `Production` and creating the `gopalakrishnanplus-creator` fork with `Staging` for future modifications. CI/CD and AWS deployment remain a separate phase.

## Counting and record integrity

The six dashboard figures use one shared service for all roles and drilldown levels. Periods use screening dates, not modification dates.

1. Students screened: distinct student identities with at least one form in the selected period.
2. Screenings completed: individual forms, including re-screenings.
3. Red flagged students: students whose latest form in the period is red or yellow.
4. Parent messages opened: forms with an opened timestamp. Historical opened events survive corrections to green, as required by the PRD.
5. Parent messages pending: red/yellow forms without an opened timestamp. A later re-screening does not silently erase an earlier pending message.
6. Re-screenings due: latest student forms due today/overdue, excluding any predecessor closed by a newer form even if that successor is outside the filtered period.

Calendar-month due dates clamp to the month's final day where necessary. Edits retain the screening date, recompute findings and due dates, preserve opened history, and append an immutable snapshot with actor/time/reason. Revision checks reject stale edits. Unique submission UUIDs and database transactions prevent retry duplication. Re-screening starts with blank answers and retains the roll/class/year. A second fresh form is rejected until due; corrections use Edit responses.

## Access and local operation

Teacher access is checked against assigned classes at every view and export. Principals can read their own school, invite teachers and grant/revoke class access. Programme users can read programme-wide records and configure content, but cannot edit teacher screening responses. Server-side scope filtering applies to direct record URLs, reports and CSV exports.

Django provides password hashing, CSRF protection, sessions and HTML escaping. Additional controls include login throttling, a same-origin referrer policy, a self-only content policy, no-store response headers, safe CSV cells, server-side validation, and loopback-only serving. SQLite data, local email contents and the local secret key are ignored by Git.

The local web server is for review. Production hardening and operations belong in the later EC2 phase: HTTPS, a production WSGI server/proxy, production email delivery, secret injection, backup/restore policies, user provisioning, monitored scheduling and dependency/security checks. The demo credentials are strictly for local use.

## Verification

`pytest` covers scoring, official WHO examples, boundary values, conditional validation, eight-language extraction, identity uniqueness, access isolation, edits and stale revisions, idempotent saves and openings, re-screening, all six totals, school-day reminders, registration, local outbox, CSRF rejection, CSV formula protection, settings and rendered pages.

Browser testing checks real authentication, full screening submission, validation recovery, conditional fields, history, parent popup handling without contacting a recipient, reporting, settings, registration and responsive layout. See `docs/TESTING.md` for the final observed results.
