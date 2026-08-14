"""End-to-end indexing and query orchestration for fault knowledge base."""

import os
import time
from typing import Any

from config import COLLECTION_NAME, REPORT_DIR
from core.chunker import chunk_report
from core.embedding import embed_texts
from core.event_card import apply_card_datetime, build_card_text, extract_event_card_fields
from core.generator import generate, generate_stream
from core.metadata import compute_report_id, extract_metadata
from core.parser import clean_text, get_report_files, parse_report
from core.qa_logger import log_qa, new_request_id
from core.query_parser import find_bare_voltage_number, parse_query
from core.retriever import (
    retrieve,
    retrieve_for_compare_with_stats,
    retrieve_for_single_tower,
    retrieve_with_stats,
)
from core.router_adapter import route_query
from core.vector_store import (
    create_collection,
    delete_collection,
    get_client,
    upsert_chunks,
)


def _elapsed_ms(start: float) -> int:
    """Milliseconds elapsed since a perf_counter timestamp."""
    return int((time.perf_counter() - start) * 1000)


def _context_chars(chunks: list[dict[str, Any]]) -> int:
    """Total payload text size sent to the LLM (timeout risk indicator)."""
    return sum(len(c.get("payload", {}).get("text", "")) for c in chunks)


def _check_tower_without_line(question: str, query) -> str | None:
    """Return warning message if tower number is present but line name is not."""
    if query.tower and not query.line:
        return (
            "查询杆塔号时必须同时指定所属线路名称，否则无法定位具体设备。"
            f"您的问题中包含杆塔号“{query.tower}”，但未说明是哪条线路的杆塔。"
            "请补充线路名称后重新提问，例如：泰吴线{query.tower}2026年故障。"
        )
    return None


def _ensure_top_n(query) -> None:
    """Default top_n to 3 for ranking_stats if not specified."""
    if query.top_n is None:
        query.top_n = 3


CLARIFY_PREFIX = "您想查询"


def _check_voltage_ambiguity(question: str, query) -> str | None:
    """问题中含"裸"电压等级数字（如"800"未带单位）且未按杆塔解析时，返回反问消歧。"""
    if query.tower:
        return None
    num = find_bare_voltage_number(question)
    if not num:
        return None
    return (
        f"{CLARIFY_PREFIX}的“{num}”未带单位，请问是指：\n"
        f"1. 电压等级{num}kV，例如“2026年{num}kV线路情况”；\n"
        f"2. 杆塔号{num}号，例如“泰吴线{num}号塔2026年故障情况”。"
    )


def _check_missing_time(query) -> str | None:
    """未携带任何时间信息且未声明"历年"时，返回反问提示。

    覆盖两类：
    - 线路/杆塔级：指定了线路名但无时间；
    - 多设备级：未指定线路但有省份/电压过滤条件但无时间
      （仅故障类型的归纳类查询除外，由 fault_type_stats 处理）。
    """
    if query.all_years or query.years or query.quarters or query.months or query.dates:
        return None
    if query.line:
        target = f"{query.line}{query.tower}杆塔" if query.tower else query.line
        return (
            f"{CLARIFY_PREFIX}{target}哪个时间段的故障情况？请补充说明：\n"
            f"1. 具体某一年，例如“{query.line}2024年故障情况”；\n"
            f"2. 历年全部情况，例如“{query.line}历年故障情况”。"
        )
    if query.province or query.voltage:
        desc = f"{query.province or ''}{query.voltage or ''}"
        if query.voltage:
            desc += "线路"
        return (
            f"{CLARIFY_PREFIX}{desc}哪个时间段的故障情况？请补充说明：\n"
            f"1. 具体某一年，例如“2026年{desc}情况”；\n"
            f"2. 历年全部情况，例如“{desc}历年情况”。"
        )
    return None


