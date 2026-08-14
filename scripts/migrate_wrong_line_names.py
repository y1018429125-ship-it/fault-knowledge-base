"""存量索引错误线路名迁移：fallback 提取 bug 导致线路名残留省份/电压碎片
（肃电力/疆电力/北电力/伏），将受影响块的 payload line 字段改写为正确名。
纯 payload 更新，无需重嵌入。幂等：错误名不存在时自动跳过。

用法: env_fault/bin/python3 scripts/migrate_wrong_line_names.py [--dry-run]
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qdrant_client import QdrantClient  # noqa: E402

from config import QDRANT_PATH  # noqa: E402

# 错误名 → 正确名（2026-07-31 核实，涉及 5 份报告、16 块）
MAPPING = {
    "肃电力祁韶线": "祁韶线",
    "疆电力吉泉线": "吉泉线",
    "北电力雁淮线": "雁淮线",
    "北电力伏王安一线": "王安一线",
}


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    client = QdrantClient(path=QDRANT_PATH)
    try:
        points_by_new_name: dict[str, list] = {}
        changes = Counter()
        offset = None
        while True:
            points, offset = client.scroll(
                collection_name="fault_reports",
                limit=256,
                offset=offset,
                with_payload=["line"],
                with_vectors=False,
            )
            for p in points:
                old = (p.payload or {}).get("line")
                if old in MAPPING:
                    new = MAPPING[old]
                    points_by_new_name.setdefault(new, []).append(p.id)
                    changes[f"{old} → {new}"] += 1
            if offset is None:
                break

        if not changes:
            print("无需迁移：未发现错误线路名（幂等跳过）")
            return

        print(f"待改写点数: {sum(changes.values())}")
        for mapping, n in sorted(changes.items()):
            print(f"  {mapping}: {n} 个块")

        if dry_run:
            print("\n[dry-run] 未执行改写")
            return

        for new_name, ids in points_by_new_name.items():
            client.set_payload(
                collection_name="fault_reports",
                payload={"line": new_name},
                points=ids,
            )
        print(f"\n迁移完成：{sum(changes.values())} 个块已改写")
    finally:
        client.close()


if __name__ == "__main__":
    main()
