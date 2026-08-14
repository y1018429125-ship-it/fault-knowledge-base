"""Query parser: extract structured fields from natural language questions."""

import re
from dataclasses import dataclass, field
from typing import Optional

from config import DEFAULT_YEAR, FAULT_TYPES, PROVINCE_ALIASES, VOLTAGE_PATTERNS
from core.metadata import canonicalize_line_name


@dataclass
class Query:
    """Structured representation of a user question."""

    raw: str
    years: list[int] = field(default_factory=list)
    quarters: list[int] = field(default_factory=list)
    months: list[int] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    province: Optional[str] = None
    voltage: Optional[str] = None
    line: Optional[str] = None
    tower: Optional[str] = None
    fault_type: Optional[str] = None
    top_n: Optional[int] = None
    exclude_lines: list[str] = field(default_factory=list)
    compare_items: list[str] = field(default_factory=list)
    is_range_year: bool = False
    all_years: bool = False

    def year_filter(self) -> list[int]:
        """Return list of years to filter, expanding ranges.

        Returns empty list when all_years is set ("历年"等)，表示不加年份过滤。
        """
        if self.all_years:
            return []
        if self.years:
            if self.is_range_year and len(self.years) == 2:
                return list(range(min(self.years), max(self.years) + 1))
            return self.years
        return [DEFAULT_YEAR]


def _extract_years(text: str) -> tuple[list[int], bool]:
    """Extract years from text. Supports ranges, expanded to full year lists:
    2023-2025 / 2023年-2025年 / 2023~2025年（连接符类）
    2023至2025年 / 2023年至2025年 / 2023年到2025年（至/到类）。
    """
    range_patterns = [
        r"(\d{4})年?\s*[-—~～]\s*(\d{4})年?",
        r"(\d{4})年?\s*(?:至|到)\s*(\d{4})年",
    ]
    for pattern in range_patterns:
        m = re.search(pattern, text)
        if m:
            start, end = int(m.group(1)), int(m.group(2))
            if 2010 <= start < end <= 2030:
                return list(range(start, end + 1)), True

    # Single years
    years = [int(y) for y in re.findall(r"(\d{4})年", text)]
    if not years:
        years = [int(y) for y in re.findall(r"(?<!\d)(\d{4})(?!\d)", text) if 2010 <= int(y) <= 2030]

    return years, False


def _extract_quarters(text: str) -> list[int]:
    """Extract quarters (1-4), accepting Chinese or Arabic numerals."""
    mapping = {"一": 1, "二": 2, "三": 3, "四": 4}
    return [mapping.get(q, int(q) if q.isdigit() else 0) for q in re.findall(r"第([一二三四1234])季度", text)]


def _extract_months(text: str) -> list[int]:
    """Extract months (1-12), expanding ranges: 3-8月 / 4至7月 / 4月至7月 / 4月到7月 / 4~7月."""
    months: set[int] = set()
    spans: list[tuple[int, int]] = []
    for m in re.finditer(r"(\d{1,2})\s*月?\s*(?:[-—~～]|至|到)\s*(\d{1,2})\s*月", text):
        a, b = int(m.group(1)), int(m.group(2))
        if 1 <= a < b <= 12:
            months.update(range(a, b + 1))
            spans.append(m.span())
    # 抹除已命中的区间文本再扫单点月份，避免区间端点被重复捕获
    chars = list(text)
    for s, e in spans:
        chars[s:e] = " " * (e - s)
    for m in re.finditer(r"(\d{1,2})月", "".join(chars)):
        month = int(m.group(1))
        if 1 <= month <= 12:
            months.add(month)
    return sorted(months)


