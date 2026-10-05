"""Provider contract tests without network calls or real credentials."""

import json
from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock

import pytest
import toml

from services import intake_recognition as service


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "TOML_ENV_FILE", tmp_path / "env.toml")
    for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL", "DEEPSEEK_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)


def _provider_config(**settings):
    service.TOML_ENV_FILE.write_text(toml.dumps({
        "deepseek_api_key": "test-key-not-a-secret", **settings,
    }), encoding="utf-8")


def _response(monkeypatch, content, finish_reason="stop"):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps({
        "choices": [{"finish_reason": finish_reason, "message": {"content": content}}]
    }).encode()
    call = MagicMock(return_value=response)
    monkeypatch.setattr(service, "urlopen", call)
    _provider_config()
    return call


IMAGE = {"data": b"synthetic-image", "mime_type": "image/png", "filename": "test.png"}


def test_empty_key_is_explicit_and_does_not_call_provider(monkeypatch):
    call = MagicMock()
    monkeypatch.setattr(service, "urlopen", call)
    assert service.recognition_available() is False
    with pytest.raises(service.IntakeRecognitionError, match="尚未配置"):
        service.recognize_paper_photos([IMAGE])
    call.assert_not_called()


def test_toml_file_reload_updates_availability():
    service.TOML_ENV_FILE.write_text('deepseek_api_key = ""\n', encoding="utf-8")
    assert service.recognition_available() is False
    service.TOML_ENV_FILE.write_text('deepseek_api_key = "local-test-key"\n', encoding="utf-8")
    assert service.recognition_available() is True
    service.TOML_ENV_FILE.write_text('deepseek_api_key = ""\n', encoding="utf-8")
    assert service.recognition_available() is False


def test_toml_key_reload_takes_priority_over_environment_and_dotenv(monkeypatch):
    call = _response(monkeypatch, '{"boxes": []}')
    monkeypatch.setenv("DEEPSEEK_API_KEY", "environment-test-key")
    service.TOML_ENV_FILE.with_name(".env").write_text('DEEPSEEK_API_KEY="dotenv-test-key"\n', encoding="utf-8")
    service.TOML_ENV_FILE.write_text('deepseek_api_key = " first-toml-test-key "\n', encoding="utf-8")
    assert service.recognition_available() is True
    service.recognize_paper_photos([IMAGE])
    assert call.call_args.args[0].get_header("Authorization") == "Bearer first-toml-test-key"

    service.TOML_ENV_FILE.write_text('deepseek_api_key = "second-toml-test-key"\n', encoding="utf-8")
    service.recognize_paper_photos([IMAGE])
    assert call.call_args.args[0].get_header("Authorization") == "Bearer second-toml-test-key"
    assert call.call_count == 2


@pytest.mark.parametrize("toml_contents", [None, 'another_setting = "value"\n'])
def test_missing_toml_file_or_key_uses_defaults_without_legacy_fallback(monkeypatch, toml_contents):
    if toml_contents is not None:
        service.TOML_ENV_FILE.write_text(toml_contents, encoding="utf-8")
    legacy_settings = {
        "DEEPSEEK_API_KEY": "legacy-test-key", "DEEPSEEK_MODEL": "legacy-model",
        "DEEPSEEK_BASE_URL": "https://legacy.example.com", "DEEPSEEK_TIMEOUT_SECONDS": "10",
    }
    for name, value in legacy_settings.items():
        monkeypatch.setenv(name, value)
    service.TOML_ENV_FILE.with_name(".env").write_text(
        "\n".join(f"{name}={value}" for name, value in legacy_settings.items()), encoding="utf-8",
    )
    for name, default in (
        ("DEEPSEEK_API_KEY", ""), ("DEEPSEEK_MODEL", "deepseek-flash"),
        ("DEEPSEEK_BASE_URL", "https://api.deepseek.com"), ("DEEPSEEK_TIMEOUT_SECONDS", "90"),
    ):
        assert service._config(name, default) == default
    assert service.recognition_available() is False


