"""Retriever orchestration: build filters and recall relevant chunks."""

import re
from typing import Any

from qdrant_client.http import models

from config import RETRIEVAL_TOP_K
from core.embedding import embed_text
from core.metadata import canon_line_key, line_stem
from core.query_parser import Query
from core.vector_store import (
    aggregate_summary_counts,
    build_filter,
    distinct_line_names,
    fetch_by_filter,
    search,
)

# 历年查询全量拉取上限（块数），防止 LLM 上下文过大
ALL_YEARS_MAX_CHUNKS = 40

# 列举类技能：目标是事件清单完整性，以事件卡（summary 块）为准
ENUMERATION_SKILLS = {"multi_line_stats", "ranking_stats", "compare_stats"}


def expand_line_variants(line: str) -> list[str]:
    """Expand a queried line name to all indexed variants of its family.

    - 精确存在于索引 → 按规范等价键扩展同线异名（查"鹰抚Ⅰ线"回
      [鹰抚I回线, 鹰抚Ⅰ线]；查"胜家Ⅰ线"仍只回胜家Ⅰ线——Ⅱ线编号不同键）
    - 不存在 → 按词干匹配同族全部变体（查"荆潇线"→[荆潇II线]，
      查"渔兴线"→[渔兴一线, 渔兴一二线, 渔兴三回线]）
    - 同族也没有 → 原样（正常走"未查到"流程）
    """
    names = distinct_line_names()
    if line in names:
        key = canon_line_key(line)
        group = sorted(n for n in names if canon_line_key(n) == key)
        return group or [line]
    stem = line_stem(line)
    family = sorted(n for n in names if line_stem(n) == stem)
    return family or [line]


def build_query_filter(query: Query, skill: str | None = None) -> Any:
    """Build Qdrant filter from parsed Query based on Skill intent.

    Rules:
    - Tower number is never a must filter (highlighted in post-processing).
    - single_line_stats: must line + year(s)
    - single_tower_stats: must line + year(s)
    - multi_line_stats/ranking/compare/fault_type: must year + province + voltage + fault_type
    - default: use whatever fields are present
    """
    years = query.year_filter()
    filter_kwargs = {"years": years}
    # 绕击/反击已统一归并为雷击（metadata/query_parser 双侧同义词规则），
    # fault_type 单值过滤即可，不再需要子类归并
    # 覆冰例外（用户 2026-08-06 定调）：用户对冰类故障的统称，库内保留
    # 冰害/冰闪/脱冰跳跃/雪闪四个标签，查询"覆冰"时展开为四标签多值过滤
    ICE_TYPES = ["冰害", "冰闪", "脱冰跳跃", "雪闪"]
    if query.fault_type == "覆冰":
        fault_types = ICE_TYPES
    else:
        fault_types = [query.fault_type] if query.fault_type else None

    if skill in {"single_line_stats", "single_tower_stats"}:
        if query.line:
            filter_kwargs["lines"] = expand_line_variants(query.line)
        if query.province:
            filter_kwargs["provinces"] = [query.province]
        if query.voltage:
            filter_kwargs["voltages"] = [query.voltage]
        if fault_types:
            filter_kwargs["fault_types"] = fault_types
        if query.quarters:
            filter_kwargs["quarters"] = query.quarters
        if query.months:
            filter_kwargs["months"] = query.months
        if query.dates:
            filter_kwargs["dates"] = query.dates

    elif skill in {"multi_line_stats", "ranking_stats", "compare_stats", "fault_type_stats"}:
        if query.line:
            # 单线锁定场景（"XX线山火最频繁月份"/同线对比）也需线路过滤
            filter_kwargs["lines"] = expand_line_variants(query.line)
        if query.province:
            filter_kwargs["provinces"] = [query.province]
        if query.voltage:
            filter_kwargs["voltages"] = [query.voltage]
        if fault_types:
            filter_kwargs["fault_types"] = fault_types
        if query.quarters:
            filter_kwargs["quarters"] = query.quarters
        if query.months:
            filter_kwargs["months"] = query.months
        if query.dates:
            filter_kwargs["dates"] = query.dates

    else:
        # default / generic
        if query.province:
            filter_kwargs["provinces"] = [query.province]
        if query.voltage:
            filter_kwargs["voltages"] = [query.voltage]
        if fault_types:
            filter_kwargs["fault_types"] = fault_types
        if query.line:
            filter_kwargs["lines"] = expand_line_variants(query.line)
        if query.quarters:
            filter_kwargs["quarters"] = query.quarters
        if query.months:
            filter_kwargs["months"] = query.months
        if query.dates:
            filter_kwargs["dates"] = query.dates

    return build_filter(**filter_kwargs)


