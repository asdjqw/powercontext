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
import math
import re
from collections import Counter
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
_TOKEN = re.compile(r"[a-z]+|\d+")

_BOILERPLATE = re.compile(
    r"(give a response to the question|respond to the question|answer in usd|in your response|"
    r"by relying on|by assuming the perspective|using the details shown|"
    r"please state that and explain why|if .*? is not a useful metric.*?why|"
    r"respond to the question by)"
)

_STOPWORDS = frozenset(
    """a an and are as at be been being by can could did do does for from had has have how in
    into is it its may might must not of on or should so than that the their them then there these
    they this those to was were what when where which who why will with would you your
    give response question questions relying relied rely detail details shown show statement
    statements please following according using use used answer assume assuming perspective
    investment analyst based about above after again against all also am any because before below
    between both but each few further here more most no nor now off once only other our out over
    own same she he her his us very we company companies inc corporation""".split()
)

_SYNONYMS = {
    "geograph": ("countr", "territor", "region", "segment", "international", "amesa", "apac", "europe", "asia"),
    "countr": ("countr", "territor"),
    "region": ("region", "geograph", "countr"),
    "legal": ("litig", "proceed", "claim", "regulat", "investig"),
    "battle": ("litig", "proceed", "claim", "legal"),
    "income": ("income", "profit", "earn", "margin"),
    "profit": ("profit", "income", "earn", "margin"),
    "revenue": ("revenu", "sale"),
    "sale": ("sale", "revenu"),
    "capex": ("capital expenditure", "purchas", "property", "equipment"),
    "expenditure": ("expenditur", "capital expenditure", "purchas"),
    "depreciation": ("depreci", "amort"),
    "amortization": ("amort", "depreci"),
    "tax": ("tax", "effective tax rate"),
    "debt": ("debt", "borrow", "oblig"),
    "borrow": ("borrow", "debt"),
    "dividend": ("dividend", "distribut"),
    "employee": ("employ", "headcount"),
    "customer": ("customer", "client"),
    "liquidity": ("liquid", "cash"),
    "margin": ("margin", "profit"),
    "repurchase": ("repurchas", "buyback"),
    "share": ("share", "stock"),
}

_INTENT_HEADINGS = {
    "income": (
        "statement of income",
        "statements of income",
        "statement of operations",
        "statements of operations",
        "statement of earnings",
        "statements of earnings",
        "consolidated results of operations",
    ),
    "cash": ("statement of cash flows", "statements of cash flows", "cash flows from operating"),
    "balance": (
        "balance sheet",
        "balance sheets",
        "statements of financial position",
        "statement of financial position",
    ),
    "equity": ("statement of equity", "statements of equity", "stockholders equity", "shareholders equity"),
    "legal": ("legal proceedings", "legal proceeding", "litigation", "legal matters", "claims and legal"),
    "geography": ("geographic", "countries and territories", "reportable segments", "segment data"),
    "segment": (
        "business segment",
        "business segments",
        "segment data",
        "summary of business segment",
        "reportable segments",
        "sales and operating income",
    ),
    "tax": ("effective tax rate", "income taxes", "provision for income taxes"),
    "margin": ("gross margin", "operating margin", "results of operations", "gross profit"),
    "capex": ("capital expenditures", "purchases of property", "property plant and equipment", "capital spending"),
    "debt": ("long-term debt", "short-term borrowings", "borrowings", "debt"),
    "dividend": ("dividends", "dividend"),
    "employee": ("employees", "employee", "human capital", "headcount"),
    "customer": ("customers", "customer"),
    "properties": ("properties", "property", "real estate"),
    "liquidity": ("liquidity", "capital resources", "cash flows"),
    "risk": ("risk factors", "risk factor"),
    "revenue": ("net sales", "net revenue", "total revenues", "revenues", "summary of business segment"),
    "goodwill": ("goodwill", "intangible assets"),
    "pension": ("pension", "retirement"),
    "lease": ("leases", "lease"),
    "cover": (
        "securities registered pursuant",
        "registered pursuant to section 12",
        "title of each class",
        "name of each exchange",
    ),
    "business": ("item 1. business", "business overview", "our business"),
    "production": ("production rate", "production rates", "production", "commercial airplanes", "deliveries"),
}

