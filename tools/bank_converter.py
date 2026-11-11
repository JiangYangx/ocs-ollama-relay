#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
题库转换器 —— 把外部题库文件转成 JY 答题助手认识的格式，并可一键推送进服务。

支持三种输入（自动识别）：
  1) CMMLU / C-Eval / MMLU 风格 CSV：列名含 Question 与 A/B/C/D 与 Answer
  2) 通用 CSV/XLSX：题干, 答案, 选项（选项用 | 分隔）
  3) 纯文本 TXT：常见题库排版
        1. 题干内容
        A. 选项一
        B. 选项二
        答案：A
     也支持单行形式：题干 A. x B. y 答案：A

输出格式（默认 CSV，与 /api/bank/import 的 CSV 分支完全对齐）：
    题干,答案,选项1|选项2|选项3

用法：
    # 转换整个目录（递归找 csv/txt）
    python tools/bank_converter.py cmmlu/test -o bank.csv

    # 只要某些科目
    python tools/bank_converter.py cmmlu/test -o bank.csv --subject college,computer,law

    # 转换完直接推进运行中的服务（会自动分批）
    python tools/bank_converter.py cmmlu/test -o bank.csv --push http://127.0.0.1:5000

    # 只看不写
    python tools/bank_converter.py cmmlu/test --dry-run
