# -*- coding: utf-8 -*-
"""卡片权重的惰性衰减。

不做后台任务：卡片本身只存「是什么时候的」，当前权重在每次需要时现算：

    w = 100 - 速率 × (今天 - 上次唤醒的日期)

越旧的卡越低；低于阈值（默认 20）就「沉底」，默认不再出现在检索结果里。
沉底不是删除——检索热路径一条都没有时，会退到冷路径把它们捞回来，
并明确标注「这是从沉底里捞回来的」。

速率按卡片性质分档，全部可在 config.json 的 decay 里改：

    kind  卡片 k 字段 → 每天掉多少分    例如 {"情绪": 1.0}
    w_min 卡片 w 字段 ≥ w_min 时用下一档
    w3    w ≥ w_min 的卡每天掉多少
    default 其余卡每天掉多少

卡片 JSONL 最小字段：

    {"id": "e20261104-1", "date": "2026-11-04", "k": "事件", "w": 2,
     "text": "把解析器重写了一遍。", "refs": ["日记.md#L4"]}

旁表（weights.json）只记 last / hits / pin，与卡片分开——卡片是正本，不动它。

命令（都接受 --config）：
    python -m engine.weight --init
    python -m engine.weight --report
    python -m engine.weight --check      # 一行 ASCII JSON，给脚本用
    python -m engine.weight --table
    python -m engine.weight --wake e20261104-1
    python -m engine.weight --flash e20261104-1
"""
import argparse
import datetime
import io
import json
import os
import sys

from . import config as _config


def today():
    return datetime.date.today()