def test_empty_toml_key_disables_provider_without_legacy_fallback(monkeypatch):
    call = _response(monkeypatch, '{"boxes": []}')
    monkeypatch.setenv("DEEPSEEK_API_KEY", "environment-test-key")
    service.TOML_ENV_FILE.with_name(".env").write_text('DEEPSEEK_API_KEY="dotenv-test-key"\n', encoding="utf-8")
    service.TOML_ENV_FILE.write_text('deepseek_api_key = "   "\n', encoding="utf-8")
    assert service.recognition_available() is False
    with pytest.raises(service.IntakeRecognitionError, match="尚未配置"):
        service.recognize_paper_photos([IMAGE])
    call.assert_not_called()


@pytest.mark.parametrize("toml_contents", [
    'deepseek_api_key = "unclosed-sensitive-test-value\n',
    'deepseek_api_key = 123\n',
    'deepseek_api_key = false\n',
    'deepseek_api_key = ["sensitive-test-value"]\n',
    'deepseek_api_key = { value = "sensitive-test-value" }\n',
])
def test_invalid_toml_never_falls_back_or_exposes_parser_details(monkeypatch, toml_contents):
    call = _response(monkeypatch, '{"boxes": []}')
    service.TOML_ENV_FILE.write_text(toml_contents, encoding="utf-8")
    assert service.recognition_available() is False
    with pytest.raises(service.IntakeRecognitionError, match="env.toml") as caught:
        service.recognize_paper_photos([IMAGE])
    assert "sensitive-test-value" not in str(caught.value)
    assert "at line" not in str(caught.value)
    assert "test-key-not-a-secret" not in str(caught.value)
    assert caught.value.__cause__ is None
    call.assert_not_called()


@pytest.mark.parametrize("failure", ["unreadable", "invalid-encoding"])
def test_unreadable_toml_is_a_safe_configuration_failure(monkeypatch, failure):
    call = _response(monkeypatch, '{"boxes": []}')
    if failure == "unreadable":
        service.TOML_ENV_FILE.unlink()
        service.TOML_ENV_FILE.mkdir()
    else:
        service.TOML_ENV_FILE.write_bytes(b"deepseek_api_key = \"\xff\"\n")
    with pytest.raises(service.IntakeRecognitionError, match="env.toml") as caught:
        service.recognize_paper_photos([IMAGE])
    assert str(service.TOML_ENV_FILE) not in str(caught.value)
    assert "codec" not in str(caught.value)
    assert "test-key-not-a-secret" not in str(caught.value)
    call.assert_not_called()


def test_images_json_mode_and_draft_nulls_are_preserved(monkeypatch):
    call = _response(monkeypatch, json.dumps({
        "mark": "ABC", "operator_name": "张三", "boxes": [{"box_number": None, "item_name": "衣服", "count": 12, "weight": None}],
        "warnings": ["重量看不清"]
    }))
    result = service.recognize_paper_photos([IMAGE], mark_hint="ABC")
    assert result["boxes"][0] == {"box_number": None, "item_name": "衣服", "count": 12, "weight": None}
    assert result["operator_name"] == "张三"
    assert result["warnings"] == ["重量看不清"]
    request = call.call_args.args[0]
    body = json.loads(request.data)
    assert request.full_url == "https://api.deepseek.com/chat/completions"
    assert body["model"] == "deepseek-flash"
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "disabled"}
    assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def _parse_candidate(boxes, **fields):
    return service._parse_result(json.dumps({"mark": "ABC", "boxes": boxes, **fields}, ensure_ascii=False), "test-model")


def _box(number, name="", count=12, weight=None):
    return {"box_number": number, "item_name": name, "count": count, "weight": weight}


