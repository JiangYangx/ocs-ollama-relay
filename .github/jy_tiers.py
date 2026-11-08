#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jy_tiers —— 一键档位（v1.3）

把散落在五个标签页里的十几个参数，收敛成三个按钮。
每档给出的是一组「协同过」的值，不是随便拼的：
超时预算、token 上限、节律间隔三者必须匹配，否则会出现
「档位说极速，结果因为 token 太小反复重试反而更慢」这类问题。
"""
from __future__ import annotations

TIERS = {
    "speed": {
        "label": "极速刷题",
        "desc": "关闭交叉验证与 CoT，间隔压到 100~300ms，128 token 直出",
        "note": "1~2s/题，正确率 85~90%；适合题量大、重复题多的场景",
        "values": {
            "verify_mode": "off",
            "cot_mode": False,
            "human_delay": True,
            "delay_min_ms": 100,
            "delay_max_ms": 300,
            "cloud_max_tokens": 128,
            "num_predict": 256,
            "rag_enable": False,
            "self_check": True,
            "answer_budget": 40,
            "request_timeout": 40,
        },
    },
    "balanced": {
        "label": "平衡日常",
        "desc": "复核标注 + 相似题参考，间隔 500~1500ms，512 token",
        "note": "2~3s/题，正确率 88~93%；默认档，适合大多数情况",
        "values": {
            "verify_mode": "fast",
            "cot_mode": False,
            "human_delay": True,
            "delay_min_ms": 500,
            "delay_max_ms": 1500,
            "cloud_max_tokens": 512,
            "num_predict": 1024,
            "rag_enable": True,
            "self_check": True,
            "answer_budget": 50,
            "request_timeout": 60,
        },
    },
    "accurate": {
        "label": "高正确率",
        "desc": "CoT + 双模型仲裁 + 相似题参考，1024 token，预算放宽",
        "note": "3~6s/题，正确率 92~96%；适合考试冲刺、难题",
        "values": {
            "verify_mode": "full",
            "cot_mode": True,
            "human_delay": True,
            "delay_min_ms": 400,
            "delay_max_ms": 1000,
            "cloud_max_tokens": 1024,
            "num_predict": 2048,
            "rag_enable": True,
            "self_check": True,
            "answer_budget": 55,
            "request_timeout": 90,
        },
    },
}

ORDER = ["speed", "balanced", "accurate"]


def apply_tier(cfg: dict, name: str) -> tuple[bool, str]:
    """把档位参数写进配置字典（调用方负责保存）。"""
    t = TIERS.get(name)
    if not t:
        return False, f"未知档位：{name}（可选：{' / '.join(ORDER)}）"
    for k, v in t["values"].items():
        cfg[k] = v
    cfg["tier"] = name
    return True, f"已切换到「{t['label']}」"


def detect_tier(cfg: dict) -> str:
    """反推当前配置最接近哪一档（用于界面高亮）。"""
    cur = cfg.get("tier")
    if cur in TIERS:
        return cur
    best, best_score = "balanced", -1
    for name in ORDER:
        vals = TIERS[name]["values"]
        score = 0
        for k, v in vals.items():
            if cfg.get(k) == v:
                score += 2
            elif isinstance(v, bool) and bool(cfg.get(k)) == v:
                score += 1
        if score > best_score:
            best, best_score = name, score
    return best


def summarize() -> list:
    return [{"key": k, "label": TIERS[k]["label"], "desc": TIERS[k]["desc"],
             "note": TIERS[k]["note"]} for k in ORDER]