def _extract_dates(text: str) -> list[str]:
    """Extract exact dates YYYY-MM-DD."""
    dates = []
    for m in re.finditer(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            from datetime import datetime
            dates.append(datetime(y, mo, d).strftime("%Y-%m-%d"))
        except ValueError:
            pass
    return dates


def _extract_province(text: str) -> Optional[str]:
    """Extract province from text."""
    for alias, province in PROVINCE_ALIASES.items():
        if alias in text:
            return province
    return None


def _extract_voltage(text: str) -> Optional[str]:
    """Extract normalized voltage（查询侧：单位必需，kV 大小写全兼容）。

    与索引侧 config.VOLTAGE_PATTERNS（单位可选）刻意分离：
    查询侧要求数字必须带单位上下文才认领——kV/Kv/kv/KV、千伏、
    前面有 ±、或后面跟"线路"。裸数字由 find_bare_voltage_number 反问兜底，
    避免"320号塔"的 320 被误作电压（问题 1）。
    """
    for n in _VOLTAGE_NUMBERS:
        pattern = rf"±?(?<!\d){n}\s*(?:[kK][vV]|千伏)|±{n}(?!\d)|(?<![\d#]){n}(?=\s*线路)"
        if re.search(pattern, text):
            return f"{n}kV"
    return None


def _extract_line_raw(text: str) -> Optional[str]:
    """Extract raw line name as written in text (pre-canonicalization)."""
    # Remove year, voltage, province, and date fragments
    cleaned = text
    for pattern, _ in VOLTAGE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned)
    cleaned = re.sub(r"\d{4}年", "", cleaned)
    cleaned = re.sub(r"\d{1,2}月\d{1,2}[日号]", "", cleaned)
    cleaned = re.sub(r"\d{1,2}月", "", cleaned)
    cleaned = re.sub(r"\d{1,2}日", "", cleaned)
    cleaned = re.sub(r"前\s*\d+\s*条|前\s*\d+\s*个|前\s*\d+\s*名", "", cleaned)

    # Remove common suffixes that contain 线 but are not line names
    cleaned = re.sub(r"(线路|多条线路|前三条线路|故障线路|的线路|这些线路)", "", cleaned)

    matches = re.findall(r"([0-9A-Za-z一-龥ⅠⅡ]{1,15}线)", cleaned)
    if matches:
        candidate = matches[-1].strip()
        if (
            candidate
            and candidate != "线"
            and len(candidate) >= 2
            # X号线：词干须含非数字（程木1号线/黄金2号线 是线路；106号线 按杆塔号场景排除）
            and (not candidate.endswith("号线") or re.search(r"\D", candidate[:-2]))
        ):
            return candidate

    # XX直流 / XX直流联络线 写法，排除“特高压直流”等泛指
    for cand in reversed(re.findall(r"([^\d\s]{2,10}直流(?:联络线)?)", cleaned)):
        if any(g in cand for g in ("特高压", "超高压", "高压", "柔性", "输电", "线路", "系统", "工程", "通道", "换流")):
            continue
        return cand
    return None


def _extract_line(text: str) -> Optional[str]:
    """Extract line name and normalize to canonical form."""
    return canonicalize_line_name(_extract_line_raw(text))


# 电压等级数字清单（与 config.VOLTAGE_PATTERNS 对应，长者优先）
_VOLTAGE_NUMBERS = ("1100", "1000", "800", "750", "500", "400", "330", "320", "220", "110")


def find_bare_voltage_number(text: str) -> Optional[str]:
    """检测文本中"裸"电压等级数字（无单位上下文），供反问消歧使用。

    命中条件：出现电压清单数字，且
    - 前面不是数字、# 或 ±（排除 1800、#800、±800）
    - 后面不是数字，也不是 kV/KV/kv/千伏/线路/MW/号/塔/杆
      （排除 800kV、800千伏、800线路、800MW、800号塔 等明确用法）
    返回命中的数字字符串；无命中返回 None。
    """
    pattern = (
        r"(?<![\d#±])(" + "|".join(_VOLTAGE_NUMBERS) + r")"
        r"(?!\d)(?!\s*(?:[kK][vV]|千伏|线路|MW|号|塔|杆))"
    )
    m = re.search(pattern, text)
    return m.group(1) if m else None


# 掩码占位符：用虚构专有名词感的"甲乙线"而非"某线"——"某线"与泛化的
# "线路"在嵌入空间语义过近，多设备的"省份+线路+故障类型"问法会被单线
# 例句假相似吸走（2026-08-06 实测 60/120 误入 single_line）。"甲乙线"
# 让单线查询与单线例句掩码后逐字相同（恒 1.0 配准），同时与"线路"拉开
# 距离（完整句式 60/120 → 120/120）。仅用于路由嵌入，不出现在回答中。
MASK_LINE = "甲乙线"
MASK_TOWER = "某号塔"


