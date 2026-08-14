"""精准重索引 fault_type=绕击 的存量报告（2026-08-04 雷击标签归一改造）。

背景：绕击/反击已统一归并为"雷击"（metadata/query_parser 双侧同义词规则，
细分由事件卡"雷击细分"字段承担）。本脚本只处理库中残留的 fault_type=绕击
旧块：删除这些报告的块并走修正后的管线重新入库，其余报告的块零改动。

用法：
    PYTHONPATH=src python3 scripts/reindex_raoji_reports.py            # 执行
    PYTHONPATH=src python3 scripts/reindex_raoji_reports.py --dry-run  # 只打印计划

幂等：库中无 fault_type=绕击 块时直接跳过（重跑安全）。
安全：报告文件不存在时拒绝删除其旧块（不删无法重建的数据）。
"""

import sys

from config import COLLECTION_NAME
from qdrant_client.http import models

from core.engine import index_report
from core.vector_store import get_client

TARGET_FAULT_TYPE = "绕击"


def find_target_reports(client) -> dict:
    """扫描全库，返回 {report_id: {"path": str, "name": str, "chunks": int}}（fault_type=绕击）。"""
    reports = {}
    offset = None
    while True:
        records, offset = client.scroll(
            collection_name=COLLECTION_NAME,
            offset=offset,
            limit=1000,
            with_payload=True,
            with_vectors=False,
        )
        for r in records:
            p = r.payload or {}
            if p.get("fault_type") == TARGET_FAULT_TYPE:
                rid = p.get("report_id")
                e = reports.setdefault(
                    rid, {"path": p.get("report_path"), "name": p.get("report_name"), "chunks": 0}
                )
                e["chunks"] += 1
        if offset is None:
            break
    return reports


def delete_report_chunks(client, report_id: str) -> None:
    """按 report_id 删除一份报告的全部块。"""
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="report_id",
                        match=models.MatchValue(value=report_id),
                    )
                ]
            )
        ),
    )


def main(dry_run: bool = False) -> int:
    client = get_client()
    try:
        reports = find_target_reports(client)
        if not reports:
            print(f"[SKIP] 库中无 fault_type={TARGET_FAULT_TYPE} 的块，无需处理（幂等退出）")
            return 0

        total_chunks = sum(e["chunks"] for e in reports.values())
        print(f"发现 {len(reports)} 份 fault_type={TARGET_FAULT_TYPE} 报告，共 {total_chunks} 块：")
        for rid, e in reports.items():
            print(f"  {rid}  {e['name']}（{e['chunks']} 块）")

        if dry_run:
            print("\n[DRY-RUN] 以上为计划删除并重索引的范围，未做任何修改。")
            return 0

        import os

        failed = 0
        for rid, e in reports.items():
            path = e["path"]
            if not path or not os.path.exists(path):
                print(f"[ABORT] {e['name']}：报告文件不存在（{path}），拒绝删除旧块")
                failed += 1
                continue
            print(f"\n--- 重索引 {e['name']}（删除 {e['chunks']} 块后重建）")
            delete_report_chunks(client, rid)
            n = index_report(path, client=client)
            print(f"    重建完成，新块数: {n}")

        # 后置断言：绕击标签清零
        remaining = find_target_reports(client)
        if remaining:
            print(f"[FAIL] 仍有 {len(remaining)} 份报告的绕击块残留")
            return 1
        print(f"\n[DONE] 重索引完成，fault_type={TARGET_FAULT_TYPE} 已清零。失败 {failed} 份。")
        return 0 if failed == 0 else 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
