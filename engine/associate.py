# -*- coding: utf-8 -*-
"""从一张卡往外找「挨着的」卡。

A 被想起来时，把 B、C 一起浮出来，顺着话题接下去，而不是干等下一句。

规矩（跟冷记忆同一套）：
- 有证据才写：分数不到 3 分不出；
- 一次最多两条，别把话塞满；
- 只写关系名（同日／同类／同 tag／同实体／同一件事／说法挨着／近时），
  **不写因果**——「同一天记下的」不等于「因为这件事」；
- 引之前自己核。

用法：
    python -m engine.associate --config demo/config.json e20261104-2 [条数]
    python -m engine.search ... --fanout     # 查完顺手浮出
"""
import argparse
import io
import json
import os
import re
import sys

from . import config as _config

CARD_ID = re.compile(r"^e\d{8}-\d+$")

# 关系权重：按「这条关系能多说明一件事」排，不一律给分
W_TAG = 3.0         # 同一个情绪标签——最深的一层
W_ENTITY = 1.0      # 每个专名 1 分，最多 3 分
W_SAME_TOPIC = 2.5  # 共享 5 个以上三字块，基本就是同一件事
W_LOOSE = 1.2       # 共享 2–4 个，只能说挨着
W_SAMEDAY = 2.0     # 同一天记下的
W_SAMEK = 1.0       # 同一类卡
W_NEAR = 1.5        # 时间衰减的上限（隔一天 1.19，三天 0.83，一周 0.42）
HALF_LIFE = 3.5     # 每 3.5 天衰减一半


def load_cards(cfg):
    out = []
    try:
        with io.open(cfg.cards, encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    c = json.loads(ln)
                except Exception:
                    continue
                if c.get("id") and c.get("text"):
                    out.append(c)
    except Exception:
        pass
    return out


def emotion_keys(cfg):
    """情绪索引里 `### 标签` 的标签集合；没有这个文件就返回空集。"""
    keys = set()
    try:
        if not cfg.emotion_index or not os.path.exists(cfg.emotion_index):
            return keys
        with io.open(cfg.emotion_index, encoding="utf-8") as fh:
            for ln in fh:
                m = re.match(r"^###\s+([^\s（(]+)", ln.strip())
                if m:
                    keys.add(m.group(1))
    except Exception:
        pass
    return keys


def tags(c, keys):
    return [t for t in re.findall(r"\[([^\[\]]{1,8})\]", c.get("text", "")) if t in keys]


def entities(c):
    """专名只认两种：ASCII 标识（文件名、命令、提交号）和「」里引的原话片段。

    中文人名不猜——猜错一次，就是张冠李戴。
    """
    txt = c.get("text", "") + " " + str(c.get("refs", ""))
    ascii_set = set(re.findall(r"(?<![.\w])[A-Za-z][A-Za-z0-9_\-/\\]{3,}", txt))
    ascii_set -= {"txt", "json", "html", "ps1", "mjs", "md", "py", "exe", "zip"}
    quoted = set(re.findall(r"「([^」]{2,12})」", txt))
    return ascii_set | quoted


def grams(text, n=3):
    """中文没有空格，按 3 字滑窗切——两张卡共享的 3 字块越多，说的越像一件事。"""
    t = re.sub(r"[\s\W_]+", "", str(text))
    return set(t[i:i + n] for i in range(max(0, len(t) - n + 1)))


def day_of(c):
    try:
        y, m, d = c["date"].split("-")
        return int(y) * 372 + int(m) * 31 + int(d)
    except Exception:
        return None


def near_score(da, db):
    """连续衰减：越近越像一回事，隔得越远越只是巧合。"""
    if da is None or db is None:
        return 0.0
    gap = abs(da - db)
    if gap <= 0:
        return 0.0
    return W_NEAR * (0.5 ** (gap / HALF_LIFE))


def score(a, b, keys):
    s = 0.0
    why = []
    if a.get("date") == b.get("date"):
        s += W_SAMEDAY
        why.append("同日")
    if a.get("date") == b.get("date") and a.get("k") and a.get("k") == b.get("k"):
        s += W_SAMEK
        why.append("同类：" + str(a.get("k")))
    same_t = set(tags(a, keys)) & set(tags(b, keys))
    if same_t:
        s += W_TAG
        why.append("同tag：" + "/".join(sorted(same_t)))
    same_e = entities(a) & entities(b)
    if same_e:
        s += min(3, len(same_e)) * W_ENTITY
        why.append("同实体：" + "/".join(sorted(same_e)[:3]))
    shared = len(grams(a.get("text", "")) & grams(b.get("text", "")))
    if shared >= 5:
        s += W_SAME_TOPIC
        why.append("同一件事")
    elif shared >= 2:
        s += W_LOOSE
        why.append("说法挨着")
    ns = near_score(day_of(a), day_of(b))
    if ns >= 0.3:
        s += ns
        why.append("近时")
    return s, "·".join(why)


def brief(text, n=38):
    t = re.sub(r"\s+", " ", str(text)).strip()
    return t[:n] + ("…" if len(t) > n else "")


def fanout(cfg, card_id, n=2):
    """返回 [(card, 分数, 关系名)]，按分数降序、同分按日期倒序。"""
    cards = load_cards(cfg)
    a = next((c for c in cards if c.get("id") == card_id), None)
    if a is None:
        return []
    keys = emotion_keys(cfg)
    scored = []
    for b in cards:
        if b.get("id") == card_id:
            continue
        s, why = score(a, b, keys)
        if s >= 3:
            scored.append((b, s, why))
    scored.sort(key=lambda x: (-x[1], x[0].get("date", ""), x[0].get("id", "")))
    return scored[:n]


def lines_for(cfg, card_id, n=2):
    out = []
    for card, s, why in fanout(cfg, card_id, n):
        out.append("〔联想〕%s（%s）· %s" % (card["id"], why, brief(card["text"])))
    return out


def cli(argv=None):
    ap = argparse.ArgumentParser(description="从一张卡往外找邻居")
    ap.add_argument("card", nargs="?", default="")
    ap.add_argument("n", nargs="?", type=int, default=2)
    ap.add_argument("--config", help="config.json 路径")
    a = ap.parse_args(argv)
    if not a.card.strip():
        print("用一张卡往外找邻居：python -m engine.associate --config demo/config.json e20261104-2 [条数]")
        return 2
    if not CARD_ID.match(a.card.strip()):
        print("这不是记忆卡号（长这样：e20261104-2）。")
        return 2
    cfg = _config.load(a.config)
    rows = lines_for(cfg, a.card.strip(), a.n)
    if not rows:
        print("这张卡附近没有够 3 分的邻居——不硬凑。")
        return 0
    for ln in rows:
        print(ln)
    print("（只写关系名，不写因果；引之前自己核。）")
    return 0


if __name__ == "__main__":
    sys.exit(cli())
