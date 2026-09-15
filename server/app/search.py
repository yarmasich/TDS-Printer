"""Cable ID and free-text search.

Numeric queries match cable markers (CBL, CAT6, LC, MPO) or a standalone
hash field, never unrelated LU/SU identifiers in the same label.
"""
from __future__ import annotations

import re
from typing import List, Tuple

MAX_QUERY_ITEMS = 5000
MAX_QUERY_LENGTH = 20000


def cable_query_pattern(query: str) -> re.Pattern:
    query = query.strip()
    # Bare # is supported only at the start of a field/line. Allowing any #
    # also matches LU#8 (or LU #8) on labels whose cable is e.g. CBL#50.1.
    marker = r"(?:(?<!\w)(?:CBL|CAT6|LC|MPO)\s*|(?:^|[|\n])\s*)#\s*\|?\s*"

    # Whole-group query: ``20.`` or ``20.*`` → the trunk ``#20`` *and* every
    # breakout ``#20.1`` … ``#20.18``. Use this when you want "all cables 20",
    # since a bare ``20`` matches only the single ``#20``.
    group = re.fullmatch(r"(\d+)\.\*?", query)
    if group:
        base = group.group(1)
        return re.compile(
            rf"{marker}{base}(?:\.\d+)?(?![\d.])",
            re.I,
        )

    is_num = bool(re.fullmatch(r"\d+(\.\d+)?", query))

    if not is_num:
        return re.compile(re.escape(query), re.I)

    if "." in query:
        return re.compile(
            rf"{marker}{re.escape(query)}(?![\d.])",
            re.I,
        )
    # Trailing ``(?![\d.])`` so a bare integer matches only the whole cable id
    # (``#1``) and not its decimal children (``#1.1`` … ``#1.18``) — the old
    # ``(\D|$)`` treated the dot as a boundary and over-matched.
    return re.compile(
        rf"{marker}{re.escape(query)}(?![\d.])",
        re.I,
    )


def parse_batch_query(query: str, *, max_items: int = MAX_QUERY_ITEMS) -> List[str]:
    """Expand numeric lists/ranges, bounding allocation before creating items.

    Both ``45.5,6,7`` and ``45.5,45.6,45.7`` are supported. A full range
    endpoint must share its starting cable's major number. Text is preserved.
    """
    query = query.strip()
    if len(query) > MAX_QUERY_LENGTH:
        raise ValueError(f"Query is too long (max {MAX_QUERY_LENGTH} characters)")
    if not re.fullmatch(r"[\d\s.,-]+", query) or not any(c in query for c in ",-"):
        return [query]

    out: List[str] = []
    base = None
    for token in query.split(","):
        token = re.sub(r"\s+", "", token)
        match = re.fullmatch(r"(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?", token)
        if not match:
            raise ValueError(f"Invalid cable list/range: {query!r}")
        start, end = match.groups()
        if "." in start:
            base, minor = start.split(".")
        elif base is not None:
            minor = start
            start = f"{base}.{minor}"
        else:
            minor = start
        if end is None:
            if len(out) >= max_items:
                raise ValueError(f"Too many queries (max {max_items})")
            out.append(start)
            continue
        if "." in end:
            end_base, end = end.split(".")
            if base != end_base:
                raise ValueError("Range endpoints must belong to the same cable group")
        lo, hi = int(minor), int(end)
        count = hi - lo + 1
        if count <= 0:
            raise ValueError("Range end must be greater than or equal to its start")
        if count > max_items - len(out):
            raise ValueError(f"Too many queries (max {max_items})")
        out.extend(f"{base}.{i}" if base is not None else str(i) for i in range(lo, hi + 1))
    return out


def validate_query(query: str) -> Tuple[bool, str]:
    """Light normalisation: trim, replace spaces and commas in numeric forms.

    Returns ``(valid, normalised_query)``. Mirrors the CLI's
    ``validate_cable_number`` but accepts short text too.
    """
    query = query.strip()
    if len(query) > MAX_QUERY_LENGTH:
        return False, query
    # Strip whitespace only in numeric forms, never in free-text phrases.
    compact = re.sub(r"\s+", "", query)
    if re.fullmatch(r"#?\d+(?:\.\d+|\.\*?)?", compact):
        query = compact.lstrip("#")
    if re.fullmatch(r"\d+(\.\d+)?", query):
        return True, query
    if re.fullmatch(r"\d+\.\*?", query):  # whole-group form: "20." / "20.*"
        return True, query
    if len(query) >= 2:
        return True, query
    return False, query
