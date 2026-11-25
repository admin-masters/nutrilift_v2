# GitHub Actions → EC2

## Repository and trigger

- Develop using **gopalakrishnanplus-creator**, in the fork's **Staging** branch.
- Promote changes to **admin-masters/nutrilift_v2**, branch **Production**.
- Pushes and pull requests to either branch run Django checks, migration checks, tests, shell lint, and static collection.
- Only a successful **Production push in the admin repository** deploys. A pull request or a Staging push cannot deploy.
- To retry the current Production commit, open **Actions → Test and deploy NutriLift → Run workflow → Production** in the admin repository.
- Deployments are serialized in GitHub and also locked on the server. A failed command stops the deployment and marks the run failed.

Workflow: [ci-cd.yml](../.github/workflows/ci-cd.yml). Server script: [deploy_ec2.sh](../scripts/deploy_ec2.sh).

## GitHub secrets

Configure these in the **admin repository**, under **Settings → Secrets and variables → Actions → Repository secrets**:

| Secret | Value |
|---|---|
| `EC2_IP` | EC2 public IP address or SSH hostname, without `https://`, username, or port. |
| `EC2_SSH_KEY` | Complete private SSH key, including BEGIN/END lines, for the server's `ubuntu` account. It must work without an interactive passphrase. |
| `EC2_KNOWN_HOSTS` (optional) | Verified OpenSSH known_hosts entry for the exact host in `EC2_IP`. |

SSH uses **ubuntu**, port **22**. The server must be reachable from the GitHub runner, and the matching public key must be in ubuntu's `~/.ssh/authorized_keys`. Keys are written to a private temporary directory on the runner and removed afterward. They are never committed or printed.

With `EC2_KNOWN_HOSTS`, the host key is pinned. Without it, the workflow uses `ssh-keyscan` on each fresh runner (trust on first use); this does not independently authenticate the first host key. Obtain and verify a pinned key through an existing trusted server connection if enabling that optional secret.

## Existing server prerequisites

The workflow deploys to an already provisioned Ubuntu server. It does not create EC2 instances, configure DNS/TLS, install nginx, replace systemd units, create virtualenvs, or seed demo users.

| Item | Required value |
|---|---|
| Existing repository | `/var/www/nutrilift_v2` |
| Checked-out branch | `Production` (case-sensitive) |
| Repository `origin` | `https://github.com/admin-masters/nutrilift_v2.git` or equivalent SSH URL |
| Existing Python virtualenv | `/var/www/venv` (Python 3.12 or newer; CI uses 3.13) |
| Django systemd service | `nutrilift.service` |
| Web server systemd service | `nginx` |
| Environment file | `/var/www/secrets/nutrilift.env` |
| Default public health endpoint | `https://nutrilift.inditech.co.in/health/` |

The checkout must be clean, with no conflicting tracked or untracked files. Ignored environment files, SQLite files, and `var/` are allowed. The ubuntu account needs write access to the checkout, virtualenv, database directory, and collected static directory, plus read access to the environment file. Existing database ownership and service access must be preserved.

The app service must load **the same environment file** used by deployment: `EnvironmentFile=/var/www/secrets/nutrilift.env` in its existing systemd unit. The deployment shell sources this trusted file with automatic export; use `KEY=value` assignments compatible with both Bash and systemd, with quoted values where necessary. It must include `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0`, and the correct data/database paths. Do not create a fresh secret key on every deployment.

The earlier production environment uses:

```dotenv
DJANGO_SETTINGS_MODULE=nutrilift.settings
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=REPLACE_WITH_YOUR_EXISTING_PRODUCTION_SECRET
DJANGO_ALLOWED_HOSTS=nutrilift.inditech.co.in,localhost,127.0.0.1
NUTRILIFT_BASE_URL=https://nutrilift.inditech.co.in
NUTRILIFT_DATA_DIR=/var/lib/nutrilift/production
NUTRILIFT_DB=/var/lib/nutrilift/production/nutrilift.sqlite3
NUTRILIFT_PORT=8000
```

`NUTRILIFT_PORT` only configures the local launcher; the production service's existing WSGI command determines its listening address. Nginx should serve `/static/` from `NUTRILIFT_DATA_DIR/static/` and proxy application requests to the existing Django service. The service must already have its WSGI server installed; the pipeline installs the app's pinned requirements and does not replace the server command.

The server needs `git`, `curl`, `flock` (util-linux), nginx, and systemd. If ubuntu does not already have passwordless sudo for the required commands, use `sudo visudo -f /etc/sudoers.d/nutrilift-deploy` to add:

```sudoers
ubuntu ALL=(root) NOPASSWD: /usr/sbin/nginx -t, /usr/bin/systemctl restart nutrilift.service, /usr/bin/systemctl restart nginx
```

## Deployment sequence

1. Validate branch, origin, clean checkout, environment, sudo permissions, and nginx configuration.
2. Run **`git pull --ff-only origin Production`** in `/var/www/nutrilift_v2`. No reset, checkout, clone, file sync, or forced overwrite is used for deployment.
3. Ensure the resulting commit is exactly the commit that passed this workflow's tests. If Production has advanced, stop and let the newer workflow deploy.
4. Run `/var/www/venv/bin/python -m pip install -r requirements.txt`.
5. Run Django checks and verify no migrations are missing from source control.
6. Back up any existing SQLite database with SQLite's online backup API, which includes committed WAL data. Integrity-check the backup before proceeding. Backups are dated files in a `backups/` directory beside the database, with private permissions. Arrange retention/off-server copies according to your own operational policy.
7. Run `manage.py migrate --noinput` and `manage.py collectstatic --noinput` with the existing virtualenv and production environment.
8. Restart **nutrilift.service**, then **nginx**, and confirm both are active.
9. Request `${NUTRILIFT_BASE_URL}/health/` (default domain above), retry transient connection/HTTP errors, and verify JSON `status: ok`.

To use an internal health URL, add `NUTRILIFT_DEPLOY_HEALTH_URL=http://127.0.0.1:8000/health/` to the same server environment file, adjusting the port to the actual service. The default public URL also checks DNS, TLS, and nginx routing.

For exceptional layouts or script tests, the SSH environment can override `NUTRILIFT_DEPLOY_APP_DIR`, `NUTRILIFT_DEPLOY_VENV_DIR`, or `NUTRILIFT_DEPLOY_ENV_FILE`. GitHub uses the paths specified above without overrides.

## Failures and recovery

Check the failed GitHub Actions step first, then inspect `journalctl -u nutrilift.service -n 100 --no-pager` and `journalctl -u nginx -n 100 --no-pager` on the server as appropriate. Missing environment, wrong branch/origin, dirty checkout, missing sudo permission, or invalid nginx configuration stop before the pull. Dependency/check/backup/migration/static failures stop before service restarts. A restart or health failure leaves the run failed and requires investigation.

Deployments update an existing checkout in place. They are not atomic: files or dependencies may already have changed when a later step fails, and a failed health check does not undo migrations. There is no automatic rollback or database restore. Correct the problem and run the workflow for current Production, or publish an intentional Git revert through the normal development process. Restore a database backup only as an explicit maintenance operation after assessing writes since the backup.

This pipeline preserves the application's current features and configuration, including its local email outbox. It does not configure SMTP or add separate reminder-worker services.
