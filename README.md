# NutriLift — local school screening application

Python/Django with a local SQLite database. Runs entirely on this computer; external WhatsApp and configured education links open only when selected. AWS deployment is a separate phase.

## Repository workflow

- Admin repository: [admin-masters/nutrilift_v2](https://github.com/admin-masters/nutrilift_v2), branch **Production**.
- Development fork: [gopalakrishnanplus-creator/nutrilift_v2](https://github.com/gopalakrishnanplus-creator/nutrilift_v2), branch **Staging**.
- Make future changes using **gopalakrishnanplus-creator**, on **Staging**. Submit changes from the fork to the admin repository's **Production** branch for promotion.
- Local `origin` points to the development fork; `upstream` points to the admin repository. Branch names are case-sensitive.
- The database, local secrets, logs, screenshots and raw source documents are excluded from version control.

## Open the app

Local URL: **http://127.0.0.1:8000/**

| Role | Email | Password |
|---|---|---|
| Teacher | teacher@nutrilift.local | NutriLift@2026 |
| Principal | principal@nutrilift.local | NutriLift@2026 |
| SAPA/GOM administrator | admin@nutrilift.local | NutriLift@2026 |

The initial database contains **fictional demo schools and screenings**. Teacher Meera has access to Class 6, Sections A and B in Vidya Mandir School (Demo). Register a new school from the sign-in page to try a clean workflow.

## Start or restart

From this project directory:

```sh
.venv/bin/python scripts/run_local.py
```

This applies migrations and starts both the local web server and reminder worker. Keep the terminal running; press Ctrl+C to stop both. It binds only to `127.0.0.1`.

The instance prepared for this handoff is already running in the background. Its manager PID is in `var/server.pid` and its server log is in `var/server.log`. To stop that background instance before restarting:

```sh
kill -TERM "$(cat var/server.pid)"
```

Use that PID file only for the current background session. After stopping it, start the app with `scripts/run_local.py` as shown above.

For a fresh installation with Python 3.12 or newer:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_demo
.venv/bin/python scripts/run_local.py
```

`seed_demo` is idempotent and does not overwrite existing demo records.

To provision an additional authorised programme user locally:

```sh
.venv/bin/python manage.py create_programme_user --email programme@example.org --name "Programme User"
```

The command prompts for a password without placing it in shell history.

## Try the workflows

1. Sign in as teacher. Choose a class, select **Start screening students**, and use a new roll number. Complete the required answers and save. Inspect findings and the next screening date.
2. Open an existing student, select a screening date, and use **Edit responses** to test an audited correction. Use a due record to test **Re-screen**.
3. Open **Notify parents** for a red/yellow record. Parent details are kept only in that page's memory. Continuing opens WhatsApp; you decide whether to send. No actual recipient is needed to inspect the message preview.
4. Sign in as principal to share the school invitation and manage teacher class access.
5. Sign in as programme admin to filter by state/district/school/class/date, open each total's records, and export CSV.
6. Open **Programme settings** as admin to configure the PDF guide, screening video, Marathi parent video URLs, message templates, school weekdays and holidays. Supplied content is labelled as a local draft until approved.
7. Open **Local email outbox** for registration credentials and reminders. The teacher/principal sees their own emails; the programme admin can inspect all local test emails.

## Data and verification

- Database: `var/nutrilift.sqlite3`.
- Secret key: `var/.secret_key`, generated locally and ignored by Git.
- Runtime storage and local screenshots are excluded from Git.
- Tests: `.venv/bin/pytest -q`.
- Django checks: `.venv/bin/python manage.py check`.
- Reminder check: `.venv/bin/python manage.py send_reminders` (idempotent).
- Health endpoint: `http://127.0.0.1:8000/health/`.
- Stop the app before making a simple filesystem backup, or use SQLite's online backup API.

See [implementation decisions](docs/IMPLEMENTATION.md), [reference provenance](core/data/SOURCES.md) and [test results](docs/TESTING.md).

## Later deployment phase

CI/CD and AWS EC2 deployment remain the next phase after local acceptance. The project includes migrations and pinned dependencies to support that transition. The current Django development server and local email backend are intentionally for local testing; the Production branch name does not deploy the application.
