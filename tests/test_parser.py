from datetime import date

import pytest

from app.layout import TextBox
from app.mrz import check_digit, parse_mrz
from app.parser import ExtractedFields, find_dates, fold, parse_document

TODAY = date(2026, 10, 10)


def box(text: str, left: float, top: float, right: float, bottom: float) -> TextBox:
    return TextBox(text, left, top, right, bottom)


def line(text: str, left: float, top: float, height: float = 30) -> TextBox:
    """A box sized like printed text: about 16 px per character."""
    return TextBox(text, left, top, left + 16 * len(text), top + height)


# Where RapidOCR placed each box on a phone photo of a Venezuelan cédula (personal data replaced).
# Every date sits above its label, so the box under "F. NACIMIENTO" is the issue date.
VENEZUELAN_CEDULA = [
    box("REPUBLICA BOLIVARIANADEVENEZUELA", 248, 50, 1060, 95),
    box("CE", 315, 112, 398, 139),
    box("DUL", 387, 113, 517, 140),
    box("IDENTIDAD", 663, 116, 985, 152),
    box("V", 510, 175, 561, 209),
    box("12.345.678", 553, 174, 730, 213),
    box("112", 984, 170, 1062, 216),
    box("APELLIDOS GONZÁLEZ PÉREZ", 162, 212, 475, 250),
    box("Juan Dugarte", 890, 211, 1055, 249),
    box("Director", 983, 249, 1077, 281),
    box("NOMBRES", 160, 266, 250, 290),
    box("MARÍA FERNANDA", 280, 260, 563, 301),
    box("URuis", 152, 291, 416, 391),
    box("14/03/2008 SOLTERA", 402, 425, 756, 462),
    box("F. NACIMIENTO", 419, 458, 553, 481),
    box("EDO CIVIL", 609, 455, 699, 483),
    box("26/01/2015 01/2025", 398, 547, 729, 585),
    box("F.EXPEDICION", 417, 580, 546, 604),
    box("F.VENCIMIENTO", 585, 582, 725, 602),
    box("VENEZOLANA", 387, 649, 742, 700),
]

# The same for an Ecuadorian cédula: every value sits under its label, and a long surname wraps
ECUADORIAN_CEDULA = [
    box("CÉDULA DE", 78, 53, 267, 95),
    box("REPÚBLICA DEL ECUADOR", 391, 45, 885, 97),
    box("IDENTIDAD", 77, 85, 264, 125),
    box("DIRECCIÓN GENERAL DE REGISTRO CIVIL, IDENTIFICACIÓN Y CEDULACIÓN", 393, 86, 1025, 126),
    box("APELLIDOS", 400, 122, 537, 155),
    box("CONDICIÓN EXT*PERMANENTE", 632, 114, 1020, 151),
    box("PÉREZ", 401, 157, 474, 189),
    box("GONZÁLEZ", 401, 188, 503, 223),
    box("NOMBRES", 400, 223, 525, 255),
    box("MARÍA FERNANDA", 401, 255, 643, 292),
    box("NACIONALIDAD", 401, 292, 580, 325),
    box("VENEZOLANA", 402, 331, 591, 368),
    box("FECHA DE NACIMIENTO", 403, 367, 673, 402),
    box("SEXO", 842, 364, 914, 394),
    box("14 MAR 2008", 406, 405, 573, 438),
    box("MUJER", 841, 397, 968, 431),
    box("LUGAR DENACIMIENTO", 404, 437, 676, 472),
    box("Barquisimeto (Lara)", 406, 509, 665, 547),
    box("FECHA DE VENCIMIENTO", 843, 504, 1125, 539),
    box("16 MAR 2036", 846, 545, 1015, 578),
    box("NUI.1712345678", 102, 630, 384, 680),
    box("150025", 846, 635, 943, 666),
]


def test_reads_a_venezuelan_cedula():
    assert parse_document(VENEZUELAN_CEDULA, TODAY) == ExtractedFields(
        first_name="María Fernanda",
        last_name="González Pérez",
        document_number="V-12345678",
        birth_date=date(2008, 3, 14),
    )


def test_reads_an_ecuadorian_cedula_with_values_under_their_labels():
    assert parse_document(ECUADORIAN_CEDULA, TODAY) == ExtractedFields(
        first_name="María Fernanda",
        last_name="Pérez González",
        document_number="1712345678",
        birth_date=date(2008, 3, 14),
    )


def test_the_same_boxes_in_any_order_give_the_same_answer():
    assert parse_document(list(reversed(ECUADORIAN_CEDULA)), TODAY) == parse_document(ECUADORIAN_CEDULA, TODAY)


def test_reads_values_inside_the_label_box():
    boxes = [
        line("APELLIDOS: Hopper Murray", 40, 40),
        line("NOMBRE: Grace Brewster", 40, 80),
        line("DNI 87654321Z", 40, 120),
        line("FECHA DE NACIMIENTO 09 DIC 1986", 40, 160),
    ]

    assert parse_document(boxes, TODAY) == ExtractedFields(
        first_name="Grace Brewster",
        last_name="Hopper Murray",
        document_number="87654321Z",
        birth_date=date(1986, 12, 9),
    )