def retrieve(
    query: Query,
    skill: str | None = None,
    top_k: int = RETRIEVAL_TOP_K,
    query_text: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve relevant chunks for a parsed query.

    Args:
        query: Parsed Query object.
        skill: Detected skill name.
        top_k: Number of results to return.
        query_text: Optional override query text for embedding.

    Returns:
        List of search results with score and payload.
    """
    filter_obj = build_query_filter(query, skill)
    # 列举类查询（历年/多年范围的单线单塔、多设备、排序、对比）：元数据过滤全量拉取
    # 事件卡（summary 块）。事件卡已含结构化字段，清单完整性优先于单事件
    # 深度；卡体量小（约 400 字符/张），40 张上下文仅 ~16k 字符，同时省掉
    # Embedding API 调用。单年聚焦类查询维持向量检索，卡与 detail 块混合召回，
    # 保证单个事件的细节深度。
    if (
        (query.all_years or len(query.year_filter()) > 1)
        and skill in {"single_line_stats", "single_tower_stats"}
    ) or (skill in ENUMERATION_SKILLS):
        return fetch_by_filter(
            filter_obj,
            limit=ALL_YEARS_MAX_CHUNKS,
            chunk_types=["summary"],
        )

    text = query_text or query.raw
    query_vector = embed_text(text)
    return search(query_vector, filter_obj=filter_obj, top_k=top_k)


_TOWER_FIELD_RE = re.compile(r"故障杆塔[：:]\s*([^\n，。；]{1,40})")
_TOWER_RANGE_RE = re.compile(r"(\d{1,4})\s*[#号]?\s*[-～]\s*#?\s*(\d{1,4})")
_TOWER_NUM_RE = re.compile(r"\d{1,4}")


def _parse_tower_numbers(text: str) -> set[int]:
    """从杆塔写法中提取杆塔号数值集合（含区间展开、前导零归一）。

    兼容真实事件卡写法：#2911 / 0591# / 87# / 350号塔 / 3403 /
    #2910-#2911 / 533#-534# / 71#-72# 及查询侧归一形式 2911号 / 2910-2911号。
    """
    nums: set[int] = set()
    for a, b in _TOWER_RANGE_RE.findall(text):
        lo, hi = int(a), int(b)
        if hi > lo and hi - lo <= 50:
            nums.update(range(lo, hi + 1))
    for n in _TOWER_NUM_RE.findall(text):
        nums.add(int(n))
    return nums


def _card_tower_numbers(card_text: str) -> set[int]:
    """提取事件卡"故障杆塔"字段的杆塔号集合；未提及返回空集。"""
    m = _TOWER_FIELD_RE.search(card_text)
    if not m or "未提及" in m.group(1):
        return set()
    return _parse_tower_numbers(m.group(1))


def retrieve_for_single_tower(
    query: Query, top_k: int = RETRIEVAL_TOP_K
) -> tuple[list[dict[str, Any]], str]:
    """杆塔级单设备检索：确定性杆塔匹配 + 匹配结论声明注入。

    杆塔号不是元数据、无法进入 Qdrant 过滤（build_query_filter 设计注释），
    匹配判断若下放给 LLM 会产生"无匹配却强行输出其他杆塔事件"的幻觉
    （实测：查询杆塔无事件且上下文有同线路同时段其他杆塔事件时必现）。
    此处将判断收回代码层：全量拉取过滤范围内的事件卡（本地 scroll，
    无 Embedding 调用），按事件卡"故障杆塔"字段与查询杆塔做数值匹配
    （支持区间包含与前导零），结论以【杆塔匹配核对】声明经 stats_text
    通道注入上下文前部，LLM 只需照实转述。

    Returns:
        (chunks, stats_text): 匹配卡在前、其余卡居中、detail 块在后；
        stats_text 为匹配核对声明。
    """
    filter_obj = build_query_filter(query, "single_tower_stats")
    cards = fetch_by_filter(
        filter_obj, limit=ALL_YEARS_MAX_CHUNKS, chunk_types=["summary"]
    )

    query_nums = _parse_tower_numbers(query.tower or "")
    matched, others = [], []
    for c in cards:
        payload = c.get("payload", c)
        card_nums = _card_tower_numbers(payload.get("text", ""))
        (matched if card_nums & query_nums else others).append(c)

    # 同一事件存在重复报告（同日期同类型同线路）时只保留首张卡，
    # 避免声明与上下文把同一事件列为多起（task #38 数据层问题，此处兜底）
    seen_events = set()
    deduped = []
    for c in matched:
        payload = c.get("payload", c)
        key = (payload.get("date"), payload.get("line"), payload.get("fault_type"))
        if key not in seen_events:
            seen_events.add(key)
            deduped.append(c)
    matched = deduped

    # detail 块补充单事件细节深度；历年查询沿用纯卡上下文（retrieve() 先例）
    details: list[dict[str, Any]] = []
    if not query.all_years:
        query_vector = embed_text(query.raw)
        for c in search(query_vector, filter_obj=filter_obj, top_k=top_k):
            payload = c.get("payload", c)
            if payload.get("chunk_type") != "summary":
                details.append(c)

    if matched:
        items = "、".join(
            f"{(c.get('payload', c)).get('date')}"
            f"{(c.get('payload', c)).get('fault_type')}"
            f"（实际杆塔{_TOWER_FIELD_RE.search((c.get('payload', c)).get('text', '')).group(1).strip() if _TOWER_FIELD_RE.search((c.get('payload', c)).get('text', '')) else '未提及'}）"
            for c in matched
        )
        declaration = (
            f"【杆塔匹配核对】经系统确定性核对，查询杆塔{query.tower}在检索范围内"
            f"匹配 {len(matched)} 张事件卡：{items}。仅这些事件可作为正式答案；"
            f"其余事件卡均非查询杆塔，如需可作为参考信息列出（注明实际杆塔号），"
            f"但禁止当作查询杆塔的事件回答。"
        )
    else:
        declaration = (
            f"【杆塔匹配核对】经系统确定性核对，检索范围内没有查询杆塔"
            f"{query.tower}的故障事件。请明确回答“{query.tower}杆塔在该时间段"
            f"无故障记录”，随后可将下列其他杆塔的事件作为参考信息简要列出"
            f"（注明各自的实际杆塔号）；禁止把任何事件标注为{query.tower}。"
        )

    return matched + others + details, declaration


def retrieve_for_compare(
    queries: list[Query],
    skill: str = "compare_stats",
    top_k: int = RETRIEVAL_TOP_K,
) -> list[dict[str, Any]]:
    """Retrieve chunks for both sides of a comparison query and merge.

    Deduplicates by report_id and preserves order from each side.
    """
    seen = set()
    merged = []
    for side_query in queries:
        side_results = retrieve(side_query, skill=skill, top_k=top_k)
        for result in side_results:
            payload = result.get("payload", result)
            report_id = payload.get("report_id")
            key = report_id if report_id else id(result)
            if key not in seen:
                seen.add(key)
                merged.append(result)
    return merged


def retrieve_by_text(
    text: str,
    filter_obj: Any | None = None,
    top_k: int = RETRIEVAL_TOP_K,
) -> list[dict[str, Any]]:
    """Simple text-based retrieval without structured query."""
    query_vector = embed_text(text)
    return search(query_vector, filter_obj=filter_obj, top_k=top_k)


def _merge_line_counts(counts: dict[str, int]) -> tuple[dict[str, int], dict[str, list[str]]]:
    """按规范等价键合并同线异名的计数（如 鹰抚I回线+鹰抚Ⅰ线 → 鹰抚线 2次）。

    返回 (合并后计数, 显示名→原始名列表)。显示名规则：组内仅 1 个原始名
    用原名；多个原始名用词干+"线"。原始名映射供 ranking 按真实线路名补拉卡片。
    """
    groups: dict[tuple, list[tuple[str, int]]] = {}
    for raw, n in counts.items():
        groups.setdefault(canon_line_key(raw), []).append((raw, n))
    merged: dict[str, int] = {}
    raw_map: dict[str, list[str]] = {}
    for key, members in groups.items():
        if len(members) == 1:
            disp = members[0][0]
        else:
            disp = f"{key[0]}线"
        merged[disp] = sum(n for _, n in members)
        raw_map[disp] = sorted(raw for raw, _ in members)
    return merged, raw_map


def _format_stats_text(
    counts: dict[str, int], label: str | None = None, field: str = "line"
) -> str:
    """Format group counts into a deterministic stats text.

    field="line"：按次数降序（排名场景）；field="month"：按月份升序
    （单线"最频繁月份"场景）。
    """
    total = sum(counts.values())
    if total == 0:
        return ""
    if field == "month":
        ranked = sorted(counts.items(), key=lambda kv: (not isinstance(kv[0], int), kv[0] if isinstance(kv[0], int) else 0))
        dist = "；".join(f"{m}月 {n} 次" if isinstance(m, int) else f"{m} {n} 次" for m, n in ranked)
        dim = "按月份分布"
    else:
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        dist = "；".join(f"{line} {n} 次" for line, n in ranked)
        dim = "按线路分布"
    title = f"【精确统计·{label}】" if label else "【精确统计】"
    return (
        f"{title}命中故障事件共 {total} 次"
        "（本表覆盖全部命中报告的元数据，不受召回条数限制）：\n"
        f"{dim}：{dist}"
    )


def build_stats_text(filter_obj: Any, label: str | None = None) -> str:
    """Aggregate event cards matching filter into a deterministic stats text.

    覆盖全部命中报告（无召回条数上限），供列举类技能把"次数/排名"
    从 LLM 数卡片改为确定性数据。无命中时返回空串。
    按线路分组时同线异名按规范等价键合并（与 retrieve_with_stats 一致）。
    """
    counts = aggregate_summary_counts(filter_obj)
    merged, _ = _merge_line_counts(counts)
    return _format_stats_text(merged, label)


def _fetch_cards_for_lines(filter_obj: Any, lines: list[str]) -> list[dict[str, Any]]:
    """Fetch summary cards for specific lines under the same query filter."""
    line_cond = models.FieldCondition(key="line", match=models.MatchAny(any=lines))
    if filter_obj is None:
        extended = models.Filter(must=[line_cond])
    else:
        extended = models.Filter(must=[*(filter_obj.must or []), line_cond])
    return fetch_by_filter(extended, limit=ALL_YEARS_MAX_CHUNKS, chunk_types=["summary"])


def retrieve_with_stats(
    query: Query,
    skill: str | None = None,
    top_k: int = RETRIEVAL_TOP_K,
    top_n: int | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """列举类查询：返回 (chunks, stats_text)，chunks 仍受召回上限约束。

    ranking_stats：排名依据为全量统计表，需保证榜单线路（含并列）的
    事件卡一定在上下文中——否则 LLM 有排名却没有细节和来源。对缺失的
    榜单线路按线路过滤补拉事件卡并入（按 report_id 去重）。

    统计维度：查询已锁定单线路时按月份分组（"XX线山火最频繁月份"），
    否则按线路分组（多线路排名/占比）。按线路分组时同线异名按规范等价键
    合并计数（鹰抚I回线+鹰抚Ⅰ线 → 鹰抚线 2次）。
    """
    filter_obj = build_query_filter(query, skill)
    chunks = retrieve(query, skill=skill, top_k=top_k)
    field = "month" if query.line else "line"
    counts = aggregate_summary_counts(filter_obj, field=field)
    raw_map: dict[str, list[str]] = {}
    if field == "line":
        counts, raw_map = _merge_line_counts(counts)
    stats_text = _format_stats_text(counts, field=field)

    if skill == "ranking_stats" and field == "line" and counts:
        n = top_n or query.top_n or 3
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        threshold = ranked[min(n, len(ranked)) - 1][1]
        top_lines = [line for line, c in ranked if c >= threshold]
        present = {c.get("payload", {}).get("line") for c in chunks}
        missing = [line for line in top_lines
                   if not any(raw in present for raw in raw_map.get(line, [line]))]
        if missing:
            raw_names = [raw for line in missing for raw in raw_map.get(line, [line])]
            extra = _fetch_cards_for_lines(filter_obj, raw_names)
            seen = {c.get("payload", {}).get("report_id") for c in chunks}
            for card in extra:
                rid = card.get("payload", {}).get("report_id")
                if rid not in seen:
                    seen.add(rid)
                    chunks.append(card)
            chunks.sort(key=lambda r: (r["payload"].get("date") or "", r["payload"].get("chunk_type") or ""))
    return chunks, stats_text


def _side_label(query: Query) -> str:
    """Label a compare side query by its distinguishing fields."""
    parts = []
    if query.years:
        parts.append("、".join(f"{y}年" for y in query.years))
    if query.province:
        parts.append(query.province)
    if query.line:
        parts.append(query.line)
    if query.fault_type:
        parts.append(query.fault_type)
    return " ".join(parts) if parts else "全部"


def retrieve_for_compare_with_stats(
    queries: list[Query],
    skill: str = "compare_stats",
    top_k: int = RETRIEVAL_TOP_K,
) -> tuple[list[dict[str, Any]], str]:
    """对比查询：合并双侧 chunks（按 report_id 去重），并为每侧生成精确统计表。"""
    seen = set()
    merged = []
    stats_parts = []
    for side_query in queries:
        side_results = retrieve(side_query, skill=skill, top_k=top_k)
        for result in side_results:
            payload = result.get("payload", result)
            report_id = payload.get("report_id")
            key = report_id if report_id else id(result)
            if key not in seen:
                seen.add(key)
                merged.append(result)
        side_stats = build_stats_text(
            build_query_filter(side_query, skill), label=_side_label(side_query)
        )
        if side_stats:
            stats_parts.append(side_stats)
    return merged, "\n".join(stats_parts)
