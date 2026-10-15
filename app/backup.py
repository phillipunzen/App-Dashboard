"""Consistent SQLite backups to stdout; restore from stdin while the server is stopped."""
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path


def main():
    database = Path(os.environ.get('DATABASE_PATH', '/data/dashboard.sqlite3')).resolve()
    restore = sys.argv[1:] == ['--restore']
    if sys.argv[1:] and not restore:
        raise SystemExit('Verwendung: python -m app.backup [--restore]')
    if restore:
        # Validate the complete input before replacing any live database files.
        with tempfile.TemporaryDirectory(dir=database.parent) as temporary:
            candidate = Path(temporary) / 'restore.sqlite3'
            with candidate.open('wb') as output:
                while chunk := sys.stdin.buffer.read(1024 * 1024):
                    output.write(chunk)
            with closing(sqlite3.connect(f'{candidate.as_uri()}?mode=ro', uri=True)) as check:
                if check.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise SystemExit('Die Sicherung ist beschädigt.')
                tables = {row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {'apps', 'config', 'login_attempts'}.issubset(tables):
                    raise SystemExit('Die Datei ist keine AppDashboard-Datenbank.')
            for suffix in ('-wal', '-shm'):
                Path(str(database) + suffix).unlink(missing_ok=True)
            candidate.chmod(0o600)
            os.replace(candidate, database)
        print('Datenbank wiederhergestellt.', file=sys.stderr)
    else:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'backup.sqlite3'
            with closing(sqlite3.connect(f'{database.as_uri()}?mode=ro', uri=True)) as source:
                with closing(sqlite3.connect(target)) as destination:
                    source.backup(destination)
            with target.open('rb') as snapshot:
                while chunk := snapshot.read(1024 * 1024):
                    sys.stdout.buffer.write(chunk)


if __name__ == '__main__':
    main()