def test_skips_every_label_of_a_bilingual_heading():
    boxes = [line("Apellidos / Surnames", 40, 40), line("TURING", 40, 75), line("Nombres / Given names", 40, 120)]
    boxes.append(line("ALAN MATHISON", 40, 155))

    fields = parse_document(boxes, TODAY)

    assert (fields.first_name, fields.last_name) == ("Alan Mathison", "Turing")


def test_joins_a_name_the_engine_split_along_the_line():
    boxes = [line("NOMBRES", 40, 40), line("MARIA", 200, 40), line("FERNANDA", 300, 40)]

    assert parse_document(boxes, TODAY).first_name == "Maria Fernanda"


def test_a_value_beside_the_label_is_preferred_to_one_above_it():
    boxes = [line("ANTONIO", 40, 0), line("NOMBRES", 40, 32), line("MARIA", 200, 32)]

    assert parse_document(boxes, TODAY).first_name == "Maria"


def test_text_that_is_not_written_like_a_name_is_not_taken_for_one():
    boxes = [line("APELLIDOS", 40, 40), line("EXT*PERMANENTE", 200, 40), line("112", 40, 72)]

    assert parse_document(boxes, TODAY).last_name is None


def test_a_label_is_never_taken_for_a_value():
    boxes = [line("APELLIDOS", 40, 40), line("NOMBRES", 40, 72), line("NACIONALIDAD", 40, 104)]

    fields = parse_document(boxes, TODAY)

    assert fields.last_name is None
    assert fields.first_name is None


def test_a_name_wrapping_over_lines_stops_at_the_next_label():
    boxes = [line("APELLIDOS", 40, 40), line("DE LA", 40, 72), line("CRUZ", 40, 104), line("NOMBRES", 40, 136)]

    assert parse_document(boxes, TODAY).last_name == "De La Cruz"


def test_text_far_from_a_label_is_not_its_value():
    boxes = [line("NOMBRES", 40, 40), line("MARIA", 40, 160), line("JUAN", 900, 40)]

    assert parse_document(boxes, TODAY).first_name is None


def test_dates_without_a_birth_label_are_not_guessed_at():
    boxes = [line("MARIA", 40, 40), line("02/05/2022 14.03.2008 05/05/2032", 40, 80)]

    assert parse_document(boxes, TODAY).birth_date is None


def test_unlabelled_numbers_are_not_guessed_at():
    boxes = [line("150025", 40, 40), line("1762361960", 40, 80)]

    assert parse_document(boxes, TODAY).document_number is None


@pytest.mark.parametrize(
    ("boxes", "expected"),
    [
        ([line("V-12.345.678", 40, 40)], "V-12345678"),
        ([line("V12345678", 40, 40)], "V-12345678"),
        ([line("E 84.123.456", 40, 40)], "E-84123456"),
        ([line("V", 40, 40), line("12.345.678", 70, 40)], "V-12345678"),
        ([line("N° 1.234.567", 40, 40)], "1234567"),
        ([line("ID 00123456", 40, 40)], "00123456"),
        ([line("NUI.1762361960", 40, 40)], "1762361960"),
        ([line("PASSPORT NO", 40, 40), line("L898902C3", 40, 72)], "L898902C3"),
    ],
)
def test_reads_document_numbers(boxes, expected):
    assert parse_document(boxes, TODAY).document_number == expected


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


def test_folding_keeps_every_character_in_place():
    assert fold("Pérez Muñoz") == "PEREZ MUNOZ"
    assert len(fold("Straße")) == len("Straße")


@pytest.mark.parametrize("boxes", [[], [line("   ", 0, 0)], [line("@@@ ### !!!", 0, 0)], [line("lorem ipsum", 0, 0)]])
def test_returns_nothing_rather_than_guessing_from_unreadable_text(boxes):
    fields = parse_document(boxes, TODAY)

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
    boxes = [line("Surname: ER1KSS0N", 40, 40), line("Passport No: L8989O2C3", 40, 80)]
    boxes += [line(PASSPORT_MRZ[0], 40, 400), line(PASSPORT_MRZ[1], 40, 440)]

    fields = parse_document(boxes, TODAY)

    assert fields.last_name == "Eriksson"
    assert fields.document_number == "L898902C3"
    assert fields.birth_date == date(1974, 8, 12)


def test_an_mrz_with_a_failed_check_digit_only_fills_gaps():
    # One misread digit in the document number
    damaged = [PASSPORT_MRZ[0], PASSPORT_MRZ[1].replace("L898902C3", "L898902C8", 1)]

    mrz = parse_mrz(damaged, TODAY)
    assert mrz is not None and mrz.verified is False

    boxes = [line("Passport No: L898902C3", 40, 40), line(damaged[0], 40, 400), line(damaged[1], 40, 440)]
    fields = parse_document(boxes, TODAY)
    assert fields.document_number == "L898902C3"
    assert fields.last_name == "Eriksson"


def test_an_mrz_line_split_into_boxes_is_joined_back():
    first, second = PASSPORT_MRZ
    boxes = [line(first[:20], 40, 400), line(first[20:], 360, 400), line(second, 40, 440)]

    assert parse_document(boxes, TODAY).document_number == "L898902C3"


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
