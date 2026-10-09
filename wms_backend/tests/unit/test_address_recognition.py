"""Address parsing contract and authenticated API tests; provider is mocked."""

import json
from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock

import pytest
import pycountry
import toml

from services import address_recognition as service
from services import address_postalcode as postal_service
from services import intake_recognition


SOURCE = "Jane Doe\n123 Main St Apt 4\nLos Angeles, CA 90001\nUSA\n+1 (555) 123-4567\njane@example.com"
FIELDS = {
    "country": "US", "province": "CA", "city": "Los Angeles",
    "zip_code": "90001", "receiver": "Jane Doe",
    "receiver_phone": "+1 (555) 123-4567", "mail": "jane@example.com", "warnings": [],
}


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setattr(intake_recognition, "TOML_ENV_FILE", tmp_path / "env.toml")
    for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL", "DEEPSEEK_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)


def _provider_config(**settings):
    intake_recognition.TOML_ENV_FILE.write_text(toml.dumps({
        "deepseek_api_key": "test-key-not-a-secret", **settings,
    }), encoding="utf-8")


def mock_provider(monkeypatch, fields=None, *, content=None, finish_reason="tool_calls", raw=None):
    if content is None:
        fields = FIELDS if fields is None else fields
        country = pycountry.countries.get(alpha_2=fields.get("country", "").upper())
        content = json.dumps({
            **dict.fromkeys(service.FIELD_LIMITS, ""),
            "country_name": country.name if country else "",
            "country_source": "USA" if country and country.alpha_2 == "US" else country.name if country else "",
            "warnings": [], **fields,
        })
    if raw is None:
        raw = json.dumps({"choices": [{"finish_reason": finish_reason, "message": {
            "content": None,
            "tool_calls": [{"id": "test-call", "type": "function", "function": {
                "name": service.ADDRESS_FUNCTION_NAME, "arguments": content,
            }}],
        }}]}).encode()
    response = MagicMock()
    response.__enter__.return_value.read.return_value = raw
    call = MagicMock(return_value=response)
    monkeypatch.setattr(service, "urlopen", call)
    # These tests isolate extraction; end-to-end tests below restore enrichment.
    monkeypatch.setattr(service, "enrich_address", lambda result: result)
    _provider_config()
    return call


@pytest.mark.parametrize("value", [None, 1, [], {}, "", " \n ", "x" * 4001])
def test_invalid_input_does_not_call_provider(monkeypatch, value):
    call = MagicMock()
    monkeypatch.setattr(service, "urlopen", call)
    with pytest.raises(service.AddressRecognitionError) as caught:
        service.parse_address(value)
    assert caught.value.status == 400
    call.assert_not_called()


def test_function_calling_provider_contract_and_original_fields(monkeypatch):
    call = mock_provider(monkeypatch)
    result = service.parse_address(SOURCE)
    assert result == FIELDS
    request = call.call_args.args[0]
    assert request.full_url == "https://api.deepseek.com/chat/completions"
    assert call.call_args.kwargs["timeout"] == 90
    body = json.loads(request.data)
    assert body["model"] == "deepseek-flash"
    assert "response_format" not in body
    assert body["tool_choice"] == {"type": "function", "function": {"name": "resolve_order_address"}}
    assert len(body["tools"]) == 1
    schema = body["tools"][0]["function"]["parameters"]
    assert set(schema["required"]) == {*service.FIELD_LIMITS, "country_name", "country_source", "warnings"}
    assert schema["additionalProperties"] is False
    assert schema["properties"]["zip_code"]["type"] == "string"
    assert schema["properties"]["warnings"]["maxItems"] == 1
    assert schema["properties"]["warnings"]["items"]["enum"] == ["存在多个地址", "地址信息有歧义"]
    assert body["thinking"] == {"type": "disabled"}
    assert body["stream"] is False
    assert body["max_tokens"] == 4096
    assert "ISO 3166-1 alpha-2" in body["messages"][0]["content"]
    assert "不输出 address 字段" in body["messages"][0]["content"]
    assert "SPIAN" in body["messages"][0]["content"]
    assert SOURCE in json.loads(body["messages"][1]["content"].split("\n", 1)[1])


@pytest.mark.parametrize("address", ["123 Main St Apt 4", "Changed street address", None, {"unexpected": "field"}])
def test_provider_address_is_never_returned(monkeypatch, address):
    mock_provider(monkeypatch, {**FIELDS, "address": address})
    assert service.parse_address(SOURCE) == FIELDS


