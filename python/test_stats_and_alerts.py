#!/usr/bin/env python3
"""
Tests unitarios para las funcionalidades de estadísticas y avisos periódicos.
Cubre: migración de esquema, contadores daily/total, estado notifying y /stop.
"""

import datetime
import os
import sys
import tempfile
import unittest

# Asegurarse de que podemos importar el módulo desde el directorio python/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Monkey-patch de 'texts' para no necesitar el módulo 'emoji' en tests
import types
texts_module = types.ModuleType("texts")
texts_module.texts = {
    "DB_QUERY_ALREADY": "ya existe",
    "DB_QUERY_INSERTED": "insertado",
    "STATS_ITEM": "{index}. {origin} - {destination} ({date} {dep_time}): {daily} consultas ({total} consultas en total)",
    "STATS_TITLE": "Total de consultas realizadas hasta el momento:",
    "DAILY_STATS_TITLE": "Resumen diario de consultas (00:00):",
    "STATS_EMPTY": "No tienes seguimientos activos en este momento.",
    "STOP_SUCCESS": "Se ha detenido el seguimiento y el envío de avisos para:\n{items}",
    "STOP_EMPTY": "No tienes ningún seguimiento activo con avisos de plazas disponibles pendientes de detener con /stop.",
}
texts_module.keyboards = {}
sys.modules["texts"] = texts_module

import dbmanager


def _tomorrow_date():
    return (datetime.date.today() + datetime.timedelta(days=1)).strftime("%d/%m/%Y")


def _tomorrow_ts():
    d = datetime.date.today() + datetime.timedelta(days=1)
    dt = datetime.datetime.combine(d, datetime.time(12, 0))
    return int(dt.timestamp())


class TestSchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".db")
        self.db = dbmanager.RenfeBotDB(self.tmp)

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_new_columns_exist(self):
        import sqlite3
        conn = sqlite3.connect(self.tmp)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(followups)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        self.assertIn("total_queries", cols)
        self.assertIn("daily_queries", cols)
        self.assertIn("last_query_date", cols)

    def test_migration_on_existing_db_without_cols(self):
        import sqlite3
        tmp2 = tempfile.mktemp(suffix=".db")
        try:
            conn = sqlite3.connect(tmp2)
            cur = conn.cursor()
            cur.execute("CREATE TABLE users (userid INTEGER PRIMARY KEY, username TEXT, auth INTEGER)")
            cur.execute("""CREATE TABLE followups (
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
                status TEXT NOT NULL DEFAULT 'active'
            )""")
            conn.commit()
            conn.close()
            dbmanager.RenfeBotDB(tmp2)
            conn2 = sqlite3.connect(tmp2)
            cur2 = conn2.cursor()
            cur2.execute("PRAGMA table_info(followups)")
            cols = {row[1] for row in cur2.fetchall()}
            conn2.close()
            self.assertIn("total_queries", cols)
            self.assertIn("daily_queries", cols)
            self.assertIn("last_query_date", cols)
        finally:
            if os.path.exists(tmp2):
                os.remove(tmp2)


class TestQueryCounters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".db")
        self.db = dbmanager.RenfeBotDB(self.tmp)
        import sqlite3
        conn = sqlite3.connect(self.tmp)
        cur = conn.cursor()
        cur.execute("INSERT INTO users VALUES (1, 'testuser', 1)")
        tomorrow = _tomorrow_date()
        dep_ts = _tomorrow_ts()
        expires_ts = dep_ts - 60
        today_str = datetime.date.today().isoformat()
        cur.execute(
            """INSERT INTO followups
               (userid, origin, destination, travel_date, departure_time, arrival_time,
                plaza_h, watch_all, created_at, expires_at, departure_ts, status,
                total_queries, daily_queries, last_query_date)
               VALUES (1, 'Origen', 'Destino', ?, '12:00', '13:00',
                0, 0, strftime('%s','now'), ?, ?, 'active', 0, 0, ?)""",
            (tomorrow, expires_ts, dep_ts, today_str)
        )
        self.followup_id = cur.lastrowid
        conn.commit()
        conn.close()

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_increment_same_day(self):
        self.db.increment_followup_queries(self.followup_id)
        self.db.increment_followup_queries(self.followup_id)
        self.db.increment_followup_queries(self.followup_id)
        import sqlite3
        conn = sqlite3.connect(self.tmp)
        conn.row_factory = dbmanager.dict_factory
        cur = conn.cursor()
        cur.execute("SELECT total_queries, daily_queries FROM followups WHERE id=?", (self.followup_id,))
        row = cur.fetchone()
        conn.close()
        self.assertEqual(row["total_queries"], 3)
        self.assertEqual(row["daily_queries"], 3)

    def test_increment_new_day_resets_daily(self):
        import sqlite3
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        conn = sqlite3.connect(self.tmp)
        cur = conn.cursor()
        cur.execute(
            "UPDATE followups SET total_queries=100, daily_queries=50, last_query_date=? WHERE id=?",
            (yesterday, self.followup_id)
        )
        conn.commit()
        conn.close()
        self.db.increment_followup_queries(self.followup_id)
        conn = sqlite3.connect(self.tmp)
        conn.row_factory = dbmanager.dict_factory
        cur = conn.cursor()
        cur.execute("SELECT total_queries, daily_queries, last_query_date FROM followups WHERE id=?", (self.followup_id,))
        row = cur.fetchone()
        conn.close()
        self.assertEqual(row["total_queries"], 101)
        self.assertEqual(row["daily_queries"], 1)
        self.assertEqual(row["last_query_date"], datetime.date.today().isoformat())

    def test_reset_daily_queries(self):
        self.db.increment_followup_queries(self.followup_id)
        self.db.increment_followup_queries(self.followup_id)
        self.db.reset_daily_queries()
        import sqlite3
        conn = sqlite3.connect(self.tmp)
        conn.row_factory = dbmanager.dict_factory
        cur = conn.cursor()
        cur.execute("SELECT daily_queries, total_queries FROM followups WHERE id=?", (self.followup_id,))
        row = cur.fetchone()
        conn.close()
        self.assertEqual(row["daily_queries"], 0)
        self.assertEqual(row["total_queries"], 2)


