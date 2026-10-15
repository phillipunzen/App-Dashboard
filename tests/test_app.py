import base64
import gzip
import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from app import create_app
from app.metadata import FetchError, clean_icon, discover, fetch, normalize_url, resolve_target

PASSWORD = 'test-password-very-long'


def png():
    output = io.BytesIO()
    Image.new('RGB', (24, 24), '#087f73').save(output, 'PNG')
    return output.getvalue()


class AppTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.config = {'TESTING': True, 'DATABASE': self.directory.name + '/test.sqlite3',
                       'ADMIN_PASSWORD': PASSWORD, 'SESSION_COOKIE_SECURE': False}
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self.token = self.client.get('/api/session').json['csrf']

    def tearDown(self):
        self.directory.cleanup()

    def write(self, path, data=None, method='post', **kwargs):
        return getattr(self.client, method)(path, json=data, headers={'X-CSRF-Token': self.token}, **kwargs)

    def login(self):
        result = self.write('/api/login', {'username': 'admin', 'password': PASSWORD})
        self.assertEqual(result.status_code, 200)
        self.token = result.json['csrf']
        return result

    def new_app(self, **overrides):
        return self.write('/api/apps', {'name': 'Meine Cloud', 'url': 'https://cloud.example.org',
                                        'description': 'Dateien und Fotos', 'category': 'Produktivität', **overrides})

    def test_public_overview_and_protected_writes(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/api/apps').json, {'apps': []})
        self.assertEqual(self.new_app().status_code, 401)
        self.assertEqual(self.write('/api/metadata', {'url': 'https://example.org'}).status_code, 401)
        self.assertEqual(self.client.get('/api/export').status_code, 401)

    def test_public_page_is_reduced_even_for_admins(self):
        self.login()
        self.new_app(name='Cloud <Test>', description='Dateien & Fotos')
        result = self.client.get('/')
        self.assertIn(b'Cloud &lt;Test&gt;', result.data)
        self.assertIn(b'Dateien &amp; Fotos', result.data)
        self.assertIn(b'http', result.data)
        self.assertIn(b'target="_blank"', result.data)
        self.assertNotIn(b'id="sidebar"', result.data)
        self.assertNotIn(b'class="stats"', result.data)
        self.assertNotIn(b'data-action="add"', result.data)
        self.assertNotIn(b'<dialog', result.data)
        self.assertNotIn(b'/static/app.js', result.data)

    def test_admin_page_has_separate_entry_point(self):
        result = self.client.get('/admin')
        self.assertEqual(result.status_code, 200)
        self.assertIn(b'id="login-dialog"', result.data)
        self.assertIn(b'/static/app.js', result.data)
        self.assertEqual(self.client.get('/admin/').status_code, 200)

    def test_csrf_and_origin_are_required_for_writes(self):
        self.assertEqual(self.client.post('/api/login', json={}).status_code, 403)
        result = self.client.post('/api/login', json={}, headers={'X-CSRF-Token': self.token, 'Origin': 'https://evil.example'})
        self.assertEqual(result.status_code, 403)
        self.app.config['PUBLIC_ORIGIN'] = 'https://apps.example.org'
        result = self.client.post('/api/login', json={'username': 'admin', 'password': PASSWORD},
                                  headers={'X-CSRF-Token': self.token, 'Origin': 'https://apps.example.org'})
        self.assertEqual(result.status_code, 200)

    def test_login_rotates_token_logout_revokes_permissions(self):
        old_token = self.token
        self.login()
        self.assertNotEqual(old_token, self.token)
        self.assertTrue(self.client.get('/api/session').json['admin'])
        self.assertEqual(self.new_app().status_code, 201)
        self.assertEqual(self.write('/api/logout').status_code, 200)
        self.token = self.client.get('/api/session').json['csrf']
        self.assertEqual(self.new_app().status_code, 401)

    def test_login_limiter_survives_new_process(self):
        for _ in range(8):
            self.assertEqual(self.write('/api/login', {'username': 'admin', 'password': 'wrong'}).status_code, 401)
        self.assertEqual(self.write('/api/login', {'username': 'admin', 'password': PASSWORD}).status_code, 429)
        another = create_app(self.config).test_client()
        token = another.get('/api/session').json['csrf']
        self.assertEqual(another.post('/api/login', json={'username': 'admin', 'password': PASSWORD},
                                     headers={'X-CSRF-Token': token}).status_code, 429)

    def test_crud_and_icon_preservation(self):
        self.login()
        image = base64.b64encode(png()).decode()
        response = self.new_app(icon=image, color='blue')
        self.assertEqual(response.status_code, 201)
        entry = response.json['app']
        self.assertEqual(entry['url'], 'https://cloud.example.org/')
        self.assertNotIn('icon', entry)
        icon_response = self.client.get(entry['icon_url'])
        self.assertEqual(icon_response.status_code, 200)
        self.assertEqual(icon_response.mimetype, 'image/png')
        response = self.write(f"/api/apps/{entry['id']}", {'name': 'Neue Cloud', 'url': entry['url'], 'category': 'Privat'}, method='put')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['app']['icon_url'], entry['icon_url'])
        self.assertEqual(self.client.get('/api/apps').json['apps'][0]['name'], 'Neue Cloud')
        response = self.write(f"/api/apps/{entry['id']}", {'name': 'Neue Cloud', 'url': entry['url'], 'icon': None}, method='put')
        self.assertIsNone(response.json['app']['icon_url'])
        self.assertEqual(self.write(f"/api/apps/{entry['id']}", method='delete').status_code, 204)
        self.assertEqual(self.client.get('/api/apps').json['apps'], [])
        self.assertEqual(self.write(f"/api/apps/{entry['id']}", method='delete').status_code, 404)

    def test_validation(self):
        self.login()
        for fields in ({'name': ''}, {'url': 'javascript:alert(1)'}, {'url': 'ftp://example.org'},
                       {'url': 'https://user:pass@example.org'}, {'color': '<script>'},
                       {'name': 'x' * 101}, {'icon': '<svg onload=alert(1)>'}, {'category': []}):
            with self.subTest(fields=fields):
                self.assertEqual(self.new_app(**fields).status_code, 400)
        self.assertEqual(self.write('/api/apps', []).status_code, 400)

    def test_persistence_and_password_rotation(self):
        self.login()
        self.new_app()
        cookie = self.client.get_cookie('session').value
        another = create_app(self.config).test_client()
        another.set_cookie('session', cookie)
        self.assertEqual(len(another.get('/api/apps').json['apps']), 1)
        self.assertTrue(another.get('/api/session').json['admin'])
        rotated = create_app({**self.config, 'ADMIN_PASSWORD': 'changed-password-very-long'}).test_client()
        rotated.set_cookie('session', cookie)
        self.assertFalse(rotated.get('/api/session').json['admin'])

    def test_export_roundtrip_contains_logo(self):
        self.login()
        self.new_app(icon=base64.b64encode(png()).decode())
        result = self.client.get('/api/export')
        self.assertIn('attachment', result.headers['Content-Disposition'])
        data = json.loads(result.data)
        self.assertEqual(data['version'], 1)
        self.assertEqual(data['apps'][0]['name'], 'Meine Cloud')
        Image.open(io.BytesIO(base64.b64decode(data['apps'][0]['icon']))).verify()

    def test_security_headers_and_escaped_title(self):
        self.app.config['DASHBOARD_TITLE'] = '<script>alert(1)</script>'
        result = self.client.get('/')
        self.assertNotIn(b'<script>alert(1)</script>', result.data)
        self.assertIn('frame-ancestors', result.headers['Content-Security-Policy'])
        self.assertEqual(result.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(self.client.get('/api/apps').headers['Cache-Control'], 'no-store')

    def test_short_password_refused(self):
        with self.assertRaises(RuntimeError):
            create_app({**self.config, 'ADMIN_PASSWORD': 'short'})

    def test_backup_and_restore_roundtrip(self):
        self.login()
        self.new_app(icon=base64.b64encode(png()).decode())
        env = {**os.environ, 'DATABASE_PATH': self.config['DATABASE']}
        backup = subprocess.run([sys.executable, '-m', 'app.backup'], env=env, check=True, capture_output=True).stdout
        # A restore replaces the modified collection with the saved collection.
        self.new_app(name='Nicht in der Sicherung')
        subprocess.run([sys.executable, '-m', 'app.backup', '--restore'], env=env,
                       input=backup, check=True, capture_output=True)
        apps = self.client.get('/api/apps').json['apps']
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]['name'], 'Meine Cloud')
        self.assertEqual(self.client.get(apps[0]['icon_url']).mimetype, 'image/png')

    def test_invalid_restore_preserves_database(self):
        self.login()
        self.new_app()
        result = subprocess.run([sys.executable, '-m', 'app.backup', '--restore'],
                                env={**os.environ, 'DATABASE_PATH': self.config['DATABASE']},
                                input=b'not a database', capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.client.get('/api/apps').json['apps']), 1)

    @patch('app.discover')
    def test_metadata_requires_login_and_uses_policy(self, discover_mock):
        self.login()
        discover_mock.return_value = {'name': 'Test', 'icon': None}
        self.assertEqual(self.write('/api/metadata', {'url': 'https://example.org'}).json['name'], 'Test')
        discover_mock.assert_called_with('https://example.org', False)


