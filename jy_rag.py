#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jy_rag —— 相似题检索（v1.3）

为什么需要它：
  题库精确命中要求题干一字不差，真实命中率只有几个百分点。
  相似题检索能把「同一考点、不同表述」的题找出来，把它的答案和解析
  作为参考喂给模型，正确率实打实提升 5~10 个点。

两种后端：
  ngram（默认，零依赖）  字符 2-gram + IDF 加权余弦，纯标准库
  vector（可选）         外部 embedding（如 Ollama 的 bge-m3 / bge-small-zh），
                         需要 numpy；没装则自动回落 ngram

阈值语义（可配置）：
  score >= rag_direct  直接采用，不再问模型
  rag_inject <= score < rag_direct  作为参考注入提示词
  score < rag_inject   忽略
注意：阈值必须随 embedding 模型变化重新校准，换模型后先跑一批样本看分布。
"""
from __future__ import annotations

import math
import os
import pickle
import re
import threading
from collections import Counter

try:
    import numpy as _np
except Exception:
    _np = None

_SPLIT = re.compile(r"[\s\u3000,，。;；:：!！?？、\"'“”‘’()（）\[\]【】<>《》/\\|-]+")
_STOP = set("的 了 和 与 及 或 是 在 有 对 为 中 上 下 这 那 其 请 问 下列 关于 以下 说法 正确 错误".split())


def _grams(text: str) -> list:
    """中文按字符 2-gram，英文/数字按词。去停用词。"""
    t = (text or "").lower()
    t = re.sub(r"[a-z0-9\.\+\#]+", lambda m: " " + m.group(0) + " ", t)
    out = []
    for seg in _SPLIT.split(t):
        seg = seg.strip()
        if not seg:
            continue
        if re.fullmatch(r"[a-z0-9\.\+\#\-]+", seg):
            if seg not in _STOP and len(seg) > 1:
                out.append("w:" + seg)
            continue
        seg = re.sub(r"[^\u4e00-\u9fff]", "", seg)
        if len(seg) == 1:
            if seg not in _STOP:
                out.append("u:" + seg)
            continue
        for i in range(len(seg) - 1):
            g = seg[i:i + 2]
            if g not in _STOP:
                out.append(g)
    return out


class RagIndex:
    def __init__(self):
        self.rows = []            # [{key,question,answer,...}]
        self.vecs = []            # ngram: Counter；vector: list/np.array
        self.idf = {}
        self.inv = {}             # gram -> set(doc idx)
        self.matrix = None        # vector 模式的归一化矩阵
        self.backend = "ngram"
        self.lock = threading.RLock()
        self.signature = ""       # 题库指纹，变了就重建

    # ---------------- 构建 ----------------
    def build(self, rows: list, backend: str = "ngram", embed_fn=None) -> dict:
        """rows: [{key,question,answer,qtype,options,src}]"""
        with self.lock:
            self.rows = [r for r in rows if (r.get("question") or "").strip()
                         and (r.get("answer") or "").strip()]
            self.backend = backend if (backend == "vector" and embed_fn and _np is not None) else "ngram"

            if self.backend == "vector":
                try:
                    return self._build_vector(embed_fn)
                except Exception:
                    self.backend = "ngram"

            self._build_ngram()
            return {"backend": self.backend, "docs": len(self.rows),
                    "grams": len(self.inv)}

    def _build_ngram(self):
        self.vecs, self.inv = [], {}
        df = Counter()
        for i, r in enumerate(self.rows):
            c = Counter(_grams(r["question"]))
            self.vecs.append(c)
            for g in c:
                df[g] += 1
                self.inv.setdefault(g, set()).add(i)
        n = max(1, len(self.rows))
        self.idf = {g: math.log(1 + n / (1 + d)) for g, d in df.items()}
        # 预计算每篇的加权范数
        self.norm = []
        for c in self.vecs:
            s = sum((cnt * self.idf.get(g, 0)) ** 2 for g, cnt in c.items())
            self.norm.append(math.sqrt(s) or 1.0)

    def _build_vector(self, embed_fn):
        self.embed_fn_ref = embed_fn
        vecs = []
        for r in self.rows:
            v = embed_fn(r["question"])
            if not v:
                raise RuntimeError("embedding 返回空")
            vecs.append(v)
        m = _np.array(vecs, dtype="float32")
        m /= (_np.linalg.norm(m, axis=1, keepdims=True) + 1e-8)
        self.matrix = m
        return {"backend": "vector", "docs": len(self.rows), "dim": int(m.shape[1])}

    # ---------------- 检索 ----------------
    def search(self, query: str, top_k: int = 3) -> list:
        """返回 [(score, row)]，score 归一到 0~1。"""
        with self.lock:
            if not self.rows:
                return []
            if self.backend == "vector" and self.matrix is not None:
                return self._search_vector(query, top_k)
            return self._search_ngram(query, top_k)

    def _search_ngram(self, query: str, top_k: int):
        qc = Counter(_grams(query))
        if not qc:
            return []
        cand = Counter()
        for g in qc:
            for i in self.inv.get(g, ()):      # 倒排取候选
                cand[i] += 1
        if not cand:
            return []
        # 候选截断，保证大题库也是毫秒级
        pool = [i for i, _ in cand.most_common(400)]

        qw = {g: cnt * self.idf.get(g, 0) for g, cnt in qc.items()}
        qnorm = math.sqrt(sum(v * v for v in qw.values())) or 1.0

        scores = []
        for i in pool:
            c = self.vecs[i]
            s = 0.0
            for g, w in qw.items():
                if g in c:
                    s += w * c[g] * self.idf.get(g, 0)
            if s > 0:
                scores.append((s / (qnorm * self.norm[i]), i))
        scores.sort(reverse=True)
        return [(round(sc, 4), self.rows[i]) for sc, i in scores[:top_k]]

    def _search_vector(self, query: str, top_k: int):
        v = _np.asarray(self.embed_fn_ref(query), dtype="float32")
        v /= (_np.linalg.norm(v) + 1e-8)
        sims = self.matrix @ v
        idx = _np.argsort(-sims)[:top_k]
        return [(round(float(sims[i]), 4), self.rows[int(i)]) for i in idx]

    # ---------------- 持久化 ----------------
    def save(self, path: str, signature: str = ""):
        try:
            with open(path, "wb") as f:
                pickle.dump({"rows": self.rows, "backend": self.backend,
                             "signature": signature, "matrix": self.matrix,
                             "inv": self.inv, "vecs": self.vecs,
                             "idf": self.idf, "norm": getattr(self, "norm", [])},
                            f, protocol=pickle.HIGHEST_PROTOCOL)
            return True
        except Exception:
            return False

    def load(self, path: str, signature: str = "") -> bool:
        if not os.path.exists(path):
            return False
        try:
            with open(path, "rb") as f:
                d = pickle.load(f)
            if signature and d.get("signature") != signature:
                return False
            self.rows = d.get("rows") or []
            self.backend = d.get("backend") or "ngram"
            self.matrix = d.get("matrix")
            self.inv = d.get("inv") or {}
            self.vecs = d.get("vecs") or []
            self.idf = d.get("idf") or {}
            self.norm = d.get("norm") or [1.0] * len(self.rows)
            self.signature = d.get("signature", "")
            return bool(self.rows)
        except Exception:
            return False


def make_embed_fn(base_url: str, model: str, timeout: float = 20.0):
    """用 Ollama 的 /api/embeddings 做向量化（需本地已有 bge-m3 等模型）。
    失败由调用方捕获并回落 ngram。"""
    import requests

    sess = requests.Session()

    def fn(text: str):
        r = sess.post(f"{base_url.rstrip('/')}/api/embeddings",
                      json={"model": model, "prompt": text[:2000]},
                      timeout=timeout)
        r.raise_for_status()
        v = (r.json() or {}).get("embedding")
        if not v:
            raise RuntimeError("embedding 为空")
        return v

    return fn


def split_reference(results: list, direct: float, inject: float) -> tuple:
    """把检索结果分成 (可直接采用, 仅供参考) 两档。"""
    use, ref = None, []
    for score, row in results:
        if score >= direct and use is None:
            use = (score, row)
        elif score >= inject:
            ref.append((score, row))
    return use, ref


def format_reference(ref: list, limit: int = 2) -> str:
    """把参考题拼成提示词片段。"""
    if not ref:
        return ""
    lines = ["【参考：题库中的相似题，仅供判断考点，不要照抄】"]
    for score, row in ref[:limit]:
        opts = row.get("options") or []
        if isinstance(opts, str):
            try:
                import json
                opts = json.loads(opts)
            except Exception:
                opts = []
        lines.append(f"- 相似度 {score:.2f}｜题目：{(row.get('question') or '')[:120]}")
        if opts:
            lines.append("  选项：" + " / ".join(str(o)[:30] for o in opts[:6]))
        lines.append(f"  该题答案：{(row.get('answer') or '')[:60]}")
    return "\n".join(lines) + "\n"
