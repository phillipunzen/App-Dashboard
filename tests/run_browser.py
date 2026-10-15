"""Run the browser suite against a disposable local instance, then clean up."""
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def main():
    project = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix='app-dashboard-e2e-') as temporary:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        password = secrets.token_urlsafe(24)
        env = {**os.environ, 'ADMIN_PASSWORD': password, 'ADMIN_USERNAME': 'admin',
               'DATABASE_PATH': str(Path(temporary) / 'dashboard.sqlite3'),
               'SECURE_COOKIE': 'false', 'TRUSTED_PROXY_HOPS': '0',
               'PUBLIC_ORIGIN': '', 'DASHBOARD_TITLE': 'App Dashboard'}
        env.pop('ADMIN_PASSWORD_FILE', None)
        with (Path(temporary) / 'server.log').open('w+') as log:
            server = subprocess.Popen(
                [sys.executable, '-m', 'gunicorn', '--bind', f'127.0.0.1:{port}',
                 '--workers', '1', '--threads', '4', '--timeout', '45', 'app:create_app()'],
                cwd=project, env=env, stdout=log, stderr=log,
            )
            try:
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError('The disposable test server exited early.')
                    try:
                        urllib.request.urlopen(url + '/healthz', timeout=1).close()
                        break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError('The disposable test server did not become ready.')
                result = subprocess.run(
                    ['npm', 'run', 'test:browser'], cwd=project,
                    env={**os.environ, 'APPHAFEN_TEST_URL': url, 'APPHAFEN_TEST_PASSWORD': password},
                )
                if result.returncode:
                    raise SystemExit(result.returncode)
            except BaseException:
                log.seek(0)
                print(log.read(), file=sys.stderr)
                raise
            finally:
                if server.poll() is None:
                    server.terminate()
                    try:
                        server.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait()


if __name__ == '__main__':
    main()
