import pytest

from app.ingest.identifiers import Identifier, detect, normalize_doi, normalize_isbn


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("10.1093/ahr/rhaa001", "10.1093/ahr/rhaa001"),
        ("https://doi.org/10.1093/AHR/RHAA001", "10.1093/ahr/rhaa001"),
        ("doi:10.1000/xyz123.", "10.1000/xyz123"),
        ("(see 10.1000/abc), p. 4", "10.1000/abc"),
        ("not a doi", None),
    ],
)
def test_normalize_doi(text, expected):
    assert normalize_doi(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("978-0-14-044913-6", "9780140449136"),
        ("0-14-044913-2", "9780140449136"),  # ISBN-10 becomes ISBN-13
        ("080442957X", "9780804429573"),
        ("978-0-14-044913-7", None),  # bad checksum
        ("0-14-044913-0", None),
        ("12345", None),
    ],
)
def test_normalize_isbn(text, expected):
    assert normalize_isbn(text) == expected


def test_detect_finds_each_kind_once_in_pasted_text():
    text = (
        "Carr, What is history? ISBN 978-0-14-044913-6 (also 0140449132); "
        "Alma 991234567890123; article https://doi.org/10.1093/ahr/rhaa001."
    )
    assert detect(text) == [
        Identifier("doi", "10.1093/ahr/rhaa001"),
        Identifier("mms_id", "991234567890123"),
        Identifier("isbn", "9780140449136"),
    ]


def test_digits_inside_a_doi_are_not_other_identifiers():
    assert detect("10.1000/991234567890123") == [Identifier("doi", "10.1000/991234567890123")]


def test_mms_ids_are_not_mistaken_for_isbns():
    # 13 digits starting 99: an MMS ID, never an ISBN-13 (those start 978/979)
    assert detect("9912345678901") == [Identifier("mms_id", "9912345678901")]


def test_nothing_found():
    assert detect("Carr, What is history?") == []
