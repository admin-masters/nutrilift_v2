# NutriLift — local school screening application

Python/Django with a SQLite database. Run locally using the instructions below, or deploy the Production branch to the existing EC2 server through GitHub Actions.

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

To create or repair just the three demo sign-ins and their school/class access:

```sh
.venv/bin/python manage.py provision_demo_accounts --reset-passwords
```

Enter the desired demo password at the hidden prompt. This preserves screenings and other accounts. Omitting `--reset-passwords` preserves existing demo passwords. Production provisioning is an explicit, one-time GitHub Actions operation; normal deployments do not create or reset demo accounts. See the [deployment guide](docs/DEPLOYMENT.md#one-time-demo-account-provisioning).

To provision an additional authorised programme user locally:

```sh
.venv/bin/python manage.py create_programme_user --email programme@example.org --name "Programme User"
```

The command prompts for a password without placing it in shell history.

## Try the workflows

1. Sign in as teacher. Choose a class and **Start screening a student**. The roll-number check finds any existing record before questions appear. A new roll opens blank answers; **Screen next student** returns to a blank, focused roll field in the same class.
2. Use **Flagged students** for red/yellow results, with pending parent messages first, or **Re-screenings due**. School reports cover the academic year without custom date filters.
3. **Edit responses** preserves the original date and audit history. **Re-screen** opens a blank, new dated form when due. The latest form controls current follow-up and due status.
4. **Notify parents** asks only for the parent's name and Indian WhatsApp number (10 digits or +91). The configured Marathi message and relevant video must be approved first. Continuing opens WhatsApp and returns to the same class report. A blocked popup or cancellation leaves the record pending. Reopening counts once and does not move the due date. Parent details are cleared and never submitted to NutriLift.
5. Use **How to screen students** to open the guide/video popup. Sign in as principal to **Share link with class teachers**, copy the invitation, or open it in WhatsApp. Invitations include the school join link and guide.
6. Programme reporting opens with Maharashtra totals. Browse district → school → class → roll → screening date, or select a total. **Back to records** preserves filters and pagination. Invalid dates show an inline error while retaining the last valid report.

Operator configuration remains available to authorised programme users at `/settings/` for guide/video URLs, Marathi templates, approval and school-day settings. It is intentionally absent from the reporting navigation. The existing local email backend and restricted `/outbox/` diagnostic endpoint remain available for operators; pilot navigation does not show the outbox. External email delivery requires separate configuration.

See [the 27 November product review](docs/PRODUCT_REVIEW_2026-11-27.md) for the implemented changes and verification.

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

## Automated EC2 deployment

GitHub Actions tests pushes and pull requests for **Staging** and **Production**. Successful pushes to **admin-masters/nutrilift_v2 → Production** deploy automatically using the repository secrets **EC2_IP** and **EC2_SSH_KEY**, with SSH user **ubuntu**. Staging only runs CI.

Deployment runs `git pull --ff-only origin Production` in `/var/www/nutrilift_v2`, installs requirements through `/var/www/venv`, backs up SQLite, migrates, collects static files, and restarts `nutrilift.service` and `nginx`. It verifies both services and the application health endpoint. See [EC2 deployment setup and troubleshooting](docs/DEPLOYMENT.md) for server prerequisites and manual retries.
