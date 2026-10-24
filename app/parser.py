"""Turns the text boxes read from an identity document into structured fields.

Pure functions only: no OCR and no I/O, so every rule is unit-tested with hand-placed boxes.
A value is found where it is printed: inside its label's box, or the nearest box that follows
the label (to its right, then below), or the one above it when nothing valid follows.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from .layout import Direction, TextBox, neighbours, rows
from .mrz import parse_mrz

_MONTHS = {
    "ENE": 1, "JAN": 1, "FEB": 2, "MAR": 3, "ABR": 4, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "AUG": 8, "SEP": 9, "SET": 9, "OCT": 10, "NOV": 11, "DIC": 12, "DEC": 12,
}  # fmt: skip

_NUMERIC_DATE = re.compile(r"\b(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})\b")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_TEXT_DATE = re.compile(r"\b(\d{1,2})[\s/.\-]+([A-Z]{3})[A-Z]*[\s/.\-]+(\d{4})\b")
_MIN_BIRTH_YEAR = 1900


def _label(alternatives: str) -> re.Pattern[str]:
    """A label at the start of a box; a letter right after it means a longer, different word."""
    return re.compile(rf"^(?:{alternatives})(?![A-Z])")


_SURNAME = r"(?:PRIMER\s+|SEGUNDO\s+)?APELLIDOS?|SURNAMES?|LAST\s+NAMES?"
_GIVEN = r"NOMBRES?|PRENOMBRES?|GIVEN\s+NAMES?|FIRST\s+NAMES?"
_BIRTH = r"(?:F\.?|FECHA\s+DE)\s*NACIMIENTO|NACIMIENTO|FECHA\s+DE\s+NAC\.?|DATE\s+OF\s+BIRTH|BIRTH\s*DATE|DOB"
_NUMBER = (
    r"(?:DOCUMENTO|DOCUMENT|PASAPORTE|PASSPORT|CEDULA)\s+(?:N[O°º]|NRO|NUM(?:ERO)?)\.?"
    r"|NUI|DNI|NIE|ID|C\.?\s?I\.?|N[O°º]\.?|NRO\.?|NUM(?:ERO)?\.?"
)
# Printed beside the identity fields; a box starting with one of these is never a value
_OTHER = (
    r"NACIONALIDAD|NATIONALITY|SEXO|SEX|LUGAR|FECHA|(?:F\.?\s*)?(?:EXPEDICION|VENCIMIENTO|EMISION)|"
    r"(?:EDO\.?|ESTADO)\s*CIVIL|FIRMA|SIGNATURE|DOMICILIO|DIRECCION|EXPIRY|CONDICION|PROFESION|AUTOIDENTIFICACION"
)

_SURNAME_LABEL = _label(_SURNAME)
_GIVEN_LABEL = _label(_GIVEN)
_BIRTH_LABEL = _label(_BIRTH)
_NUMBER_LABEL = _label(_NUMBER)
_ANY_LABEL = _label("|".join((_SURNAME, _GIVEN, _BIRTH, _NUMBER, _OTHER)))
# Bilingual cards print "APELLIDOS / SURNAMES": every label and separator before the value is skipped
_LABEL_RUN = re.compile(rf"^(?:(?:{'|'.join((_SURNAME, _GIVEN, _BIRTH, _NUMBER))})(?![A-Z])[\s:/.|\-]*)+")

_NAME_WORD = re.compile(r"[A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ'\-]*", re.IGNORECASE)
# Venezuelan style: a nationality letter and the number, usually grouped with dots ("V 12.345.678")
_NATIONAL_ID = re.compile(r"\b([VE])\s*[-.]?\s*(\d{1,3}(?:\.\d{3}){1,2}|\d{6,9})\b")
_LABELLED_NUMBER = re.compile(r"^(?:([VEJGP])\s*[-.]?\s*)?(\d[\d.,\s]{4,14}\d(?:-\d)?[A-Z]?)$")
# Passport numbers mix letters and digits ("L898902C3"); only trusted right after a label
_ALPHANUMERIC_NUMBER = re.compile(r"^(?=(?:[A-Z]*\d){3})[A-Z0-9]{6,12}$")


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


def _fold_char(char: str) -> str:
    base = "".join(part for part in unicodedata.normalize("NFD", char.upper()) if unicodedata.category(part) != "Mn")
    return base if len(base) == 1 else char


def fold(text: str) -> str:
    """Upper-cases and strips accents one character at a time, so offsets still match the original text."""
    return "".join(_fold_char(char) for char in unicodedata.normalize("NFC", text))


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
        if month := _MONTHS.get(month_name):
            found.append(_make_date(int(year), month, int(day), today))
    return [parsed for parsed in found if parsed is not None]


def _read_name(text: str) -> str | None:
    """Every word must be written like a name; anything else means the box is not a name."""
    words = [word.strip(".,;:") for word in text.split()]
    if not words or not all(_NAME_WORD.fullmatch(word) for word in words) or len("".join(words)) < 2:
        return None
    return " ".join(words)


def _normalize_number(prefix: str | None, digits: str) -> str:
    compact = re.sub(r"[.,\s]", "", digits)
    return f"{prefix}-{compact}" if prefix else compact


def _read_labelled_number(text: str) -> str | None:
    folded = fold(text).strip()
    if match := _LABELLED_NUMBER.match(folded):
        return _normalize_number(match.group(1), match.group(2))
    return folded if _ALPHANUMERIC_NUMBER.match(folded) else None


def _is_label(box: TextBox) -> bool:
    return _ANY_LABEL.match(fold(box.text).strip()) is not None


@dataclass(frozen=True)
class _Found[T]:
    value: T
    box: TextBox
    direction: Direction | None


def _beside[T](label: TextBox, boxes: list[TextBox], read: Callable[[str], T | None]) -> _Found[T] | None:
    """The nearest valid value following the label (right, then below), else the one above it."""
    for direction in Direction:
        for other in neighbours(label, boxes, direction):
            if not _is_label(other) and (value := read(other.text)) is not None:
                return _Found(value, other, direction)
    return None


def _labelled[T](boxes: list[TextBox], label: re.Pattern[str], read: Callable[[str], T | None]) -> _Found[T] | None:
    """The first value printed with the label: inside the label's own box, or beside it."""
    for box in boxes:
        text = unicodedata.normalize("NFC", box.text).strip()
        folded = fold(text)
        if not label.match(folded):
            continue
        labels = _LABEL_RUN.match(folded)
        rest = text[labels.end() :] if labels else ""
        if rest and (value := read(rest)) is not None:
            return _Found(value, box, None)
        if found := _beside(box, boxes, read):
            return found
    return None


