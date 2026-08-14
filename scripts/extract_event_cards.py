"""Trial extraction: build event cards for 10 representative reports.

Round-1 verification tool (ULW loop). Also reused in round 4 for full
reindex. Writes cards to logs/event_card_trial.md for manual review.

Usage:
    PYTHONPATH=src env_fault/bin/python3 scripts/extract_event_cards.py
    # full run over all reports (round 4):
    PYTHONPATH=src env_fault/bin/python3 scripts/extract_event_cards.py --all
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import REPORT_DIR
from core.event_card import build_card_text, extract_event_card_fields
from core.metadata import extract_metadata
from core.parser import clean_text, get_report_files, parse_report

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "logs", "event_card_trial.md")

# 10 份代表报告（文件名子串匹配），覆盖：长报告+目录 / 无目录 DOC / 老版式 /
# 现代短 PDF / 秒级时间戳 / 最短报告 / 非规范文件名 / 舞动 / 1000kV / 其他类型
TRIAL_PATTERNS = [
    "2024年2月6日±800kV雅湖线",
    "2023年5月6日±800kV雅湖线",
    "2018年3月16日±800kV祁韶线",
    "官熙Ⅰ线2026年5月21日",
    "后漳Ⅱ路2026年2月16日",
    "托海I线2026年3月17日",
    "上泰Ⅰ线07月06日",
    "衡兰Ⅱ线2026年1月18日",
    "岳定Ⅱ线2026年3月1日",
    "2023年12月13日±1100kV吉泉线",
]


def find_trial_files() -> list[str]:
    all_files = get_report_files(REPORT_DIR)
    selected = []
    for pattern in TRIAL_PATTERNS:
        matches = [f for f in all_files if pattern in os.path.basename(f)]
        if not matches:
            print(f"[警告] 未找到匹配报告: {pattern}")
            continue
        selected.append(matches[0])
    return selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="对全部报告提取（轮次4用）")
    args = parser.parse_args()

    files = get_report_files(REPORT_DIR) if args.all else find_trial_files()
    print(f"共 {len(files)} 份报告待提取")

    out_lines = []
    ok, failed = 0, 0
    for i, file_path in enumerate(files, 1):
        name = os.path.basename(file_path)
        print(f"[{i}/{len(files)}] {name}")
        t0 = time.time()
        try:
            text = clean_text(parse_report(file_path))
            metadata = extract_metadata(file_path, text)
            fields = extract_event_card_fields(text)
            card = build_card_text(metadata, fields)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR: {type(exc).__name__}: {exc}")
            out_lines.append(f"## {i}. {name}\n\n提取失败：{exc}\n")
            continue
        elapsed = time.time() - t0
        print(f"  {elapsed:.1f}s")
        out_lines.append(f"## {i}. {name}（提取耗时 {elapsed:.1f}s）\n\n```\n{card}\n```\n")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("# 事件卡试提取结果\n\n" + "\n".join(out_lines))
    print(f"\n完成：成功 {ok} / 失败 {failed}，结果已写入 {OUTPUT_PATH}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