def test_missing_fields_stay_empty_and_postcode_keeps_zero(monkeypatch):
    mock_provider(monkeypatch, {"country": "fr", "address": "12 Rue du Test", "zip_code": "01230"})
    result = service.parse_address("12 Rue du Test\n01230 France")
    assert result["country"] == "FR"
    assert result["zip_code"] == "01230"
    for field in ("province", "city", "receiver", "receiver_phone", "mail"):
        assert result[field] == ""


def test_ungrounded_contact_and_translated_components_are_discarded(monkeypatch):
    mock_provider(monkeypatch, {**FIELDS, "receiver": "Invented Person", "receiver_phone": "+44 999 111 222", "mail": "fake@example.com", "province": "California"})
    result = service.parse_address(SOURCE)
    for field in ("receiver", "receiver_phone", "mail", "province"):
        assert result[field] == ""
    assert result["warnings"] == ["请确认：收件人、收件人电话、邮箱"]
    assert "address" not in result


def test_phone_cannot_be_built_from_unrelated_address_numbers(monkeypatch):
    mock_provider(monkeypatch, {"address": "123 Main St", "zip_code": "90001", "receiver_phone": "12390001"})
    assert service.parse_address("123 Main St, CA 90001")["receiver_phone"] == ""


def test_country_cannot_be_guessed_from_city_or_zip_code(monkeypatch):
    mock_provider(monkeypatch, {"country": "US", "city": "SPRINGFIELD", "address": "123 MAIN ST", "zip_code": "01101"})
    result = service.parse_address("123 MAIN ST SPRINGFIELD 01101")
    assert result["country"] == ""
    assert any("国家" in warning for warning in result["warnings"])


def test_inline_state_code_is_not_country_even_if_provider_omits_province(monkeypatch):
    mock_provider(monkeypatch, {"country": "CA", "country_source": "CA", "address": "123 Main St"})
    assert service.parse_address("123 Main St\nLos Angeles, CA 90001")["country"] == ""


@pytest.mark.parametrize("country,proof,city,province", [("US", "SPRINGFIELD", "SPRINGFIELD", ""), ("CA", "CA", "Los Angeles", "CA")])
def test_city_and_state_cannot_be_used_as_country_proof(monkeypatch, country, proof, city, province):
    mock_provider(monkeypatch, {"country": country, "country_source": proof, "city": city, "province": province, "address": "123 MAIN ST"})
    result = service.parse_address(f"123 MAIN ST\n{city}, {province} 01101\nUSA" if country == "CA" else "123 MAIN ST SPRINGFIELD 01101")
    assert result["country"] == ""
    assert "country_source" not in result


@pytest.mark.parametrize("country,name", [("US", "美国"), ("GB", "United Kingdom"), ("NL", "Netherlands"), ("CA", "Canada"), ("AR", "Argentina")])
def test_explicit_country_names_and_internal_proof_are_accepted(monkeypatch, country, name):
    mock_provider(monkeypatch, {"country": country, "country_source": name, "address": "123 Main St"})
    result = service.parse_address(f"123 Main St\n{name}")
    assert result["country"] == country
    assert "country_source" not in result


def test_country_code_can_be_disambiguated_by_country_label(monkeypatch):
    mock_provider(monkeypatch, {"country": "CA", "country_source": "CA", "province": "CA", "address": "123 Main St"})
    assert service.parse_address("123 Main St\nprovince: CA\ncountry: CA")["country"] == "CA"


@pytest.mark.parametrize("country,name,proof", [("ES", "SPAIN", "SPIAN"), ("AR", "ARGENTINA", "ARGENTNIA")])
def test_country_typos_are_corrected_without_exposing_internal_fields(monkeypatch, country, name, proof):
    mock_provider(monkeypatch, {"country": country, "country_name": name, "country_source": proof})
    result = service.parse_address(f"123 Example St\n{proof}")
    assert result["country"] == country
    assert "country_name" not in result
    assert "country_source" not in result


def test_country_proof_cannot_name_another_country(monkeypatch):
    mock_provider(monkeypatch, {"country": "UA", "country_name": "Ukraine", "country_source": "Argentina"})
    assert service.parse_address("123 Example St\nArgentina")["country"] == ""


