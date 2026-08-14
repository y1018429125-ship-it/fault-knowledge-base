"""Metadata extraction for fault reports.

Extracts structured metadata from both filename and report text.
Filename is the primary source for date/operator/voltage/line/fault_type;
text is used to supplement tower numbers and exact trip times.
"""

import hashlib
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import DEFAULT_YEAR, FAULT_TYPES, PROVINCE_ALIASES, VOLTAGE_PATTERNS


def canonicalize_line_name(name: Optional[str]) -> Optional[str]:
    """归一线路名：同线异名合并。

    规则（用户确认：所有 XX直流 均可表述为 XX线）：
    - XX直流联络线 → XX线（如 金永直流联络线 → 金永线）
    - XX直流 → XX线（如 锦苏直流 → 锦苏线）
    - XX线极Ⅰ线/极Ⅱ线 → XX线（极号为直流电极编号，如 柴拉线极Ⅱ线 → 柴拉线）
    """
    if not name:
        return name
    s = re.sub(r"极[ⅠⅡIV一二12]+线?$", "", name)  # XX线极Ⅱ线 / XX直流极II线
    s = re.sub(r"(直流)[ⅠⅡIV]+线$", r"\1", s)  # XX直流I线 → XX直流（仅限直流极号，不误伤艳牌I线等）
    if s.endswith("直流联络线"):
        s = s[: -len("直流联络线")] + "线"
    elif s.endswith("直流"):
        s = s[: -len("直流")] + "线"
    return s


def line_stem(name: Optional[str]) -> Optional[str]:
    """线路家族词干：剥离尾"线/路"和编号后缀，用于同族变体归组。

    编号模式（用户确认：查询裸名应命中同族全部编号变体）：
    - 罗马数字（可带"回"）：官熙Ⅰ线 → 官熙；永南Ⅰ回线 → 永南
    - 中文数字（含"回"）：江莲一线 → 江莲；渔兴三回线 → 渔兴
    - 阿拉伯数字（含"号"）：黄金2号线 → 黄金；堡安5253线 → 堡安
    - 数字字母混合编号：三海5P16线 → 三海；宿安5K73线 → 宿安
    - 尾字"路"与"线"等价：大房三回线路 → 大房；后漳Ⅱ路 → 后漳
    """
    if not name:
        return name
    s = re.sub(r"(?:线|路)+$", "", name)
    s = re.sub(r"(?:[ⅠⅡⅢIV]+回?|[一二三四五六七八九十]+回?|(?:\d+[A-Za-z]?)+\d*号?)$", "", s)
    return s


_CN_NUM = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
           "六": "6", "七": "7", "八": "8", "九": "9"}
_RM_NUM = {"Ⅰ": "1", "Ⅱ": "2", "Ⅲ": "3", "Ⅳ": "4", "I": "1", "V": "5"}


def canon_line_key(name: Optional[str]) -> tuple:
    """线路规范等价键：(词干, 编号序列归一)，编号写法统一为阿拉伯数字。

    同键 = 同一物理线路的不同报告写法，用于检索扩展与统计合并：
    - 鹰抚I回线 / 鹰抚Ⅰ线 → ("鹰抚", "1")（同线，合并）
    - 大房Ⅲ线 / 大房三回线路 → ("大房", "3")（同线，合并）
    - 胜家Ⅰ线 ("胜家","1") / 胜家Ⅱ线 ("胜家","2")（不同线，不合并）
    - 渔兴一线/一二线/三回线 → ("渔兴","1")/("渔兴","12")/("渔兴","3")
    """
    if not name:
        return (name, "")
    s = re.sub(r"(?:线|路)+$", "", name)
    m = re.search(r"([ⅠⅡⅢIV一二三四五六七八九十\d]+)[回号]?$", s)
    if not m:
        return (line_stem(name), "")
    num = "".join(_CN_NUM.get(c, _RM_NUM.get(c, c)) for c in m.group(1))
    return (s[:m.start()], num)


def normalize_voltage(text: str) -> Optional[str]:
    """Normalize voltage string to canonical form like '500kV'."""
    for pattern, canonical in VOLTAGE_PATTERNS:
        if re.search(pattern, text):
            return canonical
    return None


