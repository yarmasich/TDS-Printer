"""Cable / label text search — ported verbatim from the CLI parser
(`utils/cable_search.py` + `parse_batch_query` from the main script).

Numeric queries match cable IDs inside cells. The ID always follows a
``#``, but the prefix varies by cable type — ``CBL#1.1`` (fiber),
``CAT6 #1.1``, ``LC #1.1``, ``MPO #1.1`` — so we anchor on ``#`` rather
than any one prefix. Non-numeric queries are plain substring match
(case-insensitive).
"""
from __future__ import annotations

import re
from typing import List, Tuple


def cable_query_pattern(query: str) -> re.Pattern:
    query = query.strip()
    is_num = bool(re.fullmatch(r"\d+(\.\d+)?", query))

    if not is_num:
        return re.compile(re.escape(query), re.I)

    if "." in query:
        return re.compile(
            rf"#\s*(\||)\s*(?<!\d){re.escape(query)}(?!\d)",
            re.I,
        )
    return re.compile(
        rf"#\s*(\||)(?<!\d)\s*{re.escape(query)}(\D|$)",
        re.I,
    )


def parse_batch_query(query: str) -> List[str]:
    """Expand range / list syntax into individual queries.

    Examples
    --------
    ``"45.5-7"``  → ``["45.5", "45.6", "45.7"]``
    ``"45.5,6,7"`` → ``["45.5", "45.6", "45.7"]``
    ``"65"``      → ``["65"]``
    """
    query = query.strip()

    range_match = re.match(r"^(\d+)\.(\d+)-(\d+)$", query)
    if range_match:
        base = range_match.group(1)
        start = int(range_match.group(2))
        end = int(range_match.group(3))
        if start <= end:
            return [f"{base}.{i}" for i in range(start, end + 1)]

    list_match = re.match(r"^(\d+)\.(\d+)(,[\d,]+)$", query)
    if list_match:
        base = list_match.group(1)
        first = list_match.group(2)
        rest = list_match.group(3)
        numbers = [first] + [n.strip() for n in rest.split(",") if n.strip()]
        return [f"{base}.{n}" for n in numbers]

    return [query]


def validate_query(query: str) -> Tuple[bool, str]:
    """Light normalisation: trim, replace spaces and commas in numeric forms.

    Returns ``(valid, normalised_query)``. Mirrors the CLI's
    ``validate_cable_number`` but accepts short text too.
    """
    query = query.strip().replace(" ", "").replace(",", ".") if " " in query else query.strip()
    if re.fullmatch(r"\d+(\.\d+)?", query):
        return True, query
    if len(query) >= 2:
        return True, query
    return False, query
