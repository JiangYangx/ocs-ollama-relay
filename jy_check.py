#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jy_check —— 答案自检（v1.3）

模型偶发的低级错误，规则就能拦住，不必再问一遍模型：
  1. 空答案 / 只有标点 / 只有"答案："前缀
  2. 字母越界：选项只有 A~D，却答了 E
  3. 多选题只给了一个字母（大概率漏选）
  4. 答案里混进解释文字、重复题目

分级：
  fixable  可以自动修正（裁剪越界字母、去解释）
  retry    建议重答一次（空、全越界、多选漏选）
  ok       通过
"""
from __future__ import annotations

import re

LETTERS = "ABCDEFGH"

_JUNK = re.compile(r"^(答案|正确答案|answer)\s*[:：]?\s*", re.I)
_TAIL = re.compile(r"(解析|分析|理由|说明|备注)\s*[:：].*$", re.S)
_PUNCT_ONLY = re.compile(r"^[\s\.\,，。;；:：!！?？\-—_、·\*#`~\"'“”‘’()（）\[\]【】]*$")


def _norm(s: str) -> str:
    s = (s or "").strip().rstrip("。．.；;，,")
    s = re.sub(r"\s+", "", s)
    return s.lower()


def check(answer: str, options: list, qtype: str = "", question: str = "") -> dict:
    """返回 {status, answer, reason}。status: ok / fixed / retry"""
    raw = (answer or "").strip()
    if not raw or _PUNCT_ONLY.match(raw):
        return {"status": "retry", "answer": "", "reason": "空答案"}

    a = _JUNK.sub("", raw).strip()
    # 去掉「解析：」之后的内容
    a = _TAIL.sub("", a).strip()

    # 重复题干（模型把题抄了一遍）
    if question and len(a) > 30:
        head = re.sub(r"\s+", "", question)[:20]
        if head and head in re.sub(r"\s+", "", a):
            a = a.replace(question, "").strip()
            a = _JUNK.sub("", a).strip()

    if not a or _PUNCT_ONLY.match(a):
        return {"status": "retry", "answer": "", "reason": "答案只有标点或前缀"}

    letters = re.sub(r"[^A-Ha-h]", "", a).upper()
    valid = set()
    for o in (options or []):
        lt = (o.get("letter") if isinstance(o, dict) else "") or ""
        if lt:
            valid.add(lt.upper())

    is_multi = (qtype or "").lower() in ("multiple", "multi")

    # 纯字母答案（如 "AC"）
    if letters and len(letters) >= len(a.strip()) - 2 and not re.search(r"[\u4e00-\u9fff]", a):
        if valid:
            keep = "".join(sorted(set(x for x in letters if x in valid)))
            drop = [x for x in set(letters) if x not in valid]
            if not keep:
                return {"status": "retry", "answer": a,
                        "reason": f"答案字母 {''.join(sorted(set(letters)))} 全部超出选项范围"}
            if drop:
                return {"status": "fixed", "answer": keep,
                        "reason": f"剔除不存在的选项字母 {''.join(sorted(drop))}"}
            if is_multi and len(keep) < 2:
                return {"status": "retry", "answer": keep,
                        "reason": "多选题只给出一个选项，可能漏选"}
            if keep != letters:
                return {"status": "fixed", "answer": keep, "reason": "字母顺序规范化"}
        return {"status": "ok", "answer": a, "reason": ""}

    # 文本答案：若含字母但字母越界，至少提示
    if letters and valid:
        bad = set(letters) - valid
        if bad and len(a) <= 6:
            return {"status": "retry", "answer": a,
                    "reason": f"答案含不存在的选项 {''.join(sorted(bad))}"}

    # v1.3：答案文字完全落在选项之外 —— 大概率是模型自造了一个选项
    # （例如只有 A~D 却答「成都」）。填空题不适用。
    if valid and (qtype or "").lower() not in ("completion", "fill", "blank"):
        texts = [_norm(o.get("text", "")) for o in (options or []) if isinstance(o, dict)]
        na = _norm(a)
        if na and texts and len(na) <= 40:
            hit = any(na == t or (t and (na in t or t in na)) for t in texts)
            if not hit:
                return {"status": "retry", "answer": a,
                        "reason": "答案不在给定选项范围内"}

    return {"status": "ok", "answer": a, "reason": ""}


def retry_prompt(prompt: str, reason: str, options: list) -> str:
    """重答时追加的自纠正指令。"""
    letters = "".join((o.get("letter") if isinstance(o, dict) else "")
                      for o in (options or [])) or "ABCD"
    return (
        f"{prompt}\n"
        f"【上次作答不合格：{reason}】\n"
        f"本题只有 {letters} 这些选项。请只输出正确选项的完整文字，"
        f"多选题输出所有正确项，每行一个，不要输出解释。\n答案："
    )
