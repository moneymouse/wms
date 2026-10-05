"""Postal enrichment behavior; every network request and key is isolated."""

import copy
import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from unittest.mock import MagicMock

import pytest
import toml

from services import address_postalcode as service
from services import intake_recognition


FIELDS = {
    "country": "ES", "province": "Wrong Province", "city": "Wrong City",
    "zip_code": "08001", "receiver": "Jane Doe", "receiver_phone": "+34 000 123 456",
    "mail": "jane@example.com", "warnings": ["收件人信息不完整"],
}
BARCELONA = {"country": "ES", "postal_code": "08001", "city": "Barcelona", "region": "Catalunya"}


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setattr(intake_recognition, "TOML_ENV_FILE", tmp_path / "env.toml")
    monkeypatch.delenv("API_NINJAS_API_KEY", raising=False)


def _config(**settings):
    intake_recognition.TOML_ENV_FILE.write_text(toml.dumps({
        "api_ninjas_api_key": "test-postal-key", **settings,
    }), encoding="utf-8")


def mock_postal(monkeypatch, rows=None, *, raw=None, error=None):
    if raw is None:
        raw = json.dumps([BARCELONA] if rows is None else rows).encode()
    response = MagicMock()
    response.__enter__.return_value.read.return_value = raw
    call = MagicMock(return_value=response, side_effect=error)
    monkeypatch.setattr(service, "urlopen", call)
    _config()
    return call