class TestNotifyingState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".db")
        self.db = dbmanager.RenfeBotDB(self.tmp)
        import sqlite3
        conn = sqlite3.connect(self.tmp)
        cur = conn.cursor()
        cur.execute("INSERT INTO users VALUES (1, 'testuser', 1)")
        tomorrow = _tomorrow_date()
        dep_ts = _tomorrow_ts()
        expires_ts = dep_ts - 60
        today_str = datetime.date.today().isoformat()
        cur.execute(
            """INSERT INTO followups
               (userid, origin, destination, travel_date, departure_time, arrival_time,
                plaza_h, watch_all, created_at, expires_at, departure_ts, status,
                total_queries, daily_queries, last_query_date)
               VALUES (1, 'Jerez de la Frontera', 'Virgen del Rocio', ?, '07:17', '08:30',
                0, 0, strftime('%s','now'), ?, ?, 'active', 42, 5, ?)""",
            (tomorrow, expires_ts, dep_ts, today_str)
        )
        self.followup_id = cur.lastrowid
        conn.commit()
        conn.close()

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_set_followup_notifying(self):
        self.db.set_followup_notifying(self.followup_id)
        import sqlite3
        conn = sqlite3.connect(self.tmp)
        conn.row_factory = dbmanager.dict_factory
        cur = conn.cursor()
        cur.execute("SELECT status FROM followups WHERE id=?", (self.followup_id,))
        row = cur.fetchone()
        conn.close()
        self.assertEqual(row["status"], "notifying")

    def test_get_notifying_followups(self):
        self.db.set_followup_notifying(self.followup_id)
        notifying = self.db.get_notifying_followups()
        self.assertEqual(len(notifying), 1)
        self.assertEqual(notifying[0]["id"], self.followup_id)

    def test_stop_user_notifying_deletes_and_returns(self):
        self.db.set_followup_notifying(self.followup_id)
        stopped = self.db.stop_user_notifying_followups(1)
        self.assertEqual(len(stopped), 1)
        self.assertEqual(stopped[0]["origin"], "Jerez de la Frontera")
        import sqlite3
        conn = sqlite3.connect(self.tmp)
        conn.row_factory = dbmanager.dict_factory
        cur = conn.cursor()
        cur.execute("SELECT * FROM followups WHERE id=?", (self.followup_id,))
        row = cur.fetchone()
        conn.close()
        self.assertIsNone(row)

    def test_stop_empty_returns_empty_list(self):
        stopped = self.db.stop_user_notifying_followups(1)
        self.assertEqual(len(stopped), 0)


class TestStatsTextFormat(unittest.TestCase):
    def test_stats_item_format(self):
        template = texts_module.texts["STATS_ITEM"]
        result = template.format(
            index=1,
            origin="Jerez de la Frontera",
            destination="Virgen del Rocio",
            date="01/09/2026",
            dep_time="07:17",
            daily=200,
            total=1367,
        )
        expected = "1. Jerez de la Frontera - Virgen del Rocio (01/09/2026 07:17): 200 consultas (1367 consultas en total)"
        self.assertEqual(result, expected)

    def test_stats_all_trains_format(self):
        template = texts_module.texts["STATS_ITEM"]
        result = template.format(
            index=2,
            origin="Madrid",
            destination="Barcelona",
            date="15/10/2026",
            dep_time="Todos los trenes",
            daily=10,
            total=150,
        )
        self.assertIn("Todos los trenes", result)
        self.assertIn("10 consultas", result)
        self.assertIn("150 consultas en total", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
