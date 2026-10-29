"""Durable, credential-scoped cache for read-only SIF calls.

Transactions serialize cache misses across processes. A crash rolls back the
pending entry; successful responses survive later pipeline failures. This is
not an external-write executor or a server-side incremental API.
"""
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from .ledger import redact
from .sif import SifError


def canonical(tool, params):
    params = dict(params)
    for old in ('topN', 'limit', 'max_results', 'max_competitors'):
        if old in params:
            params.setdefault('pageSize', params.pop(old))
    if isinstance(params.get('keywords'), list):
        params['keywords'] = sorted(set(params['keywords']))
    return params


class CachedSif:
    def __getattr__(self, name):
        if name in ('source_run_id', 'transport_state', 'replayed_calls'):
            return getattr(self.client, name)
        raise AttributeError(name)

    def __init__(self, path, client, *, scope, clock=time.time, max_calls=100):
        if not scope:
            raise ValueError('SIF cache requires a connection scope')
        self.path, self.client, self.scope = path, client, scope
        self.clock, self.max_calls = clock, max_calls
        self.live_calls = self.cache_hits = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, expires REAL, value TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS failures (key TEXT PRIMARY KEY, retry_at REAL)')

    def call(self, tool, params):
        if not tool.startswith(('market_get_', 'market_discover_', 'ads_get_', 'ops_get_')):
            raise ValueError('cache supports read-only SIF tools only')
        params = canonical(tool, params)
        now = self.clock()
        day = datetime.fromtimestamp(now, timezone(timedelta(hours=8))).date().isoformat()
        rolling = params.get('time_type', 'lately') == 'lately' and 'asin_keyword_signals' in tool
        key = hashlib.sha256(json.dumps([1, self.scope, tool, params, day if rolling else None],
                                       sort_keys=True).encode()).hexdigest()
        with sqlite3.connect(self.path, timeout=300) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT expires,value FROM responses WHERE key=?', (key,)).fetchone()
            if row and row[0] > now:
                self.cache_hits += 1
                self.last_call_source = 'cache'
                return json.loads(row[1])
            failed = db.execute('SELECT retry_at FROM failures WHERE key=?', (key,)).fetchone()
            if failed and failed[0] > now:
                raise SifError('SIF read cooling down; resume later', kind='cooldown')
            if self.live_calls >= self.max_calls:
                raise SifError('SIF request budget exhausted', kind='budget')
            self.live_calls += 1
            try:
                value = self.client.call(tool, params)
                if isinstance(value, dict) and (value.get('isError') or value.get('error') or value.get('success') is False):
                    raise SifError('SIF returned an error; not cached', kind='business_error')
            except Exception:
                db.execute('INSERT OR REPLACE INTO failures VALUES (?,?)', (key, now + 60))
                db.commit()
                raise
            ttl = 86400 if rolling else 7 * 86400
            db.execute('INSERT OR REPLACE INTO responses VALUES (?,?,?)',
                       (key, now + ttl, json.dumps(redact(value), ensure_ascii=False)))
            db.execute('DELETE FROM failures WHERE key=?', (key,))
            self.last_call_source = 'live'
            return value
