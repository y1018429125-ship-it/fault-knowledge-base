"""故障知识库验收测试（基于实际业务需求重构，2026-07-27）。

设计原则：
- 只读：仅调用 query() 做检索问答，禁止 delete_collection / recreate / 重建索引。
- 索引保护：运行前后校验集合记录数不变（当前基线 901 块 / 274 起故障事件）。
- 用例全部基于索引中真实存在的事件（2026-07-27 从 Qdrant 采样核对）。
- checks 为答案中必须出现的子串；LLM 生成有波动，checks 只取确定性关键信息。

运行方式（需用户授权，消耗 Embedding + LLM API）：
    cd /Users/yfzx/Desktop/故障知识库
    PYTHONPATH=src env_fault/bin/python3 tests/test_acceptance.py
    # 只跑某一类：
    PYTHONPATH=src env_fault/bin/python3 tests/test_acceptance.py --category single_line
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.engine import query
from core.vector_store import count_records, get_client

BASELINE_RECORDS = 907  # 2026-07-27：7 份 WPS 改为 PDF 入库（898-21+30）
SOURCE_LINK = "http://localhost:18080/reports"

# 事件列举类回答的通用格式断言（回答质量要求）：
# 每条事件含电压等级（"kV"）+ 来源文件超链接。边界/软性用例可 skip_format 跳过。
FORMAT_CHECK_CATEGORIES = {"single_line", "single_tower", "multi_line", "ranking", "compare"}

# ---------------------------------------------------------------------------
# 用例定义：category / name / question / checks
# 答案通用要求（每个用例隐式校验）：按时间排序、含日期/线路/电压/杆塔/类型/
# 概述、每条事件标注来源文件超链接 → 多数用例 checks 含 SOURCE_LINK。
# ---------------------------------------------------------------------------

CASES = [
    # ================= 线路级单设备 single_line_stats =================
    # 索引事实：雅湖线2024年 3 起（02-06 冰害、04-02 雷击、04-29 雷击）
    {
        "category": "single_line",
        "name": "按年查询",
        "question": "雅湖线2024年故障情况",
        "checks": ["雅湖线", "2024-02-06", "冰害", "2024-04-02", "2024-04-29", SOURCE_LINK],
    },
    # 雅湖线2023Q2 实际 3 起（04-03 山火、04-04 雷击、05-06 雷击）；
    # 原"2023-05-08"报告已证实为 2025 年事件（文件名错标，已修正重入库）
    {
        "category": "single_line",
        "name": "按季度查询",
        "question": "雅湖线2023年第二季度故障情况",
        "checks": ["雅湖线", "2023-04-03", "山火", "2023-04-04", "2023-05-06", SOURCE_LINK],
        "forbid": ["2023-05-08"],  # 错标事件不得混入 2023 年答案
    },
    # 雅湖线2023年5月 实际 1 起（05-06 雷击）
    {
        "category": "single_line",
        "name": "按月查询",
        "question": "雅湖线2023年5月故障情况",
        "checks": ["雅湖线", "2023-05-06", SOURCE_LINK],
        "forbid": ["2023-05-08"],
    },
    # 建苏线2023-09-07 1 起雷击（四川，800kV）
    {
        "category": "single_line",
        "name": "按日期查询",
        "question": "建苏线2023年9月7日故障情况",
        "checks": ["建苏线", "2023-09-07", "雷击", "800kV", SOURCE_LINK],
    },
    # 后漳Ⅱ路 2026-02-16 事件正文含秒级时间戳 04:37:43（回答质量要求：精确到秒）
    {
        "category": "single_line",
        "name": "按日期查询（校验秒级时间戳）",
        "question": "后漳Ⅱ路2026年2月16日故障情况",
        "checks": ["后漳Ⅱ路", "2026-02-16", SOURCE_LINK],
        "checks_any": [["04:37:43", "04时37分43秒"]],
    },
    # 宾金线2015年雷击 3 起（03-22、04-03、07-27）
    {
        "category": "single_line",
        "name": "按年+故障类型查询",
        "question": "宾金线2015年雷击故障情况",
        "checks": ["宾金线", "2015-03-22", "2015-04-03", "2015-07-27", "雷击", SOURCE_LINK],
    },
    # 雅湖线2023Q2 雷击 2 起（04-04、05-06，不含 04-03 山火；05-08 已修正为 2025 年事件）
    {
        "category": "single_line",
        "name": "按季度+故障类型查询",
        "question": "雅湖线2023年第二季度雷击故障情况",
        "checks": ["雅湖线", "2023-04-04", "2023-05-06", "雷击", SOURCE_LINK],
        "forbid": ["2023-05-08"],
    },
    # 临潍线2026年 3 起（05-13 异物短路、06-03 风偏、06-27 山火）
    {
        "category": "single_line",
        "name": "按年查询（2026年多类型）",
        "question": "临潍线2026年故障情况",
        "checks": ["临潍线", "2026-05-13", "异物短路", "2026-06-03", "风偏", "2026-06-27", "山火", SOURCE_LINK],
    },
    # 历年查询：雅湖线 2022~2025 共 9 起，须覆盖首尾及曾被向量 top_k 挤掉的 2023-05-06
    {
        "category": "single_line",
        "name": "历年查询（全部年份）",
        "question": "雅湖线历年故障情况",
        "checks": ["雅湖线", "2022-06-20", "2023-05-06", "2025-05-08", SOURCE_LINK],
    },
    # 无时间信息：应反问用户查具体某一年还是历年，不执行检索
    {
        "category": "single_line",
        "name": "边界：无时间应反问",
        "question": "雅湖线故障情况",
        "checks": ["您想查询", "雅湖线", "历年"],
        "skip_format": True,
    },

    # ================= 杆塔级单设备 single_tower_stats =================
    # 锦苏线 2013-08-01 雷击事件 towers 含 496号
    {
        "category": "single_tower",
        "name": "按年查询",
        "question": "锦苏线496号杆塔2013年故障情况",
        "checks": ["锦苏线", "496号", "2013-08-01", "雷击", SOURCE_LINK],
    },
    # 灵绍线 2019-02-11 冰害（浙江）towers 含 3059号
    {
        "category": "single_tower",
        "name": "按季度+故障类型查询",
        "question": "灵绍线3059号杆塔2019年第一季度冰害故障情况",
        "checks": ["灵绍线", "3059号", "2019-02-11", "冰害", SOURCE_LINK],
    },
    # 建苏线 2023-07-21 雷击 towers 含 3252号
    {
        "category": "single_tower",
        "name": "按月查询",
        "question": "建苏线3252号杆塔2023年7月故障情况",
        "checks": ["建苏线", "3252号", "2023-07-21", "雷击", SOURCE_LINK],
    },
    # 祁韶线 2017-08-22 雷击 towers 含 92号
    {
        "category": "single_tower",
        "name": "按日期查询",
        "question": "祁韶线92号杆塔2017年8月22日故障情况",
        "checks": ["祁韶线", "92号", "2017-08-22", "雷击", SOURCE_LINK],
    },
    # 灵绍线 2021-07-17 雷击（安徽）towers 含 3059号
    {
        "category": "single_tower",
        "name": "按年+故障类型查询",
        "question": "灵绍线3059号杆塔2021年雷击故障情况",
        "checks": ["灵绍线", "3059号", "2021-07-17", "雷击", SOURCE_LINK],
    },
    # 临潍线 2026-06-03 风偏 towers 含 35号
    {
        "category": "single_tower",
        "name": "按月+杆塔查询（2026）",
        "question": "临潍线35号杆塔2026年6月故障情况",
        "checks": ["临潍线", "35号", "2026-06-03", "风偏", SOURCE_LINK],
    },
    # 边界规则：杆塔号查询不带线路名，应提示用户补充线路名
    {
        "category": "single_tower",
        "name": "边界：缺线路名应提示",
        "question": "3059号杆塔2021年雷击故障情况",
        "checks": ["线路"],  # 期望回答中提示需要线路名
        "skip_format": True,
    },

    # ================= 多设备 multi_line_stats =================
    # 2026 年全国 1000kV 共 8 起（舞动/绕击/断线/冰闪/雷击）
    {
        "category": "multi_line",
        "name": "全国+电压+年",
        "question": "2026年全国1000kV线路故障情况",
        "checks": ["1000kV", "榕泰Ⅱ线", "胜锡Ⅱ线", SOURCE_LINK],
    },
    # 2026 年湖北 500kV 雷击 6 起（渔朝线、葛朝一回、渔兴三回线、渔兴一线、三江一线、孝浉一回线）
    {
        "category": "multi_line",
        "name": "省份+电压+故障类型",
        "question": "2026年湖北500kV线路雷击故障情况",
        "checks": ["渔朝线", "葛朝一回", "渔兴三回线", "渔兴一线", "三江一线", "孝浉一回线", SOURCE_LINK],
    },
    # 2026Q1 冀北 500kV 10 起（大房三回线路、南门一线、中延直流、南门二线、阜诺直流、上承一线、阜二线、南昌三线、阜一线、阜延直流）
    {
        "category": "multi_line",
        "name": "省份+季度+电压",
        "question": "2026年第一季度冀北500kV线路故障情况",
        "checks": ["大房三回线路", "南门一线", "阜延直流", "阜一线", SOURCE_LINK],
    },
    # 2026年7月 河北 500kV 2 起（瀛易Ⅱ线 风偏 07-05、光邑二线 雷击 07-07）
    {
        "category": "multi_line",
        "name": "省份+月份+电压",
        "question": "2026年7月河北500kV线路故障情况",
        "checks": ["瀛易Ⅱ线", "光邑二线", SOURCE_LINK],
    },
    # 2026Q1 全国 800kV 雷击 1 起（坤渝线 03-14）
    {
        "category": "multi_line",
        "name": "全国+季度+电压+故障类型",
        "question": "2026年第一季度全国800kV线路雷击故障情况",
        "checks": ["坤渝线", "2026-03-14", "800kV", SOURCE_LINK],
    },
    # 2026 年浙江雷击 7 起
    {
        "category": "multi_line",
        "name": "省份+故障类型（不带电压）",
        "question": "2026年浙江雷击故障情况",
        "checks": ["江莲一线", "江莲二线", "强明5423线", SOURCE_LINK],
    },
    # 2026-06-03 当天全国 500kV 至少含山东 3 起风偏（固临Ⅱ线、临潍线、淄临线）
    {
        "category": "multi_line",
        "name": "全国+电压+具体日期",
        "question": "2026年6月3日全国500kV线路故障情况",
        "checks": ["临潍线", "淄临线", "固临Ⅱ线", SOURCE_LINK],
    },
    # 2026 年湖北 1000kV 仅 1 起（荆潇II线 02-15 绕击）——覆盖"省份+电压+年（不带故障类型）"
    {
        "category": "multi_line",
        "name": "省份+电压+年",
        "question": "2026年湖北1000kV线路故障情况",
        "checks": ["荆潇II线", "1000kV", "2026-02-15", "绕击", SOURCE_LINK],
    },

    # ================= 排序 ranking_stats =================
    # 雅湖线2023年雷击：4月 1 起、5月 2 起 → 最频繁月份为 5 月
    {
        "category": "ranking",
        "name": "单线路故障最频繁月份",
        "question": "雅湖线2023年雷击故障最频繁的月份是哪几个",
        "checks": ["5月", "雅湖线", SOURCE_LINK],
    },
    # 湖北雷击（全部年份）：建苏线 2 起（2023-05-25、2025-08-06）为最多
    {
        "category": "ranking",
        "name": "省份雷击最多线路Top3",
        "question": "湖北遭受雷击故障最多的前三条线路",
        "checks": ["建苏线", SOURCE_LINK],
    },

    # ================= 对比 compare_stats =================
    # 2026 山东：风偏 9 起 vs 雷击 2 起
    {
        "category": "compare",
        "name": "同一省份不同灾害对比",
        "question": "2026年山东风偏和雷击故障哪个更多",
        "checks": ["风偏", "雷击", "山东", SOURCE_LINK],
    },
    # 湖北雷击：2025 年 1 起 vs 2026 年 6 起
    {
        "category": "compare",
        "name": "同一省份两年事故对比",
        "question": "湖北2025年和2026年雷击故障数量对比",
        "checks": ["2025", "2026", "湖北", SOURCE_LINK],
    },
    # 2026 雷击：四川 8 起 vs 浙江 7 起
    {
        "category": "compare",
        "name": "不同省份同一灾害对比",
        "question": "2026年四川和浙江雷击故障数量对比",
        "checks": ["四川", "浙江", "雷击", SOURCE_LINK],
    },
    # 临潍线2026年：异物短路/风偏/山火 各 1 起
    {
        "category": "compare",
        "name": "同一线路不同灾害对比",
        "question": "临潍线2026年异物短路、风偏和山火故障对比",
        "checks": ["异物短路", "风偏", "山火", "临潍线", SOURCE_LINK],
    },
    # 雅湖线：2023 年 4 起 vs 2024 年 3 起
    {
        "category": "compare",
        "name": "同一线路两年事故对比",
        "question": "雅湖线2023年和2024年故障情况对比",
        "checks": ["2023", "2024", "雅湖线", SOURCE_LINK],
    },

    # ================= 其他（fault_type_stats / default） =================
    {
        "category": "other",
        "name": "故障类型现象归纳",
        "question": "雷击故障通常伴随什么现象",
        "checks": ["雷", SOURCE_LINK],
    },
    # 2026 年山火线路：锦忻一二线、方永乙线、天乐一线、复奉直流、临潍线
    {
        "category": "other",
        "name": "通用列举查询",
        "question": "2026年有哪些线路发生过山火故障",
        "checks": ["山火", SOURCE_LINK],
    },
]


def check_index_guard(expected: int = BASELINE_RECORDS) -> int:
    """索引保护：返回当前记录数，调用方比对是否被改动。"""
    client = get_client()
    total = count_records(client)
    client.close()
    return total


def normalize_answer(text: str) -> str:
    """把答案中的中文日期（2026年5月13日）归一化为 ISO（2026-05-13）再断言。

    Prompt 已要求 ISO 输出，此归一化作为兜底，避免格式波动造成假失败。
    """

    def _repl(m: re.Match) -> str:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    return re.sub(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", _repl, text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", help="只运行指定分类的用例")
    args = parser.parse_args()

    before = check_index_guard()
    print(f"[索引保护] 运行前记录数: {before}")
    if before != BASELINE_RECORDS:
        print(f"[警告] 记录数与基线 {BASELINE_RECORDS} 不一致，请先确认索引完整性")

    cases = [c for c in CASES if not args.category or c["category"] == args.category]
    print(f"共 {len(cases)} 个用例\n")

    passed, failed, soft = [], [], []
    for i, case in enumerate(cases, 1):
        print(f"{'=' * 60}")
        print(f"[{i}/{len(cases)}] [{case['category']}] {case['name']}")
        print(f"Q: {case['question']}")
        try:
            answer = query(case["question"])
        except Exception as e:  # noqa: BLE001
            print(f"ERROR: {e}")
            (soft if case.get("soft") else failed).append(case["name"])
            continue
        print(answer)
        answer = normalize_answer(answer)

        if case.get("soft"):
            print("→ 软性观察用例（已知差距），不计入通过数")
            soft.append(case["name"])
            continue

        missing = [s for s in case["checks"] if s not in answer]
        # forbid：禁止出现的内容（如已修正的错标事件日期）
        leaked = [s for s in case.get("forbid", []) if s in answer]
        missing.extend(f"[禁止出现]{s}" for s in leaked)
        # checks_any：每组备选子串至少命中一个（用于兼容时间戳等格式差异）
        for group in case.get("checks_any", []):
            if not any(s in answer for s in group):
                missing.append(f"[任一未命中]{group}")
        # 通用格式断言：电压等级 + 来源超链接
        if case["category"] in FORMAT_CHECK_CATEGORIES and not case.get("skip_format"):
            for s in ("kV", SOURCE_LINK):
                if s not in answer:
                    missing.append(f"[格式]{s}")
        if missing:
            print(f"→ FAIL，缺失关键信息: {missing}")
            failed.append(case["name"])
        else:
            print("→ PASS")
            passed.append(case["name"])
        print()

    after = check_index_guard()
    print(f"{'=' * 60}")
    print(f"[索引保护] 运行后记录数: {after}", "（未被改动 ✓）" if after == before else "（!! 索引被改动 !!）")
    print(f"结果: PASS {len(passed)} / FAIL {len(failed)} / 软性 {len(soft)}，共 {len(cases)}")
    if failed:
        print("失败用例:", ", ".join(failed))
    if after != before:
        print("!! 测试改动了索引库，这不应该发生 !!")
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
