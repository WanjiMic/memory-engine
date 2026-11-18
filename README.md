# memory-engine
[![ci](https://github.com/WanjiMic/memory-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/WanjiMic/memory-engine/actions/workflows/ci.yml)
文件型长期记忆的最小实现：**正本是普通 Markdown，检索走 FTS5，旧事只沉不删，捞回来时明说是捞回来的。**

不依赖向量库、不依赖外部服务，四个 Python 文件，能在一台离线电脑上跑。

它不是一个演示：这套做法在一个真实的私人知识库里每天跑了两个月，本仓库是那套系统抽出来的公开部分——代码、文档和一份虚构的 demo 语料；真实语料与生活记录不在其中。

---

## 它解决什么问题

大多数「给 AI 加记忆」的做法是：把对话存进向量库，检索时按语义相似度捞。这类系统有两个毛病：

1. **黑箱**。记忆是嵌入向量，你看不到它记住了什么、为什么忘了。
2. **只进不出**。时间一长，三年前的琐事和昨天的事同等权重，检索质量随库变大而下降。

这个项目换一种做法：

- **正本是文件**。所有记忆是你能用编辑器打开的 `.md` / `.txt`；索引库是可丢弃的缓存，删了重跑就能回来。
- **时间会衰减**。每条记忆有一个权重，随天数按配置的速率下降；被检索到、被「唤醒」会加回来。冷掉的不删除，只是不再拦截热记忆，需要时还能捞。
- **有出处**。输出里的〔原话〕指向正本文件的 `path#L行号`，点开就能核对。
- **分源加权**。规则文件、用户自己的声音，检索时排在普通日记前面。

## 它不是什么

- 不是聊天机器人，没有 UI。
- 不是向量检索，不理解语义；它按字面、近义词表和共同标签找。
- 不托管你的数据，所有东西都在你本地目录里。
- 不替代 git：它假设你定期提交正本。

### 也不打算做

把边界先写死，是为了让它活得久：

- **向量库、嵌入模型**——不是不会做，是那条路的维护面比它解决的问题大；语义检索交给上层工具即可。
- **云同步、服务端、账号体系**——数据留在你的目录里，这就是它的边界。
- **自动摘要、自动抽卡**——写回由人和宿主决定，引擎不替你做判断；判断错了，坏的是记忆本身。
- **平台接入**（微信、抖音这类）——那是宿主侧的事，不进核心。

## 包含什么、不包含什么

| 包含 | 不包含 |
| --- | --- |
| 四个引擎模块、配置、demo、测试 | 真实语料与任何个人数据 |
| 情绪索引的读取（联想用） | 情绪索引 / 记忆索引 / 星图的生成脚本 |
| 冷记忆机制（阈值 + 回捞） | 题库服务、聊天平台接入 |
| 设计、提示词、运维、评测四份方法文档 | 提交口、体检、备份等运维脚本（做法写在 `docs/operations.md`） |

说明两点：

- **正本不限于「记忆」**。任何 `.md` / `.txt` 都能配进 `sources` / `dirs`，demo 里就混了日记、工作规则、面试笔记。
- **索引只有一份**。`记忆索引.txt` 这类「给人 grep 的速查表」在开源包里没有——引擎用 SQLite 的 FTS5，再维护一份文本索引是重复。人的阅读入口就是正本和检索输出。


## 快速开始

要求：Python ≥ 3.9，SQLite ≥ 3.34（需要内置 FTS5 的 trigram 分词器）。

```bash
python -c "import sqlite3; print(sqlite3.sqlite_version)"
```

```bash
# 1. 建索引（demo 语料）
python -m engine.import_memories --config demo/config.json

# 2. 检索
python -m engine.search --config demo/config.json "解析器"
python -m engine.search --config demo/config.json "空引用"      # 近义扩展 → 空指针
python -m engine.search --config demo/config.json "提交"        # 法源（规则文件）优先
python -m engine.search --config demo/config.json "累"          # 两字词走 LIKE 兜底
python -m engine.search --config demo/config.json "棋谱"        # 冷记忆单独回捞

# 3. 权重旁表
python -m engine.weight --config demo/config.json --init
python -m engine.weight --config demo/config.json --check

# 4. 联想：从一张记忆卡浮出相关卡
python -m engine.associate --config demo/config.json e20261104-2
python -m engine.search --config demo/config.json "疲惫" --fanout

# 5. 冒烟测试（拷 demo 到临时目录跑，不动 demo）
python tests/smoke.py
```

Windows 控制台如果显示乱码，先设置 `set PYTHONIOENCODING=utf-8`（PowerShell：`$env:PYTHONIOENCODING="utf-8"`）。

## 五个概念

| 概念 | 是什么 | 放在哪 |
| --- | --- | --- |
| 正本 | 你手写的记忆文件，Markdown，标题分节 | 任意目录，`sources` + `dirs` 指定 |
| 账本 | 按天记录的流水账，`## YYYY-MM-DD` 是一天的锚点 | `ledger` 配置，通常是正本里的一本 |
| 卡 | 从账本抽出来的一条可独立引用的记忆，带 id / 日期 / 类型 / 权重 | `cards`（JSONL） |
| 旁表 | 每张卡的衰减状态（最后醒来的日期、是否钉住） | `weights`（JSON） |
| 库 | FTS5 索引，可随时重建 | `db`（SQLite） |

## 检索行为

1. 查询拆词；两字及以下的词走 `LIKE` 兜底（trigram 需要三个字符），三字以上走 FTS5 的 `AND`。
2. 近义表（`alias_file`，格式 `词 = 说法`）双向扩展。
3. 排除已冷掉的卡（w < `cold`），除非热结果为空——这时单独回捞冷记忆，并明确告诉你这是冷记忆。
4. 加权排序：规则来源 ×3、你自己的声音 ×2，再乘以权重系数。
5. 输出〔原话〕行：找到卡片对应的正本段落，附 `path#L行号`。
6. 库比正本旧时，查询前自动重建。

## 权重怎么算

```
w = max(1, round(100 - rate × 天数))
```

- `rate` 按卡片类型取 `decay.kind`，没有就用 `decay.default`；带钉住标记的卡不衰减。
- `w3` 是「三天减半」的速率换算：`rate = 100 × (1 - 0.5^(1/3)) / 3`。
- 被检索命中时按 `wake_gain` 加回来（`weight --wake ID`）。
- 冷阈值 `cold` 默认 20。

具体数值在 `engine/weight.py` 顶部，改之前先读 `docs/design.md` 的「为什么是线性衰减」。

## 配置

复制 `config.example.json` 为 `config.json`（或放在 `MEMORY_ENGINE_CONFIG` 指向的位置），改 `root` 即可。键的含义见注释和 `docs/design.md`。

## 目录结构

```
engine/
  config.py           配置查找与路径解析
  import_memories.py  正本/卡 → SQLite FTS5
  search.py           检索、加权、原话、冷记忆
  weight.py           衰减公式与旁表
  associate.py        卡片联想
demo/                 可直接跑的虚构语料
docs/                 设计与运维方法
tests/smoke.py        冒烟测试
schema.sql            库结构
```

## 已知限制

- 中文没有分词，靠 trigram；小于三字的词只能 `LIKE`，库大时慢。
- 不理解语义；换个说法但近义表里没有，就找不到。
- 单机、单写入者；并发写同一个库不做保护。
- 衰减公式是手调的，不是拟合出来的。

## License

MIT。见 `LICENSE`。
