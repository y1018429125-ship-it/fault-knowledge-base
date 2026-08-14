"""Test semantic routing and query parsing."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.query_parser import parse_query
from router.semantic_router import route


TEST_CASES = [
    ("泰吴线2025年雷击故障情况", "single_line_stats"),
    ("泰吴线106号塔2025年雷击故障", "single_tower_stats"),
    ("2025年湖北500kV线路雷击故障", "multi_line_stats"),
    ("2025年湖北遭受雷击故障最多的前三条线路", "ranking_stats"),
    ("2025年湖北雷击和风偏故障哪个更多", "compare_stats"),
    ("雷击故障通常伴随什么现象", "fault_type_stats"),
    ("2024年1月南京平均气温是多少", None),
]


def main():
    print("=== Query Parser Tests ===")
    for text, expected_skill in TEST_CASES:
        q = parse_query(text)
        print(f"\nQ: {text}")
        print(f"  years={q.year_filter()} line={q.line} tower={q.tower} fault={q.fault_type} province={q.province} voltage={q.voltage}")

    print("\n=== Semantic Router Tests ===")
    all_pass = True
    for text, expected_skill in TEST_CASES:
        result = route(text)
        matched = result.skill == expected_skill
        status = "PASS" if matched else "FAIL"
        if not matched:
            all_pass = False
        print(f"[{status}] {text}")
        print(f"       expected={expected_skill}, got={result.skill}, sim={result.similarity:.3f}")

    if all_pass:
        print("\nAll routing tests passed.")
        return 0
    else:
        print("\nSome routing tests failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