"""
import argparse
import csv
import glob
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request

LETTERS = "ABCDEFGH"
# 单行题：题干 A. xx B. yy C. zz 答案：A
OPT_INLINE = re.compile(r"(?:(?<=\s)|^)([A-H])\s*[.．、:：\)）]\s*")
ANS_PAT = re.compile(
    r"^\s*(?:【\s*)?(?:参考|正确)?答案\s*】?\s*[:：]?\s*([A-H]|[^\s，。；、]{1,60})\s*$", re.I)
QNO_PAT = re.compile(r"^\s*(?:第\s*\d+\s*题|\d+\s*[.．、\)）])\s*")
Q_PREFIX = re.compile(r"^\s*(?:判断题|单选题|多选题|选择题|填空题|简答题)\s*[:：]\s*")
TYPE_PAT = re.compile(r"^\s*[\[【(（]\s*(单选|多选|判断|填空|简答)[^\]】)）]*[\]】)）]\s*")
JUDGE_TRUE = ("正确", "对", "√", "T", "True", "是", "A")
JUDGE_FALSE = ("错误", "错", "×", "F", "False", "否", "B")


def clean(s: str) -> str:
    """压掉换行与多余空白。注意：不动 `|`，它是列分隔符，替换掉会让列判断失效。"""
    if s is None:
        return ""
    s = str(s).replace("\r", " ").replace("\n", " ")
    return re.sub(r"[ \t\u3000]+", " ", s).strip()


def flat(s: str) -> str:
    """写进单行/CSV 字段前调用：把 `|` 换成 `/`，避免破坏选项分隔。"""
    return clean(s).replace("|", "/")


def is_header(row) -> bool:
    joined = " ".join(str(c) for c in row).lower()
    return ("question" in joined or "题干" in joined or "题目" in joined)


# ---------------------------------------------------------------- CSV 分支
def read_cmmlu(path: str):
    """CMMLU / C-Eval / MMLU 风格：Question + A/B/C/D + Answer"""
    out = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        cols = {c.strip().lower(): c for c in (rd.fieldnames or []) if c}
        qcol = next((cols[k] for k in ("question", "题干", "题目", "q") if k in cols), None)
        acol = next((cols[k] for k in ("answer", "答案", "a_key", "correct") if k in cols), None)
        if not qcol or not acol:
            return None
        optcols = [cols[k] for k in ("a", "b", "c", "d", "e", "f") if k in cols]
        if not optcols:
            return None
        for r in rd:
            q = clean(r.get(qcol, ""))
            a = clean(r.get(acol, "")).upper()
            opts = []
            for i, c in enumerate(optcols):
                t = clean(r.get(c, ""))
                if t:
                    opts.append("%s. %s" % (LETTERS[i], t))
            if q and a and len(opts) >= 2:
                out.append((q, a, opts))
    return out


def read_plain_csv(path: str):
    """通用 CSV：题干,答案,选项(|分隔)  或 题干,选项1,选项2,...,答案"""
    out = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.reader(f) if any(str(c).strip() for c in r)]
    for i, raw in enumerate(rows):
        raw = [str(c) for c in raw]
        if i == 0 and is_header(raw):
            continue
        if len(raw) < 2:
            continue
        q = clean(raw[0])
        if len(raw) == 2:
            out.append((q, clean(raw[1]).upper(), []))
            continue
        third = raw[2]
        if "|" in third:
            # 题干, 答案, 选项(|分隔)
            opts = [clean(x) for x in third.split("|") if x.strip()]
            out.append((q, clean(raw[1]).upper(), opts))
        else:
            # 题干, 选项..., 答案
            a = clean(raw[-1]).upper()
            opts = []
            for o in raw[1:-1]:
                t = clean(re.sub(r"^[A-H]\s*[.．、\)）]\s*", "", o))
                if t:
                    opts.append("%s. %s" % (LETTERS[len(opts)], t))
            if opts:
                out.append((q, a, opts))
    return out


# ---------------------------------------------------------------- 文本分支
def parse_block(chunk: list[str]):
    """解析一块文本（题干 + 选项行 + 答案行）。"""
    text = "\n".join(chunk).strip()
    if not text:
        return None

    # 抽出答案行（整行就是答案，不是"A. xxx"这种选项行）
    ans = ""
    lines = []
    for ln in text.split("\n"):
        s = ln.strip()
        mm = ANS_PAT.match(s)
        if mm and not re.match(r"^[A-H]\s*[.．、:：\)）]", s):
            ans = mm.group(1).strip()
            continue
        lines.append(ln)
    body = "\n".join(lines).strip()
    if not body:
        return None

    qtype = "single"
    tm = TYPE_PAT.match(body)
    if tm:
        qtype = {"单选": "single", "多选": "multi", "判断": "judge"}.get(tm.group(1), "single")
        body = body[tm.end():]

    # 逐行区分：题干行 / 选项行（选项续行并入上一项）
    qlines, opts, cur = [], [], None
    for ln in body.split("\n"):
        s = ln.strip()
        if not s:
            continue
        om = re.match(r"^([A-H])\s*[.．、:：\)）]\s*(.*)$", s)
        if om:
            if cur is not None:
                opts.append(cur)
            cur = "%s. %s" % (om.group(1), clean(om.group(2)))
        elif cur is not None:
            cur += " " + clean(s)
        else:
            qlines.append(s)
    if cur is not None:
        opts.append(cur)

    qtext = " ".join(qlines)
    # 没有独立选项行时，尝试单行拆：题干 A. x B. y C. z
    if not opts:
        flat = re.sub(r"\s+", " ", body).strip()
        parts = OPT_INLINE.split(flat)
        if len(parts) >= 5:
            qtext = parts[0]
            for i in range(1, len(parts) - 1, 2):
                opts.append("%s. %s" % (parts[i], clean(parts[i + 1])))

    q = clean(QNO_PAT.sub("", clean(qtext)).strip())
    q = Q_PREFIX.sub("", QNO_PAT.sub("", q).strip()).strip()

    if qtype == "judge" or (not opts and ans in JUDGE_TRUE + JUDGE_FALSE):
        qtype = "judge"
        if not ans:
            return None
        opts = ["A. 正确", "B. 错误"]
        ans = "A" if ans in JUDGE_TRUE else "B"
    a = ans.upper() if ans else ""
    if a and a not in LETTERS:
        # 答案写成了选项原文，反查是第几个
        for o in opts:
            if clean(o[2:]) == clean(ans):
                a = o[0]
                break
    if not q or not a or len(opts) < 2:
        return None
    return (q, a, opts)


def read_txt(path: str):
    out = []
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        raw = f.read().replace("\r\n", "\n").replace("\r", "\n")
    chunks, cur = [], []
    for ln in raw.split("\n"):
        s = ln.strip()
        if not s:
            if cur:
                chunks.append(cur)
                cur = []
            continue
        # 新题开始：编号开头 且 当前块里已经有答案
        if QNO_PAT.match(s) and cur and any(ANS_PAT.match(x.strip()) for x in cur):
            chunks.append(cur)
            cur = [s]
            continue
        cur.append(s)
    if cur:
        chunks.append(cur)
    for c in chunks:
        r = parse_block(c)
        if r:
            out.append(r)
    return out


# ---------------------------------------------------------------- 主流程
def collect(paths, subject_kw):
    files = []
    for p in paths:
        if os.path.isdir(p):
            for ext in ("csv", "txt"):
                files += glob.glob(os.path.join(p, "**", "*." + ext), recursive=True)
        else:
            files.append(p)
    items, stats = [], []
    for f in sorted(set(files)):
        name = os.path.basename(f).lower()
        if subject_kw and not any(k.lower() in name for k in subject_kw):
            continue
        try:
            if f.lower().endswith(".csv"):
                r = read_cmmlu(f)
                if r is None:
                    r = read_plain_csv(f)
            else:
                r = read_txt(f)
        except Exception as e:
            stats.append((name, -1, str(e)))
            continue
        r = r or []
        if r:
            items += r
        stats.append((name, len(r), ""))
    return items, stats


def write_csv(items, out_path):
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["题干", "答案", "选项"])
        for q, a, opts in items:
            w.writerow([flat(q), flat(a), "|".join(flat(o) for o in opts)])


def push(items, base, batch=500):
    """分批推送到 /api/bank/import（multipart 上传 CSV 文件）。

    走文件上传而不是 JSON items：CSV 分支的列定义最稳，
    老版本 exe 的 JSON 分支在批量时会把选项当成答案串，别踩。
    """
    base = base.rstrip("/")
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    ok = fail = 0
    for i in range(0, len(items), batch):
        chunk = items[i:i + batch]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["题干", "答案", "选项"])
        for q, a, opts in chunk:
            w.writerow([flat(q), flat(a), "|".join(flat(o) for o in opts)])
        payload = buf.getvalue().encode("utf-8-sig")

        boundary = "----JYBank%s" % os.urandom(6).hex()
        body = b"".join([
            b"--" + boundary.encode() + b"\r\n",
            b'Content-Disposition: form-data; name="file"; filename="bank.csv"\r\n',
            b"Content-Type: text/csv\r\n\r\n",
            payload, b"\r\n",
            b"--" + boundary.encode() + b"--\r\n",
        ])
        req = urllib.request.Request(
            base + "/api/bank/import", data=body,
            headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
        try:
            d = json.load(op.open(req, timeout=180))
            if not d.get("ok", True):
                raise RuntimeError(d.get("message") or "服务返回失败")
            ok += d.get("added", 0) + d.get("updated", 0)
            print("  批次 %d-%d：新增 %s 更新 %s，库内 %s"
                  % (i + 1, i + len(chunk), d.get("added"), d.get("updated"), d.get("total")))
        except Exception as e:
            fail += len(chunk)
            print("  批次 %d-%d 失败：%s" % (i + 1, i + len(chunk), e))
    return ok, fail


def main():
    ap = argparse.ArgumentParser(description="题库转换器（转成 JY 答题助手格式）")
    ap.add_argument("paths", nargs="+", help="题库文件或目录")
    ap.add_argument("-o", "--out", default="bank.csv", help="输出 CSV 路径")
    ap.add_argument("--subject", default="", help="只保留文件名含这些关键字的（逗号分隔）")
    ap.add_argument("--push", default="", help="转换后推送到服务，如 http://127.0.0.1:5000")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写文件")
    a = ap.parse_args()

    kw = [x.strip() for x in a.subject.split(",") if x.strip()]
    items, stats = collect(a.paths, kw)
    hit = [s for s in stats if s[1] > 0]
    print("扫描 %d 个文件，解析出 %d 道题（%d 个文件有效）"
          % (len(stats), len(items), len(hit)))
    for name, n, err in stats[:10]:
        print("  %-42s %5s %s" % (name, n, err))
    if len(stats) > 10:
        print("  ... 其余 %d 个文件" % (len(stats) - 10))
    if not items:
        print("没有解析出题目，检查格式")
        return 1
    print("\n示例：")
    for q, ans, opts in items[:3]:
        print("  Q: %s" % q[:60])
        print("     选项 %d 个，答案 %s" % (len(opts), ans))

    if a.dry_run:
        return 0
    write_csv(items, a.out)
    print("\n已写出 %s（%d 条）" % (a.out, len(items)))
    if a.push:
        print("\n推送到 %s ..." % a.push)
        ok, fail = push(items, a.push)
        print("完成：成功 %d，失败 %d" % (ok, fail))
    return 0


if __name__ == "__main__":
    sys.exit(main())