def extract_province(text: str) -> Optional[str]:
    """Extract province from operator text and normalize to province name."""
    # Direct patterns
    for alias, province in PROVINCE_ALIASES.items():
        if alias in text:
            return province
    return None


def extract_date_info(text: str) -> dict:
    """Extract year, quarter, month, date from text.

    Returns dict with keys: year, quarter, month, date (YYYY-MM-DD or None).
    """
    # Match YYYY年M月D日
    m = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", text)
    if not m:
        # Match YYYY-M-D or YYYY/MM/DD
        m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)

    if m:
        year = int(m.group(1))
        month = int(m.group(2))
        day = int(m.group(3))
        try:
            dt = datetime(year, month, day)
            return {
                "year": dt.year,
                "quarter": (dt.month - 1) // 3 + 1,
                "month": dt.month,
                "date": dt.strftime("%Y-%m-%d"),
            }
        except ValueError:
            pass

    # Fallback: extract year only
    m = re.search(r"(\d{4})年", text)
    if m:
        return {
            "year": int(m.group(1)),
            "quarter": None,
            "month": None,
            "date": None,
        }

    return {
        "year": None,
        "quarter": None,
        "month": None,
        "date": None,
    }


def extract_line_name(text: str) -> Optional[str]:
    """Extract line name using position-aware parsing.

    Filename structure: {operator}{voltage}{line}{date}{fault_type}分析报告
    We locate voltage and date/fault boundaries, then take the segment between.
    """
    # Locate voltage position
    voltage_match = None
    voltage_end = -1
    for pattern, _ in VOLTAGE_PATTERNS:
        m = re.search(pattern, text)
        if m and m.end() > voltage_end:
            voltage_match = m
            voltage_end = m.end()

    if not voltage_match:
        return _fallback_extract_line(text)

    # Find first date or fault type marker after voltage
    markers = [
        (r"\d{4}年", "date"),
        (r"\d{1,2}月\d{1,2}日", "date"),
        (r"雷击|异物|风偏|山火|鸟害|鸟粪|舞动|冰害|冰闪|脱冰|绕击|雪闪|断线|外力|本体|故障", "fault"),
    ]
    line_end = len(text)
    for pattern, _ in markers:
        m = re.search(pattern, text[voltage_end:])
        if m:
            candidate_end = voltage_end + m.start()
            if candidate_end < line_end:
                line_end = candidate_end

    candidate = text[voltage_end:line_end].strip()

    # Clean leading noise
    candidate = re.sub(r"^[千伏kV]+", "", candidate)
    candidate = re.sub(r"^[\s,，]+", "", candidate)
    candidate = re.sub(r"[\s,，]+$", "", candidate)

    # Validate: should end with 线 or 路 (some lines use 路 in filenames)
    if candidate.endswith(("线", "路", "直流", "柔直", "回")) and len(candidate) >= 2:
        # Allow "X号线" but reject standalone "号线"
        if candidate == "号线":
            return _fallback_extract_line(text)
        # Strip leading province/operator fragments if any remain
        candidate = re.sub(
            r"^(?:北电力|南电力|龙江电力|东电力|江电力|川电力|林电力|疆电力|肃电力|国网|网)",
            "",
            candidate,
        )
        return candidate

    return _fallback_extract_line(text)


