#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jy_store —— SQLite 持久化层（v1.3）

解决的问题：
  1. 内存 TTLCache 重启即失效，昨天答过的题今天还要重新问模型
  2. 题库上万条时，每次命中重写整个 bank.json（实测 148ms）
  3. 历史、指标没有落地，无法做统计和 RAG 索引

表结构：
  bank        题库（key 主键，answer/options/qtype/src/verified/hits）
  corrections 人工订正
  cache       答案缓存（L2，L1 是内存 LRU）
  history     答题历史（原始记录，自动建库与统计的数据源）
  metrics     逐次耗时与来源，用来算 p50/p95
  meta        杂项键值（迁移标记等）

全部操作走 WAL + 单连接 + 线程锁；单条 upsert 约 0.1ms。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS bank(
  key TEXT PRIMARY KEY, question TEXT, options TEXT, qtype TEXT,
  answer TEXT, src TEXT, verified INTEGER DEFAULT 0,
  ts REAL, hits INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_bank_ts ON bank(ts);

CREATE TABLE IF NOT EXISTS corrections(
  key TEXT PRIMARY KEY, question TEXT, options TEXT, qtype TEXT,
  answer TEXT, note TEXT, ts REAL, hits INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS cache(
  key TEXT PRIMARY KEY, payload TEXT, ts REAL, hits INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS history(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, question TEXT, options TEXT,
  answer TEXT, route TEXT, model TEXT, verify TEXT, cost REAL, verified INTEGER DEFAULT 0,
  status TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_hist_ts ON history(ts);

CREATE TABLE IF NOT EXISTS metrics(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, route TEXT,
  ms REAL, ok INTEGER, cached INTEGER);
CREATE INDEX IF NOT EXISTS idx_met_ts ON metrics(ts);

-- 抽样核对 / 答错标记：correct 1=对 0=错；src: quiz=人工抽样 thumb=答题流标记
CREATE TABLE IF NOT EXISTS quiz(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, hist_id INTEGER,
  correct INTEGER, src TEXT);
CREATE INDEX IF NOT EXISTS idx_quiz_ts ON quiz(ts);

CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""


class Store:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        first = not os.path.exists(path)
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        with self._lock:
            self.db.executescript(
                "PRAGMA journal_mode=WAL;"
                "PRAGMA synchronous=NORMAL;"
                "PRAGMA temp_store=MEMORY;"
            )
            self.db.executescript(SCHEMA)
            # 旧库迁移：history 补 status 列
            cols = [r["name"] for r in self.db.execute("PRAGMA table_info(history)")]
            if "status" not in cols:
                self.db.execute("ALTER TABLE history ADD COLUMN status TEXT DEFAULT ''")
            self.db.commit()
        self.is_new = first

    # ---------------- 通用 ----------------
    def _exec(self, sql, args=()):
        with self._lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    def _execmany(self, sql, rows):
        with self._lock:
            self.db.executemany(sql, rows)
            self.db.commit()

    def _query(self, sql, args=()):
        with self._lock:
            return self.db.execute(sql, args).fetchall()

    def close(self):
        with self._lock:
            try:
                self.db.commit()
                self.db.close()
            except Exception:
                pass

    # ---------------- 题库 ----------------
    def load_bank(self) -> dict:
        out = {}
        for r in self._query("SELECT * FROM bank"):
            opts = []
            try:
                opts = json.loads(r["options"] or "[]")
            except Exception:
                pass
            out[r["key"]] = {
                "answer": r["answer"] or "", "options": opts,
                "qtype": r["qtype"] or "single", "ts": r["ts"] or 0,
                "hits": r["hits"] or 0, "src": r["src"] or "",
                "question": r["question"] or "",
                "verified": bool(r["verified"]),
            }
        return out

    def bank_upsert(self, key: str, rec: dict):
        self._exec(
            "INSERT INTO bank(key,question,options,qtype,answer,src,verified,ts,hits) "
            "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
            "answer=excluded.answer, options=excluded.options, qtype=excluded.qtype, "
            "src=excluded.src, verified=excluded.verified, hits=excluded.hits, "
            "question=excluded.question",
            (key, rec.get("question", ""),
             json.dumps(rec.get("options") or [], ensure_ascii=False),
             rec.get("qtype", "single"), rec.get("answer", ""),
             rec.get("src", ""), 1 if rec.get("verified") else 0,
             rec.get("ts") or time.time(), int(rec.get("hits") or 0)),
        )

    def bank_sync(self, data: dict):
        """全量同步（导入后用）。只 upsert，不删除，避免误删人工数据。"""
        rows = [(k, v.get("question", ""),
                 json.dumps(v.get("options") or [], ensure_ascii=False),
                 v.get("qtype", "single"), v.get("answer", ""),
                 v.get("src", ""), 1 if v.get("verified") else 0,
                 v.get("ts") or time.time(), int(v.get("hits") or 0))
                for k, v in data.items()]
        if rows:
            self._execmany(
                "INSERT INTO bank(key,question,options,qtype,answer,src,verified,ts,hits) "
                "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
                "answer=excluded.answer, options=excluded.options, qtype=excluded.qtype, "
                "src=excluded.src, verified=excluded.verified, hits=excluded.hits, "
                "question=excluded.question", rows)

    def bank_delete(self, key: str):
        self._exec("DELETE FROM bank WHERE key=?", (key,))

    def bank_clear(self):
        self._exec("DELETE FROM bank")

    def bank_count(self) -> int:
        r = self._query("SELECT COUNT(*) c FROM bank")
        return r[0]["c"] if r else 0

    def bank_for_index(self) -> list:
        """给 RAG 建索引：只要 (key, question, answer, qtype, options, src)。"""
        rows = self._query("SELECT key,question,options,answer,qtype,src FROM bank")
        return [dict(r) for r in rows]

    # ---------------- 订正 ----------------
    def load_corrections(self) -> dict:
        out = {}
        for r in self._query("SELECT * FROM corrections"):
            out[r["key"]] = {
                "answer": r["answer"] or "", "options": r["options"] or "",
                "qtype": r["qtype"] or "single", "note": r["note"] or "",
                "ts": r["ts"] or 0, "hits": r["hits"] or 0,
                "question": r["question"] or "",
            }
        return out

    def correction_upsert(self, key: str, rec: dict):
        self._exec(
            "INSERT INTO corrections(key,question,options,qtype,answer,note,ts,hits) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
            "answer=excluded.answer, note=excluded.note, question=excluded.question, "
            "hits=excluded.hits",
            (key, rec.get("question", ""), rec.get("options", ""),
             rec.get("qtype", "single"), rec.get("answer", ""),
             rec.get("note", ""), rec.get("ts") or time.time(),
             int(rec.get("hits") or 0)),
        )

    def correction_delete(self, key: str):
        self._exec("DELETE FROM corrections WHERE key=?", (key,))

    def corrections_sync(self, data: dict):
        rows = [(k, v.get("question", ""), v.get("options", ""),
                 v.get("qtype", "single"), v.get("answer", ""),
                 v.get("note", ""), v.get("ts") or time.time(),
                 int(v.get("hits") or 0)) for k, v in data.items()]
        if rows:
            self._execmany(
                "INSERT INTO corrections(key,question,options,qtype,answer,note,ts,hits) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
                "answer=excluded.answer, note=excluded.note, question=excluded.question, "
                "hits=excluded.hits", rows)

    def bank_hit(self, key: str):
        """命中计数单行自增（约 0.05ms），替代原来的全量重写。"""
        self._exec("UPDATE bank SET hits=hits+1 WHERE key=?", (key,))

    def correction_hit(self, key: str):
        self._exec("UPDATE corrections SET hits=hits+1 WHERE key=?", (key,))

    def corrections_clear(self):
        self._exec("DELETE FROM corrections")

    # ---------------- 缓存（L2） ----------------
    def cache_get(self, key: str, ttl: float = 0):
        rows = self._query("SELECT payload, ts FROM cache WHERE key=?", (key,))
        if not rows:
            return None
        r = rows[0]
        if ttl and (time.time() - (r["ts"] or 0)) > ttl:
            self._exec("DELETE FROM cache WHERE key=?", (key,))
            return None
        try:
            return json.loads(r["payload"])
        except Exception:
            return None

    def cache_put(self, key: str, payload: dict):
        self._exec(
            "INSERT INTO cache(key,payload,ts,hits) VALUES(?,?,?,1) "
            "ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, ts=excluded.ts, "
            "hits=cache.hits+1",
            (key, json.dumps(payload, ensure_ascii=False), time.time()),
        )

    def cache_touch(self, key: str):
        self._exec("UPDATE cache SET hits=hits+1 WHERE key=?", (key,))

    def cache_count(self) -> int:
        r = self._query("SELECT COUNT(*) c FROM cache")
        return r[0]["c"] if r else 0

    def cache_clear(self):
        self._exec("DELETE FROM cache")

    def cache_purge(self, ttl: float):
        if ttl > 0:
            self._exec("DELETE FROM cache WHERE ts < ?", (time.time() - ttl,))

    # ---------------- 历史 ----------------
    def history_add(self, rec: dict):
        cur = self._exec(
            "INSERT INTO history(ts,question,options,answer,route,model,verify,cost,verified) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (rec.get("t") or time.time(), rec.get("q", ""),
             json.dumps(rec.get("opts") or [], ensure_ascii=False),
             rec.get("a", ""), rec.get("route", ""), rec.get("model", ""),
             rec.get("verify", ""), float(rec.get("cost") or 0),
             1 if rec.get("verified") else 0),
        )
        return cur.lastrowid

    def history_recent(self, limit: int = 200) -> list:
        rows = self._query("SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,))
        return [self._row_to_hist(r) for r in rows]

    def history_count(self) -> int:
        r = self._query("SELECT COUNT(*) c FROM history")
        return r[0]["c"] if r else 0

    def _row_to_hist(self, r) -> dict:
        try:
            opts = json.loads(r["options"] or "[]")
        except Exception:
            opts = []
        return {"id": r["id"], "t": r["ts"], "q": r["question"], "opts": opts,
                "a": r["answer"], "route": r["route"], "model": r["model"],
                "verify": r["verify"], "cost": r["cost"], "status": r["status"] if "status" in r.keys() else ""}

    def history_candidates(self, limit: int = 200) -> list:
        """待人工确认入库的候选：未处理 + 非题库/缓存来源（模型真实答过的题）。"""
        rows = self._query(
            "SELECT * FROM history WHERE (status IS NULL OR status='') "
            "AND route NOT IN ('bank','cache','rag') ORDER BY id DESC LIMIT ?", (limit,))
        return [self._row_to_hist(r) for r in rows]

    def history_set_status(self, ids: list, status: str) -> int:
        if not ids:
            return 0
        q = ",".join("?" * len(ids))
        cur = self._exec(f"UPDATE history SET status=? WHERE id IN ({q})",
                         [status] + [int(i) for i in ids])
        return cur.rowcount

    # ---------------- 抽样核对 / 答错标记 ----------------
    def quiz_sample(self, n: int = 30) -> list:
        """抽最近 n 条未被标记过对错的历史题，供人工核对。"""
        rows = self._query(
            "SELECT h.* FROM history h WHERE h.id NOT IN "
            "(SELECT hist_id FROM quiz WHERE hist_id IS NOT NULL) "
            "ORDER BY h.id DESC LIMIT ?", (int(n),))
        return [self._row_to_hist(r) for r in rows]

    def quiz_mark(self, hist_id: int, correct: bool, src: str = "quiz"):
        self._exec("DELETE FROM quiz WHERE hist_id=?", (int(hist_id),))
        self._exec("INSERT INTO quiz(ts,hist_id,correct,src) VALUES(?,?,?,?)",
                   (time.time(), int(hist_id), 1 if correct else 0, src))

    def quiz_stats(self, days: int = 14) -> dict:
        since = time.time() - days * 86400
        total = self._query("SELECT COUNT(*) c, SUM(correct) ok FROM quiz WHERE hist_id IS NOT NULL")
        t = total[0] if total else None
        recent = self._query("SELECT COUNT(*) c, SUM(correct) ok FROM quiz WHERE hist_id IS NOT NULL AND ts>=?", (since,))
        r = recent[0] if recent else None
        by_day = {}
        for row in self._query(
                "SELECT date(ts,'unixepoch','localtime') d, COUNT(*) c, SUM(correct) ok "
                "FROM quiz WHERE hist_id IS NOT NULL GROUP BY d ORDER BY d DESC LIMIT ?", (days,)):
            by_day[row["d"]] = {"total": row["c"], "ok": row["ok"] or 0}
        return {
            "total": (t["c"] if t else 0) or 0,
            "ok": (t["ok"] if t else 0) or 0,
            "acc": round(((t["ok"] or 0) / t["c"]) * 100, 1) if t and t["c"] else None,
            "recent_total": (r["c"] if r else 0) or 0,
            "recent_acc": round(((r["ok"] or 0) / r["c"]) * 100, 1) if r and r["c"] else None,
            "by_day": by_day,
        }

    # ---------------- 首页摘要（人话） ----------------
    def today_summary(self) -> dict:
        """今天答了多少、平均多久、抽查正确率多少 —— 首页只显示这三个数。"""
        lt = time.localtime()
        start = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                             0, 0, 0, 0, 0, -1))
        m = self._query(
            "SELECT COUNT(*) c, AVG(ms) a, "
            "SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END) ok "
            "FROM metrics WHERE ts>=?", (start,))
        q = self._query(
            "SELECT COUNT(*) c, COALESCE(SUM(correct),0) ok FROM quiz WHERE ts>=?",
            (start,))
        cnt = (m[0]["c"] if m else 0) or 0
        avg = (m[0]["a"] if m else 0) or 0
        ok = (m[0]["ok"] if m else 0) or 0
        qt = (q[0]["c"] if q else 0) or 0
        qok = (q[0]["ok"] if q else 0) or 0
        return {
            "answered": cnt,
            "ok": ok,
            "avg_ms": round(avg, 0),
            "checked": qt,
            "correct": qok,
            "acc": round(qok / qt * 100, 1) if qt else None,
        }

    # ---------------- 指标 ----------------
    def metric_add(self, kind: str, route: str, ms: float, ok: bool, cached: bool):
        self._exec(
            "INSERT INTO metrics(ts,kind,route,ms,ok,cached) VALUES(?,?,?,?,?,?)",
            (time.time(), kind, route, round(ms, 1), 1 if ok else 0,
             1 if cached else 0),
        )

    def metrics_summary(self, hours: float = 24) -> dict:
        since = time.time() - hours * 3600
        rows = self._query("SELECT route, ms, ok, cached FROM metrics WHERE ts>=?", (since,))
        n = len(rows)
        out = {"count": n, "p50": 0, "p95": 0, "avg": 0, "ok_rate": 0,
               "cached_rate": 0, "routes": {}}
        if not n:
            return out
        ms = sorted(r["ms"] or 0 for r in rows)
        out["p50"] = round(ms[int(n * 0.5)], 1)
        out["p95"] = round(ms[min(n - 1, int(n * 0.95))], 1)
        out["avg"] = round(sum(ms) / n, 1)
        out["ok_rate"] = round(sum(1 for r in rows if r["ok"]) / n, 3)
        out["cached_rate"] = round(sum(1 for r in rows if r["cached"]) / n, 3)
        routes = {}
        for r in rows:
            k = r["route"] or "text"
            routes[k] = routes.get(k, 0) + 1
        out["routes"] = routes
        return out

    # ---------------- 杂项 ----------------
    def meta_set(self, k: str, v: str):
        self._exec("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))

    def meta_get(self, k: str, default: str = "") -> str:
        rows = self._query("SELECT v FROM meta WHERE k=?", (k,))
        return rows[0]["v"] if rows else default

    def vacuum(self):
        with self._lock:
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.db.execute("VACUUM")
            self.db.commit()


def migrate_json(store: Store, bank_path: str, corr_path: str, history_path: str) -> dict:
    """把旧的 bank.json / corrections.json / history.jsonl 迁进 SQLite。
    幂等：只在目标表为空时导入，重复启动不会翻倍。"""
    stats = {"bank": 0, "corrections": 0, "history": 0}

    if store.bank_count() == 0 and os.path.exists(bank_path):
        try:
            with open(bank_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, dict):
                        store.bank_upsert(k, v)
                        stats["bank"] += 1
        except Exception:
            pass

    try:
        has_c = store._query("SELECT COUNT(*) c FROM corrections")[0]["c"]
    except Exception:
        has_c = 0
    if has_c == 0 and os.path.exists(corr_path):
        try:
            with open(corr_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, dict):
                        store.correction_upsert(k, v)
                        stats["corrections"] += 1
        except Exception:
            pass

    if store.history_count() == 0 and os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(rec, dict) and rec.get("q"):
                        store.history_add(rec)
                        stats["history"] += 1
        except Exception:
            pass

    return stats
