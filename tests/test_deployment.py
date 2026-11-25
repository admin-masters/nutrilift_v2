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
import json, os, pathlib, sys
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
elif name == 'curl':
    output = pathlib.Path(args[args.index('--output') + 1])
    output.write_text(os.environ.get('DEPLOY_TEST_HEALTH', '{"status":"ok"}'))
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
        'DEPLOY_TEST_LOG': str(log),
    }
    # Do not inherit deployment configuration from the developer's shell.
    for name in ('NUTRILIFT_DEPLOY_ENV_FILE', 'NUTRILIFT_DEPLOY_HEALTH_URL'):
        env.pop(name, None)

    def run(**overrides):
        result = subprocess.run(
            ['bash', str(ROOT / 'scripts/deploy_ec2.sh'), SHA],
            env={**env, **overrides}, text=True, capture_output=True,
            timeout=20,
        )
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls

    return run, app, tmp_path / 'data'


def test_deployment_sequence_and_online_sqlite_backup(deployment):
    run, _, data = deployment
    data.mkdir()
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
    assert 'https://nutrilift.example/health/' in curl
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


def test_production_environment_filename_fallback(deployment):
    run, app, _ = deployment
    (app / '.env').rename(app / '.env.production')
    result, _ = run()
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