def _fallback_extract_line(text: str) -> Optional[str]:
    """Fallback regex-based line extraction."""
    cleaned = re.sub(r"国网[^\d]{0,10}?(?:电力|公司|司)", "", text)
    for pattern, _ in VOLTAGE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned)
    cleaned = re.sub(r"[千伏kV]+(?=\D)", "", cleaned)
    cleaned = re.sub(r"\d{4}年", "", cleaned)
    cleaned = re.sub(r"\d{1,2}月\d{1,2}日", "", cleaned)
    cleaned = re.sub(r"\d{1,2}月", "", cleaned)
    cleaned = re.sub(r"\d{1,2}日", "", cleaned)
    cleaned = re.sub(r"[（()）,【】\[\]:：km.AL]+", "", cleaned)

    m = re.search(r"([^\d\s]{1,15}(?:线|路|直流|柔直|回))(?:雷击|异物|风偏|山火|鸟害|鸟粪|舞动|冰害|冰闪|脱冰|绕击|雪闪|断线|外力|本体|故障|跳闸|断裂|碰线|击穿|闪络|外破)", cleaned)
    if m:
        line = m.group(1).strip()
        if line and line not in {"线", "路", "号线", "直流", "柔直", "回"} and len(line) >= 2:
            return line

    matches = re.findall(r"([^\d\s]{1,15}(?:线|路|直流|柔直|回))", cleaned)
    if matches:
        candidate = matches[-1].strip()
        if candidate and candidate not in {"线", "路", "号线", "直流", "柔直", "回"} and len(candidate) >= 2:
            return candidate

    return None


def extract_fault_type(text: str) -> Optional[str]:
    """Extract primary fault type from text."""
    for ft in FAULT_TYPES:
        if ft in text:
            return ft
    # Synonyms / partial matches
    # 绕击/反击/雷害统一归并为雷击：绕击与反击是雷击的细分（同级），
    # 细分区分由事件卡"雷击细分"字段承担，不进入 fault_type 标签体系
    if "雷害" in text or "反击" in text or "绕击" in text:
        return "雷击"
    if "异物" in text:
        return "异物短路"
    if "鸟粪" in text or "鸟害" in text:
        return "鸟害"
    if "冰害" in text or "冰闪" in text or "重覆冰" in text or "相间距不足" in text:
        return "冰害"
    if "烟火" in text or "山火" in text or "火灾" in text:
        return "山火"
    if "地线断线" in text or "光缆断线" in text or "导线断线" in text or "断线" in text or "断裂" in text:
        return "断线"
    if "机械外破" in text or "外力破坏" in text or "外力" in text or "倒树碰线" in text:
        return "外力破坏"
    if "本体" in text or "倒塔" in text or "沿面闪络" in text:
        return "其他"
    return None


def extract_all_fault_types(text: str) -> list[str]:
    """Extract all fault type mentions from text."""
    found = []
    for ft in FAULT_TYPES:
        if ft in text:
            found.append(ft)
    # 绕击/反击/雷害归一为雷击（与 extract_fault_type 同义词规则一致）
    if any(k in text for k in ("绕击", "反击", "雷害")) and "雷击" not in found:
        found.append("雷击")
    return found


def parse_filename(filename: str) -> dict:
    """Parse metadata from report filename."""
    # Remove leading numeric prefixes and extension
    base = Path(filename).stem
    base = re.sub(r"^\d+\s*", "", base)
    base = re.sub(r"故障分析报告$", "", base)

    meta = {
        "province": extract_province(base),
        "voltage": normalize_voltage(base),
        "fault_type": extract_fault_type(base),
        "fault_types": extract_all_fault_types(base),
    }

    # Handle filenames without year but with month/day, e.g., "...3月31日..."
    date_info = extract_date_info(base)
    if date_info["year"] is None:
        # If month/day present but no year, try to infer from surrounding context
        if re.search(r"\d{1,2}月\s*\d{1,2}日", base):
            # Use default year (2026) as a fallback
            m = re.search(r"(\d{1,2})月\s*(\d{1,2})日", base)
            if m:
                month, day = int(m.group(1)), int(m.group(2))
                try:
                    dt = datetime(DEFAULT_YEAR, month, day)
                    date_info = {
                        "year": dt.year,
                        "quarter": (dt.month - 1) // 3 + 1,
                        "month": dt.month,
                        "date": dt.strftime("%Y-%m-%d"),
                    }
                except ValueError:
                    pass
    meta.update(date_info)

    meta["line"] = canonicalize_line_name(extract_line_name(base))

    return meta


