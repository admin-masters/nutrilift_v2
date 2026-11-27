# Verification

## Product review — 27 November 2026

**142 tests passed**, Django checks passed and no model migrations were required. Chromium checks covered the updated teacher, principal and programme flows at 360 × 640 and programme reporting at 1280 × 900. See [the review verification record](PRODUCT_REVIEW_2026-11-27.md#verification) for scope, observed outcomes and limits.

The notes below record the original 24 November build. The review supersedes its message-preview, navigation and pending-task behavior. Current deployment setup is documented in [DEPLOYMENT.md](DEPLOYMENT.md).

## Original local verification — 24 November 2026

## Automated results

- **84 tests passed**, no test failures or warnings in the final run.
- `python manage.py check`: no issues.
- `python manage.py makemigrations --check --dry-run`: no pending model changes.
- Python source compilation completed successfully.

Tests use a separate database; they do not modify the local demo database.

Coverage includes all health and diet triggers, BMI cut-off boundaries and three published WHO worked examples (including both extreme-tail extensions), month-60 data, MUAC, adolescent conditionals, required answers, invalid values, exact calendar-month due dates, distinct roll/class identities, retries, edit history, stale-edit protection, cross-school access, read-only roles, CSRF, sign-in throttling, registration, password reset, programme-user provisioning, class access revocation, local mail, content settings, reminders, period counts, CSV safety and page rendering.

## Browser verification

Checked in local Chromium at desktop sizes (1200 and 1440 px) and mobile size (390 × 844 px):

- Teacher, principal and programme-admin sign-in and sign-out.
- Real school registration, school-specific teacher invitation, teacher registration, automatic sign-in and registration email in the local outbox.
- Invitation copying confirmed by the visible clipboard status.
- Required-field error summary and preserved answers after failed submission.
- Simulated network failure during save, followed by a successful retry with one saved screening.
- Conditional MUAC, adolescent-girls and diet questions.
- A full yellow screening, correct three-month due date, then correction to green with six-month due date, one audit revision and retained message-opened history.
- Marathi question rendering and eight-language selector.
- Parent-message preview, blocked pop-up behavior, and successful-open handler using a local mock. **No WhatsApp message was sent and no real recipient was contacted.**
- The only parent-status request body was `{}`. Parent inputs cleared after the mocked opening. Both localStorage and sessionStorage remained empty.
- Principal team page and programme totals, resource settings save and local reminder outbox.
- Mobile page had no horizontal document overflow; the wide records table scrolls within its container. Account and sign-out controls remain accessible.
- PDF quick guide rendered and visually inspected with no clipping or missing text.

The first real-browser sign-in found an overly restrictive referrer policy causing an originless form POST. It was corrected to `same-origin`, keeping Django CSRF enforcement enabled. A regression test covers the policy and a valid CSRF-protected sign-in.

Local screenshots are in `output/playwright/` and are intentionally ignored by Git. Temporary browser QA accounts and records were removed after testing; the labelled demonstration dataset remains.

## Explicit verification limits

- WhatsApp delivery, reading and video views are neither verified nor tracked; the PRD counts the opening only. Cross-origin browser navigation cannot prove an external app loaded or delivered a message.
- Emails are verified against the local SQLite outbox. External SMTP delivery is not configured in this local phase.
- Approved videos and message copy were not supplied. Settings support them; local draft labels remain until configured and approved.
- GitHub, AWS, CI/CD and production hosting have not been configured or tested, as requested for the later phase.
