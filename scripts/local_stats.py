"""方案B 可行性验证：纯本地统计，不调用任何外部 API。

1. 全量扫描事件卡（chunk_type=summary）payload 元数据
2. 检查 groupby 所需字段（year/month/line/fault_type/province/voltage）完整率
3. 按 年份×故障类型 计数，找出超过召回上限 40 的查询口径
4. 模拟典型列举类查询口径，对比"元数据精确计数"与"40 张上限"的差距

用法: env_fault/bin/python3 scripts/local_stats.py
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qdrant_client import QdrantClient  # noqa: E402
from qdrant_client.http import models  # noqa: E402

from config import QDRANT_PATH  # noqa: E402

CARD_LIMIT = 40
GROUPBY_FIELDS = ["year", "month", "line", "fault_type", "province", "voltage"]


def scroll_all_cards(client: QdrantClient) -> list[dict]:
    cards = []
    offset = None
    filter_obj = models.Filter(
        must=[models.FieldCondition(key="chunk_type", match=models.MatchValue(value="summary"))]
    )
    while True:
        points, offset = client.scroll(
            collection_name="fault_reports",
            scroll_filter=filter_obj,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        cards.extend(p.payload for p in points)
        if offset is None:
            break
    return cards


def main() -> None:
    client = QdrantClient(path=QDRANT_PATH)
    try:
        cards = scroll_all_cards(client)
    finally:
        client.close()

    print(f"事件卡总数: {len(cards)}\n")

    # 1. 字段完整率（groupby 可行性）
    print("== groupby 字段完整率 ==")
    for field in GROUPBY_FIELDS:
        filled = sum(1 for c in cards if c.get(field) not in (None, "", []))
        print(f"  {field:<12} {filled}/{len(cards)} ({filled / len(cards) * 100:.1f}%)")

    # 2. 年份×故障类型计数，标记超上限口径
    print("\n== 年份×故障类型 计数（* = 超过 40 张召回上限）==")
    year_type = Counter((c.get("year"), c.get("fault_type")) for c in cards)
    over = 0
    for (year, ft), n in sorted(year_type.items(), key=lambda x: (x[0][0] or 0, -x[1])):
        mark = " *" if n > CARD_LIMIT else ""
        if n > CARD_LIMIT:
            over += 1
        print(f"  {year} {ft:<8} {n}{mark}")
    print(f"\n超上限口径数: {over}")

    # 3. 典型查询口径模拟
    print("\n== 典型查询口径模拟（元数据精确计数 vs 召回上限）==")
    scenarios = [
        ("2026年雷击", lambda c: c.get("year") == 2026 and c.get("fault_type") == "雷击"),
        ("2026年全部类型", lambda c: c.get("year") == 2026),
        ("2025年雷击", lambda c: c.get("year") == 2025 and c.get("fault_type") == "雷击"),
        ("历年雅湖线", lambda c: c.get("line") == "雅湖线"),
        ("2026年河北500kV雷击", lambda c: c.get("year") == 2026 and c.get("province") == "河北"
         and c.get("voltage") == "500kV" and c.get("fault_type") == "雷击"),
    ]
    for name, pred in scenarios:
        n = sum(1 for c in cards if pred(c))
        truncated = "是" if n > CARD_LIMIT else "否"
        print(f"  {name:<22} 精确计数={n:<4} 受40上限截断={truncated}")


if __name__ == "__main__":
    main()
