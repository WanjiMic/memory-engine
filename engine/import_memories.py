# -*- coding: utf-8 -*-
"""建库：把语料切段，灌进 FTS5(trigram) 旁路库。

正本一个字不动；库只是索引，删掉重跑即可——索引坏了不心疼，重跑就回来了。

用法：
    python -m engine.import_memories --config demo/config.json
"""
import argparse
import io
import json
import os
import re
import sqlite3
import sys

from . import config as _config
from . import weight as _weight


def chunks(path, source):
    """按标题与空行切段，返回 (source, heading, text, start_line, date)。

    date 只在「## YYYY-MM-DD」这种二级标题下才有，用来给账本段找卡片。
    行号会随增删漂移，所以它只是线索；卡片还可以写「日期＋小标题」当锚。
    """
    with io.open(path, encoding="utf-8-sig", errors="replace") as f:
        lines = f.read().splitlines()
    heading = ""
    buf = []
    start = 1
    cur_date = ""
    for no, line in enumerate(lines, 1):
        dm = re.match(r"^##\s+(\d{4}-\d{2}-\d{2})", line)
        if dm:
            cur_date = dm.group(1)
        if re.match(r"^#{1,4}\s", line):
            if buf:
                yield source, heading, "\n".join(buf).strip(), start, cur_date
                buf = []
            heading = line.lstrip("#").strip()[:80]
            start = no + 1
            continue
        if line.strip() == "":
            if buf:
                yield source, heading, "\n".join(buf).strip(), start, cur_date
                buf = []
                start = no + 1
        else:
            if not buf:
                start = no
            buf.append(line)
    if buf:
        yield source, heading, "\n".join(buf).strip(), start, cur_date


def card_chunks(cfg, path, source):
    """记忆卡逐张入索引：一张卡 = 一段，带当天惰性算出来的权重。"""
    side = _weight.load_side(cfg)
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                c = json.loads(line)
            except Exception:
                continue
            body = ("[%s] %s" % (c.get("k", ""), c.get("text", ""))).strip()
            if len(body) < 8:
                continue
            yield source, str(c.get("id", "")), body, _weight.w_now(c, side, cfg)


def iter_files(cfg):
    """按配置顺序吐 (source_name, 绝对路径)。"""
    for rel in cfg.sources:
        p = os.path.join(cfg.root, rel)
        if os.path.isfile(p):
            yield rel, p

    if cfg.cards and os.path.isfile(cfg.cards):
        yield cfg.cards_source, cfg.cards

    for d in cfg.dirs:
        base = os.path.join(cfg.root, d)
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            for p in sorted(files):
                if p.lower().endswith((".md", ".txt")):
                    rel = os.path.relpath(os.path.join(root, p), cfg.root).replace(os.sep, "/")
                    yield rel, os.path.join(root, p)


STOP = set("的了是我你他她在有和就都说要一个不这那也没很到把被给对又从还只等")


def _keys_of(text, n=4):
    """从卡片里取「像专名或术语」的片段：连续汉字或字母数字，长度 2..n，去掉停用字打头。"""
    out = set()
    for seg in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,12}", text or ""):
        for size in range(2, n + 1):
            for i in range(0, len(seg) - size + 1):
                piece = seg[i:i + size]
                if piece[0] in STOP or piece[-1] in STOP:
                    continue
                out.add(piece)
    return out