def test_field_limits_warning_limits_and_unknown_country(monkeypatch):
    mock_provider(monkeypatch, {"country": "ZZ", "receiver": "x" * 257, "address": "123 Main St", "warnings": ["a" * 201] * 15})
    result = service.parse_address("123 Main St")
    assert result["country"] == ""
    assert result["receiver"] == ""
    assert all(isinstance(result[field], str) for field in service.FIELD_LIMITS)
    assert result["warnings"] == ["未识别到地址信息"]


def test_model_disclaimers_and_correction_notices_are_discarded(monkeypatch):
    mock_provider(monkeypatch, {**FIELDS, "warnings": [
        "请人工核对所有信息，本结果仅供参考，不能保证准确性。",
        "原文未提供邮箱，请补充后再创建订单。",
        "国家拼写已修正，请核对。",
    ]})
    assert service.parse_address(SOURCE) == FIELDS


def test_model_can_return_only_one_actionable_warning(monkeypatch):
    mock_provider(monkeypatch, {**FIELDS, "warnings": ["地址信息有歧义", "存在多个地址", "地址信息有歧义"]})
    assert service.parse_address(SOURCE)["warnings"] == ["地址信息有歧义"]


@pytest.mark.parametrize("content", ["", "not-json", "[]", "{}", "null"])
def test_malformed_model_output_is_rejected(monkeypatch, content):
    mock_provider(monkeypatch, content=content)
    with pytest.raises(service.AddressRecognitionError) as caught:
        service.parse_address(SOURCE)
    assert caught.value.status == 502


@pytest.mark.parametrize("field,value", [("country", None), ("zip_code", 1234), ("country_name", []), ("country_source", False), ("warnings", "oops"), ("warnings", [1])])
def test_invalid_tool_argument_types_are_rejected(monkeypatch, field, value):
    arguments = {**dict.fromkeys(service.ADDRESS_STRING_FIELDS, ""), "warnings": [], field: value}
    mock_provider(monkeypatch, content=json.dumps(arguments))
    with pytest.raises(service.AddressRecognitionError) as caught:
        service.parse_address(SOURCE)
    assert caught.value.status == 502


@pytest.mark.parametrize("calls", [None, [], [{"type": "function", "function": {"name": "wrong", "arguments": "{}"}}], [{"type": "custom", "function": {"name": "resolve_order_address", "arguments": "{}"}}], [{}, {}], [None], [{"type": "function", "function": {"name": "resolve_order_address", "arguments": {}}}]])
def test_missing_wrong_multiple_or_invalid_tool_calls_are_rejected(monkeypatch, calls):
    raw = json.dumps({"choices": [{"finish_reason": "tool_calls", "message": {"content": json.dumps(FIELDS), "tool_calls": calls}}]}).encode()
    mock_provider(monkeypatch, raw=raw)
    with pytest.raises(service.AddressRecognitionError) as caught:
        service.parse_address(SOURCE)
    assert caught.value.status == 502


def test_free_text_json_cannot_replace_the_tool_call(monkeypatch):
    raw = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(FIELDS)}}]}).encode()
    mock_provider(monkeypatch, raw=raw)
    with pytest.raises(service.AddressRecognitionError) as caught:
        service.parse_address(SOURCE)
    assert caught.value.status == 502


@pytest.mark.parametrize("raw", [b"not-json", b"{}", b'{"choices": []}', b'{"choices": [null]}', b"x" * (service.MAX_RESPONSE_BYTES + 1)])
def test_malformed_or_oversized_provider_body_is_rejected(monkeypatch, raw):
    mock_provider(monkeypatch, raw=raw)
    with pytest.raises(service.AddressRecognitionError) as caught:
        service.parse_address(SOURCE)
    assert caught.value.status == 502


def test_truncated_output_is_rejected(monkeypatch):
    mock_provider(monkeypatch, finish_reason="length")
    with pytest.raises(service.AddressRecognitionError, match="未完整结束"):
        service.parse_address(SOURCE)


def test_missing_key_and_malformed_toml_are_safe(monkeypatch):
    call = MagicMock()
    monkeypatch.setattr(service, "urlopen", call)
    with pytest.raises(service.AddressRecognitionError, match="尚未配置") as caught:
        service.parse_address(SOURCE)
    assert caught.value.status == 503
    intake_recognition.TOML_ENV_FILE.write_text('deepseek_api_key = "unterminated\n', encoding="utf-8")
    with pytest.raises(service.AddressRecognitionError, match="配置格式"):
        service.parse_address(SOURCE)
    call.assert_not_called()