def query(question: str, raw_question: str | None = None) -> str:
    """End-to-end query: route, parse, retrieve, generate.

    Args:
        question: User question in Chinese (after clarify-merge if any).
        raw_question: Original user input before clarify-merge, for logging.

    Returns:
        Generated answer string.
    """
    t0 = time.perf_counter()
    stages: dict[str, int] = {}
    record: dict[str, Any] = {
        "request_id": new_request_id(),
        "question": question,
        "stages": stages,
    }
    if raw_question and raw_question != question:
        record["raw_question"] = raw_question
    answer = ""
    try:
        t = time.perf_counter()
        route_result = route_query(question)
        stages["route_ms"] = _elapsed_ms(t)
        skill = route_result.skill
        record["skill"] = skill or "default"
        record["route_similarity"] = round(route_result.similarity, 4)

        t = time.perf_counter()
        parsed = parse_query(question)
        stages["parse_ms"] = _elapsed_ms(t)
        record["all_years"] = parsed.all_years

        warning = _check_tower_without_line(question, parsed)
        if warning:
            answer = warning
            return answer

        ambiguity = _check_voltage_ambiguity(question, parsed)
        if ambiguity:
            answer = ambiguity
            return answer

        clarify = _check_missing_time(parsed)
        if clarify:
            answer = clarify
            return answer

        t = time.perf_counter()
        stats_text = ""
        if skill == "ranking_stats":
            _ensure_top_n(parsed)
            chunks, stats_text = retrieve_with_stats(parsed, skill=skill, top_k=10, top_n=parsed.top_n)

        elif skill == "compare_stats":
            from core.query_parser import _build_compare_queries
            side_queries = _build_compare_queries(parsed)
            chunks, stats_text = retrieve_for_compare_with_stats(side_queries, skill=skill, top_k=10)

        elif skill == "multi_line_stats":
            chunks, stats_text = retrieve_with_stats(parsed, skill=skill, top_k=10)

        elif skill == "fault_type_stats":
            if not parsed.fault_type:
                answer = "请指定具体的故障类型，例如：雷击、风偏、山火、异物短路等。"
                return answer
            chunks = retrieve(parsed, skill=skill, top_k=20)

        elif skill == "single_tower_stats" and parsed.tower:
            chunks, stats_text = retrieve_for_single_tower(parsed, top_k=10)

        else:
            chunks = retrieve(parsed, skill=skill, top_k=10)
        stages["retrieve_ms"] = _elapsed_ms(t)
        record["num_chunks"] = len(chunks)
        record["context_chars"] = _context_chars(chunks)

        if not chunks:
            answer = "未检索到相关故障报告，请检查查询条件或补充更多信息。"
            return answer

        t = time.perf_counter()
        answer = generate(question, skill, chunks, tower=parsed.tower, stats_text=stats_text)
        stages["gen_total_ms"] = _elapsed_ms(t)
        return answer
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        stages["total_ms"] = _elapsed_ms(t0)
        record["answer"] = answer
        log_qa(record)


def query_stream(question: str, raw_question: str | None = None):
    """Stream version of query. Logs the same record as query() on completion."""
    t0 = time.perf_counter()
    stages: dict[str, int] = {}
    record: dict[str, Any] = {
        "request_id": new_request_id(),
        "question": question,
        "stages": stages,
    }
    if raw_question and raw_question != question:
        record["raw_question"] = raw_question
    parts: list[str] = []
    try:
        t = time.perf_counter()
        route_result = route_query(question)
        stages["route_ms"] = _elapsed_ms(t)
        skill = route_result.skill
        record["skill"] = skill or "default"
        record["route_similarity"] = round(route_result.similarity, 4)

        t = time.perf_counter()
        parsed = parse_query(question)
        stages["parse_ms"] = _elapsed_ms(t)
        record["all_years"] = parsed.all_years

        warning = _check_tower_without_line(question, parsed)
        if warning:
            parts.append(warning)
            yield warning
            return

        ambiguity = _check_voltage_ambiguity(question, parsed)
        if ambiguity:
            parts.append(ambiguity)
            yield ambiguity
            return

        clarify = _check_missing_time(parsed)
        if clarify:
            parts.append(clarify)
            yield clarify
            return

        t = time.perf_counter()
        stats_text = ""
        if skill == "ranking_stats":
            _ensure_top_n(parsed)
            chunks, stats_text = retrieve_with_stats(parsed, skill=skill, top_k=10, top_n=parsed.top_n)

        elif skill == "compare_stats":
            from core.query_parser import _build_compare_queries
            side_queries = _build_compare_queries(parsed)
            chunks, stats_text = retrieve_for_compare_with_stats(side_queries, skill=skill, top_k=10)

        elif skill == "multi_line_stats":
            chunks, stats_text = retrieve_with_stats(parsed, skill=skill, top_k=10)

        elif skill == "fault_type_stats":
            if not parsed.fault_type:
                msg = "请指定具体的故障类型，例如：雷击、风偏、山火、异物短路等。"
                parts.append(msg)
                yield msg
                return
            chunks = retrieve(parsed, skill=skill, top_k=20)

        elif skill == "single_tower_stats" and parsed.tower:
            chunks, stats_text = retrieve_for_single_tower(parsed, top_k=10)

        else:
            chunks = retrieve(parsed, skill=skill, top_k=10)
        stages["retrieve_ms"] = _elapsed_ms(t)
        record["num_chunks"] = len(chunks)
        record["context_chars"] = _context_chars(chunks)

        if not chunks:
            msg = "未检索到相关故障报告，请检查查询条件或补充更多信息。"
            parts.append(msg)
            yield msg
            return

        t = time.perf_counter()
        first_token = True
        for token in generate_stream(question, skill, chunks, stats_text=stats_text):
            if first_token:
                stages["gen_first_token_ms"] = _elapsed_ms(t)
                first_token = False
            parts.append(token)
            yield token
        stages["gen_total_ms"] = _elapsed_ms(t)
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        stages["total_ms"] = _elapsed_ms(t0)
        record["answer"] = "".join(parts)
        log_qa(record)


