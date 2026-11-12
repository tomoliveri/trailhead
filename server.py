#!/usr/bin/env python3
"""Trailhead (garmin.ttnt.cloud): static web app + a small JSON API.

The plan itself is computed in the runner's browser. This process only:
  * stores each plan under an unguessable link (/p/<slug>; writes need the plan's key),
  * pairs a Trailhead Coach watch (code shown on the watch) with a plan, serves its daily sync and takes uploads,
  * relays Garmin Connect calls. Credentials and tokens pass through in memory only; nothing Garmin-related is
    stored or logged. A pending two-step sign-in is held in memory for at most 5 minutes.
"""
import datetime as dt
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, 'web')
DB = os.path.join(ROOT, 'data', 'trailhead.db')
PORT = int(os.environ.get('PORT', '3041'))
MAX_BODY = 3 * 1024 * 1024
SLUG = re.compile(r'^[a-z0-9]{12,32}$')
CODE = re.compile(r'^[A-Z0-9]{8}$')

mimetypes.add_type('application/wasm', '.wasm')
mimetypes.add_type('text/javascript', '.mjs')
mimetypes.add_type('application/manifest+json', '.webmanifest')

_local = threading.local()


def init_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=10)
    c.execute('PRAGMA journal_mode=WAL')
    c.executescript('''
        CREATE TABLE IF NOT EXISTS plans (slug TEXT PRIMARY KEY, key_hash TEXT NOT NULL, state TEXT, bundle TEXT,
            tz TEXT, created REAL, updated REAL);
        CREATE TABLE IF NOT EXISTS pairs (code TEXT PRIMARY KEY, slug TEXT NOT NULL, created REAL);
        CREATE TABLE IF NOT EXISTS inbox (id INTEGER PRIMARY KEY, slug TEXT NOT NULL, client_id TEXT,
            body TEXT NOT NULL, created REAL);
        CREATE UNIQUE INDEX IF NOT EXISTS inbox_client ON inbox(slug, client_id);
        CREATE TABLE IF NOT EXISTS sent (k TEXT PRIMARY KEY, at REAL);
    ''')
    c.close()


def db():
    c = getattr(_local, 'c', None)
    if c is None:
        c = sqlite3.connect(DB, timeout=10)
        c.row_factory = sqlite3.Row
        _local.c = c
    return c


def close_db():
    # one connection per request: a leaked one with an open write transaction locks every other writer
    c = getattr(_local, 'c', None)
    if c is not None:
        _local.c = None
        if c.in_transaction:
            c.rollback()
        c.close()


def khash(key):
    return hashlib.sha256(('trailhead:' + key).encode()).hexdigest()


# ------------------------------------------------------------------ rate limiting (per client IP, in memory)

_buckets = {}
_blk = threading.Lock()


def allow(ip, kind, per_min):
    now = time.time()
    with _blk:
        b = _buckets.setdefault((ip, kind), [per_min, now])
        b[0] = min(per_min, b[0] + (now - b[1]) * per_min / 60)
        b[1] = now
        if b[0] < 1:
            return False
        b[0] -= 1
        if len(_buckets) > 20000:
            _buckets.clear()
        return True


# ------------------------------------------------------------------ Garmin relay (stateless)

_mfa = {}       # id -> (Garmin client mid-login, expiry)
_mfa_lock = threading.Lock()

# Read-only calls the app may make: name -> (garminconnect method, allowed argument names)
GARMIN_CALLS = {
    'profile': ('get_user_profile', ()),
    'activities': ('get_activities_by_date', ('startdate', 'enddate')),
    'stats': ('get_stats', ('cdate',)),
    'hrv': ('get_hrv_data', ('cdate',)),
    'sleep': ('get_sleep_data', ('cdate',)),
    'max_metrics': ('get_max_metrics', ('cdate',)),
    'race_predictions': ('get_race_predictions', ()),
    'personal_records': ('get_personal_record', ()),
}


def _garmin():
    from garminconnect import Garmin
    return Garmin


