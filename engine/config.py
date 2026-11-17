# -*- coding: utf-8 -*-
"""配置加载。

查找顺序：
1. 命令行 --config PATH
2. 环境变量 MEMORY_ENGINE_CONFIG
3. 当前目录的 config.json

config.json 里的相对路径都按「配置文件所在目录」解析。
示例见仓库根目录的 config.example.json。
"""
import io
import json
import os
import sys

DECAY_DEFAULT = {
    "kind": {},        # 卡片 k 字段 → 每天掉多少分，例如 {"情绪": 1.0}
    "w_min": 3,        # 卡片 w 字段 ≥ w_min 时用下一档速率
    "w3": 0.5,
    "default": 2.0,
}


class Config(object):
    """一份 config.json 的解析结果；路径全部转成绝对路径。"""

    def __init__(self, data, base, path=None):
        self.path = path
        self.base = base

        self.root = self._path(data.get("root", "."))
        self.db = self._path(data.get("db", ".data/memory.db"))
        self.sources = list(data.get("sources") or [])
        self.dirs = list(data.get("dirs") or [])
        self.ledger = data.get("ledger") or None

        self.cards = self._path(data.get("cards", ".data/cards.jsonl"))
        self.cards_source = data.get("cards_source") or "cards"
        self.weights = self._path(data.get("weights", ".data/weights.json"))
        self.anchors = self._path(data.get("anchors", ".data/anchors.json"))
        self.stats = self._path(data.get("stats", ".data/stats.json"))

        af = data.get("alias_file")
        self.alias_file = self._path(af) if af else None
        ei = data.get("emotion_index")
        self.emotion_index = self._path(ei) if ei else None

        law = data.get("law") or {}
        self.law_prefixes = list(law.get("prefixes") or [])
        self.law_files = list(law.get("files") or [])
        self.my_voice = list(data.get("my_voice") or [])

        self.cold = int(data.get("cold", 20))
        self.decay = dict(DECAY_DEFAULT)
        user_decay = data.get("decay") or {}
        self.decay.update({k: v for k, v in user_decay.items() if k != "kind"})
        self.decay["kind"] = dict(user_decay.get("kind") or {})
        self.wake_gain = int(data.get("wake_gain", 20))

        cl = data.get("cold_log")
        self.cold_log = self._path(cl) if cl else None

    def _path(self, rel):
        rel = os.path.expanduser(str(rel))
        if os.path.isabs(rel):
            return os.path.normpath(rel)
        return os.path.normpath(os.path.join(self.base, rel))


def find(cli=None):
    """把 --config / 环境变量 / ./config.json 解析成一个路径，找不到返回 None。"""
    if cli:
        return os.path.abspath(os.path.expanduser(cli))
    env = os.environ.get("MEMORY_ENGINE_CONFIG")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    if os.path.isfile("config.json"):
        return os.path.abspath("config.json")
    return None


def load(cli=None):
    path = find(cli)
    if not path:
        sys.stderr.write(
            "找不到 config.json：用 --config 指定，或设 MEMORY_ENGINE_CONFIG，"
            "或在当前目录放一份 config.json。\n"
        )
        raise SystemExit(2)
    try:
        with io.open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as e:
        sys.stderr.write("config 读不了：%s（%s）\n" % (path, e))
        raise SystemExit(2)
    return Config(data, os.path.dirname(path), path)
