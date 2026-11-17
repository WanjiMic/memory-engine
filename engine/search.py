# -*- coding: utf-8 -*-
"""在旁路库上查。

用法：
    python -m engine.search --config demo/config.json "关键词 [关键词]" [条数] [--fanout]

规则：
- >=3 字的词走 FTS5(trigram)，多个词 AND；
- <3 字的词（如 3 个字以内的专名、编号）在命中结果里做二次过滤；全是短词时退回 LIKE；
- 长词一条都没命中时，按近义表换说法再查一遍（OR），并明说「换了说法」——
  那不是原话，引用前自己核；
- 排序加权：规则类来源乘 3.0（标【法源】），「自己的声音」类来源乘 2.0。
  加权只影响排序（找得到），不影响对错；
- 权重 ≤ 阈值的卡片默认不露面；热路径全查不到时退到冷记忆，打〔冷记忆命中〕，
  并明说「这是从沉底里捞回来的，它几乎已经被忘了」；
- 命中的卡若还活着，且卡片 refs 指得到原文件某一行，会多打一行〔原话〕——
  让「我记得」变成能核对的一行；指不到就安静跳过，不编。
"""
import argparse
import contextlib
import datetime
import importlib
import io
import json
import os
import re
import sqlite3
import sys

from . import config as _config
from . import weight as _weight

# 加权（只影响排序）
LAW_BOOST = 3.0   # 规则类来源加权
BOOST = 2.0       # 「自己的声音」类来源

CARD_ID = re.compile(r"^e\d{8}-\d+$")

_ALIAS = None
_ALIAS_KEY = None


def split_terms(q):
    for ch in "，,、":
        q = q.replace(ch, " ")
    return [p for p in q.split() if p]


def load_alias(cfg):
    """近义表：一行「词 = 说法 说法」。表坏了就当没有，不拦检索。"""
    global _ALIAS, _ALIAS_KEY
    key = cfg.alias_file or ""
    if _ALIAS is not None and _ALIAS_KEY == key:
        return _ALIAS
    m = {}
    try:
        if cfg.alias_file:
            with io.open(cfg.alias_file, encoding="utf-8") as fh:
                for ln in fh:
                    ln = ln.strip()
                    if not ln or ln.startswith("#"):
                        continue
                    if "=" in ln:
                        k, v = ln.split("=", 1)
                    elif "：" in ln:
                        k, v = ln.split("：", 1)
                    else:
                        continue
                    k = k.strip()
                    vs = [x for x in v.replace("，", " ").replace("、", " ").replace(",", " ").split() if x]
                    if k and vs:
                        m[k] = vs
    except Exception:
        m = {}
    # 反向也认：表里写「疲惫 = 累」，查「累」也要能顺着爬回「疲惫」
    for k, vs in list(m.items()):
        for v in vs:
            if v == k:
                continue
            m.setdefault(v, [])
            for w in [k] + vs:
                if w != v and w not in m[v]:
                    m[v].append(w)
    _ALIAS = m
    _ALIAS_KEY = key
    return m


def alt_match(terms, cfg):
    """把词换成「原词 OR 近义」，返回 (查询串, 用到的扩展列表)；没有可扩的回 (None, [])。"""
    al = load_alias(cfg)
    if not al:
        return None, []
    used = []
    groups = []
    for t in terms:
        syn = al.get(t) or []
        syn = [x for x in syn if x and x != t]
        pool = [t] + syn
        groups.append("(" + " OR ".join('"' + x.replace('"', '') + '"' for x in pool) + ")")
        if syn:
            used.append((t, syn))
    if not used:
        return None, []
    return " AND ".join(groups), used


def _law_where(cfg, alias):
    """返回 (SQL 条件, 参数)。alias 是列前缀，如 "c." 或 ""。"""
    parts, params = [], []
    for p in cfg.law_prefixes:
        parts.append("%ssource like ?" % alias)
        params.append(p + "%")
    for f in cfg.law_files:
        parts.append("%ssource = ?" % alias)
        params.append(f)
    if not parts:
        return "0", []
    return "(" + " or ".join(parts) + ")", params


def _voice_where(cfg, alias):
    parts, params = [], []
    for v in cfg.my_voice:
        parts.append("%ssource like ?" % alias)
        params.append("%" + v + "%")
    if not parts:
        return "0", []
    return "(" + " or ".join(parts) + ")", params


def source_tag(src, cfg):
    if any(src.startswith(p) for p in cfg.law_prefixes) or src in cfg.law_files:
        return "【法源】"
    return ""