def _labelled_name(boxes: list[TextBox], label: re.Pattern[str]) -> str | None:
    found = _labelled(boxes, label, _read_name)
    if found is None:
        return None
    words = [found.value]
    # A long name wraps onto the next line, or the engine splits it into several boxes along the line
    continuation = Direction.RIGHT if found.direction in (None, Direction.RIGHT) else found.direction
    current = found.box
    while (
        (following := next(neighbours(current, boxes, continuation), None))
        and not _is_label(following)
        and (more := _read_name(following.text))
    ):
        words.append(more)
        current = following
    return " ".join(words).title()


def _document_number(boxes: list[TextBox]) -> str | None:
    if found := _labelled(boxes, _NUMBER_LABEL, _read_labelled_number):
        return found.value
    for line in rows(boxes):
        if match := _NATIONAL_ID.search(fold(" ".join(box.text for box in line))):
            return _normalize_number(match.group(1), match.group(2))
    return None


def _birth_date(boxes: list[TextBox], today: date) -> date | None:
    def read(text: str) -> date | None:
        return next(iter(find_dates(text, today)), None)

    found = _labelled(boxes, _BIRTH_LABEL, read)
    return found.value if found else None


def parse_document(boxes: list[TextBox], today: date | None = None) -> ExtractedFields:
    """Extracts the identity fields from the boxes of one read. Any field it cannot find is None."""
    today = today or date.today()
    boxes = [box for box in boxes if box.text.strip()]
    if not boxes:
        return ExtractedFields()

    # The machine-readable zone is parsed on its own; as plain text its digits would look like numbers and dates
    printed = [box for box in boxes if "<<" not in box.text]
    labelled = ExtractedFields(
        first_name=_labelled_name(printed, _GIVEN_LABEL),
        last_name=_labelled_name(printed, _SURNAME_LABEL),
        document_number=_document_number(printed),
        birth_date=_birth_date(printed, today),
    )
    mrz = parse_mrz(["".join(box.text for box in line) for line in rows(boxes)], today)
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