class MetadataTests(unittest.TestCase):
    @patch('app.metadata.PinnedHTTPConnection')
    @patch('app.metadata.resolve_target', return_value='93.184.216.34')
    def test_compressed_html_is_decoded(self, _, connection):
        raw = b'<html><title>Compressed application</title></html>'
        response = connection.return_value.getresponse.return_value
        response.status = 200
        response.getheader.side_effect = lambda key, default='': {
            'Content-Type': 'text/html', 'Content-Encoding': 'gzip',
        }.get(key, default)
        response.read1.side_effect = [gzip.compress(raw), b'']
        result, _, _ = fetch('http://example.org')
        self.assertEqual(result, raw)
        self.assertEqual(connection.call_args.args[2], '93.184.216.34')

    @patch('app.metadata.PinnedHTTPConnection')
    @patch('app.metadata.resolve_target', return_value='93.184.216.34')
    def test_decompression_cannot_bypass_size_limit(self, _, connection):
        response = connection.return_value.getresponse.return_value
        response.status = 200
        response.getheader.side_effect = lambda key, default='': {
            'Content-Type': 'text/html', 'Content-Encoding': 'gzip',
        }.get(key, default)
        response.read1.side_effect = [gzip.compress(b'x' * 10000), b'']
        with self.assertRaises(FetchError):
            fetch('http://example.org', limit=1000)

    def test_url_normalization(self):
        self.assertEqual(normalize_url('example.org'), 'https://example.org/')
        self.assertEqual(normalize_url('http://[::1]:1234/a'), 'http://[::1]:1234/a')
        self.assertIn('xn--', normalize_url('https://bücher.example'))
        for value in ('', 'file:///etc/passwd', 'https://a\r\nb', 'https://user@host', 'https://a:99999', 'https://a\\b', 'https://a:0'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_url(value)

    def test_private_and_metadata_addresses_blocked(self):
        for address in ('127.0.0.1', '169.254.169.254', '10.0.0.1', '192.168.1.1', '::1', 'fc00::1', '0.0.0.0', '::ffff:127.0.0.1'):
            with self.subTest(address=address), patch('app.metadata.socket.getaddrinfo', return_value=[(socket.AF_INET, 1, 6, '', (address, 80))]):
                with self.assertRaises(FetchError):
                    resolve_target('test', 80, False)
        for address in ('127.0.0.1', '169.254.169.254', '::1', '0.0.0.0'):
            with self.subTest(address=address), patch('app.metadata.socket.getaddrinfo', return_value=[(socket.AF_INET, 1, 6, '', (address, 80))]):
                with self.assertRaises(FetchError):
                    resolve_target('test', 80, True)
        with patch('app.metadata.socket.getaddrinfo', return_value=[(socket.AF_INET, 1, 6, '', ('192.168.1.1', 80))]):
            self.assertEqual(resolve_target('test', 80, True), '192.168.1.1')

    def test_mixed_dns_answers_cannot_bypass_filter(self):
        addresses = [(socket.AF_INET, 1, 6, '', (ip, 80)) for ip in ('93.184.216.34', '127.0.0.1')]
        with patch('app.metadata.socket.getaddrinfo', return_value=addresses), self.assertRaises(FetchError):
            resolve_target('test', 80, False)

    @patch('app.metadata.PinnedHTTPConnection')
    @patch('app.metadata.socket.getaddrinfo')
    def test_redirects_recheck_network_policy(self, dns, connection):
        dns.side_effect = [[(socket.AF_INET, 1, 6, '', (ip, 80))] for ip in ('93.184.216.34', '127.0.0.1')]
        response = connection.return_value.getresponse.return_value
        response.status = 302
        response.getheader.return_value = 'http://127.0.0.1/admin'
        with self.assertRaises(FetchError):
            fetch('http://example.org')
        self.assertEqual(connection.call_count, 1)

    @patch('app.metadata.fetch')
    def test_metadata_with_relative_favicon_and_og_description(self, fetch_mock):
        fetch_mock.side_effect = [
            (b'<html><head><title>Meine App</title><meta property="og:description" content="Mein Werkzeug"><link rel="icon" href="assets/logo.png"></head></html>', 'text/html', 'https://example.org/tool/'),
            (png(), 'image/png', 'https://example.org/tool/assets/logo.png'),
        ]
        result = discover('https://example.org/tool/')
        self.assertEqual(result['name'], 'Meine App')
        self.assertEqual(result['description'], 'Mein Werkzeug')
        self.assertIsNotNone(result['icon'])
        self.assertIsNone(result['warning'])
        self.assertEqual(fetch_mock.call_args_list[1].args[0], 'https://example.org/tool/assets/logo.png')

    @patch('app.metadata.fetch', side_effect=FetchError('offline'))
    def test_unreachable_app_has_manual_fallback(self, _):
        result = discover('https://offline.example.org')
        self.assertEqual(result['name'], 'offline.example.org')
        self.assertIsNotNone(result['warning'])

    def test_icons_normalized_and_active_content_rejected(self):
        result = clean_icon(png())
        self.assertEqual(Image.open(io.BytesIO(result)).format, 'PNG')
        for image in (b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>', b'not an image'):
            with self.assertRaises(ValueError):
                clean_icon(image)


if __name__ == '__main__':
    unittest.main()
