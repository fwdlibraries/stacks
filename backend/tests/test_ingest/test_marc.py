import pytest

from app.ingest import marc
from app.ingest.draft import NormalizationError
from tests.test_ingest.fixtures import ALMA_EBOOK_MARC, ALMA_MARC


def test_alma_record_to_draft():
    draft = marc.to_draft(marc.parse_marcxml(ALMA_MARC))
    assert draft.title == "What is history? The George Macaulay Trevelyan lectures"
    assert draft.resource_type == "book"
    # Editors are listed separately, not as authors; initials keep their periods.
    # Corporate bodies count only when the relator says author (not sponsors, producers)
    assert draft.author == ["Carr, Edward Hallett", "Evans, Richard J.", "History Workshop Collective"]
    assert draft.editor == ["Davies, R. W."]
    # The publication 264 (ind2=1) wins over the copyright one
    assert (draft.year, draft.publisher, draft.place_of_publication) == (2017, "Vintage Books", "New York")
    assert draft.edition == "2nd ed."
    assert draft.isbn == "9780199535569"
    assert draft.metadata == {"call_number": "D16"}


def test_namespaced_electronic_record():
    draft = marc.to_draft(marc.parse_marcxml(ALMA_EBOOK_MARC))
    assert (draft.title, draft.resource_type, draft.year) == ("Digital history", "ebook", 2020)


def test_unreadable_marc():
    with pytest.raises(NormalizationError):
        marc.parse_marcxml("<not-marc")
