"""Test generator with retrieved chunks."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.generator import generate
from core.query_parser import parse_query
from core.retriever import retrieve


def main():
    test_cases = [
        ("single_line_stats", "武宗Ⅰ线2026年雷击故障情况"),
        ("multi_line_stats", "2026年河北500kV线路雷击故障"),
    ]

    for skill, text in test_cases:
        print(f"\n{'='*60}")
        print(f"Skill: {skill}")
        print(f"Question: {text}")
        print("=" * 60)

        q = parse_query(text)
        results = retrieve(q, skill=skill, top_k=5)
        if not results:
            print("No retrieved chunks.")
            continue

        answer = generate(text, skill, results)
        print(answer)

    return 0


if __name__ == "__main__":
    sys.exit(main())
