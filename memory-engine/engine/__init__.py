# -*- coding: utf-8 -*-
"""memory-engine：文件型长期记忆的最小实现。

四个模块，零第三方依赖：
- config.py            读 config.json
- import_memories.py   建 FTS5(trigram) 旁路库
- search.py            检索（热 → 冷 → 近义）
- weight.py            卡片权重的惰性衰减
- associate.py         从一张卡浮出邻居
"""

__version__ = "0.1.0"