def test_shared_toml_configuration_ignores_legacy_environment_and_dotenv(monkeypatch):
    call = mock_provider(monkeypatch)
    legacy_settings = {
        "DEEPSEEK_API_KEY": "legacy-test-key", "DEEPSEEK_MODEL": "legacy-model",
        "DEEPSEEK_BASE_URL": "https://legacy.example.com", "DEEPSEEK_TIMEOUT_SECONDS": "10",
    }
    for name, value in legacy_settings.items():
        monkeypatch.setenv(name, value)
    intake_recognition.TOML_ENV_FILE.with_name(".env").write_text(
        "\n".join(f"{name}={value}" for name, value in legacy_settings.items()), encoding="utf-8",
    )
    assert service.parse_address(SOURCE) == FIELDS
    assert call.call_args.args[0].get_header("Authorization") == "Bearer test-key-not-a-secret"
    assert call.call_args.args[0].full_url == "https://api.deepseek.com/chat/completions"
    assert call.call_args.kwargs["timeout"] == 90
    assert json.loads(call.call_args.args[0].data)["model"] == "deepseek-flash"


def test_all_shared_toml_settings_reload_for_each_address_request(monkeypatch):
    call = mock_provider(monkeypatch)
    _provider_config(
        deepseek_api_key="first-toml-test-key", deepseek_base_url="https://api.deepseek.com/v1",
        deepseek_model="first-text-model", deepseek_timeout_seconds=15,
    )
    assert service.parse_address(SOURCE) == FIELDS
    request = call.call_args.args[0]
    assert request.get_header("Authorization") == "Bearer first-toml-test-key"
    assert request.full_url == "https://api.deepseek.com/v1/chat/completions"
    assert json.loads(request.data)["model"] == "first-text-model"
    assert call.call_args.kwargs["timeout"] == 15

    _provider_config(
        deepseek_api_key="second-toml-test-key", deepseek_base_url="https://api.deepseek.com",
        deepseek_model="second-text-model", deepseek_timeout_seconds="25",
    )
    assert service.parse_address(SOURCE) == FIELDS
    request = call.call_args.args[0]
    assert request.get_header("Authorization") == "Bearer second-toml-test-key"
    assert request.full_url == "https://api.deepseek.com/chat/completions"
    assert json.loads(request.data)["model"] == "second-text-model"
    assert call.call_args.kwargs["timeout"] == 25

    intake_recognition.TOML_ENV_FILE.write_text('deepseek_api_key = ""\n', encoding="utf-8")
    with pytest.raises(service.AddressRecognitionError, match="尚未配置") as caught:
        service.parse_address(SOURCE)
    assert caught.value.status == 503
    assert call.call_count == 2


@pytest.mark.parametrize("timeout", [15, 15.5, "15.5"])
def test_toml_timeout_accepts_numbers_and_numeric_strings(monkeypatch, timeout):
    call = mock_provider(monkeypatch)
    _provider_config(deepseek_timeout_seconds=timeout)
    assert service.parse_address(SOURCE) == FIELDS
    assert call.call_args.kwargs["timeout"] == float(timeout)


@pytest.mark.parametrize("toml_contents", [
    'deepseek_api_key = "unclosed-sensitive-test-value\n',
    'deepseek_api_key = ["sensitive-test-value"]\n',
])
def test_invalid_toml_address_configuration_is_a_safe_503(monkeypatch, toml_contents):
    call = mock_provider(monkeypatch)
    intake_recognition.TOML_ENV_FILE.write_text(toml_contents, encoding="utf-8")
    with pytest.raises(service.AddressRecognitionError, match="配置格式") as caught:
        service.parse_address(SOURCE)
    assert caught.value.status == 503
    assert "sensitive-test-value" not in str(caught.value)
    assert "test-key-not-a-secret" not in str(caught.value)
    assert "at line" not in str(caught.value)
    call.assert_not_called()


