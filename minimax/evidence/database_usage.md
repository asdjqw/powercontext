# seekdb 使用记录

## 连接

- 本地 seekdb 1.4.0（Windows），MySQL 协议 `127.0.0.1:2881`
- 数据库：`sdd_context`
- 连接串：`mysql://root@127.0.0.1:2881/sdd_context`（可由 `SEEKDB_DSN` 覆盖）
- 驱动：`pymysql`

## 表结构

```sql
CREATE TABLE sdd_documents (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  doc_key VARCHAR(64) NOT NULL UNIQUE,
  path VARCHAR(512) NOT NULL,
  kind VARCHAR(32) NOT NULL,          -- spec/code/test/doc
  symbol VARCHAR(256) NOT NULL,
  title VARCHAR(512) NOT NULL,
  content LONGTEXT NOT NULL,
  content_hash VARCHAR(64) NOT NULL,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE sdd_context_runs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  task VARCHAR(1024) NOT NULL,
  source_count INT NOT NULL,
  source_paths JSON NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 导入结果

```json
{"indexed": 7, "spec": 3, "code": 1, "test": 2, "doc": 1}
```

## 实际查询

`context` 命令执行的关键词 SQL（参数化）：

```sql
SELECT id, path, kind, symbol, title, content, content_hash, updated_at
FROM sdd_documents
WHERE kind IN (%s, %s, %s, %s)
  AND (title LIKE %s OR symbol LIKE %s OR content LIKE %s OR ...)
ORDER BY id LIMIT 200;
```

每次执行的 SQL、检索词、kind 和返回行数都追加到 `seekdb_queries.jsonl`。上下文只使用这些数据库行的内容、路径、符号和 id；没有硬编码答案。

## 规格更新验证

把 `project/specs/policy_amendment.md` 的 `10,000 cents` 改成 `12,000 cents`，重新 `import` 后，同一 path 的 `content`/`content_hash` 被更新；随后 `context --task "PRICE-AMS-001 effective minimum order"` 的返回文本包含 `12,000 cents`。验收结果见 `context_after_spec_update.json`。

## 复现

```bash
python scripts/start_seekdb.py     # 或设置 SEEKDB_DSN 指向已有实例
python -m sdd_context.cli db-init --reset
python -m sdd_context.cli import --reset
python -m sdd_context.cli context --task "..."
```
