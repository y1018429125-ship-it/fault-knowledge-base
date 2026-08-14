"""Post-processing for generated answers."""

import re


def normalize_tower_format(text: str) -> str:
    """Normalize tower number representations to 'X号' or 'X-Y号'.

    Handles:
    - #106 -> 106号
    - 106# -> 106号
    - 106号塔 -> 106号
    - 106#塔 -> 106号
    - 106-110号塔 -> 106-110号

    Avoids modifying dates like 2026-06-30.
    """
    # Single towers near 号/塔/#; require digit immediately after # so
    # markdown headings like '## 1.' are not mistaken for tower refs
    text = re.sub(r"#(\d{1,4})\s*号?[塔杆]?", r"\1号", text)
    text = re.sub(r"(\d{1,4})\s*#\s*号?[塔杆]?", r"\1号", text)
    text = re.sub(r"(\d{1,4})\s*号[塔杆]", r"\1号", text)
    text = re.sub(r"(\d{1,4})\s*#[塔杆]", r"\1号", text)

    # Range towers: only when followed by 号/塔 or when numbers look like towers
    text = re.sub(
        r"(?<!\d{4}-)(\d{1,4})\s*[-～]\s*(\d{1,4})\s*#?\s*号[塔杆]?",
        r"\1-\2号",
        text,
    )
    return text


def highlight_tower(text: str, tower: str | None) -> str:
    """Bold the queried tower number in the answer."""
    if not tower:
        return text

    # Extract numeric part
    m = re.search(r"(\d+(?:-\d+)?)", tower)
    if not m:
        return text

    number = m.group(1)
    # Avoid double-bold
    pattern = rf"(?<![\*\d])({re.escape(number)}\s*#?\s*号?)(?![\*\d])"
    return re.sub(pattern, r"**\1**", text)


def postprocess_answer(text: str, tower: str | None = None) -> str:
    """Apply all post-processing to generated answer."""
    text = normalize_tower_format(text)
    if tower:
        text = highlight_tower(text, tower)
    return text
