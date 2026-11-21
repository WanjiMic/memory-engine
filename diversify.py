# -*- coding: utf-8 -*-
"""MMR 去冗余：先要最相关的，再压掉「和已经选中的太像」的。

为什么需要：同一件事往往被写进好几张卡（同一天多张、或换个说法又记一遍）。
纯按相关度排序时，它们会挤在结果的最前面，把别的意思挤掉。
MMR（Maximal Marginal Relevance）在第一项之后，把「和已选项相似度高」的分数打折，
让位置让给「也相关、但不重复」的那条。

三个约定：
- `lam`（λ）= 1.0 时完全不干预，结果跟纯相关度排序一样——想关掉就调成 1.0；
- 相似度是「字符二元组 Jaccard」，不看词义：只说「字面上像」，不装懂意思；
- 同一天的两张卡，相似度至少有 `same_day`（默认 0.35）——同一天的记录更容易互相覆盖，
  但不至于像近义句那样被直接压掉；
- 相似度 ≥ `dup`（默认 0.75）的候选不算"重复"，只是**排到最后**：人还得看得见它，
  只是别占着前排位置。
"""
import re

_DATE = re.compile(r"^e(\d{4})(\d{2})(\d{2})-\d+$")


def grams(text):
    """字符二元组集合。空串给空集合，单字给单字集合。"""
    t = re.sub(r"\s+", " ", (text or "")).strip()
    if len(t) < 2:
        return set(t)
    return set(t[i:i + 2] for i in range(len(t) - 1))


def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a) + len(b) - inter
    return float(inter) / union if union else 0.0


def day_of(heading):
    """卡片标题 eYYYYMMDD-N → 'YYYYMMDD'；不是卡片就返回空串。"""
    m = _DATE.match((heading or "").strip())
    return m.group(0)[1:9] if m else ""


def order(items, k, lam=0.70, same_day=0.35, dup=0.75):
    """挑出前 k 个，返回它们在 items 里的下标（按挑选顺序）。

    items：list of dict，至少要 `score`（越大越相关）、`text`，可选 `day`。
    """
    n = len(items)
    if n == 0:
        return []
    k = max(0, min(int(k), n))
    if k == 0:
        return []
    if n == 1 or lam >= 1.0:
        return sorted(range(n), key=lambda i: -items[i].get("score", 0.0))[:k]

    scores = [float(it.get("score", 0.0)) for it in items]
    lo, hi = min(scores), max(scores)
    span = (hi - lo) or 1.0
    norm = [(s - lo) / span for s in scores]
    grs = [grams(it.get("text", "")) for it in items]
    days = [it.get("day", "") or "" for it in items]

    def sim_to(i, j):
        s = jaccard(grs[i], grs[j])
        if days[i] and days[i] == days[j] and s < same_day:
            s = same_day
        return s

    picked = []
    rest = list(range(n))
    while rest and len(picked) < k:
        # 和已选的重到 dup 以上的，先让位；实在没有别的才轮到它们
        fresh = [i for i in rest if all(sim_to(i, j) < dup for j in picked)]
        pool = fresh if fresh else rest
        best_i, best_v = None, None
        for i in pool:
            if not picked:
                v = norm[i]
            else:
                pen = max([sim_to(i, j) for j in picked] or [0.0])
                v = lam * norm[i] - (1.0 - lam) * pen
            if best_v is None or v > best_v + 1e-12:
                best_v, best_i = v, i
        picked.append(best_i)
        rest.remove(best_i)
    return picked