def garmin_login(body):
    email, password = str(body.get('email') or ''), str(body.get('password') or '')
    if not email or not password:
        return 400, {'error': 'Email and password are required.'}
    g = _garmin()(email=email, password=password, return_on_mfa=True)
    try:
        status, _ = g.login()
    except Exception as e:   # never echo credentials; the library's messages don't contain them
        return 401, {'error': _garmin_error(e)}
    if status == 'needs_mfa':
        mid = secrets.token_urlsafe(18)
        with _mfa_lock:
            _gc_mfa()
            _mfa[mid] = (g, time.time() + 300)
        return 200, {'mfa': mid}
    return 200, {'tokens': g.client.dumps()}


def garmin_mfa(body):
    mid, code = str(body.get('mfa') or ''), str(body.get('code') or '').strip()
    with _mfa_lock:
        _gc_mfa()
        g, _ = _mfa.pop(mid, (None, 0))
    if not g:
        return 410, {'error': 'That sign-in expired. Start again.'}
    try:
        g.resume_login(None, code)
    except Exception as e:
        return 401, {'error': _garmin_error(e)}
    return 200, {'tokens': g.client.dumps()}


def garmin_call(body):
    name = str(body.get('call') or '')
    if name not in GARMIN_CALLS:
        return 400, {'error': 'Unknown call.'}
    tokens = body.get('tokens')
    if not isinstance(tokens, str) or len(tokens) > 20000:
        return 400, {'error': 'Sign in to Garmin first.'}
    meth, names = GARMIN_CALLS[name]
    args = body.get('args') or {}
    kwargs = {k: str(args[k])[:32] for k in names if k in args}
    g = _garmin()()
    try:
        g.login(tokenstore=tokens)
        data = getattr(g, meth)(**kwargs)
    except Exception as e:
        return 401, {'error': _garmin_error(e)}
    return 200, {'data': data, 'tokens': g.client.dumps()}


def _gc_mfa():
    now = time.time()
    for k in [k for k, (_, exp) in _mfa.items() if exp < now]:
        _mfa.pop(k, None)


def _garmin_error(e):
    n = type(e).__name__
    if 'Auth' in n:
        return 'Garmin did not accept that sign-in. Check the email and password.'
    if 'TooManyRequests' in n or '429' in str(e):
        return 'Garmin is rate-limiting sign-ins right now. Wait a few minutes and try again.'
    return 'Garmin Connect could not be reached. Try again shortly.'


# ------------------------------------------------------------------ plans + watch

def create_plan(body):
    slug = secrets.token_hex(8)
    key = secrets.token_urlsafe(24)
    now = time.time()
    db().execute('INSERT INTO plans VALUES (?,?,?,?,?,?,?)',
                 (slug, khash(key), json.dumps(body.get('state') or {}), json.dumps(body.get('bundle') or {}),
                  str(body.get('tz') or 'UTC')[:64], now, now))
    db().commit()
    return 201, {'slug': slug, 'key': key}


def plan_row(slug):
    if not SLUG.match(slug or ''):
        return None
    return db().execute('SELECT * FROM plans WHERE slug=?', (slug,)).fetchone()


def check_key(row, key):
    return row is not None and isinstance(key, str) and hmac.compare_digest(row['key_hash'], khash(key))


def put_plan(slug, body, key):
    row = plan_row(slug)
    if not check_key(row, key):
        return 403, {'error': 'This browser cannot change that plan.'}
    db().execute('UPDATE plans SET state=?, bundle=?, tz=?, updated=? WHERE slug=?',
                 (json.dumps(body.get('state') or {}), json.dumps(body.get('bundle') or {}),
                  str(body.get('tz') or row['tz'])[:64], time.time(), slug))
    db().commit()
    return 200, {'ok': True}


def get_plan(slug):
    row = plan_row(slug)
    if row is None:
        return 404, {'error': 'No plan at that link.'}
    paired = [r['code'] for r in db().execute('SELECT code FROM pairs WHERE slug=?', (slug,))]
    return 200, {'state': json.loads(row['state'] or '{}'), 'updated': row['updated'], 'watches': len(paired)}


def pair(slug, body, key):
    row = plan_row(slug)
    if not check_key(row, key):
        return 403, {'error': 'This browser cannot change that plan.'}
    code = re.sub(r'[^A-Z0-9]', '', str(body.get('code') or '').upper())
    if not CODE.match(code):
        return 400, {'error': 'The code on the watch has 8 letters and numbers.'}
    db().execute('INSERT OR REPLACE INTO pairs VALUES (?,?,?)', (code, slug, time.time()))
    db().commit()
    return 200, {'ok': True}


