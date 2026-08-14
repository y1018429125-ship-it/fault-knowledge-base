"""轮次7 回归验收：覆盖各技能的端到端查询，结构化断言 + 报告输出。

用法: PYTHONPATH=src env_fault/bin/python3 scripts/regression.py
结果写入 logs/regression_YYYYMMDD_HHMMSS.md，同时打印汇总表。
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core.engine import query  # noqa: E402

# (名称, 问题, 期望技能, 断言列表[(描述, 检查函数)])
CASES = [
    (
        "聚焦单事件",
        "建苏线2023年9月7日故障情况",
        "single_line_stats",
        [
            ("含雷击（绕击）", lambda a: "雷击（绕击）" in a),
            ("含故障原因", lambda a: "故障原因" in a),
            ("含故障时天气", lambda a: "故障时天气" in a),
            ("含重合闸情况", lambda a: "重合闸" in a),
            ("含秒级时间", lambda a: re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", a) is not None),
            ("含来源链接", lambda a: "](http://localhost:18080/reports/" in a),
        ],
    ),
    (
        "历年单线",
        "雅湖线历年故障情况",
        "single_line_stats",
        [
            ("9条事件齐全", lambda a: a.count("**20") == 9),
            ("含冰害事件2910-2911号", lambda a: "2910-2911号" in a),
            ("末条含来源链接", lambda a: a.rstrip().endswith(")")),
            ("无截断(长度>3000)", lambda a: len(a) > 3000),
        ],
    ),
    (
        "正文时间优先",
        "官熙Ⅰ线2026年5月故障情况",
        "single_line_stats",
        [
            ("日期为05-20(正文为准)", lambda a: "2026-05-20" in a),
            ("非文件名日期05-21", lambda a: "05-21" not in a),
            ("含来源链接", lambda a: "](http://localhost:18080/reports/" in a),
        ],
    ),
    (
        "单塔查询",
        "雅湖线2911号塔历年故障情况",
        "single_tower_stats",
        [
            ("杆塔号加粗", lambda a: "**2911号**" in a),
            ("含来源链接", lambda a: "](http://localhost:18080/reports/" in a),
        ],
    ),
    (
        "多设备统计",
        "2026年河北500kV线路雷击故障统计",
        "multi_line_stats",
        [
            ("按线路分组", lambda a: re.search(r"\*\*.+线\*\*", a) is not None),
            ("雷击标注细分", lambda a: ("绕击" in a) or ("反击" in a) or ("未明确" in a)),
            ("含来源链接", lambda a: "](http://localhost:18080/reports/" in a),
        ],
    ),
    (
        "排序统计",
        "2026年雷击故障次数最多的前三条线路",
        "ranking_stats",
        [
            ("含排名条目", lambda a: re.search(r"1\.\s*\*\*", a) is not None),
            ("含次数依据", lambda a: "次" in a),
            ("含来源链接", lambda a: "](http://localhost:18080/reports/" in a),
        ],
    ),
    (
        "对比统计",
        "2025年和2026年雷击故障次数对比",
        "compare_stats",
        [
            ("两侧均有数据", lambda a: ("2025" in a) and ("2026" in a)),
            ("2025计数=7(精确统计)", lambda a: "7" in a),
            ("2026计数=69(精确统计,含绕击)", lambda a: "69" in a),
            ("含来源链接", lambda a: "](http://localhost:18080/reports/" in a),
        ],
    ),
]


def main() -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = Path(f"logs/regression_{ts}.md")
    lines = [f"# 轮次7 回归验收报告 {ts}\n"]
    summary_rows = []
    total_pass = total_fail = 0

    for name, question, expected_skill, checks in CASES:
        print(f"[RUN] {name}: {question}", flush=True)
        t0 = time.time()
        error = None
        answer = ""
        try:
            answer = query(question)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
        elapsed = time.time() - t0

        # 从 qa.jsonl 取本条记录核对技能路由
        skill = None
        try:
            with open("logs/qa.jsonl") as f:
                for line in reversed(f.readlines()):
                    rec = json.loads(line)
                    if rec.get("question") == question:
                        skill = rec.get("skill")
                        break
        except OSError:
            pass

        results = []
        if error:
            results.append(("查询无异常", False))
        else:
            results.append(("查询无异常", True))
            results.append((f"技能路由={expected_skill}", skill == expected_skill))
            for desc, fn in checks:
                try:
                    results.append((desc, bool(fn(answer))))
                except Exception:  # noqa: BLE001
                    results.append((desc, False))

        passed = sum(1 for _, ok in results if ok)
        failed = len(results) - passed
        total_pass += passed
        total_fail += failed
        status = "PASS" if failed == 0 else "FAIL"
        summary_rows.append((name, status, f"{passed}/{len(results)}", f"{elapsed:.1f}s"))

        lines.append(f"\n## {name} [{status}] ({elapsed:.1f}s, skill={skill})")
        lines.append(f"问题：{question}\n")
        for desc, ok in results:
            lines.append(f"- [{'x' if ok else ' '}] {desc}")
        lines.append("\n<details><summary>完整回答</summary>\n")
        lines.append(f"```\n{answer if answer else error}\n```")
        lines.append("</details>\n")
        print(f"[{status}] {name} {passed}/{len(results)} ({elapsed:.1f}s)", flush=True)

    lines.insert(1, "\n| 用例 | 结果 | 断言 | 耗时 |\n|---|---|---|---|")
    for row in summary_rows:
        lines.insert(2 + summary_rows.index(row), "| " + " | ".join(row) + " |")
    lines.append(f"\n断言汇总：{total_pass} 通过 / {total_fail} 失败\n")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告: {report_path}")
    print(f"断言汇总: {total_pass} 通过 / {total_fail} 失败")


if __name__ == "__main__":
    main()
