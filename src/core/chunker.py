"""Document chunking strategy for fault reports.

Each report corresponds to one fault event. We split the report into:
- summary: title + basic metadata + first paragraph
- event: main fault description paragraphs
- detail: remaining content split by max chunk size

Each chunk carries the full metadata extracted from the report.
"""

import os
from typing import Any

from config import CHUNK_MAX_CHARS, CHUNK_OVERLAP_CHARS, FILE_SERVER_URL
from core.metadata import compute_report_id, extract_metadata


def _split_text(text: str, max_chars: int, overlap: int) -> list[str]:
    """Split text into chunks of max_chars with overlap."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunk = text[start:end]
        # Try to break at newline
        if end < len(text):
            last_nl = chunk.rfind("\n")
            if last_nl > max_chars * 0.5:
                end = start + last_nl + 1
                chunk = text[start:end]
        chunks.append(chunk.strip())
        start = end - overlap
        if start >= len(text):
            break
    return chunks


def chunk_report(
    report_path: str,
    text: str,
    metadata: dict[str, Any] | None = None,
    summary_text_override: str | None = None,
) -> list[dict[str, Any]]:
    """Split a fault report into chunks.

    Args:
        report_path: Path to the report file.
        text: Extracted text content.
        metadata: Optional pre-computed metadata. If None, it is extracted.
        summary_text_override: Optional replacement for the summary chunk text
            (the event card). If None, falls back to the legacy positional
            truncation (first ~2000 chars).

    Returns:
        List of chunk dictionaries with text, metadata, and chunk_type.
    """
    if metadata is None:
        metadata = extract_metadata(report_path, text)

    report_id = metadata.get("report_id") or compute_report_id(report_path)
    file_server_url = f"{FILE_SERVER_URL}/reports/{report_id}"

    base_meta = {
        **metadata,
        "report_id": report_id,
        "file_server_url": file_server_url,
    }

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    paragraphs = []
    current = []
    for line in lines:
        if line:
            current.append(line)
        else:
            if current:
                paragraphs.append("\n".join(current))
                current = []
    if current:
        paragraphs.append("\n".join(current))

    # Summary chunk: event card when provided, otherwise legacy positional
    # truncation (first meaningful paragraphs up to ~2000 chars)
    if summary_text_override is not None:
        summary_text = summary_text_override
    else:
        summary_parts = []
        summary_len = 0
        for para in paragraphs:
            if summary_len + len(para) > 2000:
                break
            summary_parts.append(para)
            summary_len += len(para) + 1
        summary_text = "\n".join(summary_parts) if summary_parts else text[:2000]

    chunks = []
    chunks.append({
        "text": summary_text,
        "metadata": {**base_meta, "chunk_type": "summary"},
    })

    # Event chunk: main body paragraphs, skipping very short ones
    event_parts = []
    for para in paragraphs:
        if len(para) >= 20:
            event_parts.append(para)
    event_text = "\n\n".join(event_parts)

    if event_text and len(event_text) > len(summary_text):
        if len(event_text) <= CHUNK_MAX_CHARS:
            chunks.append({
                "text": event_text,
                "metadata": {**base_meta, "chunk_type": "event"},
            })
        else:
            # Split event body into detail chunks
            for idx, chunk_text in enumerate(_split_text(event_text, CHUNK_MAX_CHARS, CHUNK_OVERLAP_CHARS)):
                chunks.append({
                    "text": chunk_text,
                    "metadata": {**base_meta, "chunk_type": f"detail_{idx}"},
                })

    return chunks


def chunk_all_reports(report_dir: str, reports: list[tuple[str, str]] | None = None) -> list[dict[str, Any]]:
    """Chunk all reports in a directory or from a provided list.

    Args:
        report_dir: Base directory for reports (used for metadata only if reports is None).
        reports: Optional list of (file_path, text) tuples.

    Returns:
        Flat list of all chunks.
    """
    from core.parser import get_report_files, parse_report

    all_chunks = []
    if reports is None:
        reports = [(fp, parse_report(fp)) for fp in get_report_files(report_dir)]

    for file_path, text in reports:
        meta = extract_metadata(file_path, text)
        chunks = chunk_report(file_path, text, meta)
        all_chunks.extend(chunks)

    return all_chunks