def _origin_line(rows, cfg):
    """命中的卡若还活着，且 refs 指得到原文件某一行，就把原话打出来。"""
    try:
        byid = {c.get("id"): c for c in _weight.load_cards(cfg)}
        side = _weight.load_side(cfg)
    except Exception:
        return
    anchors = {}
    try:
        if cfg.anchors and os.path.exists(cfg.anchors):
            with io.open(cfg.anchors, encoding="utf-8") as fh:
                anchors = json.load(fh)
    except Exception:
        anchors = {}
    shown = 0
    for _src, _head, _snip, _txt in rows:
        if shown >= 2:
            break
        card = byid.get((_head or "").strip())
        if not card:
            continue
        try:
            if _weight.w_now(card, side, cfg) < cfg.cold:
                continue
        except Exception:
            continue
        a = anchors.get(card.get("id") or "") or {}
        for ref in card.get("refs") or []:
            m = re.match(r"^(.*?)#L(\d+)$", ref)
            if not m:
                continue
            try:
                with io.open(os.path.join(cfg.root, m.group(1)), encoding="utf-8") as fh:
                    lines = fh.readlines()
                idx = int(a.get("line") or m.group(2)) - 1
                if idx < 0 or idx >= len(lines):
                    idx = int(m.group(2)) - 1
                if idx < 0 or idx >= len(lines):
                    continue
                # refs 常指向小标题行，原话在它下面一两行；往下找第一行正文。
                raw, real = "", idx
                for k in range(idx, min(idx + 4, len(lines))):
                    cand = " ".join(lines[k].split())
                    if cand and not cand.startswith("#"):
                        raw, real = cand, k
                        break
            except Exception:
                continue
            if not raw:
                continue
            _hd = (a.get("heading") or "").strip()
            print("〔原话〕%s%s · %s#L%d · %s%s" % (
                card.get("date", "?"),
                ("｜" + _hd[:22] + ("…" if len(_hd) > 22 else "")) if _hd else "",
                m.group(1), real + 1,
                raw[:60], "…" if len(raw) > 60 else ""))
            shown += 1
            break


def _ensure_fresh(cfg):
    """库比正本旧，就先重建再查。导入失败不拦路——退回旧库照查，但说一声。"""
    try:
        imp = importlib.import_module("engine.import_memories")
    except Exception as e:
        print("（提示：import_memories 不可用，按现状查库：%s）" % e, file=sys.stderr)
        return
    newest = 0.0
    try:
        for _src, path in imp.iter_files(cfg):
            try:
                newest = max(newest, os.path.getmtime(path))
            except OSError:
                pass
    except Exception:
        return
    stale = (not os.path.exists(cfg.db)) or (os.path.getmtime(cfg.db) < newest)
    if not stale:
        return
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            imp.main(cfg)
        print("（库旧了，已先按正本重建再查）", file=sys.stderr)
    except Exception as e:
        print("（提示：重建失败，按旧库查：%s）" % e, file=sys.stderr)


def _qterm(s):
    return '"' + s.replace('"', " ") + '"'


def _query_long(con, cfg, long_terms, short_terms, limit):
    law_cond, law_params = _law_where(cfg, "c.")
    voice_cond, voice_params = _voice_where(cfg, "c.")
    boost = "case when %s then ? when %s then ? else 1.0 end" % (law_cond, voice_cond)
    cold_filter = "and (c.w is null or c.w > %d)" % cfg.cold
    w_boost = "(case when c.w is null then 1.0 else 1.0 + c.w / 100.0 end)"
    match = " AND ".join(_qterm(s) for s in long_terms)

    def run(match_q, cold):
        sql = (
            "select c.source, c.heading, "
            "snippet(chunks_fts, 0, '[', ']', '…', 14), c.text "
            "from chunks_fts join chunks c on c.id = chunks_fts.rowid "
            "where chunks_fts match ? " + cold + " "
            "order by rank * " + boost + " * " + w_boost + " limit ?"
        )
        params = (match_q,) + tuple(law_params) + (LAW_BOOST,) + tuple(voice_params) + (BOOST, limit * 4)
        return con.execute(sql, params).fetchall()

    cold_hit = False
    used_alias = []
    rows = run(match, cold_filter)
    if not rows:
        rows = run(match, "")
        cold_hit = bool(rows)
    if not rows:
        alt, used_alias = alt_match(long_terms, cfg)
        if alt:
            rows = run(alt, cold_filter)
            if not rows:
                rows = run(alt, "")
                cold_hit = bool(rows)
    if short_terms:
        rows = [r for r in rows if all(s in r[3] for s in short_terms)]
    return rows[:limit], cold_hit, used_alias


def _query_short(con, cfg, terms, limit):
    cond = " and ".join(["(text like ? or heading like ?)"] * len(terms))
    term_params = []
    for t in terms:
        term_params += ["%" + t + "%", "%" + t + "%"]
    law_cond, law_params = _law_where(cfg, "")
    voice_cond, voice_params = _voice_where(cfg, "")
    cold_filter = "and (w is null or w > %d)" % cfg.cold
    w_boost = "(case when w is null then 1.0 else 1.0 + w / 100.0 end)"
    order = "case when %s then 0 when %s then 1 else 2 end" % (law_cond, voice_cond)

    def run(cold):
        sql = (
            "select source, heading, substr(text,1,120), text from chunks "
            "where " + cond + " " + cold + " "
            "order by " + order + ", " + w_boost + " desc, id limit ?"
        )
        params = term_params + law_params + voice_params + [limit]
        return con.execute(sql, params).fetchall()

    rows = run(cold_filter)
    cold_hit = False
    if not rows:
        rows = run("")
        cold_hit = bool(rows)
    return rows, cold_hit, []