def get_existing_report_ids(client: Any | None = None) -> set[str]:
    """Return set of report_ids already indexed in Qdrant.

    Uses payload field 'report_id' via scroll API.
    """
    close_client = False
    if client is None:
        client = get_client()
        close_client = True

    try:
        if not client.collection_exists(COLLECTION_NAME):
            return set()

        existing = set()
        offset = None
        while True:
            result = client.scroll(
                collection_name=COLLECTION_NAME,
                offset=offset,
                limit=1000,
                with_payload=["report_id"],
                with_vectors=False,
            )
            records, next_offset = result
            for record in records:
                report_id = record.payload.get("report_id") if record.payload else None
                if report_id:
                    existing.add(report_id)
            if next_offset is None:
                break
            offset = next_offset

        return existing
    finally:
        if close_client:
            client.close()


def _index_report_with_client(
    file_path: str,
    client: Any,
    existing_ids: set[str],
) -> int:
    """Internal helper to index a report using an already-open client."""
    report_id = compute_report_id(file_path)
    if report_id in existing_ids:
        return 0

    text = clean_text(parse_report(file_path))
    if not text:
        return 0

    metadata = extract_metadata(file_path, text)

    # 事件卡：LLM 提取结构化字段替代旧的位置截断 summary；
    # 正文故障时间覆盖元数据 date（正文优先）；提取失败降级为旧 summary 保证入库不中断
    card_text = None
    try:
        card_fields = extract_event_card_fields(text)
        apply_card_datetime(metadata, card_fields["故障时间"])
        card_text = build_card_text(metadata, card_fields)
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] 事件卡提取失败，降级为旧 summary: {os.path.basename(file_path)}: {exc}")

    chunks = chunk_report(file_path, text, metadata, summary_text_override=card_text)
    if not chunks:
        return 0

    embeddings = embed_texts([c["text"] for c in chunks])
    upsert_chunks(chunks, embeddings, client)

    existing_ids.add(report_id)
    return len(chunks)


def index_report(file_path: str, client: Any | None = None, existing_ids: set[str] | None = None) -> int:
    """Index a single report file.

    Args:
        file_path: Path to report file.
        client: Optional Qdrant client.
        existing_ids: Optional set of already-indexed report_ids.

    Returns:
        Number of chunks indexed (0 if already exists).
    """
    close_client = False
    if client is None:
        client = get_client()
        close_client = True

    try:
        create_collection(client)
        if existing_ids is None:
            existing_ids = get_existing_report_ids(client)
        return _index_report_with_client(file_path, client, existing_ids)
    finally:
        if close_client:
            client.close()


def index_all_reports(
    report_dir: str | None = None,
    recreate: bool = False,
    max_reports: int | None = None,
) -> dict[str, Any]:
    """Index all reports under report_dir.

    Args:
        report_dir: Directory containing reports. Defaults to REPORT_DIR.
        recreate: If True, delete and recreate the collection.
        max_reports: Optional limit for testing.

    Returns:
        Dict with total_files, indexed_files, skipped_files, total_chunks.
    """
    if report_dir is None:
        report_dir = REPORT_DIR

    client = get_client()
    try:
        if recreate:
            delete_collection(client)
        create_collection(client)

        existing_ids = get_existing_report_ids(client)
        files = get_report_files(report_dir)
        if max_reports is not None:
            files = files[:max_reports]

        total_chunks = 0
        indexed = 0
        skipped = 0
        failed = 0

        for file_path in files:
            try:
                chunks_count = _index_report_with_client(file_path, client, existing_ids)
                if chunks_count > 0:
                    total_chunks += chunks_count
                    indexed += 1
                else:
                    skipped += 1
            except Exception as exc:
                failed += 1
                print(f"[FAIL] {os.path.basename(file_path)}: {exc}")

        return {
            "total_files": len(files),
            "indexed_files": indexed,
            "skipped_files": skipped,
            "failed_files": failed,
            "total_chunks": total_chunks,
        }
    finally:
        client.close()


