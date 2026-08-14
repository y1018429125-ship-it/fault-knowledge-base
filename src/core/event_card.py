"""Event card extraction: LLM-based structured fields per fault report.

At index time, each report gets one "event card" chunk replacing the old
positional summary chunk. The card header (line/voltage/date/province/
fault_type) is injected programmatically from reliable metadata; only the
content fields (tower, lightning subtype, cause, weather, reclosing,
one-line overview) are extracted by the LLM from the full report text.

Rules encoded in the prompt:
- short original passage -> quote verbatim; long passage -> condense to 1-2 sentences
- lightning faults must be classified as 绕击 (strike on conductor) or
  反击 (back-flashover after strike on ground wire/tower)
- missing information -> "报告未提及", never guess
"""

import re

import requests

from config import LLM_ENDPOINT, LLM_MODEL, LLM_TEMPERATURE

# 提取调用比问答更耗时（输入为报告全文，最长约 33k 字符），超时放宽到 180s
_EXTRACT_TIMEOUT = 180
_EXTRACT_MAX_TOKENS = 1024

CARD_FIELDS = ["故障时间", "故障杆塔", "雷击细分", "故障原因", "故障时天气", "重合闸情况", "概述"]

EXTRACTION_PROMPT = """你是输电线路故障分析报告的信息提取专家。从用户提供的故障分析报告全文中提取以下字段，严格按模板逐行输出，不要输出任何其他内容（不要解释、不要 Markdown 标记）。

输出模板（每行一个字段，字段名与值之间用中文冒号）：
故障时间：...
故障杆塔：...
雷击细分：...
故障原因：...
故障时天气：...
重合闸情况：...
概述：...

提取规则：
1. 故障时间：故障发生的具体时刻，一律以正文记载的跳闸/故障发生时间为准；当正文时间与报告文件名、封面、落款（编制日期）不一致时，必须以正文为准。注意区分"接调度通知时间"，要取故障发生时刻而非接报时刻。输出格式 YYYY-MM-DD HH:MM:SS；报告精确到秒（含毫秒可省略毫秒）就写到秒，只精确到分钟则写到分钟。报告确实未给出时刻时填"报告未提及"。
2. 故障杆塔：报告明确指出的故障发生杆塔或区段（如“#2910-#2911”）。注意区分“故障区段”（故障发生位置）与“灾损区段/排查区段”（灾后巡查范围），以故障发生位置为准；有多个候选时取报告结论认定的故障点。
3. 雷击细分：仅当故障类型为雷击时判断——雷电直接击中导线为“绕击”；击中地线或杆塔塔身后反击导线为“反击”。报告未明确判断时填“未明确”。非雷击故障填“不适用”。
4. 故障原因：报告给出的故障原因结论。原文结论为 1-2 句话时照抄原文；原文较长（如整节原因分析）时浓缩为 1-2 句，保留关键数据（杆塔号、设备部位、放电路径）。
5. 故障时天气：故障发生时故障区段的天气情况（天气现象、气温、风向风力、湿度等）。原文短则照抄，长则浓缩为 1-2 句。
6. 重合闸情况：故障跳闸后的重合闸/再启动情况，包含跳闸时刻、重合闸或再启动是否成功、故障时运行电压、负荷损失。原文短则照抄，长则浓缩为 1-2 句。
7. 概述：报告“故障概述/故障简况”部分的首句，照抄原文（通常为“X年X月X日X时X分，XX线发生XX故障”句式）。
8. 所有字段只能依据报告原文，禁止推测、禁止编造。报告确实没有的字段填“报告未提及”。"""


def _parse_fields(output: str) -> dict[str, str]:
    """Parse the LLM's line-based field output into a dict.

    Missing fields default to 报告未提及 so the card is always complete.
    """
    fields = {name: "报告未提及" for name in CARD_FIELDS}
    for line in output.splitlines():
        line = line.strip().lstrip("*-• ").strip()
        if "：" not in line:
            continue
        name, _, value = line.partition("：")
        name = name.strip()
        if name in fields and value.strip():
            fields[name] = value.strip()
    return fields


def extract_event_card_fields(report_text: str) -> dict[str, str]:
    """Extract content fields from full report text via the LLM."""
    response = requests.post(
        LLM_ENDPOINT,
        json={
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": f"以下是故障分析报告全文：\n\n{report_text}"},
            ],
            "temperature": LLM_TEMPERATURE,
            "max_tokens": _EXTRACT_MAX_TOKENS,
            "stream": False,
        },
        timeout=_EXTRACT_TIMEOUT,
    )
    response.raise_for_status()
    output = response.json()["choices"][0]["message"]["content"].strip()
    return _parse_fields(output)


def build_card_text(metadata: dict, fields: dict[str, str]) -> str:
    """Assemble the final event card text: metadata header + extracted fields.

    故障时间以正文提取为准（字段 1），不回退文件名日期。
    雷击故障在故障类型后追加绕击/反击细分（未明确或不适用时不追加）。
    """
    fault_type = metadata.get("fault_type") or "其他"
    subtype = fields.get("雷击细分", "报告未提及")
    if fault_type == "雷击" and subtype in {"绕击", "反击"}:
        fault_type = f"雷击（{subtype}）"

    return "\n".join(
        [
            f"线路：{metadata.get('line', '')} | 电压：{metadata.get('voltage', '')} | "
            f"故障时间：{fields['故障时间']} | 省份：{metadata.get('province', '')}",
            f"故障类型：{fault_type}",
            f"故障杆塔：{fields['故障杆塔']}",
            f"故障原因：{fields['故障原因']}",
            f"故障时天气：{fields['故障时天气']}",
            f"重合闸情况：{fields['重合闸情况']}",
            f"概述：{fields['概述']}",
        ]
    )


def extract_event_card(report_text: str, metadata: dict) -> str:
    """One-call helper: extract fields and assemble the card text."""
    return build_card_text(metadata, extract_event_card_fields(report_text))


def apply_card_datetime(metadata: dict, fault_time: str) -> bool:
    """Override metadata date/year/month/quarter from the card's body-derived 故障时间.

    正文时间优先：检索过滤（date/month/quarter/year must 条件）与卡片展示
    保持一致。解析失败（如“报告未提及”）时保留原元数据，返回 False。
    """
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", fault_time or "")
    if not m:
        return False
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    metadata["year"] = year
    metadata["month"] = month
    metadata["quarter"] = (month - 1) // 3 + 1
    metadata["date"] = f"{year:04d}-{month:02d}-{day:02d}"
    return True