_INTENT_TRIGGERS = {
    "income": (
        "income statement",
        "profit and loss",
        "p&l",
        "statement of operations",
        "statements of operations",
        "statement of earnings",
        "statements of earnings",
        "operating margin",
        "gross margin",
    ),
    "cash": ("cash flow statement", "statement of cash flows", "statements of cash flows", "cash flow"),
    "balance": ("balance sheet", "financial position", "balance sheets"),
    "equity": ("stockholders equity", "shareholders equity", "statement of equity"),
    "legal": ("legal", "litigation", "lawsuit", "battles", "proceedings"),
    "geography": ("geograph", "countries", "geographies", "regions", "operates in"),
    "segment": ("segment", "category", "categories", "product line", "service line"),
    "tax": ("tax rate", "effective tax", "income tax"),
    "margin": ("margin", "gross profit"),
    "capex": ("capital expenditure", "capex", "capital intensive", "capital spending"),
    "debt": ("debt", "borrowings", "leverage"),
    "dividend": ("dividend", "capital return", "buyback", "repurchase"),
    "employee": ("employee", "headcount", "workforce"),
    "customer": ("customer", "client"),
    "properties": ("properties", "real estate", "facilities"),
    "liquidity": ("liquidity", "cash position"),
    "risk": ("risk factor", "risks"),
    "revenue": ("revenue", "sales", "net sales"),
    "goodwill": ("goodwill", "intangible"),
    "pension": ("pension", "retirement"),
    "lease": ("lease",),
    "cover": ("registered to trade", "securities exchange", "registered securities", "registered pursuant", "ticker"),
    "business": ("product", "service", "business", "market", "compete", "customer", "sell", "offer"),
    "production": ("production rate", "production", "forecast", "delivery", "deliveries"),
}

_FINANCIAL_TRIGGERS = (
    "income",
    "revenue",
    "sales",
    "profit",
    "earn",
    "margin",
    "ebitda",
    "ebit",
    "tax",
    "capex",
    "capital",
    "expense",
    "cost",
    "cash",
    "asset",
    "liabilit",
    "equity",
    "debt",
    "borrow",
    "dividend",
    "buyback",
    "repurchase",
    "goodwill",
    "pension",
    "lease",
    "insurance",
    "growth",
    "ratio",
    "return",
    "liquidity",
)

_STATEMENT_INTENTS = frozenset({"income", "cash", "balance", "equity"})


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
        source_id = f"{_SOURCE_ID_PREFIX}:h:{digest}:{document_sha256}:{page_number}"
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


def _normalize_question(question: str) -> str:
    text = question.lower()
    text = re.sub(r"[-–—]", " ", text)
    text = text.replace("p & l", "income statement").replace("p&l", "income statement")
    text = re.sub(r"\bd\s*&\s*a\b", "depreciation amortization", text)
    text = re.sub(r"\bsg\s*&\s*a\b", "selling general administrative", text)
    text = re.sub(r"\bcogs\b", "cost of sales", text)
    text = re.sub(r"\br\s*&\s*d\b", "research development", text)
    text = re.sub(r"\bm\s*&\s*a\b", "merger acquisition", text)
    return _BOILERPLATE.sub(" ", text)


def _content_terms(question: str) -> list[str]:
    tokens = _TOKEN.findall(_normalize_question(question))
    return [token for token in tokens if token not in _STOPWORDS and len(token) > 1]


def _similar(left: str, right: str) -> bool:
    if left == right:
        return True
    if len(left) < 5 or len(right) < 5:
        return False
    if left.startswith(right) or right.startswith(left):
        return True
    common = 0
    for first, second in zip(left, right):
        if first != second:
            break
        common += 1
    return common >= 6


def _intents(question: str) -> set[str]:
    text = _normalize_question(question)
    found = {intent for intent, triggers in _INTENT_TRIGGERS.items() if any(term in text for term in triggers)}
    if any(term in text for term in _FINANCIAL_TRIGGERS) and not (_STATEMENT_INTENTS & found):
        found |= _STATEMENT_INTENTS
    return found


def _heading_boost(text: str, intents: set[str], terms: Sequence[str]) -> float:
    lowered = re.sub(r"\s+", " ", text.lower())
    head = lowered[:240]
    value = 0.0
    for intent in intents:
        for heading in _INTENT_HEADINGS.get(intent, ()):
            if heading in lowered:
                strong = 22.0 if intent in _STATEMENT_INTENTS else 16.0
                value += strong if heading in head else strong * 0.55
    for phrase in (
        "item 3. legal proceedings",
        "legal proceedings",
        "geographic operations",
        "business environment",
        "results of operations",
    ):
        if phrase in head:
            value += 4.0
    if "customer" in intents:
        value += 8.0 + min(lowered.count("customer") + lowered.count("client"), 10) * 0.5
        value += min(
            lowered.count("airline")
            + lowered.count("government")
            + lowered.count("contract")
            + lowered.count("retailer")
            + lowered.count("distributor")
            + lowered.count("consumer")
            + lowered.count("defense"),
            10,
        ) * 3.0
        for phrase in ("u.s. government", "government contracts", "revenues from", "commercial airlines"):
            if phrase in lowered:
                value += 4.0
    if "business" in intents and "item 1. business" in head:
        value += 30.0
    if "legal" in intents:
        value += min(lowered.count("legal") + lowered.count("litigation") + lowered.count("proceeding"), 12) * 1.5
    if "geography" in intents:
        regions = (
            "africa",
            "asia",
            "europe",
            "latin america",
            "middle east",
            "north america",
            "amesa",
            "apac",
            "international",
        )
        for region in regions:
            if region in lowered:
                value += 3.0
    head_terms = set(_TOKEN.findall(head))
    for term in terms:
        for token in head_terms:
            if _similar(term, token):
                value += 1.5
                break
    return value


