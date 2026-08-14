"""Qdrant vector store wrapper for fault report chunks."""

import os
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models

from config import COLLECTION_NAME, EMBEDDING_DIMENSION, QDRANT_PATH, VECTOR_DISTANCE


def get_client() -> QdrantClient:
    """Get or create a Qdrant local client."""
    os.makedirs(QDRANT_PATH, exist_ok=True)
    return QdrantClient(path=QDRANT_PATH)


def create_collection(client: QdrantClient | None = None, recreate: bool = False) -> None:
    """Create the fault_reports collection if it does not exist."""
    if client is None:
        client = get_client()

    exists = client.collection_exists(COLLECTION_NAME)
    if exists and recreate:
        client.delete_collection(COLLECTION_NAME)
        exists = False

    if not exists:
        distance = models.Distance.COSINE
        if VECTOR_DISTANCE.lower() == "euclid":
            distance = models.Distance.EUCLID
        elif VECTOR_DISTANCE.lower() == "dot":
            distance = models.Distance.DOT

        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=EMBEDDING_DIMENSION,
                distance=distance,
            ),
        )


def _infer_payload_schema(payload: dict[str, Any]) -> dict[str, Any]:
    """Infer Qdrant payload field schema from a sample payload.

    Returns a dict of field name to (type, values) for indexing.
    """
    return payload


import uuid


def _make_point_id(report_id: str, chunk_index: int, chunk_type: str) -> str:
    """Generate a deterministic UUID from report_id and chunk info."""
    base = f"{report_id}_{chunk_index}_{chunk_type}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, base))


def upsert_chunks(
    chunks: list[dict[str, Any]],
    embeddings: list[list[float]] | None = None,
    client: QdrantClient | None = None,
    batch_size: int = 64,
    start_index: int = 0,
) -> list[str]:
    """Upsert chunks with embeddings into Qdrant.

    Args:
        chunks: List of chunk dicts with 'text' and 'metadata'.
        embeddings: Optional pre-computed embeddings. If None, computed via API.
        client: Optional Qdrant client.
        batch_size: Number of points per upsert batch.
        start_index: Global starting index for point IDs.

    Returns:
        List of assigned point IDs.
    """
    from core.embedding import embed_texts

    if client is None:
        client = get_client()

    create_collection(client)

    if embeddings is None:
        texts = [chunk["text"] for chunk in chunks]
        embeddings = embed_texts(texts)

    point_ids = []
    for i in range(0, len(chunks), batch_size):
        batch_chunks = chunks[i : i + batch_size]
        batch_embeddings = embeddings[i : i + batch_size]
        points = []
        for idx, (chunk, embedding) in enumerate(zip(batch_chunks, batch_embeddings)):
            point_id = _make_point_id(
                chunk["metadata"]["report_id"],
                start_index + i + idx,
                chunk["metadata"]["chunk_type"],
            )
            point_ids.append(point_id)
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "text": chunk["text"],
                        **chunk["metadata"],
                    },
                )
            )
        client.upsert(collection_name=COLLECTION_NAME, points=points)

    return point_ids


def build_filter(
    years: list[int] | None = None,
    quarters: list[int] | None = None,
    months: list[int] | None = None,
    dates: list[str] | None = None,
    provinces: list[str] | None = None,
    voltages: list[str] | None = None,
    lines: list[str] | None = None,
    fault_types: list[str] | None = None,
) -> models.Filter | None:
    """Build a Qdrant must filter from query conditions."""
    must_conditions = []

    def add_match(field: str, values: list[Any] | None) -> None:
        if not values:
            return
        if len(values) == 1:
            must_conditions.append(models.FieldCondition(key=field, match=models.MatchValue(value=values[0])))
        else:
            must_conditions.append(models.FieldCondition(key=field, match=models.MatchAny(any=values)))

    add_match("year", years)
    add_match("quarter", quarters)
    add_match("month", months)
    add_match("date", dates)
    add_match("province", provinces)
    add_match("voltage", voltages)
    add_match("line", lines)
    add_match("fault_type", fault_types)

    if not must_conditions:
        return None
    return models.Filter(must=must_conditions)


