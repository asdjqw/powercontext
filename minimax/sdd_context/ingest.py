"""Build the seekdb engineering index from project specs, code, docs and tests."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .config import CODE_DIR, DOC_DIR, PROJECT_DIR, ROOT, SPEC_DIR, TEST_DIR
from .db import Document, SeekdbStore

SPEC_GLOB = "*.md"
CODE_GLOB = "*.py"
TEST_GLOB = "*.py"

_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)|^\s*class\s+(\w+)", re.MULTILINE)
_HEADING_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def _first_title(text: str, fallback: str) -> str:
    heading = _HEADING_RE.search(text)
    if heading:
        return heading.group(1).strip()[:500]
    return fallback


def _symbols(text: str, fallback: str) -> str:
    names: list[str] = []
    for match in _DEF_RE.finditer(text):
        name = match.group(1) or match.group(2)
        if name and name not in names:
            names.append(name)
    return ", ".join(names[:12]) if names else fallback


def _document(path: Path, kind: str) -> Document:
    content = path.read_text(encoding="utf-8")
    rel = path.relative_to(ROOT).as_posix()
    title = _first_title(content, path.stem)
    symbol = _symbols(content, path.stem)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return Document(rel, kind, symbol, title, content, digest)


def collect_documents() -> list[Document]:
    documents: list[Document] = []
    for path in sorted(SPEC_DIR.glob(SPEC_GLOB)):
        documents.append(_document(path, "spec"))
    for path in sorted(DOC_DIR.glob(SPEC_GLOB)):
        documents.append(_document(path, "doc"))
    for path in sorted(CODE_DIR.rglob(CODE_GLOB)):
        if "__pycache__" not in path.parts:
            documents.append(_document(path, "code"))
    for path in sorted(TEST_DIR.rglob(TEST_GLOB)):
        if "__pycache__" not in path.parts:
            documents.append(_document(path, "test"))
    # These are optional before the write-up steps; the index remains valid
    # without them.
    for name in ("README.md", "TECHNICAL_NOTE.md"):
        path = ROOT / name
        if path.is_file():
            documents.append(_document(path, "doc"))
    return documents


def import_project(store: SeekdbStore, reset: bool = False) -> dict[str, int]:
    store.ensure_schema()
    if reset:
        store.reset()
    documents = collect_documents()
    store.delete_missing([doc.doc_key for doc in documents])
    store.upsert(documents)
    counts = store.count_documents()
    return {"indexed": len(documents), **counts}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    store = SeekdbStore()
    try:
        print(import_project(store, reset=args.reset))
    finally:
        store.close()
