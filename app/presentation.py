import re


def representative_display_name(value):
    """UI-only representative label; stored identity remains unchanged."""
    display_name = re.sub(
        r"^\s*ATANMAMI[ŞS]\s*(?:[·\-–—:]\s*)?",
        "",
        str(value or ""),
        flags=re.IGNORECASE,
    ).strip()

    # "901 DIYARBAKIR · DIYARBAKIR BOS" -> "901 DIYARBAKIR BOS"
    context, separator, vacancy_name = display_name.partition("·")
    region_code = re.match(r"^\s*(\d+)\b", context)
    if separator and region_code and vacancy_name.strip():
        return f"{region_code.group(1)} {vacancy_name.strip()}"
    return display_name
