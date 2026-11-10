# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Page-level PDF Sources with evidence-page retrieval."""

from __future__ import annotations

import hashlib
import io
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from pydantic import BaseModel

if TYPE_CHECKING:
    from powercontext.builtin.artifacts.memory.models import MemoryCitation

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PDF_PAGE_SOURCE_TYPE = "pdf-page"
_SOURCE_ID_PREFIX = "pdf"
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "did",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "which",
        "who",
        "why",
        "with",
        "any",
        "reported",
        "report",
        "company",
        "fy2022",
        "fy2021",
    }
)


class PDFDocumentInput(BaseModel):
    """Complete original PDF bytes plus caller-selected document identity."""

    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    """One physical page parsed from a complete PDF revision."""

    document_id: str
    document_sha256: str
    page_number: int
    text: str


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Parse every physical page of a PDF atomically."""

    if not isinstance(value, PDFDocumentInput):
        raise ValueError("value must be a PDFDocumentInput")  # noqa: TRY003
    if not value.document_id or not value.document_id.strip():
        raise ValueError("document_id must be a non-blank string")  # noqa: TRY003
    if not value.content:
        raise ValueError("PDF content must not be empty")  # noqa: TRY003

    from pypdf import PdfReader

    document_sha256 = hashlib.sha256(value.content).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(value.content))
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise ValueError("PDF requires a user password")  # noqa: TRY003
        page_count = len(reader.pages)
    except ValueError:
        raise
    except Exception as error:  # noqa: BLE001 - pypdf exposes several failure types
        raise ValueError("PDF could not be parsed") from error
    if page_count < 1:
        raise ValueError("PDF must contain at least one page")  # noqa: TRY003

    pages: list[PDFPageInput] = []
    try:
        for index in range(page_count):
            text = reader.pages[index].extract_text() or ""
            pages.append(
                PDFPageInput(
                    document_id=value.document_id,
                    document_sha256=document_sha256,
                    page_number=index + 1,
                    text=text,
                )
            )
    except Exception as error:  # noqa: BLE001 - any page extraction failure is atomic
        raise ValueError("PDF could not be parsed completely") from error
    return tuple(pages)


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    """Build the stable identity for one physical page of one PDF revision."""

    encoded_document = quote(document_id, safe="")
    source_id = f"{_SOURCE_ID_PREFIX}:{encoded_document}:{document_sha256}:{page_number}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        digest = hashlib.sha256(document_id.encode("utf-8")).hexdigest()
        source_id = f"{_SOURCE_ID_PREFIX}:{digest}:{document_sha256}:{page_number}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"page identity must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return source_id


class PDFPageSource(Source):
    """Captured physical page retaining document identity, revision and page number."""

    source_id: str
    document_id: str
    document_sha256: str
    page_number: int
    text: str


class _PDFPageTextEvidenceProjection:
    """Standard powercontext.text-evidence projection for one PDF page."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_TYPE,
            source_id=source.name,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


class _PDFPageAdapter:
    name = PDF_PAGE_SOURCE_TYPE
    input_class = PDFPageInput
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        source_id = pdf_page_source_id(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(
    adapter=_PDFPageAdapter(),
    version="1",
    projections=(_PDFPageTextEvidenceProjection(),),
)


def _question_keywords(question: str) -> tuple[str, ...]:
    tokens = re.findall(r"[a-z0-9][a-z0-9&.'-]*", question.lower())
    keywords = [token.strip(".") for token in tokens if token not in _STOPWORDS and len(token) > 1]
    seen: dict[str, None] = {}
    for keyword in keywords:
        seen.setdefault(keyword, None)
    return tuple(seen)


async def search_pdf_pages(
    memory: Any,
    question: str,
    limit: int = 10,
) -> "tuple[MemoryCitation, ...]":
    """Search the scoped Memory for distinct physical evidence pages."""

    from powercontext.builtin.artifacts.memory.models import MemoryCitation
    from powercontext.builtin.runtime.models import GetMemoryEntryRequest, SearchMemoryRequest

    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")  # noqa: TRY003
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be non-empty")  # noqa: TRY003

    keywords = _question_keywords(question)
    terms = keywords or tuple(re.findall(r"[a-z0-9]{2,}", question.lower()))
    queries: list[str] = [question.strip()]
    if keywords:
        queries.extend(keyword for keyword in keywords[:6])
        queries.append(" ".join(keywords[:6]))
        queries.append(" ".join(keywords[:3]))

    citations: dict[tuple[str, str, str], "MemoryCitation"] = {}
    first_seen: dict[tuple[str, str, str], int] = {}
    fts_rank: dict[tuple[str, str, str], int] = {}
    fetch_limit = max(limit * 4, 20)
    for query in queries:
        try:
            page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=fetch_limit))
        except Exception:  # noqa: BLE001 - one weak sub-query must not abort evidence retrieval
            continue
        for rank, hit in enumerate(page.hits):
            key = (hit.entry_id, hit.entry_version_id, hit.memory_ref.artifact_id)
            if key not in citations:
                first_seen[key] = len(first_seen)
                citations[key] = MemoryCitation(
                    memory_ref=hit.memory_ref,
                    entry_id=hit.entry_id,
                    entry_version_id=hit.entry_version_id,
                )
            fts_rank[key] = min(fts_rank.get(key, rank), rank)

    # The whole page set is small enough to score locally: reading every active page removes
    # dependence on one query's postings, so evidence pages that share few literal tokens with
    # the question still reach the reranker and can enter the top pages.
    scores: dict[tuple[str, str, str], float] = {}
    try:
        page_entries = await memory.list()
        for record in page_entries.entries:
            citation = record.citation
            key = (citation.entry_id, citation.entry_version_id, citation.memory_ref.artifact_id)
            if key not in citations:
                citations[key] = citation
                first_seen[key] = len(first_seen)
            scores[key] = _page_relevance(record.entry.text, terms)
    except Exception:  # noqa: BLE001 - local scoring is an optimisation, FTS results still apply
        pass

    for key, citation in citations.items():
        if key in scores:
            continue
        try:
            entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
            scores[key] = _page_relevance(entry.text, terms)
        except Exception:  # noqa: BLE001 - a read failure must not drop otherwise searchable evidence
            scores[key] = 0.0

    ranked = sorted(
        citations,
        key=lambda key: (-(scores.get(key, 0.0) + 6.0 / (1.0 + fts_rank.get(key, 1000))), first_seen[key]),
    )
    return tuple(citations[key] for key in ranked[:limit])


def _page_relevance(text: str, terms: Sequence[str]) -> float:
    """Score one page by how much of the question it literally covers."""

    lowered = text.lower()
    if not terms:
        return 0.0
    matched = 0
    frequency = 0
    for term in terms:
        occurrences = lowered.count(term)
        if occurrences:
            matched += 1
            frequency += min(occurrences, 5)
    coverage = matched / len(terms)
    return coverage * 10.0 + frequency * 0.5


__all__ = [
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "PDF_PAGE_SOURCE_DEFINITION",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]
