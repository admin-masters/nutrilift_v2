"""Exercise deployment sequencing without touching a server or invoking sudo."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40


@pytest.fixture
def deployment(tmp_path):
    app = tmp_path / 'app'
    app.mkdir()
    (app / '.git').mkdir()
    (tmp_path / 'data').mkdir()
    (app / '.env').write_text(
        'DJANGO_DEBUG=0\n'
        'DJANGO_SECRET_KEY=test-deployment-key\n'
        'DJANGO_SETTINGS_MODULE=nutrilift.settings\n'
        f'NUTRILIFT_DATA_DIR="{tmp_path / "data"}"\n'
        f'NUTRILIFT_DB="{tmp_path / "data" / "live.sqlite3"}"\n'
        'NUTRILIFT_BASE_URL=https://nutrilift.example\n'
    )
    commands = tmp_path / 'commands'
    commands.mkdir()
    venv = tmp_path / 'venv' / 'bin'
    venv.mkdir(parents=True)
    log = tmp_path / 'commands.jsonl'
    # Use the real Python for inline backup/health validation, and substitute
    # external effects (Git, pip, management commands, services, and networking).
    executable = f'#!{sys.executable}\n' + r'''
import grp, json, os, pathlib, pwd, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['DEPLOY_TEST_LOG'], 'a') as log:
    log.write(json.dumps([name, *args]) + '\n')
command = ' '.join([name, *args])
if command == os.environ.get('DEPLOY_TEST_FAIL'):
    sys.exit(1)
if name == 'git':
    if args == ['branch', '--show-current']:
        print(os.environ.get('DEPLOY_TEST_BRANCH', 'Production'))
    elif args == ['remote', 'get-url', 'origin']:
        print(os.environ.get('DEPLOY_TEST_ORIGIN', 'https://github.com/admin-masters/nutrilift_v2.git'))
    elif args == ['status', '--porcelain']:
        print(os.environ.get('DEPLOY_TEST_DIRTY', ''), end='')
    elif args == ['rev-parse', 'HEAD']:
        print(os.environ.get('DEPLOY_TEST_SHA', 'a' * 40))
    elif args != ['pull', '--ff-only', 'origin', 'Production']:
        sys.exit('Unexpected git command: ' + command)
elif name == 'python':
    if os.environ.get('DJANGO_SECRET_KEY') != 'test-deployment-key':
        sys.exit('The production environment was not loaded')
    if args[0] == '-':
        os.execv(sys.executable, [sys.executable, *args])
    if args[:2] in (['manage.py', 'makemigrations'], ['manage.py', 'migrate']):
        pathlib.Path(os.environ['NUTRILIFT_DB']).touch(exist_ok=True)
elif name == 'curl':
    output = pathlib.Path(args[args.index('--output') + 1])
    output.write_text(os.environ.get('DEPLOY_TEST_HEALTH', '{"status":"ok"}'))
elif name == 'systemctl':
    if '--property=User' in args and '--value' in args:
        print(os.environ.get('DEPLOY_TEST_SERVICE_USER', pwd.getpwuid(os.getuid()).pw_name))
    elif '--property=Group' in args and '--value' in args:
        print(grp.getgrgid(os.getgid()).gr_name)
elif name == 'sudo' and args[:2] == ['-n', '/usr/bin/install']:
    pathlib.Path(args[-1]).mkdir(parents=True)
'''
    for path in [venv / 'python', *(commands / name for name in ('git', 'sudo', 'flock', 'systemctl', 'curl'))]:
        path.write_text(executable)
        path.chmod(0o755)
    env = {
        **os.environ,
        'PATH': f'{commands}:{os.environ["PATH"]}',
        'PYTHONPATH': str(ROOT),
        'NUTRILIFT_DEPLOY_APP_DIR': str(app),
        'NUTRILIFT_DEPLOY_VENV_DIR': str(venv.parent),
        'NUTRILIFT_DEPLOY_ENV_FILE': str(app / '.env'),
        'DEPLOY_TEST_LOG': str(log),
    }
    # Do not inherit deployment configuration from the developer's shell.
    env.pop('NUTRILIFT_DEPLOY_HEALTH_URL', None)

    def run(operation='deploy', **overrides):
        result = subprocess.run(
            ['bash', str(ROOT / 'scripts/deploy_ec2.sh'), SHA, operation],
            env={**env, **overrides}, text=True, capture_output=True,
            timeout=20,
        )
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls

    return run, app, tmp_path / 'data'


def test_inspection_does_not_pull_migrate_or_restart(deployment):
    run, _, data = deployment
    data.rmdir()
    result, calls = run(operation='inspect')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Inspection complete' in result.stdout
    assert any(call[:3] == ['systemctl', 'show', 'nutrilift.service'] for call in calls)
    assert not any(call[:2] == ['git', 'pull'] for call in calls)
    assert not any(call[:2] == ['python', 'manage.py'] for call in calls)
    assert not any(call[0] == 'sudo' for call in calls)
    assert not data.exists()


def test_missing_data_directory_reports_prerequisites_before_pull(deployment):
    run, _, data = deployment
    data.rmdir()
    result, calls = run()
    assert result.returncode != 0
    assert 'Provision a writable production data directory' in result.stderr
    assert not any(call[:2] == ['git', 'pull'] for call in calls)
    assert not data.exists()


def test_explicit_first_time_setup_creates_data_directory_then_deploys(deployment):
    run, _, data = deployment
    data.rmdir()
    result, calls = run(operation='prepare-data')
    assert result.returncode == 0, result.stdout + result.stderr
    assert data.is_dir()
    assert (data / 'live.sqlite3').stat().st_mode & 0o777 == 0o600
    install = next(call for call in calls if call[:3] == ['sudo', '-n', '/usr/bin/install'])
    assert calls.index(install) < calls.index(['git', 'pull', '--ff-only', 'origin', 'Production'])


@pytest.mark.parametrize('suffix', ['', '-wal', '-journal'])
def test_first_time_setup_never_discards_a_legacy_database(deployment, suffix):
    run, app, data = deployment
    data.rmdir()
    (app / 'var').mkdir()
    legacy = app / 'var' / f'nutrilift.sqlite3{suffix}'
    if suffix:
        legacy.write_bytes(b'existing transaction data')
    else:
        with sqlite3.connect(legacy) as database:
            database.execute('CREATE TABLE preserved (id INTEGER)')
    result, calls = run(operation='prepare-data')
    assert result.returncode != 0
    assert 'legacy database contains data' in result.stderr
    assert not data.exists()
    assert not any(call[:3] == ['sudo', '-n', '/usr/bin/install'] for call in calls)


def test_first_time_setup_requires_matching_service_user(deployment):
    run, _, data = deployment
    data.rmdir()
    result, _ = run(operation='prepare-data', DEPLOY_TEST_SERVICE_USER='different-service-user')
    assert result.returncode != 0
    assert 'same user' in result.stderr
    assert not data.exists()


def test_deployment_sequence_and_online_sqlite_backup(deployment):
    run, _, data = deployment
    # Keep WAL open: copying only the database file would lose this record.
    with sqlite3.connect(data / 'live.sqlite3') as live:
        live.execute('PRAGMA journal_mode=WAL')
        live.execute('CREATE TABLE records (value TEXT)')
        live.execute("INSERT INTO records VALUES ('preserved')")
        live.commit()
        result, calls = run()
        assert result.returncode == 0, result.stdout + result.stderr
        backups = list((data / 'backups').glob('*.sqlite3'))
        assert len(backups) == 1
        with sqlite3.connect(backups[0]) as backup:
            assert backup.execute('SELECT value FROM records').fetchall() == [('preserved',)]
        assert backups[0].stat().st_mode & 0o777 == 0o600
        assert live.execute('SELECT value FROM records').fetchall() == [('preserved',)]
        assert (data / 'live.sqlite3').stat().st_mode & 0o777 == 0o600

    expected = [
        ['git', 'pull', '--ff-only', 'origin', 'Production'],
        ['python', '-m', 'pip', 'install', '-r', 'requirements.txt'],
        ['python', 'manage.py', 'check'],
        ['python', 'manage.py', 'makemigrations', '--check', '--dry-run'],
        ['python', '-'],
        ['python', 'manage.py', 'migrate', '--noinput'],
        ['python', 'manage.py', 'collectstatic', '--noinput'],
        ['sudo', '-n', '/usr/bin/systemctl', 'restart', 'nutrilift.service'],
        ['sudo', '-n', '/usr/bin/systemctl', 'restart', 'nginx'],
        ['systemctl', 'is-active', '--quiet', 'nutrilift.service'],
        ['systemctl', 'is-active', '--quiet', 'nginx'],
    ]
    positions = [calls.index(command) for command in expected]
    assert positions == sorted(positions)
    curl = next(call for call in calls if call[0] == 'curl')
    assert 'http://127.0.0.1/health/' in curl
    assert 'Host: nutrilift.example' in curl
    assert calls.index(curl) > positions[-1]
    assert 'Deployment successful' in result.stdout


@pytest.mark.parametrize('overrides', [
    {'DEPLOY_TEST_DIRTY': ' M nutrilift/settings.py\n'},
    {'DEPLOY_TEST_BRANCH': 'Staging'},
    {'DEPLOY_TEST_ORIGIN': 'https://github.com/gopalakrishnanplus-creator/nutrilift_v2.git'},
    {'DEPLOY_TEST_FAIL': 'flock -n 9'},
    {'DEPLOY_TEST_FAIL': 'sudo -n -l /usr/bin/systemctl restart nutrilift.service'},
    {'DEPLOY_TEST_FAIL': 'sudo -n /usr/sbin/nginx -t'},
])
def test_preflight_failure_does_not_pull_or_restart(deployment, overrides):
    run, _, _ = deployment
    result, calls = run(**overrides)
    assert result.returncode != 0
    assert not any(call[:2] == ['git', 'pull'] for call in calls)
    assert not any(call[:4] == ['sudo', '-n', '/usr/bin/systemctl', 'restart'] for call in calls)


@pytest.mark.parametrize('failed_command', [
    'git pull --ff-only origin Production',
    'python -m pip install -r requirements.txt',
    'python manage.py check',
    'python manage.py makemigrations --check --dry-run',
    'python -',
    'python manage.py migrate --noinput',
    'python manage.py collectstatic --noinput',
])
def test_failure_stops_before_service_restart(deployment, failed_command):
    run, _, _ = deployment
    result, calls = run(DEPLOY_TEST_FAIL=failed_command)
    assert result.returncode != 0
    assert not any(call[:4] == ['sudo', '-n', '/usr/bin/systemctl', 'restart'] for call in calls)
    assert not any(call[0] == 'curl' for call in calls)


def test_untested_commit_stops_before_dependencies_or_migrations(deployment):
    run, _, _ = deployment
    result, calls = run(DEPLOY_TEST_SHA='b' * 40)
    assert result.returncode != 0
    assert 'tested commit' in result.stderr
    assert not any(call[0] == 'python' for call in calls)


def test_missing_environment_stops_before_pull(deployment):
    run, app, _ = deployment
    (app / '.env').unlink()
    result, calls = run()
    assert result.returncode != 0
    assert 'environment file' in result.stderr
    assert not any(call[:2] == ['git', 'pull'] for call in calls)


def test_custom_environment_file(deployment):
    run, app, _ = deployment
    (app / '.env').rename(app / '.env.production')
    result, _ = run(NUTRILIFT_DEPLOY_ENV_FILE=str(app / '.env.production'))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('overrides', [
    {'DEPLOY_TEST_FAIL': 'sudo -n /usr/bin/systemctl restart nutrilift.service'},
    {'DEPLOY_TEST_FAIL': 'sudo -n /usr/bin/systemctl restart nginx'},
    {'DEPLOY_TEST_FAIL': 'systemctl is-active --quiet nutrilift.service'},
    {'DEPLOY_TEST_FAIL': 'systemctl is-active --quiet nginx'},
    {'DEPLOY_TEST_HEALTH': '{"status":"error"}'},
    {'DEPLOY_TEST_HEALTH': '<html>Bad gateway</html>'},
])
def test_unhealthy_deployment_is_not_reported_as_success(deployment, overrides):
    run, _, _ = deployment
    result, _ = run(**overrides)
    assert result.returncode != 0
    assert 'Deployment successful' not in result.stdout