def _specifications(terms: Sequence[str]) -> dict[tuple[str, str], float]:
    specs: dict[tuple[str, str], float] = {}
    for term in terms:
        specs[("similar", term)] = 1.0
        for key, expansions in _SYNONYMS.items():
            if not term.startswith(key):
                continue
            for expansion in expansions:
                kind = "prefix" if " " not in expansion else "similar"
                specs[(kind, expansion)] = max(specs.get((kind, expansion), 0.0), 0.35)
    return specs


def _rank(
    corpus: Sequence[tuple[Any, str, str]],
    question: str,
    limit: int,
) -> list[tuple[Any, str]]:
    """Rank page entries by question intent, section headings and BM25 coverage."""

    terms = _content_terms(question)
    if not terms:
        selected: list[tuple[Any, str]] = []
        seen: set[str] = set()
        for record, _, key in corpus:
            if key in seen:
                continue
            seen.add(key)
            selected.append((record, key))
            if len(selected) >= limit:
                break
        return selected
    intents = _intents(question)
    counters = [Counter(_TOKEN.findall(text.lower())) for _, text, _ in corpus]
    lengths = [sum(counter.values()) for counter in counters]
    average = sum(lengths) / max(1, len(lengths))
    postings: dict[str, list[tuple[int, int]]] = {}
    for index, counter in enumerate(counters):
        for token, count in counter.items():
            postings.setdefault(token, []).append((index, count))
    specs = _specifications(terms)
    page_terms: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for spec in specs:
        kind, needle = spec
        matched: list[tuple[int, int]] = []
        for token, entries in postings.items():
            if (token.startswith(needle) if kind == "prefix" else _similar(token, needle)):
                matched.extend(entries)
        page_terms[spec] = matched
    total_pages = len(corpus)
    idf = {}
    for spec in specs:
        document_count = len({index for index, _ in page_terms[spec]})
        idf[spec] = math.log(1 + (total_pages - document_count + 0.5) / (document_count + 0.5))
    scores = [0.0] * total_pages
    for spec, weight in specs.items():
        aggregated: dict[int, int] = {}
        for index, count in page_terms[spec]:
            aggregated[index] = aggregated.get(index, 0) + count
        if not aggregated:
            continue
        for index, count in aggregated.items():
            length = lengths[index]
            scores[index] += (
                weight
                * idf[spec]
                * count
                * (1.2 + 1)
                / (count + 1.2 * (1 - 0.75 + 0.75 * length / average))
            )
    for index, (record, text, _) in enumerate(corpus):
        scores[index] += _heading_boost(text, intents, terms)
    order = sorted(range(total_pages), key=lambda index: (-scores[index], corpus[index][2]))
    selected: list[tuple[Any, str]] = []
    seen: set[str] = set()
    for index in order:
        record, _, key = corpus[index]
        if key in seen:
            continue
        seen.add(key)
        selected.append((record, key))
        if len(selected) >= limit:
            break
    return selected


def _page_corpus(entries: Sequence[Any]) -> list[tuple[Any, str, str]]:
    corpus: list[tuple[Any, str, str]] = []
    for record in entries:
        references = tuple(
            reference
            for reference in (record.entry.sources or ())
            if reference.source_type == PDF_PAGE_SOURCE_TYPE
        )
        if not references:
            continue
        corpus.append((record, record.entry.text, references[0].source_id))
    return corpus


async def search_pdf_pages(
    memory: Any,
    question: str,
    limit: int = 10,
) -> "tuple[MemoryCitation, ...]":
    """Search the scoped Memory for distinct physical evidence pages."""

    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")  # noqa: TRY003
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be non-empty")  # noqa: TRY003

    listing = await memory.list()
    corpus = _page_corpus(listing.entries)
    if not corpus:
        corpus = [(record, record.entry.text, record.entry.entry_version_id) for record in listing.entries]
    citations = _rank(corpus, question, limit)
    return tuple(record.citation for record, _ in citations)


__all__ = [
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "PDF_PAGE_SOURCE_DEFINITION",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]
