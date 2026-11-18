"""Durable single-stage leases and request budgets, using SQLite transactions.

No network retry is implicit. Interrupted remote attempts have unknown consumption.
Use a shared database for workers sharing a provider account. Not a distributed queue.
"""
import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class JobStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, spec TEXT NOT NULL, status TEXT NOT NULL,
              attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL,
              lease_until REAL, owner TEXT, result TEXT, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS reservations (
              id TEXT PRIMARY KEY, day TEXT NOT NULL, token_cap INTEGER NOT NULL,
              status TEXT NOT NULL, actual_tokens INTEGER);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA busy_timeout=30000')
        try:
            with db:yield db
        finally:db.close()

    def enqueue(self, spec, max_attempts=2):
        if not 1 <= max_attempts <= 3:
            raise ValueError('max_attempts must be 1..3')
        raw = json.dumps(spec, sort_keys=True)
        ident = hashlib.sha256(raw.encode()).hexdigest()
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO jobs(id,spec,status,max_attempts,updated) VALUES(?,?,?,?,?)',
                       (ident, raw, 'pending', max_attempts, time.time()))
        return ident

    def claim(self, ident, lease_seconds=1200, now=None):
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status,attempts,max_attempts,lease_until,spec FROM jobs WHERE id=?', (ident,)).fetchone()
            if not row:
                raise KeyError(ident)
            status, attempts, maximum, lease, spec = row
            if status == 'running' and (lease or 0) <= now:
                # Do not blindly replay a call that may have reached the provider.
                db.execute("UPDATE jobs SET status='interrupted',updated=? WHERE id=?", (now, ident))
                return None
            if status != 'pending' or attempts >= maximum:
                return None
            owner = uuid.uuid4().hex
            db.execute("UPDATE jobs SET status='running',attempts=attempts+1,owner=?,lease_until=?,updated=? WHERE id=?",
                       (owner, now + lease_seconds, now, ident))
            return owner, json.loads(spec)

    def finish(self, ident, owner, result, success):
        with self.connect() as db:
            cur = db.execute("UPDATE jobs SET status=?,result=?,lease_until=NULL,updated=? WHERE id=? AND owner=? AND status='running'",
                             ('complete' if success else 'needs_attention', json.dumps(result), time.time(), ident, owner))
            if cur.rowcount != 1:
                raise ValueError('Lost job lease')

    def retry(self, ident):
        """Explicit operator retry only, retaining attempt count and result history on disk."""
        with self.connect() as db:
            cur = db.execute("UPDATE jobs SET status='pending',updated=? WHERE id=? AND status IN ('needs_attention','interrupted') AND attempts<max_attempts",
                             (time.time(), ident))
            return cur.rowcount == 1

    def reserve(self, ident, token_cap, daily_requests=24, daily_tokens=180000, day=None):
        from datetime import datetime, timezone
        day = day or datetime.now(timezone.utc).strftime('%Y-%m-%d')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            n, tokens = db.execute('SELECT count(*),coalesce(sum(coalesce(actual_tokens,token_cap)),0) FROM reservations WHERE day=?', (day,)).fetchone()
            if n >= daily_requests or tokens + token_cap > daily_tokens:
                return False
            db.execute('INSERT INTO reservations VALUES(?,?,?,?,NULL)', (ident, day, token_cap, 'reserved'))
            return True

    def settle(self, ident, status, tokens=None):
        with self.connect() as db:
            db.execute('UPDATE reservations SET status=?,actual_tokens=? WHERE id=?', (str(status), tokens, ident))

    def snapshot(self, ident):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT * FROM jobs WHERE id=?', (ident,)).fetchone()
            return dict(row) if row else None
