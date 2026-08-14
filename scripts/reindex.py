"""Full reindex script for all fault reports.

重建/增量索引完成后自动执行双线报告拆分（split_dual_line_report，幂等），
防止"青林一线、兰林一线"一报告两事件的拆分成果被重建冲掉。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.engine import index_all_reports

from split_dual_line_report import main as split_dual_line


def main():
    recreate = "--recreate" in sys.argv
    max_reports = None
    for arg in sys.argv:
        if arg.startswith("--max="):
            max_reports = int(arg.split("=", 1)[1])

    print(f"Starting reindex (recreate={recreate}, max={max_reports})...")
    stats = index_all_reports(recreate=recreate, max_reports=max_reports)
    print("Reindex complete.")
    print(f"  Total files:   {stats['total_files']}")
    print(f"  Indexed:       {stats['indexed_files']}")
    print(f"  Skipped:       {stats['skipped_files']}")
    print(f"  Failed:        {stats['failed_files']}")
    print(f"  Total chunks:  {stats['total_chunks']}")

    # 重建后修复：双线报告拆分（幂等，拼接名不存在时自动跳过）
    print("Post-reindex: dual-line report split check...")
    split_dual_line(dry_run=False)


if __name__ == "__main__":
    main()
