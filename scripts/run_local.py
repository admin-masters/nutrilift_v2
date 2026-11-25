#!/usr/bin/env python3
"""Start Django and the reminder worker, keeping both tied to this process."""
import os
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
python = str(ROOT / '.venv/bin/python')
port = os.environ.get('NUTRILIFT_PORT', '8000')
os.environ.setdefault('NUTRILIFT_BASE_URL', f'http://127.0.0.1:{port}')
subprocess.run([python, 'manage.py', 'migrate', '--noinput'], check=True)
children = []


def shutdown(*_):
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)
try:
    children.append(subprocess.Popen([python, 'manage.py', 'runserver', f'127.0.0.1:{port}', '--noreload']))
    children.append(subprocess.Popen([python, 'manage.py', 'send_reminders', '--loop']))
    print(f'NutriLift running at http://127.0.0.1:{port}', flush=True)
    children[0].wait()
finally:
    shutdown()