def inbox(slug, key, ack=None):
    row = plan_row(slug)
    if not check_key(row, key):
        return 403, {'error': 'This browser cannot read that plan’s uploads.'}
    if ack:
        db().executemany('DELETE FROM inbox WHERE slug=? AND id=?', [(slug, int(i)) for i in ack])
        db().commit()
    items = [{'id': r['id'], 'activity': json.loads(r['body'])}
             for r in db().execute('SELECT id, body FROM inbox WHERE slug=? ORDER BY id', (slug,))]
    return 200, {'items': items}


def watch_slug(auth):
    code = re.sub(r'[^A-Z0-9]', '', (auth or '').replace('Bearer', '').upper())
    if not CODE.match(code):
        return code, None
    r = db().execute('SELECT slug FROM pairs WHERE code=?', (code,)).fetchone()
    return code, (r['slug'] if r else None)


def watch_sync(auth, query):
    code, slug = watch_slug(auth)
    if not slug:
        return 404, {'pair': code}
    row = plan_row(slug)
    try:
        zone = ZoneInfo(row['tz'] or 'UTC')
    except Exception:
        zone = ZoneInfo('UTC')
    now = dt.datetime.now(zone)
    bundle = json.loads(row['bundle'] or '{}')
    day = now.date().isoformat()
    p = bundle.get(day)
    if p is None:   # plan not refreshed for a while: say so instead of showing an old day
        return 200, {'today': None, 'tasks': [], 'wk': [], 'stale': 1, 'race': '', 'cd': 0, 'tot': 0, 'now': int(now.timestamp())}
    p = dict(p)
    done = {json.loads(r['body']).get('sport') for r in db().execute(
        'SELECT body FROM inbox WHERE slug=? AND created>=?', (slug, now.replace(hour=0, minute=0, second=0).timestamp()))}
    hhmm = now.strftime('%H:%M')
    for t in p.get('tasks', []):
        want = t.pop('want', None)
        t['d'] = bool(want and (want in done or (want == 'run' and done & {'run', 'trail', 'treadmill'})))
        if t['at'] and t['at'] <= hhmm and not t['d']:
            t['at'] = 'NOW'
    p['now'] = int(now.timestamp())
    preview = p.pop('preview', None)
    if query.get('face') != '1' and preview and 10 <= now.hour < 22:
        at = now.replace(hour=20, minute=0, second=0, microsecond=0)
        k = f'{code}:{day}:preview'
        if at <= now < at + dt.timedelta(minutes=30):
            try:
                db().execute('INSERT INTO sent VALUES (?,?)', (k, time.time()))
                db().commit()
                p['n'] = preview
            except sqlite3.IntegrityError:
                db().rollback()
    return 200, p


def watch_activity(auth, body):
    code, slug = watch_slug(auth)
    if not slug:
        return 404, {'pair': code}
    cid = str(body.get('id') or '')[:64] or None
    old = db().execute('SELECT id, body FROM inbox WHERE slug=? AND client_id=?', (slug, cid)).fetchone() if cid else None
    if old:   # answers given after saving (RPE / feel) re-send the same id
        merged = {**json.loads(old['body']), **{k: v for k, v in body.items() if v is not None}}
        db().execute('UPDATE inbox SET body=? WHERE id=?', (json.dumps(merged), old['id']))
    else:
        db().execute('INSERT INTO inbox (slug, client_id, body, created) VALUES (?,?,?,?)',
                     (slug, cid, json.dumps(body)[:200000], time.time()))
    db().commit()
    return 201, {'ok': True, 'cheer': 'Saved to Trailhead'}


# ------------------------------------------------------------------ HTTP

class _Null:
    """Swallows the body after the headers for HEAD requests."""

    def __init__(self, f):
        self.f, self.headers_done = f, False

    def write(self, b):
        if not self.headers_done:
            self.headers_done = True
            return self.f.write(b)
        return len(b)

    def flush(self):
        self.f.flush()


