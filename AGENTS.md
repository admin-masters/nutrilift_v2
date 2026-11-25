# NutriLift repository workflow

The user requested this repository and account arrangement on 25 November 2026:

- Admin/upstream: `admin-masters/nutrilift_v2`, branch `Production`.
- Development/origin: `gopalakrishnanplus-creator/nutrilift_v2`, branch `Staging`.
- Use the `gopalakrishnanplus-creator` GitHub account for future modifications. This is the authenticated account corresponding to the user's shorthand “Gopalakrishnanplus”. Do not switch to the admin account for routine development.
- Keep future work on `Staging` and push it to `origin`. Promote to `upstream/Production` only when the user requests promotion, normally through a pull request.
- Preserve local SQLite data and runtime files. Do not commit `var/`, `.env` files, credentials, screenshots, or raw source documents in `docs/source/`.
- Verify meaningful code changes with `.venv/bin/pytest -q` and `.venv/bin/python manage.py check`.
- GitHub repository setup does not authorise deploying to AWS or activating a deployment pipeline; that remains a separate phase.
