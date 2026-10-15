import base64
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
import time
from contextlib import closing
from datetime import timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, abort, g, jsonify, render_template, request, send_file, session
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from .metadata import decode_icon, discover, normalize_url


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        DATABASE=os.environ.get('DATABASE_PATH', '/data/dashboard.sqlite3'),
        ADMIN_USERNAME=os.environ.get('ADMIN_USERNAME', 'admin'),
        ADMIN_PASSWORD=os.environ.get('ADMIN_PASSWORD', ''),
        SESSION_COOKIE_SECURE=os.environ.get('SECURE_COOKIE', 'true').lower() == 'true',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MAX_CONTENT_LENGTH=512_000,
        ALLOW_PRIVATE_METADATA=os.environ.get('ALLOW_PRIVATE_METADATA', 'false').lower() == 'true',
        DASHBOARD_TITLE=os.environ.get('DASHBOARD_TITLE', 'App Dashboard')[:60],
        PUBLIC_ORIGIN=os.environ.get('PUBLIC_ORIGIN', '').rstrip('/'),
    )
    password_file = os.environ.get('ADMIN_PASSWORD_FILE')
    if password_file:
        app.config['ADMIN_PASSWORD'] = Path(password_file).read_text().strip()
    if test_config:
        app.config.update(test_config)
    password = app.config['ADMIN_PASSWORD']
    if len(password) < 12:
        raise RuntimeError('ADMIN_PASSWORD muss gesetzt sein und mindestens 12 Zeichen haben (alternativ ADMIN_PASSWORD_FILE).')
    app.config['ADMIN_HASH'] = generate_password_hash(password)
    app.config['AUTH_VERSION'] = hashlib.sha256(password.encode()).hexdigest()
    app.config.pop('ADMIN_PASSWORD')
    proxy_hops = int(os.environ.get('TRUSTED_PROXY_HOPS', '0'))
    if proxy_hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_hops, x_proto=proxy_hops, x_host=0)

    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(app.config['DATABASE'], timeout=10)) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS apps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, url TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '', color TEXT NOT NULL DEFAULT 'teal',
                icon BLOB, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
            CREATE TABLE IF NOT EXISTS login_attempts (address TEXT NOT NULL, attempted_at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS login_time ON login_attempts(attempted_at);
        ''')
        db.execute('INSERT OR IGNORE INTO config VALUES (?, ?)', ('secret', secrets.token_hex(32)))
        app.secret_key = db.execute('SELECT value FROM config WHERE key=?', ('secret',)).fetchone()[0]
        db.commit()

    def database():
        if 'db' not in g:
            g.db = sqlite3.connect(app.config['DATABASE'], timeout=10)
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_database(_):
        db = g.pop('db', None)
        if db is not None:
            db.close()

    def is_admin():
        return session.get('admin') is True and hmac.compare_digest(session.get('version', ''), app.config['AUTH_VERSION'])

    def admin_required(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not is_admin():
                abort(401, description='Bitte zuerst als Admin anmelden.')
            return fn(*args, **kwargs)
        return wrapped

    @app.before_request
    def check_csrf():
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            expected = session.get('csrf', '')
            supplied = request.headers.get('X-CSRF-Token', '')
            if not expected or not hmac.compare_digest(expected, supplied):
                abort(403, description='Die Sitzung ist abgelaufen. Bitte lade die Seite neu.')
            origin = request.headers.get('Origin')
            expected_origin = app.config['PUBLIC_ORIGIN'] or request.host_url.rstrip('/')
            if origin and origin != expected_origin:
                abort(403, description='Die Anfrage stammt von einer anderen Website.')

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error=exc.description), exc.code

    @app.errorhandler(ValueError)
    def validation_error(exc):
        return jsonify(error=str(exc)), 400

    @app.get('/')
    def index():
        apps = [serialize(row) for row in database().execute('SELECT * FROM apps ORDER BY name COLLATE NOCASE, id')]
        return render_template('public.html', title=app.config['DASHBOARD_TITLE'], apps=apps)

    @app.get('/admin')
    @app.get('/admin/')
    def admin():
        return render_template('index.html', title=app.config['DASHBOARD_TITLE'])

    @app.get('/healthz')
    def health():
        database().execute('SELECT 1').fetchone()
        return jsonify(status='ok')

    @app.get('/api/session')
    def current_session():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_urlsafe(32)
        return jsonify(admin=is_admin(), csrf=session['csrf'], title=app.config['DASHBOARD_TITLE'])

    @app.post('/api/login')
    def login():
        db = database()
        now = time.time()
        address = request.remote_addr or 'unknown'
        # Reserve the attempt in a write transaction, including concurrent requests.
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM login_attempts WHERE attempted_at < ?', (now - 900,))
        count = db.execute('SELECT COUNT(*) FROM login_attempts WHERE address=?', (address,)).fetchone()[0]
        if count >= 8:
            db.commit()
            abort(429, description='Zu viele Anmeldeversuche. Bitte in 15 Minuten erneut versuchen.')
        db.execute('INSERT INTO login_attempts VALUES (?, ?)', (address, now))
        db.commit()
        data = request.get_json()
        if not isinstance(data, dict):
            abort(400, description='Ungültige Anfrage.')
        username, password = data.get('username', ''), data.get('password', '')
        valid_password = isinstance(password, str) and len(password) <= 1024 and check_password_hash(app.config['ADMIN_HASH'], password)
        if not (valid_password and username == app.config['ADMIN_USERNAME']):
            abort(401, description='Benutzername oder Passwort ist falsch.')
        db.execute('DELETE FROM login_attempts WHERE address=?', (address,))
        db.commit()
        session.clear()
        session.permanent = True
        session.update(admin=True, version=app.config['AUTH_VERSION'], csrf=secrets.token_urlsafe(32))
        return jsonify(admin=True, csrf=session['csrf'])

    @app.post('/api/logout')
    def logout():
        session.clear()
        session['csrf'] = secrets.token_urlsafe(32)
        return jsonify(admin=False, csrf=session['csrf'])

    def serialize(row):
        data = dict(row)
        icon = data.pop('icon')
        data['icon_url'] = f"/api/apps/{data['id']}/icon?v={hashlib.sha256(icon).hexdigest()[:12]}" if icon else None
        return data

    @app.get('/api/apps')
    def list_apps():
        return jsonify(apps=[serialize(row) for row in database().execute('SELECT * FROM apps ORDER BY name COLLATE NOCASE, id')])

    @app.get('/api/apps/<int:app_id>/icon')
    def get_icon(app_id):
        row = database().execute('SELECT icon FROM apps WHERE id=?', (app_id,)).fetchone()
        if not row or not row['icon']:
            abort(404)
        return send_file(io.BytesIO(row['icon']), mimetype='image/png', max_age=86400, etag=hashlib.sha256(row['icon']).hexdigest())

    def app_data():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError('Ungültige Anfrage.')
        fields = {}
        for field, limit in (('name', 100), ('description', 500), ('category', 40)):
            value = data.get(field, '')
            if not isinstance(value, str) or len(value.strip()) > limit:
                raise ValueError(f'{field}: maximal {limit} Zeichen erlaubt.')
            fields[field] = value.strip()
        if not fields['name']:
            raise ValueError('Bitte einen Namen eingeben.')
        fields['url'] = normalize_url(data.get('url', ''))
        color = data.get('color', 'teal')
        if color not in ('teal', 'blue', 'purple', 'orange', 'rose', 'slate'):
            raise ValueError('Ungültige Farbe.')
        fields['color'] = color
        return fields, decode_icon(data.get('icon')) if 'icon' in data else None, 'icon' in data

    @app.post('/api/apps')
    @admin_required
    def add_app():
        fields, icon, _ = app_data()
        db = database()
        cursor = db.execute(
            'INSERT INTO apps (name,description,category,url,color,icon) VALUES (?,?,?,?,?,?)',
            (fields['name'], fields['description'], fields['category'], fields['url'], fields['color'], icon))
        db.commit()
        return jsonify(app=serialize(db.execute('SELECT * FROM apps WHERE id=?', (cursor.lastrowid,)).fetchone())), 201

    @app.put('/api/apps/<int:app_id>')
    @admin_required
    def update_app(app_id):
        fields, icon, has_icon = app_data()
        db = database()
        row = db.execute('SELECT * FROM apps WHERE id=?', (app_id,)).fetchone()
        if not row:
            abort(404, description='Dieser Eintrag existiert nicht mehr.')
        db.execute("UPDATE apps SET name=?,description=?,category=?,url=?,color=?,icon=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                   (fields['name'], fields['description'], fields['category'], fields['url'], fields['color'],
                    icon if has_icon else row['icon'], app_id))
        db.commit()
        return jsonify(app=serialize(db.execute('SELECT * FROM apps WHERE id=?', (app_id,)).fetchone()))

    @app.delete('/api/apps/<int:app_id>')
    @admin_required
    def delete_app(app_id):
        db = database()
        cursor = db.execute('DELETE FROM apps WHERE id=?', (app_id,))
        db.commit()
        if not cursor.rowcount:
            abort(404, description='Dieser Eintrag existiert nicht mehr.')
        return '', 204

    @app.post('/api/metadata')
    @admin_required
    def metadata():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError('Ungültige Anfrage.')
        return jsonify(discover(data.get('url', ''), app.config['ALLOW_PRIVATE_METADATA']))

    @app.get('/api/export')
    @admin_required
    def export():
        records = []
        for row in database().execute('SELECT * FROM apps ORDER BY id'):
            data = dict(row)
            data['icon'] = base64.b64encode(data['icon']).decode() if data['icon'] else None
            records.append(data)
        raw = json.dumps({'version': 1, 'apps': records}, ensure_ascii=False, indent=2).encode()
        return send_file(io.BytesIO(raw), mimetype='application/json', as_attachment=True, download_name='apphafen-export.json')

    return app
