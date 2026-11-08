#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 CSV / TSV / Excel / TXT 转成 JY Relay 能导入的题库格式。

用法：
    python tools/make_bank.py 题库.xlsx                 # 输出 题库.bank.txt
    python tools/make_bank.py 题库.csv -o bank.txt
    python tools/make_bank.py 题库.xlsx --json bank.json   # 直接生成 bank.json

输出的 .txt 可以直接粘进控制台「题库与订正 → 导入题库」，
也可以放到程序目录后用 /api/bank 接口导入。

列名自动识别（中英文、大小写都行）：
    题干  question / title / 题目 / 题干 / 问题 / q
    选项  options / 选项 / opts                （一格内用换行、|、；分隔均可）
          或分成多列：A / B / C / D，选项A / 选项B ...
    答案  answer / 答案 / 正确答案 / a

答案写字母（B）或写选项原文（北京）都可以，两种都能被匹配。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys

Q_NAMES = {"question", "title", "题目", "题干", "问题", "q", "试题", "题目内容"}
A_NAMES = {"answer", "答案", "正确答案", "a", "参考答案", "正确选项"}
O_NAMES = {"options", "option", "选项", "opts", "备选项", "选项内容"}
LETTERS = "ABCDEFGH"


# --------------------------------------------------------------------------- #
# 读文件
# --------------------------------------------------------------------------- #
def _read_csv(path: str) -> list[dict]:
    last = None
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                sample = f.read(4096)
                f.seek(0)
                delim = "\t" if path.lower().endswith((".tsv", ".tab")) else None
                if delim is None:
                    try:
                        delim = csv.Sniffer().sniff(sample, delimiters=",\t;").delimiter
                    except Exception:
                        delim = ","
                return [dict(r) for r in csv.DictReader(f, delimiter=delim)]
        except UnicodeDecodeError as e:
            last = e
    raise SystemExit(f"无法识别编码：{path}（{last}）")


def _read_xlsx(path: str) -> list[dict]:
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise SystemExit("读取 Excel 需要 openpyxl：pip install openpyxl")
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    head = [str(c).strip() if c is not None else "" for c in rows[0]]
    out = []
    for r in rows[1:]:
        if r is None or all(c in (None, "") for c in r):
            continue
        out.append({head[i] if i < len(head) else f"col{i}": r[i]
                    for i in range(len(r))})
    return out


def read_rows(path: str) -> list[dict]:
    low = path.lower()
    if low.endswith((".xlsx", ".xlsm")):
        return _read_xlsx(path)
    if low.endswith((".csv", ".tsv", ".tab", ".txt")):
        return _read_csv(path)
    raise SystemExit(f"不支持的格式：{path}（用 .csv / .tsv / .xlsx）")


# --------------------------------------------------------------------------- #
# 归一化
# --------------------------------------------------------------------------- #
def _pick(row: dict, names: set) -> str:
    for k, v in row.items():
        if k is None:
            continue
        if str(k).strip().lower() in names:
            return "" if v is None else str(v).strip()
    return ""


def _split_options(text: str) -> list[str]:
    parts = re.split(r"[\n\r|；;]+", text or "")
    out = []
    for p in parts:
        p = re.sub(r"^[A-Ha-h][.．、:：)）]\s*", "", p.strip())
        if p:
            out.append(p)
    return out


def _option_cols(row: dict) -> list[str]:
    """从 A/B/C/D 或 选项A 这类分列里取选项。"""
    got = {}
    for k, v in row.items():
        if k is None or v in (None, ""):
            continue
        ks = str(k).strip()
        m = re.match(r"^(?:选项|option)?\s*([A-Ha-h])$", ks, re.I)
        if m:
            got[m.group(1).upper()] = str(v).strip()
    return [got[c] for c in sorted(got)]


def to_entries(rows: list[dict]) -> tuple[list[dict], list[str]]:
    entries, errors = [], []
    for i, row in enumerate(rows, start=2):
        q = _pick(row, Q_NAMES)
        ans = _pick(row, A_NAMES)
        opts = _split_options(_pick(row, O_NAMES)) or _option_cols(row)
        if not q:
            errors.append(f"第 {i} 行：没有题干，已跳过")
            continue
        if not ans:
            errors.append(f"第 {i} 行：没有答案，已跳过")
            continue
        if not opts:
            errors.append(f"第 {i} 行：没有选项，已跳过（判断题请把「正确/错误」写成两个选项）")
            continue
        entries.append({"question": q, "options": opts, "answer": ans})
    return entries, errors


def _flat(s: str) -> str:
    """把多行内容压成一行：题库文本是按行解析的，题干/选项里残留的换行
    （常见于代码题）会被误判成新的题目或选项。"""
    return re.sub(r"[\r\n]+", " ", str(s or "")).strip()


def to_block_text(entries: list[dict]) -> str:
    blocks = []
    for e in entries:
        lines = [_flat(e["question"])]
        for idx, opt in enumerate(e["options"][:8]):
            lines.append(f"{LETTERS[idx]}. {_flat(opt)}")
        lines.append(f"答案：{_flat(e['answer'])}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


# --------------------------------------------------------------------------- #
# 生成 bank.json（与程序内部 key 算法保持一致）
# --------------------------------------------------------------------------- #
def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[\s\u3000，。、；：！？,.;:!?（）()\[\]【】\"'“”‘’《》<>]+", "", s)
    return s


def q_key(title: str, options: list[str]) -> str:
    sig = _norm(title)
    ot = _norm("".join(re.sub(r"^[A-Ha-h][.．、:：)）]\s*", "", o).strip() for o in options))
    if ot:
        sig += "#" + hashlib.md5(ot.encode()).hexdigest()[:8]
    return sig


def build_json(entries: list[dict]) -> dict:
    import time
    out = {}
    for e in entries:
        k = q_key(e["question"], e["options"])
        if not k:
            continue
        out[k] = {
            "answer": e["answer"], "options": e["options"],
            "qtype": "multiple" if len(re.sub(r"[^A-Ha-h]", "", e["answer"])) > 1 else "single",
            "ts": time.time(), "hits": 0, "src": "make_bank",
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="把表格转成 JY Relay 题库")
    ap.add_argument("input", help="源文件：.csv / .tsv / .xlsx")
    ap.add_argument("-o", "--output", help="输出的题库文本（默认 原名.bank.txt）")
    ap.add_argument("--json", metavar="PATH", help="直接生成 bank.json 到指定路径")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        raise SystemExit(f"文件不存在：{args.input}")

    rows = read_rows(args.input)
    entries, errors = to_entries(rows)

    print(f"读入 {len(rows)} 行 → 有效题目 {len(entries)} 条")
    if errors:
        print(f"跳过 {len(errors)} 行：")
        for e in errors[:10]:
            print("  ·", e)
        if len(errors) > 10:
            print(f"  … 其余 {len(errors) - 10} 行同理")

    if not entries:
        raise SystemExit("没有可用题目，检查列名是否为「题干 / 选项 / 答案」")

    out = args.output or os.path.splitext(args.input)[0] + ".bank.txt"
    with open(out, "w", encoding="utf-8") as f:
        f.write(to_block_text(entries))
    print(f"已写出题库文本：{out}")
    print("  → 打开控制台「题库与订正」，把内容粘进「导入题库」")

    if args.json:
        data = build_json(entries)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print(f"已写出 {args.json}（{len(data)} 条），放到程序目录后重启即可生效")


if __name__ == "__main__":
    sys.exit(main())
