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

"""Row-level CSV Sources with stable identity and the standard text projection."""

from __future__ import annotations

import csv
import io
import json
from urllib.parse import quote

from pydantic import BaseModel

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

CSV_ROW_SOURCE_TYPE = "csv-row"
_SOURCE_ID_PREFIX = "csv"


class CSVDocumentInput(BaseModel):
    """Complete offline CSV document bytes plus the caller-selected primary key."""

    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    """One parsed CSV data record in original header order."""

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


class CSVRowSource(Source):
    """Captured row-level Source retaining the original columns and values."""

    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Build the stable, delimiter-safe identity for one CSV row."""

    if not isinstance(document_id, str) or not document_id or document_id != document_id.strip():
        raise ValueError("document_id must be a non-empty string without surrounding whitespace")
    if not isinstance(primary_key_value, str):
        raise ValueError("primary_key_value must be a string")
    source_id = (
        f"{_SOURCE_ID_PREFIX}:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    )
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(
            f"row identity must not exceed {MAX_SOURCE_ID_LENGTH} characters"
        )
    return source_id


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Parse and validate a complete CSV document atomically."""

    if not isinstance(value, CSVDocumentInput):
        raise ValueError("value must be a CSVDocumentInput")
    if not value.document_id or value.document_id != value.document_id.strip():
        raise ValueError("document_id must be a non-empty string without surrounding whitespace")
    if not value.primary_key or not value.primary_key.strip():
        raise ValueError("primary_key must be a non-empty string")

    try:
        text = value.content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CSV content must be valid UTF-8") from error

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        records = list(reader)
    except csv.Error as error:
        raise ValueError("malformed CSV content") from error

    if not records:
        raise ValueError("CSV document must contain a header record")
    header = records[0]
    if not header:
        raise ValueError("CSV header must not be empty")
    seen_columns: set[str] = set()
    for column in header:
        if not column or not column.strip():
            raise ValueError("CSV header fields must be non-empty and not blank")
        if column in seen_columns:
            raise ValueError(f"duplicate CSV header field: {column!r}")
        seen_columns.add(column)
    if value.primary_key not in seen_columns:
        raise ValueError(f"primary key {value.primary_key!r} is not a CSV header field")
    primary_key_index = header.index(value.primary_key)

    rows: list[CSVRowInput] = []
    seen_keys: set[str] = set()
    for record in records[1:]:
        if not record:
            # Completely empty physical records are ignored.
            continue
        if len(record) != len(header):
            raise ValueError("CSV record width must match the header width")
        primary_key_value = record[primary_key_index]
        if not primary_key_value.strip():
            raise ValueError("CSV primary key values must be non-empty and not blank")
        if primary_key_value in seen_keys:
            raise ValueError(f"duplicate CSV primary key value: {primary_key_value!r}")
        seen_keys.add(primary_key_value)
        rows.append(
            CSVRowInput(
                document_id=value.document_id,
                primary_key=value.primary_key,
                primary_key_value=primary_key_value,
                columns=tuple(header),
                values=tuple(record),
            )
        )
    return tuple(rows)


def _row_mapping(source: CSVRowSource) -> dict[str, str]:
    return dict(zip(source.columns, source.values, strict=True))


class _CSVRowTextEvidenceProjection:
    """Standard powercontext.text-evidence projection for one CSV row."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = CSVRowSource
    output_class = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row = _row_mapping(source)
        content = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        return TextEvidence(
            source_type=CSV_ROW_SOURCE_TYPE,
            source_id=source.name,
            content=content,
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


class _CSVRowAdapter:
    """Resolve CSVRowInput values into captured CSVRowSource records."""

    name = CSV_ROW_SOURCE_TYPE
    input_class = CSVRowInput
    source_class = CSVRowSource

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        source_id = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=value.primary_key_value,
            columns=value.columns,
            values=value.values,
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


CSV_ROW_SOURCE_DEFINITION = AdapterSourceDefinition(
    adapter=_CSVRowAdapter(),
    version="1",
    projections=(_CSVRowTextEvidenceProjection(),),
)


__all__ = [
    "CSV_ROW_SOURCE_DEFINITION",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "csv_row_source_id",
    "parse_csv_document",
]