def _ledger_weights(cfg, ledger):
    """账本段落的权重取「盖住它的卡片里最低的那个」。

    卡片沉底了、原话还从账本被捞回来，等于没忘；让盖住它的原段一起沉，
    但仍留在库里——检索热路径命中 0 条时退到冷路径，打〔冷记忆命中〕，
    这才是「闪回」。
    """
    ledger_w = [100] * len(ledger)
    if not ledger:
        return ledger_w
    try:
        side = _weight.load_side(cfg)
        spans = []
        for i, item in enumerate(ledger):
            end = ledger[i + 1][3] if i + 1 < len(ledger) else 10 ** 9
            spans.append((item[3], end, i))

        for c in _weight.load_cards(cfg):
            cw = _weight.w_now(c, side, cfg)
            if cw >= 100:
                continue

            # 一、卡片自己写的行号（会漂，只当线索）
            for ref in (c.get("refs") or []):
                m = re.search(r"(?:#|\b)L(\d+)(?:\s*[-–]\s*L?(\d+))?", ref)
                if not m:
                    continue
                a = int(m.group(1))
                b = int(m.group(2) or a)
                for s0, s1, idx in spans:
                    if s0 <= b and a < s1 and cw < ledger_w[idx]:
                        ledger_w[idx] = cw

            # 二、行号会漂，新卡可以写「日期＋小标题」锚
            for ref in (c.get("refs") or []):
                am = re.search(r"(?:^|[#／/])(\d{4}-\d{2}-\d{2})[ T]+(.{2,40})", ref)
                if not am:
                    continue
                adate, aname = am.group(1), am.group(2).strip()
                if not aname:
                    continue
                for idx, item in enumerate(ledger):
                    head, body = item[1], item[2]
                    segday = item[4] if len(item) > 4 else ""
                    if adate not in (segday, head) and adate not in body[:200]:
                        continue
                    if aname[:10] in head or aname[:10] in body:
                        if cw < ledger_w[idx]:
                            ledger_w[idx] = cw

            # 三、同一天里，谁的词命中得多就是谁（标题与正文一起算）
            day = (c.get("date") or "")[:10]
            ks = _keys_of(c.get("text", ""))
            if len(ks) < 3:
                continue
            scored = []
            for idx, item in enumerate(ledger):
                head, body = item[1], item[2]
                segday = item[4] if len(item) > 4 else ""
                if day and day not in (segday, head) and day not in body[:200]:
                    continue
                blob = head + "\n" + body
                scored.append((sum(1 for k in ks if k in blob), idx))
            if not scored:
                continue
            scored.sort(reverse=True)
            best = scored[0][0]
            if best < 3:
                continue
            # 一张卡常横跨相邻两三段：和最高分差 1 以内、且命中 ≥2 个词的段都算被它盖住。
            floor = max(2, int(best * 0.6))
            for sc, idx in scored:
                if sc >= floor and cw < ledger_w[idx]:
                    ledger_w[idx] = cw
    except Exception as e:
        print("[warn] 账本段权重没算成：%s" % e)
    return ledger_w


def main(cfg=None):
    cfg = cfg or _config.load()
    os.makedirs(os.path.dirname(cfg.db), exist_ok=True)
    if os.path.exists(cfg.db):
        os.remove(cfg.db)
    con = sqlite3.connect(cfg.db)
    con.execute(
        "create table chunks(id integer primary key, source text, "
        "heading text, text text, w integer default 100)"
    )
    con.execute(
        "create virtual table chunks_fts using fts5("
        "text, heading, content='chunks', content_rowid='id', tokenize='trigram')"
    )

    ledger = []
    if cfg.ledger:
        lp = os.path.join(cfg.root, cfg.ledger)
        if os.path.isfile(lp):
            ledger = list(chunks(lp, cfg.ledger))
    ledger_w = _ledger_weights(cfg, ledger)

    n = 0
    for source, path in iter_files(cfg):
        if source == cfg.cards_source:
            gen = card_chunks(cfg, path, source)
        elif cfg.ledger and source == cfg.ledger:
            gen = ((it[0], it[1], it[2], ledger_w[i]) for i, it in enumerate(ledger))
        else:
            gen = ((it[0], it[1], it[2], 100) for it in chunks(path, source))
        for src, head, body, w in gen:
            if len(body) < 8:
                continue
            con.execute(
                "insert into chunks(source, heading, text, w) values(?,?,?,?)",
                (src, head, body, w),
            )
            n += 1

    con.execute("insert into chunks_fts(chunks_fts) values('rebuild')")
    con.commit()
    con.close()
    print("导入 %d 段 -> %s" % (n, cfg.db))
    return n


def cli(argv=None):
    ap = argparse.ArgumentParser(description="建 FTS5(trigram) 记忆索引")
    ap.add_argument("--config", help="config.json 路径")
    a = ap.parse_args(argv)
    cfg = _config.load(a.config)
    main(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(cli())
