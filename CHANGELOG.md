# 更新记录

## 未发布

- **文档**：新增 `docs/derivations.md`——派生物（结构化索引、星图、行号锚点、冷检索库）是什么、何时重算、为什么不属于引擎。
- **README**：新增「维护模式」：0.1.x 只修 bug；不承诺路线图；可 fork 自留。
- **CI**：新增 `privacy` job，扫描绝对路径、邮箱与常见令牌字样。

## 0.1.0 — 2026-11-17

首个公开版本。

- **导入**：Markdown 按标题切段，日期从 `## YYYY-MM-DD` 取；FTS5 trigram 索引；账本锚定与卡片行号回填。
- **检索**：字面、近义表、短词三路；规则类来源与「自己的声音」加权；〔原话〕带 `path#L行号` 出处；冷记忆回捞。
- **权重**：线性衰减，速率可按来源配置；`--wake` 可唤醒。
- **联想**：按标签、实体、共同话题浮出相关卡。
- **自检**：14 项冒烟测试（`python tests/smoke.py`）。
- **文档**：`docs/design.md`、`docs/prompt-framework.md`、`docs/operations.md`、`docs/evaluation.md`。
