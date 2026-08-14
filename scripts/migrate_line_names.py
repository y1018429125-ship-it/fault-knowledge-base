"""存量索引线路名归一迁移：将同线异名（XX直流/XX直流联络线/XX线极X线）
的 payload line 字段改写为规范名（XX线）。纯 payload 更新，无需重嵌入。

用法: env_fault/bin/python3 scripts/migrate_line_names.py [--dry-run]
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qdrant_client import QdrantClient  # noqa: E402

from config import QDRANT_PATH  # noqa: E402
from core.metadata import canonicalize_line_name  # noqa: E402


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    client = QdrantClient(path=QDRANT_PATH)
    try:
        # 全量扫描所有块（summary/event/detail 都带 line 字段）
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
                if not old:
                    continue
                new = canonicalize_line_name(old)
                if new != old:
                    points_by_new_name.setdefault(new, []).append(p.id)
                    changes[f"{old} → {new}"] += 1
            if offset is None:
                break

        if not changes:
            print("无需迁移：所有线路名已是规范形式")
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
