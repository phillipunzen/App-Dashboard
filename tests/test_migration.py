import hashlib
import pickle
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app import create_app
from app.migrate import copy_database


def snapshot(path):
    with closing(sqlite3.connect(path)) as db:
        return hashlib.sha256(pickle.dumps([
            db.execute('SELECT * FROM apps ORDER BY id').fetchall(),
            db.execute('SELECT * FROM config ORDER BY key').fetchall(),
        ], protocol=4)).hexdigest()


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source' / 'dashboard.sqlite3'
        self.target = self.root / 'target' / 'dashboard.sqlite3'
        create_app({'TESTING': True, 'DATABASE': str(self.source), 'ADMIN_PASSWORD': 'migration-test-password-only'})
        with closing(sqlite3.connect(self.source)) as db:
            db.execute('INSERT INTO apps (name,url,description,category,color,icon) VALUES (?,?,?,?,?,?)',
                       ('Meine Cloud', 'https://cloud.example.org/', 'Dateien und Fotos', 'Privat', 'teal', b'cached-logo-bytes'))
            db.commit()

    def tearDown(self):
        self.temporary.cleanup()

    def test_migration_preserves_records_logos_and_session_key(self):
        before = snapshot(self.source)
        self.assertEqual(copy_database(self.source, self.target), 1)
        self.assertEqual(snapshot(self.target), before)
        self.assertEqual(snapshot(self.source), before)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)

    def test_uncheckpointed_wal_records_are_preserved(self):
        with closing(sqlite3.connect(self.source)) as writer:
            writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute('INSERT INTO apps(name,url) VALUES(?,?)', ('Noch im WAL', 'https://wal.example.org/'))
            writer.commit()
            wal = Path(str(self.source) + '-wal')
            self.assertTrue(wal.exists())
            source_bytes = self.source.read_bytes()
            wal_bytes = wal.read_bytes()
            self.assertEqual(copy_database(self.source, self.target), 2)
            self.assertEqual(self.source.read_bytes(), source_bytes)
            self.assertEqual(wal.read_bytes(), wal_bytes)
            with closing(sqlite3.connect(self.target)) as target:
                names = {row[0] for row in target.execute('SELECT name FROM apps')}
            self.assertEqual(names, {'Meine Cloud', 'Noch im WAL'})

    def test_existing_target_is_never_overwritten(self):
        self.target.parent.mkdir()
        self.target.write_bytes(b'existing-data')
        with self.assertRaises(ValueError):
            copy_database(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b'existing-data')

    def test_migration_rejects_source_as_target(self):
        before = snapshot(self.source)
        with self.assertRaises(ValueError):
            copy_database(self.source, self.source)
        self.assertEqual(snapshot(self.source), before)

    def test_invalid_source_does_not_create_target(self):
        invalid = self.root / 'invalid.sqlite3'
        with closing(sqlite3.connect(invalid)) as db:
            db.execute('CREATE TABLE unrelated (id INTEGER)')
        with self.assertRaises(ValueError):
            copy_database(invalid, self.target)
        self.assertFalse(self.target.exists())


if __name__ == '__main__':
    unittest.main()