def _print_cold(rows, cfg):
    marks = []
    for _src, _head, _snip, _txt in rows[:3]:
        m = re.match(r"^e(\d{4})(\d{2})(\d{2})-\d+$", (_head or "").strip())
        if m:
            marks.append((m.group(1) + "-" + m.group(2) + "-" + m.group(3),
                          _head.strip(), " ".join(_snip.split())[:28]))
    if marks:
        print("〔冷记忆命中〕" + " ｜ ".join("%s · %s · %s" % x for x in marks))
    else:
        print("〔冷记忆命中〕（不是记忆卡，来源：" + str(rows[0][0]) + "）")
    print("（这轮只有冷记忆命中：从沉底的卡里捞回来的——它几乎已经被忘了。）")
    if cfg.cold_log:
        try:
            d = datetime.datetime.now()
            os.makedirs(os.path.dirname(cfg.cold_log), exist_ok=True)
            with io.open(cfg.cold_log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "t": d.strftime("%Y-%m-%d %H:%M"),
                    "text": ", ".join(m[1] for m in marks) or ("段（" + str(rows[0][0]) + "）"),
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass


def _bump(cfg, terms, n, alias_n=0):
    """记一笔：查了几次、最后一次查什么、命中几段。只写统计，不动正本。"""
    if not cfg.stats:
        return
    try:
        old = {}
        if os.path.exists(cfg.stats):
            with io.open(cfg.stats, encoding="utf-8") as fh:
                old = json.load(fh)
    except Exception:
        old = {}
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    old["查询次数"] = int(old.get("查询次数", 0)) + 1
    old["上次查询"] = now
    old["最近关键词"] = " ".join(terms)[:60]
    old["上次命中数"] = n
    if alias_n:
        old["近义扩展次数"] = int(old.get("近义扩展次数", 0)) + 1
    try:
        os.makedirs(os.path.dirname(cfg.stats), exist_ok=True)
        with io.open(cfg.stats, "w", encoding="utf-8", newline="") as fh:
            json.dump(old, fh, ensure_ascii=False, indent=1)
    except Exception:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="在 FTS5(trigram) 记忆库上检索")
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("limit", nargs="?", type=int, default=8)
    ap.add_argument("--config", help="config.json 路径")
    ap.add_argument("--fanout", action="store_true", help="命中卡片后顺手浮出邻居")
    ap.add_argument("--no-refresh", action="store_true", help="不要自动重建旧库")
    a = ap.parse_args(argv)

    if not a.query.strip():
        print('用法: python -m engine.search --config demo/config.json "关键词 [关键词]" [条数] [--fanout]')
        return 1
    cfg = _config.load(a.config)
    terms = split_terms(a.query.strip())
    if not terms:
        print("用法：给一个关键词。")
        return 1
    limit = max(1, a.limit)
    if not a.no_refresh:
        _ensure_fresh(cfg)

    con = sqlite3.connect(cfg.db)
    try:
        long_terms = [t for t in terms if len(t) >= 3]
        short_terms = [t for t in terms if len(t) < 3]
        if long_terms:
            rows, cold_hit, used_alias = _query_long(con, cfg, long_terms, short_terms, limit)
        else:
            rows, cold_hit, used_alias = _query_short(con, cfg, terms, limit)
    finally:
        con.close()

    if not rows:
        print("没有命中。")
        return 0
    if cold_hit:
        _print_cold(rows, cfg)
    if used_alias:
        print("（近义扩展：" + "；".join("%s → %s" % (k, "/".join(v)) for k, v in used_alias)
              + "。下面命中的是意思相近的说法，不是原话，引用前自己核。）")
    for i, (src, head, snip, _text) in enumerate(rows, 1):
        print("%d. %s%s  · %s" % (i, source_tag(src, cfg), src, head or "(无标题)"))
        print("   " + " ".join(snip.split()))
    _origin_line(rows, cfg)

    if a.fanout:
        _card = ""
        for _row in rows:
            _h = (_row[1] or "").strip()
            if CARD_ID.match(_h):
                _card = _h
                break
        if _card:
            try:
                from . import associate
                for _ln in associate.lines_for(cfg, _card, 2):
                    print(_ln)
            except Exception as _e:
                print("（联想没跑起来：%s）" % _e)

    _bump(cfg, terms, len(rows), len(used_alias))
    return 0


if __name__ == "__main__":
    sys.exit(main())
