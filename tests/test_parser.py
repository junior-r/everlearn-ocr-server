from datetime import date

import pytest

from app.mrz import check_digit, parse_mrz
from app.parser import ExtractedFields, find_dates, parse_document

TODAY = date(2026, 10, 10)

VENEZUELAN_CEDULA = """
REPÚBLICA BOLIVARIANA DE VENEZUELA
CÉDULA DE IDENTIDAD
V 12.345.678
APELLIDOS
GONZÁLEZ PÉREZ
NOMBRES
MARÍA FERNANDA
F. NACIMIENTO 14/03/2008   EDO. CIVIL SOLTERA
F. EXPEDICIÓN 02/05/2022
F. VENCIMIENTO 05/2032
VENEZOLANA
"""


def test_reads_a_venezuelan_cedula_with_values_under_their_labels():
    fields = parse_document(VENEZUELAN_CEDULA, TODAY)

    assert fields == ExtractedFields(
        first_name="María Fernanda",
        last_name="González Pérez",
        document_number="V-12345678",
        birth_date=date(2008, 3, 14),
    )


def test_reads_values_on_the_same_line_as_their_labels():
    text = """
    DOCUMENTO NACIONAL DE IDENTIDAD
    APELLIDOS: Hopper Murray
    NOMBRE: Grace Brewster
    DNI 87654321Z
    FECHA DE NACIMIENTO 09 DIC 1986
    """

    fields = parse_document(text, TODAY)

    assert fields.first_name == "Grace Brewster"
    assert fields.last_name == "Hopper Murray"
    assert fields.document_number == "87654321Z"
    assert fields.birth_date == date(1986, 12, 9)


def test_reads_english_labels():
    text = """
    Surname: TURING
    Given names: ALAN MATHISON
    Passport No: 123456789
    Date of birth: 23/06/1912
    """

    fields = parse_document(text, TODAY)

    assert (fields.first_name, fields.last_name) == ("Alan Mathison", "Turing")
    assert fields.document_number == "123456789"
    assert fields.birth_date == date(1912, 6, 23)


def test_takes_the_labelled_birth_date_even_when_an_earlier_date_is_printed():
    text = """
    LEY DEL 01/01/1990
    FECHA DE NACIMIENTO
    14-03-2008
    EXPEDICION 02-05-2022
    """

    assert parse_document(text, TODAY).birth_date == date(2008, 3, 14)


def test_without_a_label_the_birth_date_is_the_earliest_date():
    text = "MARIA 02/05/2022 14.03.2008 05/05/2032"

    assert parse_document(text, TODAY).birth_date == date(2008, 3, 14)


def test_a_date_is_never_mistaken_for_the_document_number():
    text = """
    NACIMIENTO 14/03/2008
    CEDULA 12.345.678
    """

    assert parse_document(text, TODAY).document_number == "12345678"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("V-12.345.678", "V-12345678"),
        ("V12345678", "V-12345678"),
        ("E 84.123.456", "E-84123456"),
        ("N° 1.234.567", "1234567"),
        ("ID 00123456", "00123456"),
    ],
)
def test_normalises_document_numbers(text, expected):
    assert parse_document(text, TODAY).document_number == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("14/03/2008", [date(2008, 3, 14)]),
        ("14-03-2008", [date(2008, 3, 14)]),
        ("14.03.2008", [date(2008, 3, 14)]),
        ("2008-03-14", [date(2008, 3, 14)]),
        ("14 MAR 2008", [date(2008, 3, 14)]),
        ("14 MARZO 2008", [date(2008, 3, 14)]),
        ("9 dic 1986", [date(1986, 12, 9)]),
        # Not real days, in the future, or implausibly old
        ("31/02/2008", []),
        ("14/13/2008", []),
        ("14/03/2030", []),
        ("14/03/1850", []),
    ],
)
def test_finds_dates_in_the_formats_ids_use(text, expected):
    assert find_dates(text, TODAY) == expected


def test_does_not_take_a_label_for_a_name():
    text = """
    APELLIDOS
    NOMBRES
    """

    fields = parse_document(text, TODAY)

    assert fields.last_name is None
    assert fields.first_name is None


@pytest.mark.parametrize("text", ["", "   \n  ", "@@@ ### !!!", "lorem ipsum dolor sit amet"])
def test_returns_nothing_rather_than_guessing_from_unreadable_text(text):
    fields = parse_document(text, TODAY)

    assert fields == ExtractedFields()
    assert fields.found == 0


# ICAO 9303 specimen passport
PASSPORT_MRZ = [
    "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<",
    "L898902C36UTO7408122F1204159ZE184226B<<<<<10",
]


def test_computes_icao_check_digits():
    assert check_digit("L898902C3") == "6"
    assert check_digit("740812") == "2"


def test_reads_a_passport_from_its_machine_readable_zone():
    mrz = parse_mrz(PASSPORT_MRZ, TODAY)

    assert mrz is not None
    assert mrz.verified is True
    assert (mrz.first_name, mrz.last_name) == ("Anna Maria", "Eriksson")
    assert mrz.document_number == "L898902C3"
    assert mrz.birth_date == date(1974, 8, 12)


def test_a_verified_mrz_overrides_what_the_printed_text_seemed_to_say():
    text = "\n".join(["Surname: ER1KSS0N", "Passport No: L8989O2C3", *PASSPORT_MRZ])

    fields = parse_document(text, TODAY)

    assert fields.last_name == "Eriksson"
    assert fields.document_number == "L898902C3"
    assert fields.birth_date == date(1974, 8, 12)


def test_an_mrz_with_a_failed_check_digit_only_fills_gaps():
    # One misread digit in the document number
    damaged = [PASSPORT_MRZ[0], PASSPORT_MRZ[1].replace("L898902C3", "L898902C8", 1)]

    mrz = parse_mrz(damaged, TODAY)
    assert mrz is not None and mrz.verified is False

    fields = parse_document("\n".join(["Passport No: L898902C3", *damaged]), TODAY)
    assert fields.document_number == "L898902C3"
    assert fields.last_name == "Eriksson"


def test_reads_an_id_card_mrz_and_puts_two_digit_years_in_the_right_century():
    # TD1 layout: document number on line 1, birth date on line 2, names on line 3
    number, birth = "D23145890", "080314"
    lines = [
        f"I<UTO{number}{check_digit(number)}<<<<<<<<<<<<<<<",
        f"{birth}{check_digit(birth)}F3001012UTO<<<<<<<<<<<6",
        "GONZALEZ<PEREZ<<MARIA<FERNANDA",
    ]

    mrz = parse_mrz(lines, TODAY)

    assert mrz is not None and mrz.verified is True
    assert mrz.document_number == number
    # "08" cannot be 1908 for someone photographed in 2026... but "74" must be 1974
    assert mrz.birth_date == date(2008, 3, 14)
    assert (mrz.first_name, mrz.last_name) == ("Maria Fernanda", "Gonzalez Perez")


def test_ordinary_text_is_not_mistaken_for_an_mrz():
    assert parse_mrz(["APELLIDOS", "GONZALEZ PEREZ", "V 12.345.678"], TODAY) is None
