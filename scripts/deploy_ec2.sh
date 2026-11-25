#!/usr/bin/env bash
# Executed over SSH by GitHub Actions. Source updates use git pull only.
set -Eeuo pipefail
umask 022
trap 'printf "Deployment failed at line %s. Inspect the GitHub Actions log before retrying.\n" "$LINENO" >&2' ERR

fail() { printf '%s\n' "$*" >&2; exit 1; }

readonly APP_DIR="${NUTRILIFT_DEPLOY_APP_DIR:-/var/www/nutrilift_v2}"
readonly VENV_DIR="${NUTRILIFT_DEPLOY_VENV_DIR:-/var/www/venv}"
readonly PYTHON="$VENV_DIR/bin/python"
readonly EXPECTED_SHA="${1:-}"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'Pass the full commit SHA that passed CI.'
[[ -d "$APP_DIR/.git" ]] || fail "An existing Git checkout is required at $APP_DIR."
[[ -x "$PYTHON" ]] || fail "Python virtualenv is missing at $VENV_DIR."
cd "$APP_DIR"

# Stored inside .git so the lock never makes the working tree dirty.
exec 9>.git/nutrilift-deploy.lock
flock -n 9 || fail 'Another deployment is running on this server.'
[[ "$(git branch --show-current)" == Production ]] || fail 'The server checkout must be on Production.'
case "$(git remote get-url origin)" in
  https://github.com/admin-masters/nutrilift_v2|https://github.com/admin-masters/nutrilift_v2.git|git@github.com:admin-masters/nutrilift_v2|git@github.com:admin-masters/nutrilift_v2.git|ssh://git@github.com/admin-masters/nutrilift_v2.git) ;;
  *) fail 'Server origin must point to admin-masters/nutrilift_v2.' ;;
esac
[[ -z "$(git status --porcelain)" ]] || fail 'The server checkout has local changes. Resolve them before deployment.'

# Use the same environment file as nutrilift.service; never echo its contents.
ENV_FILE="${NUTRILIFT_DEPLOY_ENV_FILE:-/var/www/secrets/nutrilift.env}"
[[ -r "$ENV_FILE" ]] || fail "Missing readable server environment file: $ENV_FILE"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-nutrilift.settings}"
[[ "${DJANGO_DEBUG:-0}" == 0 ]] || fail 'Production requires DJANGO_DEBUG=0.'
[[ -n "${DJANGO_SECRET_KEY:-}" ]] || fail 'Set DJANGO_SECRET_KEY in the server environment file.'

# Validate required privileged commands before modifying code or the database.
sudo -n -l /usr/sbin/nginx -t >/dev/null
sudo -n -l /usr/bin/systemctl restart nutrilift.service >/dev/null
sudo -n -l /usr/bin/systemctl restart nginx >/dev/null
sudo -n /usr/sbin/nginx -t

printf 'Pulling Production into %s\n' "$APP_DIR"
git pull --ff-only origin Production
[[ "$(git rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail 'Production advanced or the server diverged from the tested commit. Run CI again for the current Production commit.'

"$PYTHON" -m pip install -r requirements.txt
"$PYTHON" manage.py check
"$PYTHON" manage.py makemigrations --check --dry-run

# SQLite's online backup API includes committed WAL data while the app is live.
# Backups stay beside the database, outside version control, with private access.
"$PYTHON" - <<'PY'
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from django.conf import settings

database = settings.DATABASES['default']
if database['ENGINE'] != 'django.db.backends.sqlite3':
    raise SystemExit('This deployment expects SQLite; configure a backup before changing database engines.')
source = Path(database['NAME']).resolve()
if source.exists():
    directory = source.parent / 'backups'
    directory.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = directory / f'{source.stem}-{stamp}.sqlite3'
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as live:
        with sqlite3.connect(target) as backup:
            live.backup(backup)
            if backup.execute('PRAGMA quick_check').fetchone() != ('ok',):
                raise SystemExit('Database backup integrity check failed.')
    target.chmod(0o600)
    print(f'Database backup saved: {target}')
else:
    print('No existing database; migrations will create it.')
PY

"$PYTHON" manage.py migrate --noinput
"$PYTHON" manage.py collectstatic --noinput

sudo -n /usr/bin/systemctl restart nutrilift.service
sudo -n /usr/bin/systemctl restart nginx
systemctl is-active --quiet nutrilift.service
systemctl is-active --quiet nginx

HEALTH_URL="${NUTRILIFT_DEPLOY_HEALTH_URL:-${NUTRILIFT_BASE_URL:-https://nutrilift.inditech.co.in}/health/}"
health_file=$(mktemp)
trap 'rm -f "$health_file"' EXIT
curl --fail --silent --show-error --location \
  --connect-timeout 10 --max-time 30 --retry 5 --retry-delay 5 --retry-connrefused \
  "$HEALTH_URL" --output "$health_file"
"$PYTHON" - "$health_file" <<'PY'
import json
import sys
with open(sys.argv[1]) as response:
    if json.load(response).get('status') != 'ok':
        raise SystemExit('The application health endpoint did not return status=ok.')
PY
printf 'Deployment successful: %s\n' "$EXPECTED_SHA"