def search(
    query_vector: list[float],
    filter_obj: models.Filter | None = None,
    top_k: int = 10,
    client: QdrantClient | None = None,
    with_payload: bool = True,
) -> list[dict[str, Any]]:
    """Search Qdrant with optional metadata filter."""
    if client is None:
        client = get_client()

    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=filter_obj,
        limit=top_k,
        with_payload=with_payload,
    ).points

    return [
        {
            "id": r.id,
            "score": r.score,
            "payload": r.payload,
        }
        for r in results
    ]


def fetch_by_filter(
    filter_obj: models.Filter | None = None,
    limit: int = 40,
    chunk_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch chunks matching a metadata filter without vector search.

    Used for all-years line queries where completeness matters more than
    semantic ranking. Results are ordered by fault date. Skips the embedding
    API call entirely (local payload scan only). chunk_types 可限定块类型
    （如只取 event/summary），控制上下文规模。
    """
    if chunk_types:
        type_cond = models.FieldCondition(
            key="chunk_type", match=models.MatchAny(any=chunk_types)
        )
        if filter_obj is None:
            filter_obj = models.Filter(must=[type_cond])
        else:
            filter_obj = models.Filter(must=[*(filter_obj.must or []), type_cond])

    client = get_client()
    results: list[dict[str, Any]] = []
    try:
        offset = None
        while len(results) < limit:
            points, offset = client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=filter_obj,
                limit=min(100, limit - len(results)),
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for p in points:
                results.append({"id": p.id, "score": None, "payload": p.payload})
            if offset is None:
                break
    finally:
        client.close()

    results.sort(key=lambda r: (r["payload"].get("date") or "", r["payload"].get("chunk_type") or ""))
    return results


def aggregate_summary_counts(
    filter_obj: models.Filter | None = None,
    field: str = "line",
) -> dict[str, int]:
    """Count summary chunks (event cards) per payload field matching filter.

    全量扫描、无条数上限，供程序化预聚合精确计数使用（区别于
    fetch_by_filter 的召回上限）。仅取分组字段，本地毫秒级。
    field 常用值：line（按线路）、month（按月份，单线"最频繁月份"场景）。
    """
    type_cond = models.FieldCondition(
        key="chunk_type", match=models.MatchValue(value="summary")
    )
    if filter_obj is None:
        filter_obj = models.Filter(must=[type_cond])
    else:
        filter_obj = models.Filter(must=[*(filter_obj.must or []), type_cond])

    client = get_client()
    counts: dict[str, int] = {}
    unknown = f"未知{field}"
    try:
        offset = None
        while True:
            points, offset = client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=filter_obj,
                limit=256,
                offset=offset,
                with_payload=[field],
                with_vectors=False,
            )
            for p in points:
                key = (p.payload or {}).get(field)
                if key is None:
                    key = unknown
                counts[key] = counts.get(key, 0) + 1
            if offset is None:
                break
    finally:
        client.close()
    return counts


_line_names_cache: set[str] | None = None


def distinct_line_names(refresh: bool = False) -> set[str]:
    """Return all distinct line names in the collection (cached).

    供查询侧线路家族扩展使用：本地 scroll 约 73ms，进程内缓存。
    重建/增量索引后调用 refresh=True 失效缓存。
    """
    global _line_names_cache
    if _line_names_cache is not None and not refresh:
        return _line_names_cache

    type_cond = models.FieldCondition(
        key="chunk_type", match=models.MatchValue(value="summary")
    )
    client = get_client()
    names: set[str] = set()
    try:
        offset = None
        while True:
            points, offset = client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=models.Filter(must=[type_cond]),
                limit=256,
                offset=offset,
                with_payload=["line"],
                with_vectors=False,
            )
            for p in points:
                line = (p.payload or {}).get("line")
                if line:
                    names.add(line)
            if offset is None:
                break
    finally:
        client.close()
    _line_names_cache = names
    return names


def count_records(client: QdrantClient | None = None) -> int:
    """Return total number of points in the collection."""
    if client is None:
        client = get_client()
    return client.count(collection_name=COLLECTION_NAME).count


def delete_collection(client: QdrantClient | None = None) -> None:
    """Delete the entire collection. Use with caution."""
    if client is None:
        client = get_client()
    if client.collection_exists(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)
