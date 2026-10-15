"""Copy a quiescent dashboard database without changing its source."""
import argparse
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path


def copy_database(source, target):
    """Copy a stopped database, including any remaining WAL transactions."""
    source, target = Path(source).resolve(), Path(target).resolve()
    if not source.is_file():
        raise ValueError('Die Quell-Datenbank wurde nicht gefunden.')
    if source == target:
        raise ValueError('Quelle und Ziel müssen verschieden sein.')
    if target.exists() or any(Path(str(target) + suffix).exists() for suffix in ('-wal', '-shm')):
        raise ValueError('Im Ziel liegt bereits eine Datenbank. Die Migration überschreibt keine vorhandenen Daten.')
    target.parent.mkdir(parents=True, exist_ok=True)
    # WAL databases can require a writable shared-memory index even for reads.
    # Copy the stopped source and its WAL into private temporary storage; SQLite
    # can recover and checkpoint this copy without writing to the source volume.
    with tempfile.TemporaryDirectory(prefix='appdashboard-source-') as snapshot:
        snapshot_db = Path(snapshot) / 'dashboard.sqlite3'
        shutil.copyfile(source, snapshot_db)
        source_wal = Path(str(source) + '-wal')
        if source_wal.exists():
            shutil.copyfile(source_wal, Path(str(snapshot_db) + '-wal'))
        with closing(sqlite3.connect(snapshot_db)) as original:
            if original.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Die Quell-Datenbank ist beschädigt.')
            tables = {row[0] for row in original.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'apps', 'config', 'login_attempts'}.issubset(tables):
                raise ValueError('Die Quelle ist keine AppDashboard-Datenbank.')
            with tempfile.TemporaryDirectory(prefix='.migration-', dir=target.parent) as temporary:
                staged = Path(temporary) / 'dashboard.sqlite3'
                with closing(sqlite3.connect(staged)) as destination:
                    original.backup(destination)
                    if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('Die kopierte Datenbank ist ungültig.')
                    count = destination.execute('SELECT COUNT(*) FROM apps').fetchone()[0]
                staged.chmod(0o600)
                # Atomic creation; a concurrently created target cannot be overwritten.
                os.link(staged, target)
    return count


def main():
    parser = argparse.ArgumentParser(description='AppDashboard-Datenbank in ein leeres Ziel kopieren.')
    parser.add_argument('--source', default='/source/dashboard.sqlite3')
    parser.add_argument('--target', default='/data/dashboard.sqlite3')
    args = parser.parse_args()
    try:
        count = copy_database(args.source, args.target)
    except (ValueError, sqlite3.Error, OSError) as exc:
        parser.exit(1, f'Migration fehlgeschlagen: {exc}\n')
    print(f'Migration abgeschlossen: {count} Einträge, Logos und Sitzungsschlüssel übernommen.')


if __name__ == '__main__':
    main()
