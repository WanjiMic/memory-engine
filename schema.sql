-- memory-engine 的旁路库结构。
-- 库是可丢弃的：删掉重跑 import_memories 就能回来。

CREATE TABLE chunks(
  id INTEGER PRIMARY KEY,
  source TEXT,              -- 语料文件的相对路径，或 cards_source 标签
  heading TEXT,             -- 小标题；记忆卡的 heading 是卡片 id
  text TEXT,
  w INTEGER DEFAULT 100     -- 导入时的权重快照
);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
  text,
  heading,
  content='chunks',
  content_rowid='id',
  tokenize='trigram'
);
