# -*- coding: utf-8 -*-
"""冒烟测试：用 demo 语料跑一遍导入、检索、权重、联想。

demo 目录只读：整个 demo 拷到临时目录里跑，跑完删掉。

用法（在仓库根目录）：
    python tests/smoke.py
"""
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "demo")
PY = sys.executable
ENV = dict(os.environ, PYTHONIOENCODING="utf-8")


def run(*args):
    r = subprocess.run(
        [PY] + list(args),
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=ENV,
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def check_mmr(check):
    """去冗余是纯函数，不用起子进程：直接喂几条假候选。"""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from engine import diversify as dv

    items = [
        {"score": 10.0, "text": "今天把检索的排序改好了，MMR 那一步也接上了，测试也过了。", "day": "20261120"},
        {"score": 9.7, "text": "今天把检索的排序改好了，MMR 那一步也接上了，测试过了。", "day": "20261120"},
        {"score": 9.4, "text": "晚饭煮了面，盐放多了，喝了两杯水。", "day": "20261120"},
    ]
    check("去冗余：λ=1 不干预", dv.order(items, 3, lam=1.0) == [0, 1, 2])
    check("去冗余：压掉同日近义句", dv.order(items, 3, lam=0.7) == [0, 2, 1])
    check("去冗余：日期从卡片标题取", dv.day_of("e20261120-3") == "20261120" and dv.day_of("日记") == "")


def main():
    # 建在仓库里当临时工作区；不用 tempfile.mkdtemp——它在 Windows 沙箱里
    # 建出来的目录连创建者自己都写不进（WinError 5）。
    tmp = os.path.join(ROOT, ".smoke-%d-%d" % (os.getpid(), int(time.time())))
    while os.path.exists(tmp):
        tmp += "x"
    os.makedirs(tmp)
    fail = 0
    names = []

    def check(name, ok, out=""):
        nonlocal fail
        print(("过  " if ok else "挂  ") + name)
        names.append(name)
        if not ok:
            fail += 1
            tail = (out or "").strip().splitlines()[-6:]
            print("    尾巴：" + " | ".join(tail))

    try:
        dst = os.path.join(tmp, "demo")
        shutil.copytree(DEMO, dst)
        for name in ("memory.db", "weights.json", "stats.json"):
            p = os.path.join(dst, "data", name)
            if os.path.exists(p):
                os.remove(p)

        # 加一张很旧的卡，用来验证「冷记忆回捞」
        with open(os.path.join(dst, "data", "cards.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(
                '{"id": "e20200101-1", "date": "2020-01-01", "k": "事件", "w": 2, '
                '"text": "很久以前跑通的一次棋谱解析。", "refs": []}\n'
            )

        cfg = os.path.join(dst, "config.json")

        rc, out = run("-m", "engine.import_memories", "--config", cfg)
        check("导入", rc == 0 and "导入" in out and "段" in out, out)

        rc, out = run("-m", "engine.search", "--config", cfg, "解析器")
        check("检索：长词命中", rc == 0 and "解析器" in out and "没有命中" not in out, out)

        rc, out = run("-m", "engine.search", "--config", cfg, "解析器 用例")
        check("检索：多词 AND", rc == 0 and "解析器" in out, out)

        rc, out = run("-m", "engine.search", "--config", cfg, "空引用")
        check("检索：近义扩展", rc == 0 and "近义扩展" in out and "空指针" in out, out)

        rc, out = run("-m", "engine.search", "--config", cfg, "累")
        check("检索：短词走 LIKE", rc == 0 and "有点累" in out, out)

        rc, out = run("-m", "engine.search", "--config", cfg, "提交")
        check("检索：法源加权", rc == 0 and "【法源】" in out, out)

        rc, out = run("-m", "engine.search", "--config", cfg, "zzz不存在zzz")
        check("检索：查不到要说话", rc == 0 and "没有命中" in out, out)

        rc, out = run("-m", "engine.search", "--config", cfg)
        check("检索：空查询给用法", rc == 1 and "用法" in out, out)

        rc, out = run("-m", "engine.search", "--config", cfg, "棋谱")
        check("检索：冷记忆回捞", rc == 0 and "〔冷记忆命中〕" in out, out)

        rc, out = run("-m", "engine.weight", "--config", cfg, "--init")
        check("权重：建旁表", rc == 0 and "旁表" in out, out)

        rc, out = run("-m", "engine.weight", "--config", cfg, "--check")
        check("权重：check 输出一行 JSON", rc == 0 and '"cards": 7' in out, out)

        rc, out = run("-m", "engine.associate", "--config", cfg, "e20261104-2")
        check("联想：同 tag 浮出", rc == 0 and "〔联想〕" in out, out)

        rc, out = run("-m", "engine.search", "--config", cfg, "疲惫", "--fanout")
        check("检索：--fanout", rc == 0 and "〔联想〕" in out, out)

        # 让正本比库新：下次检索应自动重建
        src = os.path.join(dst, "corpus", "日记.md")
        future = time.time() + 10
        os.utime(src, (future, future))
        rc, out = run("-m", "engine.search", "--config", cfg, "解析器")
        check("检索：旧库自动重建", rc == 0 and "已先按正本重建" in out, out)

        check_mmr(check)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("%d 项，%d 挂" % (len(names), fail))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
