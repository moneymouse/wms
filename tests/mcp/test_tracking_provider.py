"""Mock-only tests of bounded 17TRACK batch requests and safe failures."""
from unittest.mock import Mock

import pytest
import requests

from utils import l7track


@pytest.fixture
def provider(monkeypatch):
    post = Mock(side_effect=AssertionError("Real provider access is forbidden"))
    monkeypatch.setattr(l7track.requests, "post", post)
    monkeypatch.setattr(l7track, "endpoint", "https://provider.example/track/v2.2")
    monkeypatch.setattr(l7track, "headers", {"17token": "test-only"})
    return post


def respond(post, *, payload=None, status=200):
    post.side_effect = None
    post.return_value = Mock(status_code=status)
    post.return_value.json.return_value = payload if payload is not None else {
        "code": 0, "data": {"accepted": [], "rejected": []},
    }


def test_batch_queries_once_with_timeout_and_keeps_per_number_results(provider):
    payload = {"code": 0, "data": {
        "accepted": [{"number": "000123", "track_info": None}],
        "rejected": [{"number": "000456", "error": {"code": -18019902}}],
    }}
    respond(provider, payload=payload)
    assert l7track.query_tracking_infos(["000123", "000456"]) is payload
    provider.assert_called_once_with(
        url="https://provider.example/track/v2.2/getTrackInfo",
        json=[{"number": "000123"}, {"number": "000456"}], headers=l7track.headers,
        timeout=(3, 10), allow_redirects=False,
    )


@pytest.mark.parametrize("numbers", [[], ["X"] * 41, [""], [None], "000123", None])
def test_invalid_batches_do_not_contact_provider(provider, numbers):
    with pytest.raises(l7track.TrackingQueryError) as caught:
        l7track.query_tracking_infos(numbers)
    assert caught.value.code == 400
    provider.assert_not_called()


@pytest.mark.parametrize("exception,code", [
    (requests.ConnectTimeout("private-request"), 504),
    (requests.ReadTimeout("private-request"), 504),
    (requests.ConnectionError("private-request"), 502),
])
def test_network_failures_are_bounded_and_do_not_expose_details(provider, exception, code):
    provider.side_effect = exception
    with pytest.raises(l7track.TrackingQueryError) as caught:
        l7track.query_tracking_infos(["000123"])
    assert caught.value.code == code
    assert "private-request" not in caught.value.msg
    assert provider.call_count == 1


@pytest.mark.parametrize("http_status,code", [(302, 502), (401, 502), (429, 429), (500, 502)])
def test_http_errors_and_redirects_are_not_successful_tracking(provider, http_status, code):
    respond(provider, status=http_status)
    with pytest.raises(l7track.TrackingQueryError) as caught:
        l7track.query_tracking_infos(["000123"])
    assert caught.value.code == code
    provider.return_value.json.assert_not_called()


@pytest.mark.parametrize("payload", [
    [], {"code": True}, {"code": 0, "data": None},
    {"code": 0, "data": {"accepted": [None], "rejected": []}},
    {"code": 0, "data": {"accepted": [], "rejected": {}}},
    {"code": 0, "data": {"accepted": [], "rejected": []}, "errors": [{"code": {}}]},
])
def test_malformed_response_envelopes_fail_safely(provider, payload):
    respond(provider, payload=payload)
    with pytest.raises(l7track.TrackingQueryError) as caught:
        l7track.query_tracking_infos(["000123"])
    assert caught.value.code == 502


def test_invalid_json_does_not_expose_response_body(provider):
    respond(provider)
    provider.return_value.json.side_effect = ValueError("private-response-body")
    with pytest.raises(l7track.TrackingQueryError) as caught:
        l7track.query_tracking_infos(["000123"])
    assert caught.value.code == 502
    assert "private-response-body" not in caught.value.msg
