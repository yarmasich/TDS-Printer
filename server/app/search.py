"""Cable ID and free-text search.

Numeric queries match cable markers (CBL, CAT6, LC, MPO) or a standalone
hash field, never unrelated LU/SU identifiers in the same label.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

MAX_QUERY_ITEMS = 5000
MAX_QUERY_LENGTH = 20000
# SQLite refuses an expression tree deeper than 1000 and the prefilter spends
# two LIKE clauses per token, so larger batches scan as they did before.
MAX_PREFILTER_TERMS = 256


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
            rf"{marker}{base}(?:\.\d+)?(?![\w.-])",
            re.I,
        )

    is_num = bool(re.fullmatch(r"\d+(\.\d+)?", query))

    if not is_num:
        return re.compile(re.escape(query), re.I)

    # Exact numeric IDs must end before a field separator, not another part
    # of the identifier: #8 differs from #8.1, #8-B, #8A and #8_B.
    return re.compile(
        rf"{marker}{re.escape(query)}(?![\w.-])",
        re.I,
    )


# ``re.I`` folds these onto characters SQLite's ASCII-only lower() leaves
# alone (k↔U+212A, s↔U+017F, i↔U+0131), as it does every non-ASCII letter.
# LIKE's single-character wildcard covers them instead of missing a row.
_LIKE_ANY_CHAR = re.compile(r"[IiKkSs]|[^\x00-\x7f]")


def like_prefilter(query: str) -> str:
    """LIKE pattern for a substring every ``cable_query_pattern`` match holds.

    Lets SQL drop rows the regex could never match, which is what keeps a
    search off the whole label table. Deliberately a superset — the regex
    still decides each hit — so a whole-group query like ``20.*`` contributes
    only its base, matching both ``#20`` and ``#20.1``.
    """
    query = query.strip()
    group = re.fullmatch(r"(\d+)\.\*?", query)
    if group:
        query = group.group(1)
    for char in ("\\", "%", "_"):
        query = query.replace(char, "\\" + char)
    return "%" + _LIKE_ANY_CHAR.sub("_", query) + "%"


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
    expanded = _expand_list(query, max_items)
    # Digits and dashes that are not a cable list — a date, a port like 7-3 —
    # are what the operator typed, so search for them instead of failing.
    return expanded if expanded is not None else [query]


def _expand_list(query: str, max_items: int) -> Optional[List[str]]:
    """The expanded cable list/range, or ``None`` when it is not one.

    Only the item ceiling raises: it bounds allocation before the items exist,
    which a fallback to searching the text verbatim would defeat.
    """
    out: List[str] = []
    base = None
    for token in query.split(","):
        token = re.sub(r"\s+", "", token)
        match = re.fullmatch(r"(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?", token)
        if not match:
            return None
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
                return None
        lo, hi = int(minor), int(end)
        count = hi - lo + 1
        if count <= 0:
            return None
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
