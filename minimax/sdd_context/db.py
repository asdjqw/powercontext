"""Thin seekdb (MySQL protocol) storage adapter for engineering documents."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pymysql

from .config import EVIDENCE_DIR, ensure_dirs, parse_dsn, seekdb_dsn


@dataclass
class Document:
    path: str
    kind: str
    symbol: str
    title: str
    content: str
    content_hash: str

    @property
    def doc_key(self) -> str:
        return hashlib.sha256(f"{self.path}|{self.kind}|{self.symbol}".encode()).hexdigest()


class SeekdbStore:
    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or seekdb_dsn()
        settings = parse_dsn(self.dsn)
        self.host = str(settings["host"])
        self.port = int(settings["port"])
        self.user = str(settings["user"])
        self.password = str(settings["password"])
        self.database = str(settings["database"])
        self._conn: pymysql.connections.Connection | None = None

    def _connect(self, database: str | None = None) -> pymysql.connections.Connection:
        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=database,
            autocommit=True,
            charset="utf8mb4",
        )

    def connect(self) -> pymysql.connections.Connection:
        if self._conn is None:
            self._conn = self._connect(self.database)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def ensure_schema(self) -> None:
        server = self._connect()
        try:
            with server.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{self.database}` "
                    "DEFAULT CHARACTER SET utf8mb4"
                )
        finally:
            server.close()
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sdd_documents (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    doc_key VARCHAR(64) NOT NULL,
                    path VARCHAR(512) NOT NULL,
                    kind VARCHAR(32) NOT NULL,
                    symbol VARCHAR(256) NOT NULL DEFAULT '',
                    title VARCHAR(512) NOT NULL,
                    content LONGTEXT NOT NULL,
                    content_hash VARCHAR(64) NOT NULL,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY uk_sdd_documents_key (doc_key),
                    KEY idx_sdd_documents_kind (kind)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sdd_context_runs (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    task VARCHAR(1024) NOT NULL,
                    source_count INT NOT NULL,
                    source_paths JSON NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        self._log({"event": "schema_ready", "database": self.database})

    def reset(self) -> None:
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS sdd_context_runs")
            cur.execute("DROP TABLE IF EXISTS sdd_documents")
        self.ensure_schema()

    def upsert(self, documents: Iterable[Document]) -> int:
        conn = self.connect()
        count = 0
        with conn.cursor() as cur:
            for doc in documents:
                cur.execute(
                    """
                    INSERT INTO sdd_documents
                        (doc_key, path, kind, symbol, title, content, content_hash)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        path=VALUES(path), kind=VALUES(kind), symbol=VALUES(symbol),
                        title=VALUES(title), content=VALUES(content),
                        content_hash=VALUES(content_hash), updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        doc.doc_key,
                        doc.path,
                        doc.kind,
                        doc.symbol,
                        doc.title,
                        doc.content,
                        doc.content_hash,
                    ),
                )
                count += 1
        self._log({"event": "upsert", "documents": count})
        return count

    def delete_missing(self, keys: list[str]) -> None:
        if not keys:
            return
        conn = self.connect()
        placeholders = ",".join(["%s"] * len(keys))
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM sdd_documents WHERE doc_key NOT IN ({placeholders})", keys)

    def query_documents(self, tokens: list[str], kinds: list[str]) -> list[dict[str, object]]:
        conn = self.connect()
        clauses: list[str] = []
        params: list[object] = []
        kind_placeholders = ",".join(["%s"] * len(kinds))
        clauses.append(f"kind IN ({kind_placeholders})")
        params.extend(kinds)
        if tokens:
            token_clauses: list[str] = []
            for token in tokens[:12]:
                escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                like = f"%{escaped}%"
                token_clauses.append("(title LIKE %s OR symbol LIKE %s OR content LIKE %s)")
                params.extend([like, like, like])
            clauses.append("(" + " OR ".join(token_clauses) + ")")
        sql = (
            "SELECT id, path, kind, symbol, title, content, content_hash, updated_at "
            "FROM sdd_documents WHERE " + " AND ".join(clauses) + " ORDER BY id LIMIT 200"
        )
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(sql, params)
            rows = list(cur.fetchall())
        self._log(
            {
                "event": "query",
                "sql": sql,
                "tokens": tokens,
                "kinds": kinds,
                "rows": len(rows),
            }
        )
        return rows

    def record_context_run(self, task: str, source_paths: list[str]) -> None:
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sdd_context_runs (task, source_count, source_paths) VALUES (%s, %s, %s)",
                (task[:1024], len(source_paths), json.dumps(source_paths, ensure_ascii=False)),
            )

    def count_documents(self) -> dict[str, int]:
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute("SELECT kind, COUNT(*) AS n FROM sdd_documents GROUP BY kind ORDER BY kind")
            rows = cur.fetchall()
        return {str(kind): int(count) for kind, count in rows}

    def _log(self, payload: dict[str, object]) -> None:
        ensure_dirs()
        record = {"at": datetime.now(timezone.utc).isoformat(), **payload}
        with (EVIDENCE_DIR / "seekdb_queries.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