def load_cards(cfg):
    out = []
    if not os.path.exists(cfg.cards):
        return out
    with io.open(cfg.cards, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def load_side(cfg):
    if cfg.weights and os.path.exists(cfg.weights):
        try:
            with io.open(cfg.weights, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return {}


def save_side(cfg, side):
    os.makedirs(os.path.dirname(cfg.weights), exist_ok=True)
    with io.open(cfg.weights, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(side, fh, ensure_ascii=False, indent=1, sort_keys=True)


def entry(card, side):
    """旁表里这一张的状态；缺的按卡片日期补，不写盘。"""
    sid = card["id"]
    se = side.get(sid) or {}
    return {
        "last": se.get("last") or card.get("date") or str(today()),
        "hits": int(se.get("hits") or 0),
        "pin": bool(se.get("pin")),
    }


def rate_for(card, cfg):
    """这张卡每天掉多少分。"""
    d = cfg.decay
    kind = card.get("k") or ""
    if kind in d.get("kind", {}):
        return float(d["kind"][kind])
    try:
        w = int(card.get("w") or 1)
    except Exception:
        w = 1
    if w >= int(d.get("w_min", 3)):
        return float(d.get("w3", 0.5))
    return float(d.get("default", 2.0))


def w_now(card, side, cfg, day=None):
    """这张卡今天的权重（1..100）。"""
    day = day or today()
    st = entry(card, side)
    if st["pin"]:
        return 100
    try:
        last = datetime.date.fromisoformat(st["last"])
    except Exception:
        last = day
    days = max(0, (day - last).days)
    return max(1, int(round(100 - rate_for(card, cfg) * days)))


def cmd_init(cfg):
    side = load_side(cfg)
    cards = load_cards(cfg)
    n = 0
    for c in cards:
        if c["id"] not in side:
            side[c["id"]] = {"last": c.get("date") or str(today()), "hits": 0, "pin": False}
            n += 1
    save_side(cfg, side)
    print("旁表 %d 张（新补 %d）" % (len(side), n))
    return 0


def cmd_wake(cfg, cid):
    cards = {c["id"]: c for c in load_cards(cfg)}
    if cid not in cards:
        print("没有这张卡：%s" % cid)
        return 2
    side = load_side(cfg)
    st = side.setdefault(cid, {"last": cards[cid].get("date") or str(today()), "hits": 0, "pin": False})
    base = w_now(cards[cid], side, cfg)
    st["last"] = str(today())
    st["hits"] = int(st.get("hits") or 0) + 1
    save_side(cfg, side)
    print("%s 唤醒：%d -> %d（第 %d 次）" % (cid, base, min(100, base + cfg.wake_gain), st["hits"]))
    return 0


def cmd_flash(cfg, cid):
    """闪回：从沉底里被精准关键词捞回来，直接回 100，跟 +20 的唤醒分开。"""
    cards = {c["id"]: c for c in load_cards(cfg)}
    if cid not in cards:
        print("没有这张卡：%s" % cid)
        return 2
    side = load_side(cfg)
    st = side.setdefault(cid, {"last": cards[cid].get("date") or str(today()), "hits": 0, "pin": False})
    base = w_now(cards[cid], side, cfg)
    st["last"] = str(today())
    st["hits"] = int(st.get("hits") or 0) + 1
    save_side(cfg, side)
    print("%s 闪回：%d -> 100（第 %d 次）" % (cid, base, st["hits"]))
    return 0


def cmd_report(cfg):
    cards = load_cards(cfg)
    side = load_side(cfg)
    if not cards:
        print("没有卡片。")
        return 0
    rows = [(w_now(c, side, cfg), c["id"], (c.get("text") or "")[:34]) for c in cards]
    rows.sort()
    cold = [r for r in rows if r[0] <= cfg.cold]
    missing = [c["id"] for c in cards if c["id"] not in side]
    print("卡片 %d 张，沉底 %d 张，旁表缺 %d 张。" % (len(cards), len(cold), len(missing)))
    for w, cid, txt in rows[:3]:
        print("  最久没唤醒：%d 分 %s · %s" % (w, cid, txt))
    if missing:
        print("  对不上：" + "、".join(missing[:6]))
    return 0


def cmd_check(cfg):
    """只吐一行 ASCII JSON，免得控制台编码把中文搅烂。"""
    cards = load_cards(cfg)
    side = load_side(cfg)
    rows = sorted((w_now(c, side, cfg), c["id"], c.get("text") or "") for c in cards)
    cold = [r for r in rows if r[0] <= cfg.cold]
    missing = [c["id"] for c in cards if c["id"] not in side]
    out = {
        "cards": len(cards),
        "cold": len(cold),
        "missing": missing[:6],
        "worst": [{"w": w, "id": cid, "text": txt[:34]} for w, cid, txt in rows[:3]],
    }
    print(json.dumps(out, ensure_ascii=True))
    return 0


def cmd_table(cfg):
    cards = load_cards(cfg)
    side = load_side(cfg)
    for w, cid, txt in sorted(((w_now(c, side, cfg), c["id"], (c.get("text") or "")[:30]) for c in cards)):
        print("%3d  %s  %s" % (w, cid, txt))
    return 0


def cli(argv=None):
    ap = argparse.ArgumentParser(description="卡片权重：惰性衰减与唤醒")
    ap.add_argument("--config", help="config.json 路径")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--init", action="store_true", help="建旁表（缺的补上，已有不动）")
    g.add_argument("--report", action="store_true", help="沉底张数、最久没唤醒")
    g.add_argument("--check", action="store_true", help="一行 ASCII JSON；给脚本用")
    g.add_argument("--table", action="store_true", help="全部卡片当前读数")
    g.add_argument("--wake", metavar="ID", help="唤醒一次（+wake_gain，刷新 last）")
    g.add_argument("--flash", metavar="ID", help="闪回（直接回 100）")
    a = ap.parse_args(argv)
    if not (a.init or a.report or a.check or a.table or a.wake or a.flash):
        ap.print_help()
        return 1
    cfg = _config.load(a.config)
    if a.init:
        return cmd_init(cfg)
    if a.report:
        return cmd_report(cfg)
    if a.check:
        return cmd_check(cfg)
    if a.table:
        return cmd_table(cfg)
    if a.wake:
        return cmd_wake(cfg, a.wake)
    if a.flash:
        return cmd_flash(cfg, a.flash)
    return 1


if __name__ == "__main__":
    sys.exit(cli())