def extract_towers(text: str) -> list[str]:
    """Extract tower numbers from text.

    Supported formats:
    - #106
    - 106#
    - 106号塔
    - 106号铁塔
    - 106-110号塔
    - 106号塔附近放电 -> 106号
    """
    if not text:
        return []

    towers = set()

    # Range towers: 106-110号塔 / 106～110号塔
    for m in re.finditer(r"(?<!\d{4})(\d+)[\-～](\d+)\s*号?[塔|铁塔]?", text):
        start, end = int(m.group(1)), int(m.group(2))
        if 1 <= start < 10000 and 1 <= end < 10000:
            # Avoid false ranges like 2026-4号
            if start > 1900 and end <= 12:
                continue
            # Avoid implausible ranges
            if abs(end - start) > 5000:
                continue
            towers.add(f"{start}-{end}号")

    # Single towers: avoid matching ranges again
    for m in re.finditer(r"(?:#|(\d+)#|(\d+)\s*号?[塔|铁塔])", text):
        raw = m.group(0)
        if "-" in raw or "～" in raw:
            continue

        num = None
        if raw.startswith("#"):
            num_str = raw[1:]
            if num_str.isdigit():
                num = int(num_str)
        elif raw.endswith("#"):
            num_str = raw[:-1]
            if num_str.isdigit():
                num = int(num_str)
        elif "号" in raw or "塔" in raw:
            num_str = re.search(r"\d+", raw)
            if num_str:
                num = int(num_str.group())

        if num and 1 <= num < 10000:
            # Skip if it looks like a year
            if 1900 <= num <= 2100:
                continue
            towers.add(f"{num}号")

    return sorted(list(towers), key=lambda x: int(re.search(r"\d+", x).group()))


def extract_trip_times(text: str) -> list[str]:
    """Extract precise trip times (HH:MM:SS or HH:MM:SS.mmm) from text."""
    if not text:
        return []

    times = []
    # HH:MM:SS or HH:MM:SS.mmm
    pattern = r"(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?"
    for m in re.finditer(pattern, text):
        h, mi, s, ms = m.groups()
        try:
            if 0 <= int(h) < 24 and 0 <= int(mi) < 60 and 0 <= int(s) < 60:
                time_str = f"{int(h):02d}:{mi}:{s}"
                if ms:
                    time_str += f".{ms.ljust(3, '0')}"
                times.append(time_str)
        except ValueError:
            continue

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for t in times:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def _project_root() -> str:
    """Infer project root directory (parent of src directory)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def compute_report_id(file_path: str) -> str:
    """Compute stable report_id from absolute file path.

    If file_path is relative and does not exist from CWD, resolve it against
    the project root directory to ensure consistent report_id regardless of
    the current working directory.
    """
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path) and not os.path.isabs(file_path):
        project_abs = os.path.abspath(os.path.join(_project_root(), file_path))
        if os.path.exists(project_abs):
            abs_path = project_abs
    return hashlib.sha256(abs_path.encode("utf-8")).hexdigest()[:16]


def extract_metadata(file_path: str, text: Optional[str] = None) -> dict:
    """Extract full metadata from a report file.

    Args:
        file_path: Path to the report file.
        text: Optional pre-extracted text. If None, text is not extracted here.

    Returns:
        Metadata dictionary with all fields.
    """
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path) and not os.path.isabs(file_path):
        project_abs = os.path.abspath(os.path.join(_project_root(), file_path))
        if os.path.exists(project_abs):
            abs_path = project_abs

    filename = os.path.basename(abs_path)

    meta = parse_filename(filename)
    meta.update({
        "report_id": compute_report_id(file_path),
        "report_name": filename,
        "report_path": abs_path,
    })

    if text:
        meta.setdefault("towers", extract_towers(text))
        meta.setdefault("trip_times", extract_trip_times(text))

        # If filename missed date, try text header
        if not meta.get("date"):
            date_info = extract_date_info(text[:500])
            if date_info["year"]:
                meta.update(date_info)

        # If filename missed fault type, try text
        if not meta.get("fault_type"):
            meta["fault_type"] = extract_fault_type(text[:1000])
            meta["fault_types"] = extract_all_fault_types(text[:1000])

        # If filename missed line, try text
        if not meta.get("line"):
            meta["line"] = canonicalize_line_name(extract_line_name(text[:500]))
    else:
        meta["towers"] = []
        meta["trip_times"] = []

    return meta