def test_unique_lookup_corrects_only_city_and_province_and_keeps_source(monkeypatch):
    call = mock_postal(monkeypatch)
    source = copy.deepcopy(FIELDS)
    result = service.enrich_address(source)
    assert result["city"] == "Barcelona"
    assert result["province"] == "Catalunya"
    assert result["warnings"] == FIELDS["warnings"]
    assert source == FIELDS
    assert result is not source
    assert result["warnings"] is not source["warnings"]
    for field in ("country", "zip_code", "receiver", "receiver_phone", "mail"):
        assert result[field] == source[field]
    request = call.call_args.args[0]
    parsed = urlparse(request.full_url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "api.api-ninjas.com"
    assert parsed.path == "/v1/postalcode"
    assert parse_qs(parsed.query) == {"country": ["ES"], "postal_code": ["08001"]}
    assert request.get_method() == "GET"
    assert request.get_header("X-api-key") == "test-postal-key"
    assert call.call_args.kwargs == {"timeout": 10}
    call.return_value.__enter__.return_value.read.assert_called_once_with(service.MAX_RESPONSE_BYTES + 1)


def test_api_fields_need_no_original_text_and_can_fill_missing_fields(monkeypatch):
    mock_postal(monkeypatch)
    result = service.enrich_address({**FIELDS, "city": "", "province": ""})
    assert result["city"] == "Barcelona"
    assert result["province"] == "Catalunya"
    assert result["warnings"] == FIELDS["warnings"]


@pytest.mark.parametrize("warning", ["存在多个地址", "未识别到地址信息"])
def test_empty_extraction_keeps_one_relevant_warning_without_postal_warning(monkeypatch, warning):
    call = mock_postal(monkeypatch)
    source = {**dict.fromkeys((field for field in FIELDS if field != "warnings"), ""), "warnings": [warning]}
    assert service.enrich_address(source) == source
    call.assert_not_called()


def test_duplicate_candidates_ignore_case_whitespace_punctuation_and_unicode_width(monkeypatch):
    mock_postal(monkeypatch, [BARCELONA, {**BARCELONA, "city": "ＢＡＲＣＥＬＯＮＡ.", "region": "CAT ALU NYA."}])
    result = service.enrich_address({**FIELDS, "city": "barcelona", "province": "cat alunya"})
    assert result["city"] == "Barcelona"
    assert result["province"] == "Catalunya"
    assert result["warnings"] == FIELDS["warnings"]


def test_multiple_candidates_choose_unique_source_city_even_with_wrong_province(monkeypatch):
    other = {**BARCELONA, "city": "Badalona", "region": "Other Region"}
    mock_postal(monkeypatch, [BARCELONA, other])
    result = service.enrich_address({**FIELDS, "city": "BAR CELONA."})
    assert result["city"] == "Barcelona"
    assert result["province"] == "Catalunya"


def test_multiple_same_city_candidates_use_source_region(monkeypatch):
    other = {**BARCELONA, "region": "Other Region"}
    mock_postal(monkeypatch, [other, BARCELONA])
    result = service.enrich_address({**FIELDS, "city": "Barcelona", "province": "Cat alunya."})
    assert result["city"] == "Barcelona"
    assert result["province"] == "Catalunya"
    assert result["warnings"] == FIELDS["warnings"]


def test_region_code_from_duplicate_candidate_can_disambiguate(monkeypatch):
    mock_postal(monkeypatch, [
        BARCELONA, {**BARCELONA, "region_code": "CT"},
        {**BARCELONA, "region": "Other Region", "region_code": "OT"},
    ])
    result = service.enrich_address({**FIELDS, "city": "Barcelona", "province": "CT"})
    assert result["province"] == "Catalunya"
    assert result["warnings"] == FIELDS["warnings"]


def test_unique_province_match_can_choose_city_without_city_match(monkeypatch):
    mock_postal(monkeypatch, [BARCELONA, {**BARCELONA, "city": "Madrid", "region": "Madrid"}])
    result = service.enrich_address({**FIELDS, "province": "Catalunya"})
    assert result["city"] == "Barcelona"
    assert result["province"] == "Catalunya"


def test_city_match_is_prioritized_over_another_candidates_province(monkeypatch):
    mock_postal(monkeypatch, [
        {**BARCELONA, "region": "Region A"},
        {**BARCELONA, "region": "Region B"},
        {**BARCELONA, "city": "Other City", "region": "Wrong Province"},
    ])
    result = service.enrich_address({**FIELDS, "city": "Barcelona"})
    assert result["city"] == "Barcelona"
    assert result["province"] == "Wrong Province"
    assert service.AMBIGUOUS_LOOKUP_WARNING in result["warnings"]


def test_ambiguous_cities_fill_common_region_but_keep_original_city(monkeypatch):
    mock_postal(monkeypatch, [BARCELONA, {**BARCELONA, "city": "Badalona", "region": "CAT ALUNYA."}])
    result = service.enrich_address(FIELDS)
    assert result["city"] == "Wrong City"
    assert result["province"] == "Catalunya"
    assert service.AMBIGUOUS_LOOKUP_WARNING in result["warnings"]


def test_ambiguous_regions_preserve_both_source_fields(monkeypatch):
    mock_postal(monkeypatch, [BARCELONA, {**BARCELONA, "city": "Madrid", "region": "Madrid"}])
    result = service.enrich_address(FIELDS)
    assert result["city"] == FIELDS["city"]
    assert result["province"] == FIELDS["province"]
    assert service.AMBIGUOUS_LOOKUP_WARNING in result["warnings"]


@pytest.mark.parametrize("country,postal_code", [("", "08001"), ("ES", ""), (None, "08001"), ("ES", 8001), ("Spain", "08001"), ("E1", "08001"), ("ＥＳ", "08001"), ("ES", "0" * 65)])
def test_missing_or_invalid_country_or_postal_skips_lookup(monkeypatch, country, postal_code):
    call = mock_postal(monkeypatch)
    source = {**FIELDS, "country": country, "zip_code": postal_code}
    result = service.enrich_address(source)
    assert result == {**source, "warnings": [*FIELDS["warnings"], service.MISSING_FIELDS_WARNING]}
    call.assert_not_called()


def test_missing_key_ignores_environment_and_preserves_fields(monkeypatch):
    call = mock_postal(monkeypatch)
    _config(api_ninjas_api_key="")
    monkeypatch.setenv("API_NINJAS_API_KEY", "ignored-legacy-key")
    result = service.enrich_address(FIELDS)
    assert result == {**FIELDS, "warnings": [*FIELDS["warnings"], service.MISSING_CONFIG_WARNING]}
    call.assert_not_called()


@pytest.mark.parametrize("settings", [None, {"api_ninjas_api_key": 123}, {"api_ninjas_api_key": "secret\nkey"}, {"api_ninjas_api_key": "密钥"}])
def test_bad_configuration_has_safe_fallback(monkeypatch, settings):
    call = mock_postal(monkeypatch)
    if settings is None:
        intake_recognition.TOML_ENV_FILE.write_text('api_ninjas_api_key = "unterminated\n', encoding="utf-8")
    else:
        _config(**settings)
    result = service.enrich_address(FIELDS)
    assert result == {**FIELDS, "warnings": [*FIELDS["warnings"], service.BAD_CONFIG_WARNING]}
    call.assert_not_called()


def test_key_is_reloaded_for_each_request(monkeypatch):
    call = mock_postal(monkeypatch)
    _config(api_ninjas_api_key="first-test-key")
    service.enrich_address(FIELDS)
    assert call.call_args.args[0].get_header("X-api-key") == "first-test-key"
    _config(api_ninjas_api_key="second-test-key")
    service.enrich_address(FIELDS)
    assert call.call_args.args[0].get_header("X-api-key") == "second-test-key"


@pytest.mark.parametrize("postal_code", ["L-4968", "SW1A 1AA", "1011AB"])
def test_flexible_postal_format_is_encoded_but_never_overwritten(monkeypatch, postal_code):
    call = mock_postal(monkeypatch, [{**BARCELONA, "postal_code": "normalized-code"}])
    result = service.enrich_address({**FIELDS, "zip_code": postal_code})
    assert result["zip_code"] == postal_code
    assert parse_qs(urlparse(call.call_args.args[0].full_url).query)["postal_code"] == [postal_code]


def test_us_uses_only_postalcode_endpoint(monkeypatch):
    call = mock_postal(monkeypatch, [])
    result = service.enrich_address({**FIELDS, "country": "US", "zip_code": "01101"})
    assert urlparse(call.call_args.args[0].full_url).path == "/v1/postalcode"
    assert result["zip_code"] == "01101"
    assert service.EMPTY_LOOKUP_WARNING in result["warnings"]


@pytest.mark.parametrize("error", [TimeoutError("raw secret"), URLError("raw address"), OSError("raw address")])
def test_transport_failure_is_safe_and_does_not_retry(monkeypatch, error):
    call = mock_postal(monkeypatch, error=error)
    result = service.enrich_address(FIELDS)
    assert result == {**FIELDS, "warnings": [*FIELDS["warnings"], service.FAILED_LOOKUP_WARNING]}
    call.assert_called_once()
    assert "raw" not in json.dumps(result["warnings"])


@pytest.mark.parametrize("status,warning_fragment", [(401, "密钥无效"), (403, "密钥无效"), (429, "限流"), (500, "查询失败")])
def test_http_failure_preserves_fields_with_safe_warning(monkeypatch, status, warning_fragment):
    call = mock_postal(monkeypatch, error=HTTPError(service.POSTALCODE_URL, status, "secret provider body", {}, None))
    result = service.enrich_address(FIELDS)
    assert {field: result[field] for field in FIELDS if field != "warnings"} == {field: FIELDS[field] for field in FIELDS if field != "warnings"}
    assert any(warning_fragment in warning for warning in result["warnings"])
    assert "secret" not in json.dumps(result)
    call.assert_called_once()


@pytest.mark.parametrize("raw", [b"not-json", b"\xff", b"{}", b"null", b'{"has_postal_codes": false}', b"x" * (service.MAX_RESPONSE_BYTES + 1)])
def test_invalid_or_oversized_response_preserves_all_fields(monkeypatch, raw):
    mock_postal(monkeypatch, raw=raw)
    result = service.enrich_address(FIELDS)
    assert result == {**FIELDS, "warnings": [*FIELDS["warnings"], service.BAD_RESPONSE_WARNING]}


@pytest.mark.parametrize("row", [None, {**BARCELONA, "country": "FR"}, {**BARCELONA, "country": 123}, {**BARCELONA, "city": ""}, {**BARCELONA, "city": "..."}, {**BARCELONA, "region": None}, {**BARCELONA, "region": "x" * 129}])
def test_malformed_or_wrong_country_candidates_do_not_create_false_unique_match(monkeypatch, row):
    mock_postal(monkeypatch, [BARCELONA, row])
    result = service.enrich_address(FIELDS)
    assert result == {**FIELDS, "warnings": [*FIELDS["warnings"], service.BAD_RESPONSE_WARNING]}


def test_warnings_are_sanitized_deduplicated_bounded_and_include_failure(monkeypatch):
    mock_postal(monkeypatch, [])
    source = {**FIELDS, "warnings": ["same", "same", None, 1, "", "x" * 201, *[str(index) for index in range(30)]]}
    result = service.enrich_address(source)
    assert len(result["warnings"]) == 3
    assert result["warnings"].count("same") == 1
    assert service.EMPTY_LOOKUP_WARNING in result["warnings"]
    assert all(isinstance(warning, str) and 0 < len(warning) <= 60 for warning in result["warnings"])
    assert source["warnings"][2] is None


def test_successful_correction_returns_no_lookup_warning(monkeypatch):
    mock_postal(monkeypatch)
    result = service.enrich_address({**FIELDS, "warnings": []})
    assert result["city"] == "Barcelona"
    assert result["province"] == "Catalunya"
    assert result["warnings"] == []


def test_lookup_warning_is_not_repeated(monkeypatch):
    mock_postal(monkeypatch, [])
    result = service.enrich_address({**FIELDS, "warnings": [service.EMPTY_LOOKUP_WARNING]})
    assert result["warnings"] == [service.EMPTY_LOOKUP_WARNING]