def mask_line_tower(text: str) -> str:
    """把开放词汇（线路名、杆塔号）替换为占位符。

    供语义路由在向量化前剔除词面差异，使相似度比较句式结构/意图，
    而非线路名词汇（188+ 个线路名无法枚举进例句）。
    """
    masked = text
    raw_line = _extract_line_raw(text)
    if raw_line:
        masked = masked.replace(raw_line, MASK_LINE, 1)
    # 抹除年份区间/ISO 日期/月份区间，防止被杆塔区间掩码误吞
    # （"2025年3-8月"曾被误掩码为"2025年某号塔月"，导致线路级问题误入杆塔技能）
    work = re.sub(r"\d{4}年?\s*[-—~～至到]\s*\d{4}年?", " ", masked)
    work = re.sub(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", " ", work)
    work = re.sub(r"\d{1,2}\s*月?\s*[-—~～至到]\s*\d{1,2}\s*月", " ", work)
    # 杆塔号：区间优先，再单塔（#106 / 106号塔 / 106号杆塔 / 106杆）；杆塔/塔杆整体匹配避免残留
    masked = re.sub(r"\d+\s*[-～]\s*\d+\s*号?(?:杆塔|塔杆|塔|杆)?", MASK_TOWER, work)
    masked = re.sub(r"#\s*\d+|\d+\s*号?(?:杆塔|塔杆|塔|杆)", MASK_TOWER, masked)
    return masked


def _extract_tower(text: str) -> Optional[str]:
    """Extract tower number or range."""
    # 工作副本：抹除年份区间/ISO 日期/月份区间/年份单点，
    # 防止"数字-数字"被杆塔区间正则误吞（"3-8月"→误作3-8号；
    # "2911号塔2023-2025年"中的年份区间会顶替真杆塔2911）
    work = re.sub(r"\d{4}年?\s*[-—~～至到]\s*\d{4}年?", " ", text)
    work = re.sub(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", " ", work)
    work = re.sub(r"\d{1,2}\s*月?\s*[-—~～至到]\s*\d{1,2}\s*月", " ", work)
    work = re.sub(r"\d{4}年", " ", work)

    # Range first（逐个匹配取首个合法区间；1900-2100 起始值视为年份残留，拒绝）
    for m in re.finditer(r"(\d+)\s*[-～]\s*(\d+)\s*号?[塔杆]?", work):
        start, end = int(m.group(1)), int(m.group(2))
        if 1 <= start < 10000 and 1 <= end < 10000 and not (1900 <= start <= 2100):
            return f"{start}-{end}号"

    # Single
    for m in re.finditer(r"(\d+)\s*号?[塔杆]", work):
        num = int(m.group(1))
        if 1 <= num < 10000 and not (1900 <= num <= 2100):
            return f"{num}号"

    # "X号"（号后无塔/杆，问题 5）：排除"月X号"日期语境与"X号线"线路名语境
    for m in re.finditer(r"(?<!月)(\d+)\s*号(?![塔杆线])", work):
        num = int(m.group(1))
        if 1 <= num < 10000 and not (1900 <= num <= 2100):
            return f"{num}号"

    # 106# style (hash suffix, e.g. "2911#2024年")
    m = re.search(r"(\d+)\s*#", work)
    if m:
        num = int(m.group(1))
        if 1 <= num < 10000 and not (1900 <= num <= 2100):
            return f"{num}号"

    # #106 style
    m = re.search(r"#\s*(\d+)", work)
    if m:
        num = int(m.group(1))
        if 1 <= num < 10000 and not (1900 <= num <= 2100):
            return f"{num}号"

    return None


def _extract_fault_type(text: str) -> Optional[str]:
    """Extract fault type from text."""
    for ft in FAULT_TYPES:
        if ft in text:
            return ft
    # 绕击/反击/雷害归一为雷击（与 metadata 侧同义词规则一致；
    # 绕击/反击细分由事件卡承担，不作为独立查询标签）
    if "绕击" in text or "反击" in text or "雷害" in text:
        return "雷击"
    if "异物" in text:
        return "异物短路"
    if "鸟粪" in text or "鸟害" in text:
        return "鸟害"
    # 覆冰是用户对冰类故障的统称（用户 2026-08-06 定调）：返回特殊标记，
    # 由 retriever 展开为 [冰害, 冰闪, 脱冰跳跃, 雪闪] 四标签多值过滤；
    # 与雷击"多措辞合并单标签"方向相反——这里是"单措辞映射标签集合"
    if "覆冰" in text:
        return "覆冰"
    if "冰害" in text or "冰闪" in text:
        return "冰害"
    if "烟火" in text or "山火" in text:
        return "山火"
    if "断线" in text:
        return "断线"
    return None


def _extract_top_n(text: str) -> Optional[int]:
    """Extract top-N number."""
    m = re.search(r"前\s*(\d+)\s*条|前\s*(\d+)\s*个|前\s*(\d+)\s*名|top\s*(\d+)", text, re.IGNORECASE)
    if m:
        for g in m.groups():
            if g:
                return int(g)
    # Chinese numbers
    cn_numbers = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    m = re.search(r"前([一二三四五六七八九十])", text)
    if m:
        return cn_numbers.get(m.group(1))
    return None


def _extract_exclude_lines(text: str) -> list[str]:
    """Extract excluded lines like '除了泰吴线'."""
    lines = []
    for m in re.finditer(r"除了([^\d\s]{1,15}线)", text):
        line = m.group(1).strip()
        if line and line != "线":
            lines.append(line)
    return lines


def _extract_compare_items(text: str) -> list[str]:
    """Extract comparison items joined by 和/与/及/、.

    Supports paired years, provinces, lines, fault types.
    Returns a list of raw item strings.
    """
    # Remove common noise
    cleaned = re.sub(r"(?:哪个更多|哪个更少|对比|比较|数量|情况|哪些)", "", text)

    # Try multiple patterns in order of specificity
    patterns = [
        # Two line names: X线和Y线...
        r"([^\d\s]{1,15}(?:线|路|直流|柔直|回))(?:和|与|及|、)([^\d\s]{1,15}(?:线|路|直流|柔直|回))",
        # Two years: 2024年和2025年...
        r"(\d{4}年?)(?:和|与|及|、)(\d{4}年?)",
        # Two provinces: 江苏和浙江
        r"([^\d\s]{1,10}(?:省|市)?)(?:和|与|及|、)([^\d\s]{1,10}(?:省|市)?)",
        # Generic fallback
        r"([^和与及、]{1,15})(?:和|与|及|、)([^和与及、]{1,15})",
    ]

    for pattern in patterns:
        m = re.search(pattern, cleaned)
        if m:
            return [m.group(1).strip(), m.group(2).strip()]
    return []


def _build_compare_queries(query: Query) -> list[Query]:
    """Split a compare_stats query into two side queries.

    Currently supports:
    - paired fault types (e.g., 雷击和风偏)
    - paired years (e.g., 2024和2025年)
    - paired provinces (e.g., 湖北和浙江)
    - paired lines (e.g., 泰吴线和武宗Ⅰ线)
    """
    items = _extract_compare_items(query.raw)
    if len(items) < 2:
        return [query]

    left = Query(
        raw=query.raw,
        years=query.years.copy(),
        quarters=query.quarters.copy(),
        months=query.months.copy(),
        dates=query.dates.copy(),
        province=query.province,
        voltage=query.voltage,
        line=query.line,
        tower=query.tower,
        fault_type=query.fault_type,
        top_n=query.top_n,
        exclude_lines=query.exclude_lines.copy(),
    )
    right = Query(
        raw=query.raw,
        years=query.years.copy(),
        quarters=query.quarters.copy(),
        months=query.months.copy(),
        dates=query.dates.copy(),
        province=query.province,
        voltage=query.voltage,
        line=query.line,
        tower=query.tower,
        fault_type=query.fault_type,
        top_n=query.top_n,
        exclude_lines=query.exclude_lines.copy(),
    )

    # Determine what is being compared and assign to each side
    def _is_year(s: str) -> bool:
        return bool(re.match(r"^\d{4}年?$", s))

    def _is_province(s: str) -> bool:
        return s in PROVINCE_ALIASES

    def _is_fault_type(s: str) -> bool:
        return s in FAULT_TYPES or s in {"异物", "鸟粪", "火灾", "雷害", "反击", "绕击", "覆冰"}

    def _is_line(s: str) -> bool:
        return s.endswith(("线", "路", "直流", "柔直", "回")) and len(s) >= 2

    for idx, item in enumerate(items):
        target = left if idx == 0 else right
        if _is_year(item):
            year = int(re.match(r"(\d{4})", item).group(1))
            target.years = [year]
        elif _is_province(item):
            target.province = item
        elif _is_fault_type(item):
            # 绕击/反击/雷害归一为雷击，避免按库中不存在的标签过滤（必返 0）
            target.fault_type = "雷击" if item in {"绕击", "反击", "雷害"} else item
        elif _is_line(item):
            target.line = item
        else:
            # Fallback: try to interpret as fault type if contains known keyword
            for ft in FAULT_TYPES:
                if ft in item:
                    target.fault_type = ft
                    break

    return [left, right]


def parse_query(text: str) -> Query:
    """Parse a natural language question into structured Query."""
    years, is_range = _extract_years(text)
    # “历年/各年/所有年份/全部年份”表示查询全部年份，不加年份过滤；
    # 仅在没有显式年份时生效（如“2023年至2025年”仍走范围逻辑）
    all_years = not years and bool(re.search(r"历年|各年|所有年份|全部年份", text))
    query = Query(
        raw=text,
        years=years,
        is_range_year=is_range,
        all_years=all_years,
        quarters=_extract_quarters(text),
        months=_extract_months(text),
        dates=_extract_dates(text),
        province=_extract_province(text),
        voltage=_extract_voltage(text),
        line=_extract_line(text),
        tower=_extract_tower(text),
        fault_type=_extract_fault_type(text),
        top_n=_extract_top_n(text),
        exclude_lines=_extract_exclude_lines(text),
        compare_items=_extract_compare_items(text),
    )
    return query
