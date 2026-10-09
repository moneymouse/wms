"""Country evidence validation without network calls or address service state."""

import pytest

from services.address_country import country_grounded


ALIASES = {
    "US": ("USA", "U.S.A.", "United States", "美国"),
    "GB": ("UK", "U.K.", "United Kingdom", "英国"),
    "CA": ("Canada", "加拿大"),
    "ES": ("Spain", "España", "西班牙"),
    "NL": ("Netherlands", "Holland", "荷兰"),
}


def grounded(code, name, proof, source=None, **fields):
    return country_grounded(code, {
        "country_name": name, "country_source": proof, **fields,
    }, source if source is not None else f"123 Main Street\n{proof}", ALIASES)


@pytest.mark.parametrize("proof", ["SPIAN", "spian", "SPAI", "SPAIIN", "SPAIM"])
def test_unique_one_edit_spelling_corrections_include_transposition(proof):
    assert grounded("ES", "SPAIN", proof, f"Madrid, 28001, {proof}", city="Madrid")


def test_complete_iso_catalogue_handles_countries_outside_shipping_aliases():
    assert grounded("AR", "Argentina", "Argentina")
    assert grounded("AR", "Argentina", "ARGENTNIA")
    assert grounded("CI", "Côte d'Ivoire", "Côte d'Ivoire")


@pytest.mark.parametrize("code,name,proof", [
    ("US", "United States", "USA"), ("GB", "United Kingdom", "UK"),
    ("US", "United States", "美国"), ("NL", "Netherlands", "Holland"),
    ("ES", "Spain", "西班牙"), ("CA", "Canada", "加拿大"),
])
def test_exact_country_names_codes_and_existing_language_aliases(code, name, proof):
    assert grounded(code, name, proof)


def test_exact_country_name_wins_over_similar_country_names():
    assert grounded("IR", "Iran", "Iran")
    assert not grounded("IQ", "Iraq", "Iran")


def test_ambiguous_spelling_correction_is_rejected():
    assert not grounded("IR", "Iran", "IRAK")
    assert not grounded("IQ", "Iraq", "IRAK")


@pytest.mark.parametrize("code,name,proof", [
    ("UA", "Ukraine", "Argentina"), ("US", "United States", "SPRINGFIELD"),
    ("ES", "France", "Spain"), ("ZZ", "Spain", "Spain"),
    ("ES", "Spain", "SXXAIN"), ("US", "United States", "UT"),
    ("US", "United States", "USP"),
])
def test_arbitrary_mismatched_unknown_or_unsupported_country_evidence_is_rejected(code, name, proof):
    assert not grounded(code, name, proof)


@pytest.mark.parametrize("name,proof", [("", "Spain"), ("Spain", ""), (None, "Spain"), ("Spain", None), (1, "Spain"), ("Spain", []), ("Spain", "x" * 129)])
def test_country_name_and_source_must_be_present_valid_strings(name, proof):
    assert not grounded("ES", name, proof, "Spain")


def test_corrected_country_name_cannot_replace_verbatim_source_proof():
    assert not grounded("ES", "Spain", "SPAIN", "Madrid, 28001, SPIAN")
    assert not grounded("ES", "Spain", "SPIAN", "Madrid, 28001, Spain")


def test_country_source_must_be_a_whole_token():
    assert not grounded("ES", "Spain", "Spain", "123 SPAINDON Street")


@pytest.mark.parametrize("fields", [{}, {"province": "CA"}, {"province": "CA", "city": "Los Angeles"}])
def test_inline_state_code_cannot_establish_canada(fields):
    assert not grounded("CA", "Canada", "CA", "Los Angeles, CA 90001", **fields)


def test_normalized_state_codes_still_require_country_context():
    assert not grounded("CA", "Canada", "ＣＡ", "Los Angeles, ＣＡ 90001")
    assert not grounded("CA", "Canada", "C.A.", "Los Angeles, C.A. 90001")


@pytest.mark.parametrize("source", ["province: CA\ncountry: CA", "Los Angeles, CA 90001\nCA", "国家: CA"])
def test_country_label_and_final_country_line_disambiguate_short_codes(source):
    assert grounded("CA", "Canada", "CA", source, province="CA")


def test_final_country_line_ignores_following_contact_lines():
    assert grounded("CA", "Canada", "CA", "Toronto\nCA\n+1 555 123 4567\njane@example.com", receiver_phone="+1 555 123 4567", mail="jane@example.com")


@pytest.mark.parametrize("field", ["city", "province", "receiver", "address"])
def test_other_address_components_do_not_establish_country(field):
    assert not grounded("ES", "Spain", "SPIAN", "SPIAN 28001", **{field: "SPIAN"})


@pytest.mark.parametrize("source", ["spian@example.com", "https://example.com/SPIAN", "Spain@example.com"])
def test_country_tokens_inside_contact_details_or_links_are_not_evidence(source):
    proof = "Spain" if source.startswith("Spain") else "SPIAN"
    assert not grounded("ES", "Spain", proof, source)