@pytest.mark.parametrize("operator_name,expected", [
    ("  张三  ", "张三"), (None, ""), (123, ""), ("未知", ""),
    ("看不清", ""), ("疑似张三", ""), ("张?", ""), ("-", ""),
])
def test_paper_operator_is_preserved_only_when_identifiable(operator_name, expected):
    result = _parse_candidate([_box(1, "衣服")], operator_name=operator_name)
    assert result["operator_name"] == expected


def test_missing_paper_operator_is_not_inferred_from_uploading_user():
    result = _parse_candidate([_box(1, "衣服")], submitted_by_name="登录上传人")
    assert result["operator_name"] == ""


def test_multiple_paper_operators_are_preserved_with_review_warning():
    result = _parse_candidate([_box(1, "衣服")], operator_name="张三、李四")
    assert result["operator_name"] == "张三、李四"
    assert any("多位作业人员" in warning for warning in result["warnings"])


def test_consecutive_omissions_inherit_names_and_switch_at_explicit_new_name():
    boxes = [
        _box(1, "衣服", 10), _box(2, "", 8), _box(3, "同上", None, 7.2),
        _box(4, "〃", 4), _box(5, "鞋子", 2), _box(6, "", None, 3.5),
    ]
    result = _parse_candidate(boxes)
    assert [box["item_name"] for box in result["boxes"]] == ["衣服", "衣服", "衣服", "衣服", "鞋子", "鞋子"]
    # Every numeric field remains the transcription for that row, including nulls.
    for actual, original in zip(result["boxes"], boxes):
        assert {key: actual[key] for key in ("box_number", "count", "weight")} == {key: original[key] for key in ("box_number", "count", "weight")}
    assert len(result["warnings"]) == 4
    for number in (2, 3, 4, 6):
        assert any(f"第 {number} 箱" in warning for warning in result["warnings"])


@pytest.mark.parametrize("ditto", ["同上", " 同上。 ", "〃", "″", '"'])
def test_unambiguous_ditto_notation_can_continue_an_evidenced_box(ditto):
    result = _parse_candidate([_box(1, "衣服"), _box(2, ditto)])
    assert result["boxes"][1]["item_name"] == "衣服"


@pytest.mark.parametrize("broken_number,next_number", [
    (None, 2), (3, 4), (1, 2), (0, 1), (-1, 2), (1.5, 2.5),
    ("未知", 2), (False, 2), ("2?", 3),
])
def test_missing_nonpositive_duplicate_or_discontinuous_box_number_breaks_inheritance(broken_number, next_number):
    result = _parse_candidate([_box(1, "衣服"), _box(broken_number), _box(next_number)])
    assert [box["item_name"] for box in result["boxes"]] == ["衣服", "", ""]
    assert result["warnings"] == []
    # The missing number is not invented, and valid numeric strings are retained.
    assert result["boxes"][1]["box_number"] == (None if broken_number is False else broken_number)


@pytest.mark.parametrize("count,weight", [
    (None, None), (0, None), (-2, None), (False, None), ("未知", None),
    ("12?", None), (None, 0), (None, "NaN"), (0, -3),
])
def test_omitted_name_without_positive_numeric_evidence_breaks_inheritance(count, weight):
    result = _parse_candidate([_box(1, "衣服"), _box(2, count=count, weight=weight), _box(3)])
    assert [box["item_name"] for box in result["boxes"]] == ["衣服", "", ""]


def test_explicit_name_without_numeric_evidence_is_not_an_inheritance_anchor():
    result = _parse_candidate([_box(1, "衣服", None, None), _box(2)])
    assert result["boxes"][1]["item_name"] == ""


@pytest.mark.parametrize("uncertain_name", ["未知", "衣服?", "看不清", "不详", "-", "N/A", "疑似鞋子", "同上？"])
def test_uncertain_name_is_preserved_but_cannot_supply_later_omitted_names(uncertain_name):
    result = _parse_candidate([_box(1, "衣服"), _box(2, uncertain_name), _box(3)])
    assert result["boxes"][1]["item_name"] == uncertain_name
    assert result["boxes"][2]["item_name"] == ""