class Handler(BaseHTTPRequestHandler):
    server_version = 'trailhead'

    def log_message(self, fmt, *args):   # path only: never bodies
        sys.stderr.write('%s %s\n' % (self.command, urlparse(self.path).path[:80]))

    def ip(self):
        return self.headers.get('X-Real-IP') or self.client_address[0]

    def send_json(self, code, obj):
        b = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > MAX_BODY:
            raise ValueError('too large')
        raw = self.rfile.read(n) if n else b''
        return json.loads(raw or b'{}')

    def do_GET(self):
        self.route('GET')

    def do_HEAD(self):   # headers only (link checkers, uptime monitors)
        self.wfile = _Null(self.wfile)
        self.route('GET')

    def do_POST(self):
        self.route('POST')

    def do_PUT(self):
        self.route('PUT')

    def route(self, method):
        u = urlparse(self.path)
        path = u.path
        query = dict(p.split('=', 1) for p in u.query.split('&') if '=' in p)
        try:
            if path.startswith('/api/'):
                if not allow(self.ip(), 'garmin' if path.startswith('/api/garmin') else 'api',
                             # every client arrives as 127.0.0.1 via the host forward, so these are site-wide caps
                             30 if path.startswith('/api/garmin/login') else 1200):
                    return self.send_json(429, {'error': 'Too many requests. Wait a minute.'})
                return self.api(method, path, query)
            if method != 'GET':
                return self.send_json(405, {'error': 'method'})
            return self.static(path)
        except ValueError as e:
            return self.send_json(400, {'error': str(e)[:100]})
        except Exception:
            traceback.print_exc()
            return self.send_json(500, {'error': 'Server error.'})
        finally:
            close_db()

    def api(self, method, path, query):
        key = self.headers.get('X-Plan-Key')
        auth = self.headers.get('Authorization')
        if path == '/api/health':
            return self.send_json(200, {'ok': True})
        if path == '/api/plans' and method == 'POST':
            return self.send_json(*create_plan(self.body()))
        m = re.match(r'^/api/plans/([a-z0-9]+)(/pair|/inbox)?$', path)
        if m:
            slug, sub = m.group(1), m.group(2)
            if sub is None and method == 'GET':
                return self.send_json(*get_plan(slug))
            if sub is None and method == 'PUT':
                return self.send_json(*put_plan(slug, self.body(), key))
            if sub == '/pair' and method == 'POST':
                return self.send_json(*pair(slug, self.body(), key))
            if sub == '/inbox':
                ack = self.body().get('ack') if method == 'POST' else None
                return self.send_json(*inbox(slug, key, ack))
        if path == '/api/device/sync' and method == 'GET':
            return self.send_json(*watch_sync(auth, query))
        if path == '/api/device/activity' and method == 'POST':
            return self.send_json(*watch_activity(auth, self.body()))
        if path == '/api/garmin/login' and method == 'POST':
            return self.send_json(*garmin_login(self.body()))
        if path == '/api/garmin/mfa' and method == 'POST':
            return self.send_json(*garmin_mfa(self.body()))
        if path == '/api/garmin/call' and method == 'POST':
            return self.send_json(*garmin_call(self.body()))
        return self.send_json(404, {'error': 'Not found.'})

    def static(self, path):
        if path.startswith('/p/'):
            path = '/plan.html'
        elif path in ('/setup', '/setup/'):
            path = '/setup.html'
        if path in ('', '/'):
            path = '/index.html'
        full = os.path.realpath(os.path.join(WEB, path.lstrip('/')))
        if not full.startswith(os.path.realpath(WEB) + os.sep) or not os.path.isfile(full):
            return self.send_json(404, {'error': 'Not found.'})
        ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
        size = os.path.getsize(full)
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(size))
        immutable = '/vendor/' in full or full.endswith('.prg')
        self.send_header('Cache-Control', 'public, max-age=604800' if immutable else 'no-cache')
        if full.endswith('.html'):
            self.send_header('Content-Security-Policy',
                             "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; "
                             "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        with open(full, 'rb') as fh:
            while chunk := fh.read(262144):
                self.wfile.write(chunk)


if __name__ == '__main__':
    init_db()
    print(f'trailhead listening on 127.0.0.1:{PORT}', flush=True)
    ThreadingHTTPServer.request_queue_size = 256   # engine workers fetch ~15 files each at once (default backlog: 5)
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