@pytest.mark.parametrize("setting,value", [
    ("deepseek_base_url", "http://localhost"), ("deepseek_base_url", "https://user:pass@api.deepseek.com"),
    ("deepseek_base_url", "https://api.deepseek.com?secret=test"), ("deepseek_base_url", "https://[invalid"),
    ("deepseek_timeout_seconds", "NaN"), ("deepseek_timeout_seconds", "4"),
    ("deepseek_timeout_seconds", "181"), ("deepseek_timeout_seconds", "invalid"),
    ("deepseek_api_key", 123), ("deepseek_model", 123), ("deepseek_base_url", 123),
    ("deepseek_timeout_seconds", True), ("deepseek_timeout_seconds", [15]),
])
def test_invalid_config_never_calls_provider(monkeypatch, setting, value):
    call = mock_provider(monkeypatch)
    _provider_config(**{setting: value})
    with pytest.raises(service.AddressRecognitionError) as caught:
        service.parse_address(SOURCE)
    assert caught.value.status == 503
    call.assert_not_called()


@pytest.mark.parametrize("status,public_status", [(401, 502), (403, 502), (402, 503), (429, 503), (400, 502), (500, 502)])
def test_provider_errors_do_not_leak_credentials_or_address(monkeypatch, status, public_status):
    call = mock_provider(monkeypatch)
    call.side_effect = HTTPError("https://api.deepseek.com", status, SOURCE + " test-key-not-a-secret", {}, None)
    with pytest.raises(service.AddressRecognitionError) as caught:
        service.parse_address(SOURCE)
    assert caught.value.status == public_status
    assert "Jane Doe" not in str(caught.value)
    assert "test-key-not-a-secret" not in str(caught.value)


@pytest.mark.parametrize("failure,status", [(TimeoutError("sensitive detail"), 504), (URLError(TimeoutError()), 504), (URLError("sensitive detail"), 502)])
def test_connection_failure_is_safe(monkeypatch, failure, status):
    call = mock_provider(monkeypatch)
    call.side_effect = failure
    with pytest.raises(service.AddressRecognitionError) as caught:
        service.parse_address(SOURCE)
    assert caught.value.status == status
    assert "sensitive detail" not in str(caught.value)


def test_api_requires_authentication(client, monkeypatch):
    call = MagicMock()
    monkeypatch.setattr("controllers.order_controller.parse_address", call)
    response = client.post("/api/orders/parse-address", json={"address": SOURCE})
    assert response.status_code == 401
    call.assert_not_called()


def test_api_success_contract_and_no_store(client, employee_token, monkeypatch):
    call = mock_provider(monkeypatch)
    response = client.post("/api/orders/parse-address", json={"address": SOURCE}, headers={"x-token": employee_token})
    assert response.status_code == 200
    assert response.get_json() == {"code": 200, "data": FIELDS}
    assert "address" not in response.get_json()["data"]
    assert response.headers["Cache-Control"] == "private, no-store"
    call.assert_called_once()


def _postal_provider(monkeypatch, rows=None, failure=None):
    monkeypatch.setattr(service, "enrich_address", postal_service.enrich_address)
    _provider_config(api_ninjas_api_key="postal-test-key")
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(rows or []).encode()
    call = MagicMock(return_value=response, side_effect=failure)
    monkeypatch.setattr(postal_service, "urlopen", call)
    return call


def test_api_corrects_country_and_enriches_independent_city_region(client, employee_token, monkeypatch):
    source = "Jane Doe\nCalle Example 1\nOldcity Oldregion 01230\nSPIAN\n+1 (555) 123-4567\njane@example.com"
    deepseek = mock_provider(monkeypatch, {
        **FIELDS, "country": "ES", "country_name": "SPAIN", "country_source": "SPIAN",
        "city": "Oldcity", "province": "Oldregion", "zip_code": "01230",
    })
    postal = _postal_provider(monkeypatch, [{"country": "ES", "postal_code": "01230", "city": "Madrid", "region": "Madrid"}])
    response = client.post("/api/orders/parse-address", json={"address": source}, headers={"x-token": employee_token})
    assert response.status_code == 200
    result = response.get_json()["data"]
    assert result == {**FIELDS, "country": "ES", "city": "Madrid", "province": "Madrid", "zip_code": "01230"}
    assert set(result) == set(FIELDS)
    assert response.headers["Cache-Control"] == "private, no-store"
    deepseek.assert_called_once()
    postal.assert_called_once()
    assert postal.call_args.args[0].full_url == "https://api.api-ninjas.com/v1/postalcode?country=ES&postal_code=01230"
    assert postal.call_args.kwargs["timeout"] == 10