@pytest.mark.parametrize("mark", ["", None, "未知"])
def test_missing_or_uncertain_batch_mark_prevents_cross_batch_inheritance(mark):
    result = _parse_candidate([_box(1, "衣服"), _box(2)], mark=mark, warnings=["存在多个唛头，请拆分核对"])
    assert result["boxes"][1]["item_name"] == ""
    assert result["warnings"] == ["存在多个唛头，请拆分核对"]


def test_explicit_row_mark_conflict_disables_inheritance_even_if_top_level_mark_is_present():
    result = _parse_candidate([{**_box(1, "衣服"), "mark": "ABC"}, {**_box(2), "mark": "XYZ"}])
    assert result["boxes"][1]["item_name"] == ""
    assert any("不同唛头" in warning for warning in result["warnings"])


def test_numeric_strings_are_evidence_without_changing_transcribed_values():
    result = _parse_candidate([_box("1", "衣服", "12"), _box("2", count=None, weight="8.5")])
    assert result["boxes"][1] == {"box_number": "2", "item_name": "衣服", "count": None, "weight": "8.5"}


def test_explicit_new_name_after_gap_can_anchor_a_new_continuous_run():
    result = _parse_candidate([_box(1, "衣服"), _box(3, "鞋子"), _box(4)])
    assert [box["item_name"] for box in result["boxes"]] == ["衣服", "鞋子", "鞋子"]
    assert len(result["warnings"]) == 1
    assert "第 4 箱" in result["warnings"][0]


@pytest.mark.parametrize("content", ["", "not-json", "[]", '{"boxes": {}}', '{"boxes": [1]}'])
def test_malformed_output_is_never_returned_as_valid_draft(monkeypatch, content):
    _response(monkeypatch, content)
    with pytest.raises(service.IntakeRecognitionError):
        service.recognize_paper_photos([IMAGE])


def test_truncated_response_is_rejected(monkeypatch):
    _response(monkeypatch, '{"boxes": []}', finish_reason="length")
    with pytest.raises(service.IntakeRecognitionError, match="未完整结束"):
        service.recognize_paper_photos([IMAGE])


@pytest.mark.parametrize("status,message", [(401, "密钥"), (402, "余额"), (429, "繁忙"), (500, "暂时失败")])
def test_http_errors_are_safe_and_actionable(monkeypatch, status, message):
    call = _response(monkeypatch, "")
    call.side_effect = HTTPError("https://api.deepseek.com/chat/completions", status, "provider details", {}, None)
    with pytest.raises(service.IntakeRecognitionError, match=message) as caught:
        service.recognize_paper_photos([IMAGE])
    assert "test-key" not in str(caught.value)
    assert "provider details" not in str(caught.value)


def test_network_error_keeps_retry_message(monkeypatch):
    call = _response(monkeypatch, "")
    call.side_effect = URLError("offline")
    with pytest.raises(service.IntakeRecognitionError, match="照片已保留"):
        service.recognize_paper_photos([IMAGE])


def test_text_only_model_is_rejected_before_sending(monkeypatch):
    call = _response(monkeypatch, "")
    _provider_config(deepseek_model="deepseek-v4-pro")
    with pytest.raises(service.IntakeRecognitionError, match="不支持图片"):
        service.recognize_paper_photos([IMAGE])
    call.assert_not_called()


def test_photo_limits_checked_before_network(monkeypatch):
    call = _response(monkeypatch, "")
    with pytest.raises(service.IntakeRecognitionError, match="1 至 8"):
        service.recognize_paper_photos([IMAGE] * 9)
    with pytest.raises(service.IntakeRecognitionError, match="格式无效"):
        service.recognize_paper_photos([{**IMAGE, "mime_type": "text/html"}])
    call.assert_not_called()
