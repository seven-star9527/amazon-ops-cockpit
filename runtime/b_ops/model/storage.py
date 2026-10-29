"""Durable keyword assets and append-only observations."""

from __future__ import annotations

import re
import sqlite3
import math
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL


def normalize_keyword(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


class StateStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _db(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init(self):
        with self._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS keyword_assets (
              id TEXT PRIMARY KEY, site TEXT NOT NULL, asin TEXT NOT NULL,
              keyword TEXT NOT NULL, normalized TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'active', pinned INTEGER NOT NULL DEFAULT 0,
              first_run_id TEXT NOT NULL, first_seen_at TEXT NOT NULL,
              UNIQUE(site, asin, normalized)
            );
            CREATE TABLE IF NOT EXISTS keyword_sources (
              keyword_id TEXT NOT NULL, source TEXT NOT NULL, reason TEXT NOT NULL,
              run_id TEXT NOT NULL, observed_at TEXT NOT NULL,
              UNIQUE(keyword_id, source, run_id),
              FOREIGN KEY(keyword_id) REFERENCES keyword_assets(id)
            );
            CREATE TABLE IF NOT EXISTS keyword_memberships (
              keyword_id TEXT NOT NULL, sid TEXT NOT NULL,
              PRIMARY KEY(keyword_id, sid),
              FOREIGN KEY(keyword_id) REFERENCES keyword_assets(id)
            );
            CREATE TABLE IF NOT EXISTS keyword_tracking (
              keyword_id TEXT NOT NULL, sid TEXT NOT NULL,
              state TEXT NOT NULL DEFAULT 'candidate', pending TEXT,
              first_core_run_id TEXT, last_sif_run_id TEXT, updated_at TEXT NOT NULL,
              PRIMARY KEY(keyword_id,sid),
              FOREIGN KEY(keyword_id) REFERENCES keyword_assets(id)
            );
            CREATE TABLE IF NOT EXISTS sif_product_priority (
              product_key TEXT PRIMARY KEY, active INTEGER NOT NULL DEFAULT 0,
              pending INTEGER, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS competitor_assets (
              sid TEXT NOT NULL, site TEXT NOT NULL, parent_asin TEXT NOT NULL,
              asin TEXT NOT NULL, origin TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0,
              pending TEXT, first_run_id TEXT NOT NULL, last_seen_run_id TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY(sid,site,parent_asin,asin)
            );
            CREATE TABLE IF NOT EXISTS tracking_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT NOT NULL,
              site TEXT NOT NULL, asin TEXT NOT NULL, keyword_id TEXT,
              action TEXT NOT NULL, run_id TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rank_observations (
              id INTEGER PRIMARY KEY AUTOINCREMENT, keyword_id TEXT NOT NULL,
              observed_date TEXT NOT NULL, channel TEXT NOT NULL,
              rank REAL, state TEXT NOT NULL, display TEXT, run_id TEXT NOT NULL,
              captured_at TEXT NOT NULL,
              UNIQUE(keyword_id, observed_date, channel, run_id),
              FOREIGN KEY(keyword_id) REFERENCES keyword_assets(id)
            );
            CREATE TABLE IF NOT EXISTS review_decisions (
              run_id TEXT NOT NULL, version INTEGER NOT NULL,
              action_key TEXT NOT NULL, profile_id TEXT NOT NULL,
              value TEXT NOT NULL, note TEXT NOT NULL, bid REAL,
              target_campaign_id TEXT, target_ad_group_id TEXT,
              created_at TEXT NOT NULL,
              PRIMARY KEY(run_id, version)
            );
            CREATE INDEX IF NOT EXISTS review_action_idx ON review_decisions(run_id, action_key, version);
            CREATE TABLE IF NOT EXISTS sif_fetches (
              site TEXT NOT NULL, asin TEXT NOT NULL, run_id TEXT NOT NULL,
              status TEXT NOT NULL, observed_at TEXT NOT NULL,
              PRIMARY KEY(site, asin, run_id)
            );
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(review_decisions)")}
            if "bid" not in columns:
                db.execute("ALTER TABLE review_decisions ADD COLUMN bid REAL")
            if "target_campaign_id" not in columns:
                db.execute("ALTER TABLE review_decisions ADD COLUMN target_campaign_id TEXT")
            if "target_ad_group_id" not in columns:
                db.execute("ALTER TABLE review_decisions ADD COLUMN target_ad_group_id TEXT")
            rank_columns = {row[1] for row in db.execute("PRAGMA table_info(rank_observations)")}
            if "display" not in rank_columns:
                db.execute("ALTER TABLE rank_observations ADD COLUMN display TEXT")
            now = datetime.now(timezone.utc).isoformat()
            db.execute("""INSERT OR IGNORE INTO keyword_tracking
                (keyword_id,sid,state,first_core_run_id,last_sif_run_id,updated_at)
                SELECT m.keyword_id,m.sid,'active',a.first_run_id,a.first_run_id,?
                FROM keyword_memberships m JOIN keyword_assets a ON a.id=m.keyword_id
                WHERE EXISTS(SELECT 1 FROM keyword_sources s WHERE s.keyword_id=a.id AND s.source='sif_asin_signals')""", (now,))

    def add_keyword(self, site: str, asin: str, keyword: str, source: str,
                    reason: str, run_id: str, sid: str | None = None) -> str:
        return self.add_keywords([{"site": site, "asin": asin, "keyword": keyword,
                                   "source": source, "reason": reason, "run_id": run_id, "sid": sid}])[0]

    def add_keywords(self, rows: list[dict]) -> list[str]:
        now = datetime.now(timezone.utc).isoformat()
        keys = []
        with self._db() as db:
            for row in rows:
                site = str(row.get("site") or "").upper()
                asin = str(row.get("asin") or "").upper()
                keyword = str(row.get("keyword") or "").strip()
                normalized = normalize_keyword(keyword)
                run_id = str(row.get("run_id") or "")
                if not site or not asin or not normalized or not run_id:
                    raise ValueError("keyword requires site, ASIN, term and run_id")
                key = uuid5(NAMESPACE_URL, f"amazon-keyword:{site}|{asin}|{normalized}").hex
                keys.append(key)
                db.execute("""INSERT OR IGNORE INTO keyword_assets
                    (id,site,asin,keyword,normalized,first_run_id,first_seen_at)
                    VALUES(?,?,?,?,?,?,?)""",
                    (key, site, asin, keyword, normalized, run_id, now))
                db.execute("""INSERT OR IGNORE INTO keyword_sources
                    (keyword_id,source,reason,run_id,observed_at) VALUES(?,?,?,?,?)""",
                    (key, str(row.get("source") or ""), str(row.get("reason") or ""), run_id, now))
                if row.get("sid"):
                    db.execute("INSERT OR IGNORE INTO keyword_memberships(keyword_id,sid) VALUES(?,?)", (key, str(row["sid"])))
        return keys

    def list_keywords(self, site: str, asin: str, *, status: str | None = None,
                      sid: str | None = None) -> list[dict]:
        query = "SELECT * FROM keyword_assets WHERE site=? AND asin=?"
        args: list = [site.upper(), asin.upper()]
        if status:
            query += " AND status=?"
            args.append(status)
        if sid is not None:
            query += " AND EXISTS (SELECT 1 FROM keyword_memberships m WHERE m.keyword_id=keyword_assets.id AND m.sid=?)"
            args.append(str(sid))
        query += " ORDER BY pinned DESC, first_seen_at, normalized"
        with self._db() as db:
            rows = [dict(row) for row in db.execute(query, args)]
            for row in rows:
                row["sources"] = [item[0] for item in db.execute(
                    "SELECT DISTINCT source FROM keyword_sources WHERE keyword_id=? ORDER BY source", (row["id"],))]
                if sid is not None:
                    tracking = db.execute("SELECT state,pending,first_core_run_id,last_sif_run_id FROM keyword_tracking "
                                          "WHERE keyword_id=? AND sid=?", (row["id"], str(sid))).fetchone()
                    row["tracking"] = dict(tracking) if tracking else {"state": "candidate", "pending": None,
                                                                         "first_core_run_id": None, "last_sif_run_id": None}
        return rows

    def tracking_version(self) -> int:
        with self._db() as db:
            return int(db.execute("SELECT COALESCE(MAX(id),0) FROM tracking_events").fetchone()[0])

    def tracking_state(self, keyword_id: str, sid: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM keyword_tracking WHERE keyword_id=? AND sid=?",
                             (keyword_id, str(sid))).fetchone()
            return dict(row) if row else None

    def mark_sif_core(self, keyword_id: str, sid: str, run_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            db.execute("""INSERT INTO keyword_tracking
                (keyword_id,sid,state,first_core_run_id,last_sif_run_id,updated_at)
                VALUES(?,?,'active',?,?,?)
                ON CONFLICT(keyword_id,sid) DO UPDATE SET
                last_sif_run_id=excluded.last_sif_run_id,updated_at=excluded.updated_at""",
                (keyword_id, str(sid), run_id, run_id, now))

    def stage_tracking_change(self, sid: str, site: str, asin: str, keyword: str,
                              action: str, run_id: str) -> str:
        if action not in {"add", "remove"}:
            raise ValueError("tracking action must be add or remove")
        sid, site, asin = str(sid).strip(), site.upper().strip(), asin.upper().strip()
        if not sid or not site or not asin or not normalize_keyword(keyword):
            raise ValueError("tracking identity incomplete")
        keyword_id = self.add_keyword(site, asin, keyword, "operator", "运营待生效跟踪意见", run_id, sid)
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            db.execute("""INSERT INTO keyword_tracking(keyword_id,sid,state,pending,updated_at)
                VALUES(?,?,'candidate',?,?) ON CONFLICT(keyword_id,sid) DO UPDATE SET
                pending=excluded.pending,updated_at=excluded.updated_at""", (keyword_id, sid, action, now))
            db.execute("INSERT INTO tracking_events(sid,site,asin,keyword_id,action,run_id,created_at) VALUES(?,?,?,?,?,?,?)",
                       (sid, site, asin, keyword_id, "stage_" + action, run_id, now))
        return keyword_id

    def stage_tracking_batch(self, sid: str, site: str, asin: str, keywords: list[str],
                             action: str, run_id: str) -> list[str]:
        """One bounded all-or-none keyword change; source history stays append-only."""
        sid, site, asin = str(sid).strip(), str(site).upper().strip(), str(asin).upper().strip()
        if action not in {"add", "remove"} or not sid or not site or not asin or not run_id:
            raise ValueError("tracking batch identity incomplete")
        if not isinstance(keywords, list) or not 1 <= len(keywords) <= 200:
            raise ValueError("tracking batch requires 1–200 terms")
        values: dict[str, str] = {}
        for value in keywords:
            if not isinstance(value, str):
                raise ValueError("invalid keyword type")
            word = value.strip()
            normalized = normalize_keyword(word)
            if (not normalized or len(word) > 120 or re.fullmatch(r"B[A-Z0-9]{9}", word.upper())
                    or re.fullmatch(r"\d+(?:\.\d+)?", word)):
                raise ValueError("invalid keyword in batch")
            values.setdefault(normalized, word)
        now = datetime.now(timezone.utc).isoformat()
        ids = []
        with self._db() as db:
            for normalized, word in values.items():
                key = uuid5(NAMESPACE_URL, f"amazon-keyword:{site}|{asin}|{normalized}").hex
                ids.append(key)
                if action == "remove":
                    exists = db.execute("SELECT 1 FROM keyword_memberships WHERE keyword_id=? AND sid=?",
                                        (key, sid)).fetchone()
                    if not exists:
                        raise ValueError("cannot remove an unknown keyword")
                else:
                    db.execute("""INSERT OR IGNORE INTO keyword_assets
                        (id,site,asin,keyword,normalized,first_run_id,first_seen_at)
                        VALUES(?,?,?,?,?,?,?)""", (key, site, asin, word, normalized, run_id, now))
                    db.execute("""INSERT OR IGNORE INTO keyword_sources
                        (keyword_id,source,reason,run_id,observed_at) VALUES(?,?,?,?,?)""",
                        (key, "operator", "运营批量维护待下轮生效", run_id, now))
                    db.execute("INSERT OR IGNORE INTO keyword_memberships(keyword_id,sid) VALUES(?,?)", (key, sid))
                db.execute("""INSERT INTO keyword_tracking(keyword_id,sid,state,pending,updated_at)
                    VALUES(?,?,'candidate',?,?) ON CONFLICT(keyword_id,sid) DO UPDATE SET
                    pending=excluded.pending,updated_at=excluded.updated_at""", (key, sid, action, now))
                db.execute("""INSERT INTO tracking_events(sid,site,asin,keyword_id,action,run_id,created_at)
                    VALUES(?,?,?,?,?,?,?)""", (sid, site, asin, key, "stage_" + action, run_id, now))
        return ids

    def cancel_tracking_change(self, sid: str, keyword_id: str, run_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            row = db.execute("SELECT a.site,a.asin FROM keyword_tracking t JOIN keyword_assets a ON a.id=t.keyword_id "
                             "WHERE t.keyword_id=? AND t.sid=? AND t.pending IS NOT NULL",
                             (keyword_id, str(sid))).fetchone()
            if not row:
                raise ValueError("no pending tracking change")
            db.execute("UPDATE keyword_tracking SET pending=NULL,updated_at=? WHERE keyword_id=? AND sid=?",
                       (now, keyword_id, str(sid)))
            db.execute("INSERT INTO tracking_events(sid,site,asin,keyword_id,action,run_id,created_at) VALUES(?,?,?,?,?,?,?)",
                       (str(sid), row["site"], row["asin"], keyword_id, "cancel", run_id, now))

    def stage_sif_priority(self, sid: str, site: str, asin: str, active: bool, run_id: str) -> None:
        sid, site, asin = str(sid).strip(), site.upper().strip(), asin.upper().strip()
        if not sid or not site or not asin:
            raise ValueError("product identity incomplete")
        key = f"{sid}|{site}|{asin}"
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            db.execute("""INSERT INTO sif_product_priority(product_key,active,pending,updated_at)
                VALUES(?,0,?,?) ON CONFLICT(product_key) DO UPDATE SET pending=excluded.pending,
                updated_at=excluded.updated_at""", (key, int(active), now))
            db.execute("INSERT INTO tracking_events(sid,site,asin,keyword_id,action,run_id,created_at) VALUES(?,?,?,?,?,?,?)",
                       (sid, site, asin, None, "priority_on" if active else "priority_off", run_id, now))

    def sif_priority_keys(self) -> set[str]:
        with self._db() as db:
            return {row[0] for row in db.execute("SELECT product_key FROM sif_product_priority WHERE active=1")}

    def sif_priority_state(self, product_key: str) -> dict:
        with self._db() as db:
            row = db.execute("SELECT active,pending FROM sif_product_priority WHERE product_key=?",
                             (product_key,)).fetchone()
            return dict(row) if row else {"active": 0, "pending": None}

    def upsert_discovered_competitors(self, sid: str, site: str, parent_asin: str,
                                      asins: list[str], run_id: str) -> None:
        from b_ops.collect.sif_discovery import competitor_asin
        now = datetime.now(timezone.utc).isoformat()
        sid, site, parent_asin = str(sid), site.upper(), parent_asin.upper()
        with self._db() as db:
            db.execute("""UPDATE competitor_assets SET active=0,updated_at=?
                WHERE sid=? AND site=? AND parent_asin=? AND origin='sif_serp_discovery'""",
                (now, sid, site, parent_asin))
            for value in asins[:3]:
                asin = competitor_asin(value)
                if not asin or asin == parent_asin:
                    continue
                db.execute("""INSERT INTO competitor_assets
                    (sid,site,parent_asin,asin,origin,active,first_run_id,last_seen_run_id,updated_at)
                    VALUES(?,?,?,?,'sif_serp_discovery',1,?,?,?)
                    ON CONFLICT(sid,site,parent_asin,asin) DO UPDATE SET
                    active=CASE WHEN competitor_assets.origin='sif_serp_discovery' THEN 1
                                ELSE competitor_assets.active END,
                    last_seen_run_id=excluded.last_seen_run_id,updated_at=excluded.updated_at""",
                    (sid, site, parent_asin, asin, run_id, run_id, now))

    def stage_competitor_change(self, sid: str, site: str, parent_asin: str,
                                asin: str, action: str, run_id: str) -> None:
        from b_ops.collect.sif_discovery import competitor_asin
        if action not in {"add", "remove"}:
            raise ValueError("competitor action must be add or remove")
        sid, site, parent_asin = str(sid).strip(), site.upper(), parent_asin.upper()
        asin = competitor_asin(asin)
        if not sid or not site or not parent_asin or not asin or asin == parent_asin:
            raise ValueError("invalid competitor identity")
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            db.execute("""INSERT INTO competitor_assets
                (sid,site,parent_asin,asin,origin,active,pending,first_run_id,last_seen_run_id,updated_at)
                VALUES(?,?,?,?,'operator',0,?,?,?,?)
                ON CONFLICT(sid,site,parent_asin,asin) DO UPDATE SET
                origin='operator',pending=excluded.pending,updated_at=excluded.updated_at""",
                (sid, site, parent_asin, asin, action, run_id, run_id, now))
            db.execute("INSERT INTO tracking_events(sid,site,asin,keyword_id,action,run_id,created_at) VALUES(?,?,?,?,?,?,?)",
                       (sid, site, parent_asin, None, "competitor_stage_" + action, run_id, now))

    def list_competitors(self, sid: str, site: str, parent_asin: str) -> list[dict]:
        with self._db() as db:
            return [dict(row) for row in db.execute("""SELECT * FROM competitor_assets
                WHERE sid=? AND site=? AND parent_asin=?
                ORDER BY CASE WHEN origin='operator' THEN 0 ELSE 1 END, active DESC, asin""",
                (str(sid), site.upper(), parent_asin.upper()))]

    def competitor_priority_keys(self, products: list[dict]) -> set[str]:
        with self._db() as db:
            parents = {(row["sid"], row["site"], row["parent_asin"])
                       for row in db.execute("""SELECT DISTINCT sid,site,parent_asin FROM competitor_assets
                           WHERE active=1 AND origin='operator'""")}
        return {product["key"] for product in products
                if (str(product["sid"]), str(product["site"]).upper(),
                    str(product.get("parent_asin") or product["asin"]).upper()) in parents}

    def apply_pending_tracking(self, run_id: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            words = list(db.execute("SELECT keyword_id,sid,pending FROM keyword_tracking WHERE pending IS NOT NULL"))
            for row in words:
                db.execute("UPDATE keyword_tracking SET state=?,pending=NULL,updated_at=? WHERE keyword_id=? AND sid=?",
                           ("active" if row["pending"] == "add" else "suppressed", now,
                            row["keyword_id"], row["sid"]))
            priorities = list(db.execute("SELECT product_key,pending FROM sif_product_priority WHERE pending IS NOT NULL"))
            for row in priorities:
                db.execute("UPDATE sif_product_priority SET active=?,pending=NULL,updated_at=? WHERE product_key=?",
                           (row["pending"], now, row["product_key"]))
            competitors = list(db.execute("SELECT sid,site,parent_asin,asin,pending FROM competitor_assets WHERE pending IS NOT NULL"))
            for row in competitors:
                db.execute("""UPDATE competitor_assets SET active=?,pending=NULL,updated_at=?
                    WHERE sid=? AND site=? AND parent_asin=? AND asin=?""",
                    (int(row["pending"] == "add"), now, row["sid"], row["site"], row["parent_asin"], row["asin"]))
        return {"run_id": run_id, "keywords": len(words), "product_priorities": len(priorities),
                "competitors": len(competitors)}

    def keyword_memberships(self, keyword_id: str) -> list[str]:
        with self._db() as db:
            return [row[0] for row in db.execute(
                "SELECT sid FROM keyword_memberships WHERE keyword_id=? ORDER BY sid", (keyword_id,))]

    def record_sif_fetch(self, site: str, asin: str, run_id: str, status: str) -> None:
        if status not in {"verified", "no_rows", "source_failed"}:
            raise ValueError("invalid SIF fetch state")
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO sif_fetches(site,asin,run_id,status,observed_at) VALUES(?,?,?,?,?)",
                       (site.upper(), asin.upper(), run_id, status, datetime.now(timezone.utc).isoformat()))

    def sif_last_success_map(self) -> dict[tuple[str, str], str]:
        with self._db() as db:
            result = {(row["site"], row["asin"]): row["latest"] for row in db.execute(
                "SELECT site,asin,MAX(observed_at) AS latest FROM sif_fetches "
                "WHERE status IN ('verified','no_rows') GROUP BY site,asin")}
            for row in db.execute("SELECT a.site,a.asin,MAX(s.observed_at) AS latest "
                                  "FROM keyword_sources s JOIN keyword_assets a ON a.id=s.keyword_id "
                                  "WHERE s.source='sif_asin_signals' GROUP BY a.site,a.asin"):
                key = (row["site"], row["asin"])
                result[key] = max(result.get(key, ""), row["latest"])
            return result

    def record_rank(self, keyword_id: str, observed_date: str, channel: str,
                    rank: float | None, state: str, run_id: str, *, display: str | None = None) -> None:
        if channel not in {"natural", "advertising"}:
            raise ValueError("invalid rank channel")
        if state == "absolute_rank" and (rank is None or rank <= 0):
            raise ValueError("absolute rank must be greater than zero")
        if state != "absolute_rank" and rank is not None:
            raise ValueError("non-absolute state cannot have rank")
        if state == "reported_position" and not display:
            raise ValueError("reported position needs source display")
        with self._db() as db:
            db.execute("""INSERT INTO rank_observations
                (keyword_id,observed_date,channel,rank,state,display,run_id,captured_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(keyword_id,observed_date,channel,run_id) DO UPDATE SET
                rank=excluded.rank,state=excluded.state,display=excluded.display,
                captured_at=excluded.captured_at""",
                (keyword_id, observed_date, channel, rank, state, display, run_id,
                 datetime.now(timezone.utc).isoformat()))

    def rank_window(self, keyword_id: str, start: str, end: str,
                    *, run_id: str | None = None) -> list[dict]:
        query = """SELECT observed_date,channel,rank,state,display,run_id
                FROM rank_observations WHERE keyword_id=? AND observed_date BETWEEN ? AND ?"""
        args = [keyword_id, start, end]
        if run_id is not None:
            query += " AND run_id=?"
            args.append(run_id)
        query += " ORDER BY observed_date, id"
        with self._db() as db:
            rows = db.execute(query, args)
            latest = {(row["observed_date"], row["channel"]): dict(row) for row in rows}
        return [latest[key] for key in sorted(latest)]

    def decision_version(self, run_id: str) -> int:
        with self._db() as db:
            return int(db.execute("SELECT COALESCE(MAX(version),0) FROM review_decisions WHERE run_id=?", (run_id,)).fetchone()[0])

    def save_decision(self, run_id: str, action_key: str, profile_id: str, value: str,
                      note: str, *, expected_version: int, bid: float | None = None,
                      target_campaign_id: str | None = None,
                      target_ad_group_id: str | None = None) -> dict:
        if value not in {"accept", "reject", "observe", "modify"}:
            raise ValueError("invalid review decision")
        if not run_id or not action_key or not profile_id:
            raise ValueError("review decision identity incomplete")
        if bid is not None and (not math.isfinite(float(bid)) or not 0 < float(bid) <= 1000):
            raise ValueError("invalid bid")
        now = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            actual = int(db.execute("SELECT COALESCE(MAX(version),0) FROM review_decisions WHERE run_id=?", (run_id,)).fetchone()[0])
            if expected_version != actual:
                raise ValueError(f"decision version conflict: expected {expected_version}, actual {actual}")
            version = actual + 1
            db.execute("INSERT INTO review_decisions(run_id,version,action_key,profile_id,value,note,bid,target_campaign_id,target_ad_group_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (run_id, version, action_key, profile_id, value, note, bid,
                        target_campaign_id, target_ad_group_id, now))
        return {"run_id": run_id, "version": version, "action_key": action_key,
                "profile_id": profile_id, "value": value, "note": note, "bid": bid,
                "target_campaign_id": target_campaign_id,
                "target_ad_group_id": target_ad_group_id, "created_at": now}

    def decision_history(self, run_id: str) -> list[dict]:
        with self._db() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM review_decisions WHERE run_id=? ORDER BY version", (run_id,))]

    def latest_decisions(self, run_id: str) -> dict[str, dict]:
        result = {}
        for row in self.decision_history(run_id):
            result[row["action_key"]] = row
        return result

    def mark_executed(self, run_id: str, action_keys: list[str], batch_id: str) -> int:
        """Append an executed marker; the original opinion remains in history."""
        current = self.latest_decisions(run_id)
        now = datetime.now(timezone.utc).isoformat()
        count = 0
        with self._db() as db:
            row = db.execute("SELECT COALESCE(MAX(version),0) AS version FROM review_decisions WHERE run_id=?", (run_id,)).fetchone()
            version = int(row["version"]) + 1
            for action_key in action_keys:
                decision = current.get(action_key)
                if not decision:
                    continue
                db.execute("INSERT INTO review_decisions(run_id,version,action_key,profile_id,value,note,bid,target_campaign_id,target_ad_group_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (run_id, version, action_key, decision.get("profile_id"), "executed",
                            f"write batch {batch_id}", decision.get("bid"),
                            decision.get("target_campaign_id"), decision.get("target_ad_group_id"), now))
                version += 1
                count += 1
        return count
