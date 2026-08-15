"""私有文档的按需事实提取；结果仅返回 owner，不写数据库。"""

from __future__ import annotations

import re

from app.schemas.actions import DocumentParsedFact

_FIELD_LABELS = {
    "name": "姓名",
    "email": "邮箱",
    "phone": "电话",
    "dept": "院系",
    "grade": "年级",
    "gpa": "GPA",
    "research_interest": "研究兴趣",
    "research_experience": "科研经历",
    "interest_tags": "兴趣标签",
    "awards": "奖项",
    "positions": "职务",
}


def _clean(value: str, limit: int = 800) -> str:
    return re.sub(r"\s+", " ", value).strip(" ：:;；,，")[:limit]


def _fact(field: str, value: str | list[str], excerpt: str) -> DocumentParsedFact:
    return DocumentParsedFact(
        field=field,
        label=_FIELD_LABELS[field],
        value=value,
        source_excerpt=_clean(excerpt, 300),
    )


def _labelled_value(lines: list[str], labels: tuple[str, ...], limit: int) -> tuple[str, str] | None:
    alternatives = "|".join(re.escape(label) for label in labels)
    pattern = re.compile(rf"^(?:{alternatives})\s*[：:]\s*(.+)$", re.IGNORECASE)
    for line in lines:
        match = pattern.match(line)
        if match:
            value = _clean(match.group(1), limit)
            if value:
                return value, line
    return None


def _list_value(
    lines: list[str],
    labels: tuple[str, ...],
) -> tuple[list[str], str] | None:
    alternatives = "|".join(re.escape(label) for label in labels)
    pattern = re.compile(rf"^(?:{alternatives})\s*[：:]\s*(.*)$", re.IGNORECASE)
    header_pattern = re.compile(r"^[\w\u4e00-\u9fff ]{1,30}\s*[：:]", re.IGNORECASE)
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        values: list[str] = []
        inline = _clean(match.group(1), 600)
        if inline:
            values.extend(
                _clean(item, 120)
                for item in re.split(r"[、;；|]", inline)
                if _clean(item, 120)
            )
        cursor = index + 1
        while not inline and cursor < len(lines) and len(values) < 12:
            candidate = lines[cursor]
            if header_pattern.match(candidate):
                break
            values.append(_clean(candidate, 120))
            cursor += 1
        values = [item for item in values if item][:12]
        if values:
            excerpt = " ".join([line, *lines[index + 1 : cursor]])
            return values, excerpt
    return None


def extract_profile_facts(text: str) -> list[DocumentParsedFact]:
    """保守提取明确标注的事实；不猜测、不补写缺失信息。"""

    lines = [_clean(line, 1200) for line in text.splitlines()]
    lines = [line for line in lines if line]
    facts: list[DocumentParsedFact] = []

    labelled_fields = (
        ("name", ("姓名", "Name"), 60),
        ("dept", ("院系", "学院", "系所", "Department"), 120),
        ("grade", ("年级", "入学年份", "Grade"), 40),
        ("gpa", ("GPA", "平均绩点", "绩点"), 24),
        ("research_interest", ("研究兴趣", "研究方向", "Research Interests"), 600),
        ("research_experience", ("科研经历", "研究经历", "Research Experience"), 800),
    )
    for field, labels, limit in labelled_fields:
        result = _labelled_value(lines, labels, limit)
        if result:
            facts.append(_fact(field, result[0], result[1]))

    for field, labels in (
        ("awards", ("奖项", "荣誉奖项", "Awards")),
        ("positions", ("职务", "学生工作", "Positions")),
    ):
        result = _list_value(lines, labels)
        if result:
            facts.append(_fact(field, result[0], result[1]))

    joined = "\n".join(lines)
    email_match = re.search(r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])", joined, re.IGNORECASE)
    if email_match:
        facts.append(_fact("email", email_match.group(0), email_match.group(0)))

    phone_match = re.search(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)", joined)
    if phone_match:
        phone = re.sub(r"\D", "", phone_match.group(0))
        if phone.startswith("86") and len(phone) == 13:
            phone = phone[2:]
        facts.append(_fact("phone", phone, phone_match.group(0)))

    interest = next((item for item in facts if item.field == "research_interest"), None)
    if interest and isinstance(interest.value, str):
        tags = [
            _clean(item, 20)
            for item in re.split(r"[、,，;；/|]", interest.value)
            if _clean(item, 20)
        ][:8]
        if len(tags) > 1:
            facts.append(_fact("interest_tags", tags, interest.source_excerpt))

    # 保持字段唯一与稳定顺序，避免同一联系方式在多处出现时制造冲突。
    unique: dict[str, DocumentParsedFact] = {}
    for item in facts:
        unique.setdefault(item.field, item)
    return list(unique.values())