@pytest.mark.parametrize("failure", [TimeoutError("private address postal-test-key"), HTTPError("https://api.api-ninjas.com", 429, "private address postal-test-key", {}, None)])
def test_api_postal_failure_returns_extracted_fields_and_safe_warning(client, employee_token, monkeypatch, caplog, failure):
    mock_provider(monkeypatch)
    _postal_provider(monkeypatch, failure=failure)
    response = client.post("/api/orders/parse-address", json={"address": SOURCE}, headers={"x-token": employee_token})
    assert response.status_code == 200
    result = response.get_json()["data"]
    assert {key: result[key] for key in service.FIELD_LIMITS} == {key: FIELDS[key] for key in service.FIELD_LIMITS}
    assert result["warnings"]
    assert "private address" not in response.get_data(as_text=True)
    assert "postal-test-key" not in response.get_data(as_text=True)
    assert "Jane Doe" not in caplog.text


def test_api_missing_postal_key_still_returns_extracted_fields(client, employee_token, monkeypatch):
    mock_provider(monkeypatch)
    monkeypatch.setattr(service, "enrich_address", postal_service.enrich_address)
    postal = MagicMock()
    monkeypatch.setattr(postal_service, "urlopen", postal)
    response = client.post("/api/orders/parse-address", json={"address": SOURCE}, headers={"x-token": employee_token})
    assert response.status_code == 200
    assert response.get_json()["data"] == {**FIELDS, "warnings": [postal_service.MISSING_CONFIG_WARNING]}
    postal.assert_not_called()


def test_rejected_tool_call_does_not_query_postal_api(monkeypatch):
    mock_provider(monkeypatch, content="{}")
    postal = _postal_provider(monkeypatch)
    with pytest.raises(service.AddressRecognitionError):
        service.parse_address(SOURCE)
    postal.assert_not_called()


@pytest.mark.parametrize("payload", [[], {}, {"address": None}, {"address": " "}, {"address": "x" * 4001}])
def test_api_invalid_json_or_address(client, employee_token, monkeypatch, payload):
    call = mock_provider(monkeypatch)
    response = client.post("/api/orders/parse-address", json=payload, headers={"x-token": employee_token})
    assert response.status_code == 400
    assert response.get_json()["code"] == 400
    call.assert_not_called()


def test_api_invalid_json_body_and_request_limit(client, employee_token):
    headers = {"x-token": employee_token, "Content-Type": "application/json"}
    assert client.post("/api/orders/parse-address", data="{bad", headers=headers).status_code == 400
    assert client.post("/api/orders/parse-address", data="x" * (32 * 1024 + 1), headers=headers).status_code == 413


def test_api_safe_service_error_keeps_status(client, employee_token, monkeypatch):
    call = MagicMock(side_effect=service.AddressRecognitionError("安全提示", 504))
    monkeypatch.setattr("controllers.order_controller.parse_address", call)
    response = client.post("/api/orders/parse-address", json={"address": SOURCE}, headers={"x-token": employee_token})
    assert response.status_code == 504
    assert response.get_json() == {"code": 504, "msg": "安全提示"}


def test_api_invalid_toml_returns_safe_503(client, employee_token, monkeypatch, caplog):
    call = mock_provider(monkeypatch)
    intake_recognition.TOML_ENV_FILE.write_text('deepseek_api_key = "sensitive-test-value\n', encoding="utf-8")
    response = client.post("/api/orders/parse-address", json={"address": SOURCE}, headers={"x-token": employee_token})
    assert response.status_code == 503
    assert response.get_json() == {"code": 503, "msg": "DeepSeek 后端配置格式不正确，请联系管理员检查"}
    assert "sensitive-test-value" not in response.get_data(as_text=True)
    assert "sensitive-test-value" not in caplog.text
    assert "Jane Doe" not in caplog.text
    call.assert_not_called()


def test_api_unexpected_failure_does_not_log_source(client, employee_token, monkeypatch, caplog):
    call = MagicMock(side_effect=RuntimeError(SOURCE))
    monkeypatch.setattr("controllers.order_controller.parse_address", call)
    response = client.post("/api/orders/parse-address", json={"address": SOURCE}, headers={"x-token": employee_token})
    assert response.status_code == 500
    assert "Jane Doe" not in response.get_data(as_text=True)
    assert "Jane Doe" not in caplog.text
