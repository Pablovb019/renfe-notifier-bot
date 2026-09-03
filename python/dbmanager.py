#!/usr/bin/python3

import datetime
import logging
import os
import sqlite3

from texts import texts as TEXTS

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.DEBUG)

logger = logging.getLogger(__name__)


def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


class RenfeBotDB:
    def __init__(self, f_database):
        self._f_database = f_database
        self._ensure_schema()

    def _openclose(foo):
        def wrapper(self, *args, **kw):
            conn = sqlite3.connect(self._f_database)
            conn.row_factory = dict_factory
            cur = conn.cursor()
            ret = foo(self, conn, cur, *args, **kw)
            cur.close()
            conn.close()
            return ret
        return wrapper

    def _ensure_schema(self):
        folder = os.path.dirname(self._f_database)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder, exist_ok=True)

        conn = sqlite3.connect(self._f_database)
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS users (
                        userid INTEGER PRIMARY KEY,
                        username TEXT,
                        auth INTEGER
                    )""")
        # Legacy table (kept for backward compatibility with existing deployments)
        cur.execute("""CREATE TABLE IF NOT EXISTS queries (
                        origin TEXT,
                        destination TEXT,
                        date INTEGER,
                        userid INTEGER,
                        FOREIGN KEY(userid) REFERENCES users(userid)
                    )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS followups (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        userid INTEGER NOT NULL,
                        origin TEXT NOT NULL,
                        destination TEXT NOT NULL,
                        travel_date TEXT NOT NULL,
                        departure_time TEXT,
                        arrival_time TEXT,
                        plaza_h INTEGER NOT NULL DEFAULT 0,
                        watch_all INTEGER NOT NULL DEFAULT 0,
                        created_at INTEGER NOT NULL,
                        expires_at INTEGER NOT NULL,
                        departure_ts INTEGER NOT NULL,
                        status TEXT NOT NULL DEFAULT 'active',
                        total_queries INTEGER NOT NULL DEFAULT 0,
                        daily_queries INTEGER NOT NULL DEFAULT 0,
                        last_query_date TEXT,
                        FOREIGN KEY(userid) REFERENCES users(userid)
                    )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_followups_status ON followups(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_followups_user ON followups(userid)")

        # Migración retrocompatible de columnas si la tabla ya existía
        cur.execute("PRAGMA table_info(followups)")
        existing_cols = {row[1] for row in cur.fetchall()}
        if "total_queries" not in existing_cols:
            cur.execute("ALTER TABLE followups ADD COLUMN total_queries INTEGER NOT NULL DEFAULT 0")
        if "daily_queries" not in existing_cols:
            cur.execute("ALTER TABLE followups ADD COLUMN daily_queries INTEGER NOT NULL DEFAULT 0")
        if "last_query_date" not in existing_cols:
            cur.execute("ALTER TABLE followups ADD COLUMN last_query_date TEXT")

        conn.commit()
        cur.close()
        conn.close()

    def _now_ts(self):
        return int(datetime.datetime.now().timestamp())

    def _parse_date(self, date_str):
        return datetime.datetime.strptime(date_str, "%d/%m/%Y").date()

    def _parse_time(self, time_str):
        return datetime.datetime.strptime(time_str, "%H:%M").time()

    def _departure_ts(self, travel_date, departure_time=None, watch_all=False):
        base_date = self._parse_date(travel_date)
        if departure_time:
            dt = datetime.datetime.combine(base_date, self._parse_time(departure_time))
        elif watch_all:
            dt = datetime.datetime.combine(base_date, datetime.time(23, 59))
        else:
            dt = datetime.datetime.combine(base_date, datetime.time(0, 0))
        return int(dt.timestamp())

    def _expires_ts(self, departure_ts):
        monthly = self._now_ts() + (30 * 24 * 60 * 60)
        return min(monthly, departure_ts)

    @_openclose
    def get_user_auth(self, conn, cur, userid, username):
        auth = 0
        cur.execute("SELECT auth FROM users WHERE userid=?", (userid,))
        val = cur.fetchall()
        if len(val) == 0:
            cur.execute("INSERT INTO users VALUES (?,?,?)", (userid, username, 0))
            conn.commit()
        elif len(val) == 1:
            auth = val[0]["auth"]
        else:
            logger.error("Not possible, something is clearly wrong")
        return auth

    @_openclose
    def update_user(self, conn, cur, userid, username, auth):
        cur.execute("UPDATE users SET username=?, auth=? WHERE userid=?",
                    (username, auth, userid))
        conn.commit()

    def date_to_timestamp(self, date):
        return int(datetime.datetime.strptime(date, "%d/%m/%Y").timestamp())

    def timestamp_to_date(self, timestamp):
        return datetime.datetime.fromtimestamp(timestamp).strftime("%d/%m/%Y")

    # ---------- Followups ----------
    @_openclose
    def create_followup(self, conn, cur, userid, origin, destination, travel_date,
                        departure_time=None, arrival_time=None, plaza_h=False, watch_all=False):
        departure_ts = self._departure_ts(travel_date, departure_time, watch_all)
        expires_ts = self._expires_ts(departure_ts)
        now = self._now_ts()
        if expires_ts <= now:
            return False, None
        today_str = datetime.date.today().isoformat()
        cur.execute(
            """INSERT INTO followups
               (userid, origin, destination, travel_date, departure_time, arrival_time,
                plaza_h, watch_all, created_at, expires_at, departure_ts, status,
                total_queries, daily_queries, last_query_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 0, 0, ?)""",
            (
                userid,
                origin,
                destination,
                travel_date,
                departure_time,
                arrival_time,
                1 if plaza_h else 0,
                1 if watch_all else 0,
                now,
                expires_ts,
                departure_ts,
                today_str,
            ),
        )
        conn.commit()
        return True, cur.lastrowid

    @_openclose
    def get_user_followups(self, conn, cur, userid):
        cur.execute(
            """SELECT * FROM followups
               WHERE userid=? AND status IN ('active', 'awaiting_extension', 'notifying')
               ORDER BY travel_date, departure_time, id""",
            (userid,)
        )
        return cur.fetchall()

    @_openclose
    def increment_followup_queries(self, conn, cur, followup_id):
        cur.execute("SELECT total_queries, daily_queries, last_query_date FROM followups WHERE id=?", (followup_id,))
        rows = cur.fetchall()
        if not rows:
            return
        row = rows[0]
        today_str = datetime.date.today().isoformat()
        total_q = (row.get("total_queries") or 0) + 1
        if row.get("last_query_date") == today_str:
            daily_q = (row.get("daily_queries") or 0) + 1
        else:
            daily_q = 1
        cur.execute(
            "UPDATE followups SET total_queries=?, daily_queries=?, last_query_date=? WHERE id=?",
            (total_q, daily_q, today_str, followup_id),
        )
        conn.commit()

    @_openclose
    def reset_daily_queries(self, conn, cur):
        cur.execute("UPDATE followups SET daily_queries=0")
        conn.commit()

    @_openclose
    def set_followup_notifying(self, conn, cur, followup_id):
        cur.execute(
            "UPDATE followups SET status='notifying' WHERE id=?",
            (followup_id,)
        )
        conn.commit()

    @_openclose
    def get_notifying_followups(self, conn, cur):
        cur.execute(
            """SELECT * FROM followups
               WHERE status='notifying'
               ORDER BY id"""
        )
        return cur.fetchall()

    @_openclose
    def stop_user_notifying_followups(self, conn, cur, userid):
        cur.execute(
            "SELECT * FROM followups WHERE userid=? AND status='notifying'",
            (userid,)
        )
        stopped = cur.fetchall()
        if stopped:
            cur.execute(
                "DELETE FROM followups WHERE userid=? AND status='notifying'",
                (userid,)
            )
            conn.commit()
        return stopped

    @_openclose
    def get_all_followups_for_daily_stats(self, conn, cur):
        cur.execute(
            """SELECT * FROM followups
               WHERE status IN ('active', 'awaiting_extension', 'notifying')
               ORDER BY userid, travel_date, departure_time, id"""
        )
        return cur.fetchall()

    @_openclose
    def get_active_followups(self, conn, cur):
        cur.execute(
            """SELECT * FROM followups
               WHERE status='active'
               ORDER BY created_at, id"""
        )
        return cur.fetchall()

    @_openclose
    def get_user_pending_extensions(self, conn, cur, userid):
        cur.execute(
            """SELECT * FROM followups
               WHERE userid=? AND status='awaiting_extension'
               ORDER BY id""",
            (userid,)
        )
        return cur.fetchall()

    @_openclose
    def set_followup_awaiting_extension(self, conn, cur, followup_id):
        cur.execute(
            "UPDATE followups SET status='awaiting_extension' WHERE id=?",
            (followup_id,)
        )
        conn.commit()

    @_openclose
    def extend_followup(self, conn, cur, followup_id):
        cur.execute("SELECT * FROM followups WHERE id=?", (followup_id,))
        rows = cur.fetchall()
        if len(rows) != 1:
            return False
        followup = rows[0]
        now = self._now_ts()
        if followup["departure_ts"] <= now:
            return False
        new_expires = min(now + (30 * 24 * 60 * 60), followup["departure_ts"])
        if new_expires <= now:
            return False
        cur.execute(
            "UPDATE followups SET status='active', expires_at=? WHERE id=?",
            (new_expires, followup_id),
        )
        conn.commit()
        return True

    @_openclose
    def delete_followup(self, conn, cur, followup_id):
        cur.execute("DELETE FROM followups WHERE id=?", (followup_id,))
        conn.commit()

    @_openclose
    def delete_user_followup(self, conn, cur, userid, followup_id):
        cur.execute("DELETE FROM followups WHERE id=? AND userid=?", (followup_id, userid))
        conn.commit()
        return cur.rowcount == 1

    # ---------- Legacy periodic query API ----------
    @_openclose
    def get_user_queries(self, conn, cur, userid):
        cur.execute("SELECT * FROM queries WHERE userid=?", (userid,))
        return cur.fetchall()

    def _get_user_queries(self, cur, userid):
        cur.execute("SELECT * FROM queries WHERE userid=?", (userid,))
        return cur.fetchall()

    @_openclose
    def add_periodic_query(self, conn, cur, userid, origin, destination, date):
        ret = (False, "")
        i_date = self.date_to_timestamp(date)
        user_queries = self._get_user_queries(cur, userid)
        found = False
        for q in user_queries:
            if q["origin"] == origin and q["destination"] == destination and q["date"] == i_date:
                logger.debug("Query already in DB")
                ret = (False, TEXTS.get("DB_QUERY_ALREADY", "Query already exists"))
                found = True
                break
        if not found:
            cur.execute("INSERT INTO queries VALUES (?, ?, ?, ?)",
                        (origin, destination, i_date, userid))
            conn.commit()
            ret = (True, TEXTS.get("DB_QUERY_INSERTED", "Query inserted"))
        return ret

    @_openclose
    def remove_periodic_query(self, conn, cur, userid, origin, destination, i_date):
        cur.execute(
            "DELETE FROM queries WHERE origin=? AND destination=? AND date=? AND userid=?",
            (origin, destination, i_date, userid),
        )
        conn.commit()
        return True

    @_openclose
    def remove_old_periodic_queries(self, conn, cur):
        todaytimestamp = datetime.datetime.timestamp(datetime.datetime.now())
        cur.execute("DELETE FROM queries WHERE date < ?", (todaytimestamp,))
        conn.commit()

    @_openclose
    def get_queries(self, conn, cur):
        cur.execute("SELECT * FROM queries")
        return cur.fetchall()
