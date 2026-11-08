#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把公开学术题库 C-Eval 拉下来，转成 JY Relay 可直接导入的题库。

C-Eval 是公开的中文考试评测数据集（52 个学科、约 1.4 万道单选题），
覆盖计算机、数学、法律、医学、经济、公务员等。许可证 CC BY-NC-SA 4.0：
仅限个人学习/研究使用，不得商用，再分发需保留署名与相同许可。

用法：
    python tools/fetch_ceval.py --list                  # 看有哪些学科
    python tools/fetch_ceval.py                         # 全部学科 → ceval_bank.txt
    python tools/fetch_ceval.py --subjects computer_network,math
    python tools/fetch_ceval.py --split val             # 只要验证集（更少）
    python tools/fetch_ceval.py --json bank.json        # 直接生成 bank.json

说明：题库命中的前提是"题干一致"，C-Eval 是通用学科题，
不会命中你课程的原题；它的作用是覆盖通用概念题、以及作为相似题的参考。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

MIRROR = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com").rstrip("/")
DATASET = "ceval/ceval-exam"
# 缓存放用户目录，避免把几 MB 数据留在仓库里（重复运行不重复下载）
CACHE = os.environ.get("JY_CEVAL_CACHE") or os.path.join(
    os.path.expanduser("~"), ".cache", "jy-relay", "ceval")
UA = {"User-Agent": "Mozilla/5.0 (compatible; jy-relay-bank-fetch/1.0)"}

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from make_bank import to_block_text, build_json
except Exception:
    to_block_text = build_json = None


def _get(url: str, timeout: int = 40, binary: bool = False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if binary else json.loads(data)


def list_subjects() -> list[str]:
    api = f"{MIRROR}/api/datasets/{DATASET}/tree/main"
    items = _get(api)
    return sorted(i["path"] for i in items if i.get("type") == "directory")


def list_files(subject: str) -> list[str]:
    api = f"{MIRROR}/api/datasets/{DATASET}/tree/main/{urllib.parse.quote(subject)}"
    items = _get(api)
    return [i["path"] for i in items if i.get("type") == "file" and i["path"].endswith(".parquet")]


def download(rel_path: str) -> str | None:
    """下载一个 parquet 到本地缓存，返回本地路径。"""
    os.makedirs(CACHE, exist_ok=True)
    local = os.path.join(CACHE, rel_path.replace("/", "__"))
    if os.path.exists(local) and os.path.getsize(local) > 1024:
        return local
    url = f"{MIRROR}/datasets/{DATASET}/resolve/main/{urllib.parse.quote(rel_path)}"
    try:
        data = _get(url, timeout=60, binary=True)
        if len(data) < 200:
            return None
        with open(local, "wb") as f:
            f.write(data)
        return local
    except Exception as e:
        print(f"  ! 下载失败 {rel_path}: {e}")
        return None


def read_entries(parquet_path: str, subject: str) -> list[dict]:
    import pandas as pd
    df = pd.read_parquet(parquet_path)
    out = []
    for rec in df.to_dict("records"):
        q = str(rec.get("question") or "").strip()
        ans = str(rec.get("answer") or "").strip().upper()
        opts = [str(rec.get(k) or "").strip() for k in ("A", "B", "C", "D")]
        opts = [o for o in opts if o]
        if not q or not ans or len(opts) < 2:
            continue
        out.append({"question": q, "options": opts, "answer": ans, "subject": subject})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="下载 C-Eval 并转成 JY Relay 题库")
    ap.add_argument("--list", action="store_true", help="只列出学科")
    ap.add_argument("--subjects", default="", help="逗号分隔的学科名，默认全部")
    ap.add_argument("--split", default="val,test", help="val / test / 两者都下（默认 val,test）")
    ap.add_argument("-o", "--output", default="ceval_bank.txt", help="输出题库文本")
    ap.add_argument("--json", metavar="PATH", help="同时生成 bank.json")
    args = ap.parse_args()

    if to_block_text is None:
        raise SystemExit("找不到 tools/make_bank.py，请在本仓库目录下运行")

    try:
        subjects = list_subjects()
    except Exception as e:
        raise SystemExit(f"无法连接 {MIRROR}：{e}\n可设置环境变量 HF_ENDPOINT 换镜像")

    if args.list:
        print(f"C-Eval 共 {len(subjects)} 个学科：")
        for i in range(0, len(subjects), 4):
            print("  " + "  ".join(f"{s:<34}" for s in subjects[i:i + 4]))
        return

    want = [s.strip() for s in args.subjects.split(",") if s.strip()] or subjects
    unknown = [s for s in want if s not in subjects]
    if unknown:
        print(f"忽略未知学科：{', '.join(unknown)}")
        want = [s for s in want if s in subjects]
    splits = [s.strip() for s in args.split.split(",") if s.strip()]

    print(f"学科 {len(want)} 个，数据集划分 {splits}，镜像 {MIRROR}")

    jobs = []
    for subj in want:
        try:
            files = list_files(subj)
        except Exception as e:
            print(f"  ! 列出 {subj} 失败：{e}")
            continue
        for f in files:
            name = os.path.basename(f)
            if any(name.startswith(sp) for sp in splits):
                jobs.append((subj, f))

    print(f"待下载 {len(jobs)} 个文件 …")
    downloaded = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for (subj, rel), local in zip(jobs, ex.map(lambda j: download(j[1]), jobs)):
            if local:
                downloaded.append((subj, local))
    print(f"下载完成 {len(downloaded)}/{len(jobs)}")

    entries = []
    for subj, path in downloaded:
        try:
            part = read_entries(path, subj)
            entries.extend(part)
        except Exception as e:
            print(f"  ! 解析 {path} 失败：{e}")

    # 去重（同一题干 + 选项只留一条）
    seen, uniq = set(), []
    for e in entries:
        k = (e["question"], tuple(e["options"]))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(e)

    print(f"解析得到 {len(entries)} 题，去重后 {len(uniq)} 题")

    by_subj = {}
    for e in uniq:
        by_subj[e["subject"]] = by_subj.get(e["subject"], 0) + 1
    top = sorted(by_subj.items(), key=lambda x: -x[1])[:8]
    print("题量最多的学科：" + "，".join(f"{k} {v}" for k, v in top))

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(to_block_text(uniq))
    print(f"已写出 {args.output}")
    print("  → 控制台「题库与订正」→ 粘贴导入（1 万多题建议分学科导入，单次别超过 2 万字）")

    if args.json:
        data = build_json(uniq)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print(f"已写出 {args.json}（{len(data)} 条），放到程序目录后重启生效")


if __name__ == "__main__":
    sys.exit(main())
