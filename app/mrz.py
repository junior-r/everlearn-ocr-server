"""Machine-readable zone (MRZ) parsing for passports (TD3) and ID cards (TD1).

The MRZ is the most reliable part of a document to read: it uses a fixed font
and layout, and carries check digits that tell a correct read from a wrong one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_WEIGHTS = (7, 3, 1)
_MRZ_LINE = re.compile(r"^[A-Z0-9<]{28,46}$")
# OCR engines often read the filler "<" as these characters
_FILLER_LOOKALIKES = str.maketrans({"«": "<", "‹": "<", "(": "<", "{": "<", "[": "<"})


@dataclass(frozen=True)
class MrzData:
    first_name: str
    last_name: str
    document_number: str
    birth_date: date | None
    # True when every check digit matched, i.e. the read can be trusted
    verified: bool


def _char_value(char: str) -> int:
    if char.isdigit():
        return int(char)
    if char.isalpha():
        return ord(char) - ord("A") + 10
    return 0


def check_digit(field: str) -> str:
    """ICAO 9303 check digit of a field: weighted sum (7, 3, 1) modulo 10."""
    total = sum(_char_value(char) * _WEIGHTS[index % 3] for index, char in enumerate(field))
    return str(total % 10)


def _birth_date(yymmdd: str, today: date) -> date | None:
    if not yymmdd.isdigit():
        return None
    year, month, day = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    # Two-digit years: a birth date cannot be in the future
    century = 2000 if year <= today.year % 100 else 1900
    try:
        return date(century + year, month, day)
    except ValueError:
        return None


def _names(field: str) -> tuple[str, str]:
    surname, _, given = field.partition("<<")
    clean = lambda part: " ".join(part.replace("<", " ").split()).title()  # noqa: E731
    return clean(given), clean(surname)


def _candidate_lines(lines: list[str]) -> list[str]:
    candidates = []
    for line in lines:
        compact = line.upper().translate(_FILLER_LOOKALIKES).replace(" ", "")
        if _MRZ_LINE.match(compact) and compact.count("<") >= 2:
            candidates.append(compact)
    return candidates


def _parse_td3(first: str, second: str, today: date) -> MrzData | None:
    """Passport: two lines of 44 characters."""
    if not first.startswith("P") or len(second) < 28:
        return None
    first_name, last_name = _names(first[5:])
    number, number_check = second[0:9], second[9:10]
    birth, birth_check = second[13:19], second[19:20]
    return MrzData(
        first_name=first_name,
        last_name=last_name,
        document_number=number.replace("<", ""),
        birth_date=_birth_date(birth, today),
        verified=check_digit(number) == number_check and check_digit(birth) == birth_check,
    )


def _parse_td1(first: str, second: str, third: str, today: date) -> MrzData | None:
    """ID card: three lines of 30 characters."""
    if len(first) < 15 or len(second) < 7:
        return None
    number, number_check = first[5:14], first[14:15]
    birth, birth_check = second[0:6], second[6:7]
    first_name, last_name = _names(third)
    return MrzData(
        first_name=first_name,
        last_name=last_name,
        document_number=number.replace("<", ""),
        birth_date=_birth_date(birth, today),
        verified=check_digit(number) == number_check and check_digit(birth) == birth_check,
    )


def parse_mrz(lines: list[str], today: date | None = None) -> MrzData | None:
    """Finds and parses an MRZ among OCR text lines. Returns None when there is none."""
    today = today or date.today()
    candidates = _candidate_lines(lines)
    for index, line in enumerate(candidates):
        if line.startswith("P<") and index + 1 < len(candidates):
            parsed = _parse_td3(line, candidates[index + 1], today)
            if parsed:
                return parsed
    if len(candidates) >= 3 and all(len(line) <= 32 for line in candidates[-3:]):
        return _parse_td1(*candidates[-3:], today)
    return None
