"""Turns the text read from an identity document into structured fields.

Pure functions only: no OCR and no I/O, so every rule here is unit-tested with
plain strings. Rules are written for Spanish-language IDs (cédula, DNI) and for
passports, and fall back to patterns when a document has no recognisable labels.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from .mrz import parse_mrz

_MONTHS = {
    "ENE": 1, "JAN": 1, "FEB": 2, "MAR": 3, "ABR": 4, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "AUG": 8, "SEP": 9, "SET": 9, "OCT": 10, "NOV": 11, "DIC": 12, "DEC": 12,
}  # fmt: skip

_NUMERIC_DATE = re.compile(r"\b(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})\b")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_TEXT_DATE = re.compile(r"\b(\d{1,2})[\s/.\-]+([A-Z]{3})[A-Z]*[\s/.\-]+(\d{4})\b")

# "V-12.345.678", "V 12345678", "E-84.123.456": a nationality letter and a grouped number
_PREFIXED_NUMBER = re.compile(r"\b([VEJGP])\s*[-.]?\s*(\d{1,3}(?:[.,\s]?\d{3}){1,3})\b")
_GROUPED_NUMBER = re.compile(r"\b(\d{1,3}(?:[.,]\d{3}){1,3})\b")
_PLAIN_NUMBER = re.compile(r"\b(\d{6,10}[A-Z]?)\b")
# Passport numbers mix letters and digits ("L898902C3"); only trusted right after a label
_ALPHANUMERIC_NUMBER = re.compile(r"\b((?=[A-Z0-9]*\d[A-Z0-9]*\d[A-Z0-9]*\d)[A-Z0-9]{6,12})\b")

_SURNAME_LABEL = re.compile(r"\b(?:PRIMER\s+|SEGUNDO\s+)?(?:APELLIDOS?|SURNAMES?|LAST\s+NAMES?)\b")
_GIVEN_LABEL = re.compile(r"\b(?:GIVEN\s+NAMES?|FIRST\s+NAMES?|PRENOMBRES?|NOMBRES?)\b")
_NUMBER_LABEL = re.compile(
    r"\b(?:CEDULA|C\.?\s?I\.?|DNI|NIE|DOCUMENTO|IDENTIDAD|PASAPORTE|PASSPORT|NUMERO|NUM|NRO|NO)\b"
)
_BIRTH_LABEL = re.compile(r"\b(?:NACIMIENTO|NAC|BIRTH|DOB|NACIDO|NACIDA)\b")
_ANY_LABEL = re.compile(
    r"\b(?:APELLIDOS?|NOMBRES?|SURNAMES?|NAMES?|NACIMIENTO|NAC|BIRTH|CEDULA|DNI|DOCUMENTO|"
    r"IDENTIDAD|PASAPORTE|PASSPORT|NACIONALIDAD|NATIONALITY|SEXO|SEX|EXPEDICION|VENCIMIENTO|"
    r"EMISION|EXPIRY|FIRMA|ESTADO|REPUBLICA)\b"
)
_NAME_VALUE = re.compile(r"^[A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ' \-]{1,60}$", re.IGNORECASE)

_MIN_BIRTH_YEAR = 1900


@dataclass(frozen=True)
class ExtractedFields:
    first_name: str | None = None
    last_name: str | None = None
    document_number: str | None = None
    birth_date: date | None = None

    @property
    def found(self) -> int:
        return sum(value is not None for value in (
            self.first_name, self.last_name, self.document_number, self.birth_date,
        ))  # fmt: skip


def fold(text: str) -> str:
    """Upper-cases and strips accents, so labels match however the OCR read them."""
    decomposed = unicodedata.normalize("NFD", text.upper())
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def _make_date(year: int, month: int, day: int, today: date) -> date | None:
    try:
        parsed = date(year, month, day)
    except ValueError:
        return None
    return parsed if _MIN_BIRTH_YEAR <= year and parsed < today else None


def find_dates(text: str, today: date) -> list[date]:
    """Every plausible past date in the text, in day-month-year order as used on Spanish IDs."""
    folded = fold(text)
    found: list[date | None] = []
    for day, month, year in _NUMERIC_DATE.findall(folded):
        found.append(_make_date(int(year), int(month), int(day), today))
    for year, month, day in _ISO_DATE.findall(folded):
        found.append(_make_date(int(year), int(month), int(day), today))
    for day, month_name, year in _TEXT_DATE.findall(folded):
        month = _MONTHS.get(month_name)
        if month:
            found.append(_make_date(int(year), month, int(day), today))
    return [parsed for parsed in found if parsed is not None]


def _birth_date(lines: list[str], today: date) -> date | None:
    for index, line in enumerate(lines):
        if _BIRTH_LABEL.search(fold(line)):
            # The value is on the label's line or, on two-row layouts, the next one
            for candidate in (line, *lines[index + 1 : index + 2]):
                dates = find_dates(candidate, today)
                if dates:
                    return dates[0]
    # Without a label, the birth date is the earliest date: issue and expiry come later
    every = find_dates("\n".join(lines), today)
    return min(every) if every else None


def _normalize_number(prefix: str | None, digits: str) -> str:
    compact = re.sub(r"[.,\s]", "", digits)
    return f"{prefix}-{compact}" if prefix else compact


def _number_in(text: str) -> str | None:
    folded = fold(text)
    if match := _PREFIXED_NUMBER.search(folded):
        return _normalize_number(match.group(1), match.group(2))
    if match := _GROUPED_NUMBER.search(folded):
        return _normalize_number(None, match.group(1))
    if match := _PLAIN_NUMBER.search(folded):
        return match.group(1)
    return None


def _labelled_number_in(text: str) -> str | None:
    """The number following a label, where an alphanumeric code is also acceptable."""
    if number := _number_in(text):
        return number
    match = _ALPHANUMERIC_NUMBER.search(fold(text))
    return match.group(1) if match else None


def _document_number(lines: list[str]) -> str | None:
    # Dates look like numbers, so they are removed before searching
    without_dates = [
        _TEXT_DATE.sub(" ", _ISO_DATE.sub(" ", _NUMERIC_DATE.sub(" ", fold(line)))) for line in lines
    ]
    for index, line in enumerate(without_dates):
        if label := _NUMBER_LABEL.search(line):
            # Only what follows the label on its line, so the label itself is never the value
            for candidate in (line[label.end() :], *without_dates[index + 1 : index + 2]):
                if number := _labelled_number_in(candidate):
                    return number
    # No label: prefer the most specific shape anywhere on the document
    for pattern in (_PREFIXED_NUMBER, _GROUPED_NUMBER, _PLAIN_NUMBER):
        for line in without_dates:
            if match := pattern.search(line):
                groups = match.groups()
                prefix, digits = groups if len(groups) == 2 else (None, groups[0])
                return _normalize_number(prefix, digits)
    return None


def _clean_name(value: str) -> str | None:
    value = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ' \-]", " ", value)
    value = " ".join(value.split())
    if not _NAME_VALUE.match(value) or _ANY_LABEL.search(fold(value)):
        return None
    return value.title()


def _labelled_name(lines: list[str], label: re.Pattern[str]) -> str | None:
    for index, line in enumerate(lines):
        match = label.search(fold(line))
        if not match:
            continue
        # Same line, after the label and any separator ("NOMBRES: MARIA")
        same_line = _clean_name(line[match.end() :].lstrip(" :.-"))
        if same_line:
            return same_line
        if index + 1 < len(lines) and (next_line := _clean_name(lines[index + 1])):
            return next_line
    return None


def parse_document(text: str, today: date | None = None) -> ExtractedFields:
    """Extracts the identity fields from OCR text. Any field it cannot find is None."""
    today = today or date.today()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ExtractedFields()

    # The machine-readable zone is parsed on its own; as plain text its digits would look like numbers and dates
    printed = [line for line in lines if "<<" not in line]
    labelled = ExtractedFields(
        first_name=_labelled_name(printed, _GIVEN_LABEL),
        last_name=_labelled_name(printed, _SURNAME_LABEL),
        document_number=_document_number(printed),
        birth_date=_birth_date(printed, today),
    )
    mrz = parse_mrz(lines, today)
    if mrz is None:
        return labelled
    # A verified MRZ beats anything read from the printed labels; an unverified
    # one only fills the gaps, since a failed check digit means a misread character
    if mrz.verified:
        return ExtractedFields(
            first_name=mrz.first_name or labelled.first_name,
            last_name=mrz.last_name or labelled.last_name,
            document_number=mrz.document_number or labelled.document_number,
            birth_date=mrz.birth_date or labelled.birth_date,
        )
    return ExtractedFields(
        first_name=labelled.first_name or mrz.first_name or None,
        last_name=labelled.last_name or mrz.last_name or None,
        document_number=labelled.document_number or mrz.document_number or None,
        birth_date=labelled.birth_date or mrz.birth_date,
    )
