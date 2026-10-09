import logging
import requests
import json
import os
import toml

env = toml.load("./env.toml")
endpoint = "https://api.17track.net/track/v2.2"
token = env.get("17track_token", "")
logger = logging.getLogger(__name__)

headers = {
    "Content-Type": "application/json",
    "17token": token,
}

"""
    tuple[0]: cargo_uid
    tuple[1]: waybill_id
"""


def registerTrack(_numbers: list[tuple]):
    length = len(_numbers)
    loop_times = length // 40
    rest = length % 40

    def register_loop(numbers):
        res = requests.post(
            url=f"{endpoint}/register",
            json=[
                {"number": waybill_id, "tag": cargo_uid}
                for (cargo_uid, waybill_id) in numbers
            ],
            headers=headers,
        )
        res = res.json()

        if res["code"] != 0:
            raise Exception(
                {
                    "code": 501,
                    "message": "17track registration failed",
                    "data": res["code"],
                }
            )
        if len(res["data"]["rejected"]) != 0:
            raise Exception(
                {
                    "code": 502,
                    "message": "17track rejected",
                    "data": res["data"]["rejected"],
                    "accepted": res["data"]["accepted"],
                }
            )
        return True

    for l in range(loop_times):
        number_list = _numbers[l * 40 : (l + 1) * 40]
        register_loop(number_list)

    register_loop(_numbers[-rest:])
    
def getTrackInfo(_waybill_numbers: list):
    length = len(_waybill_numbers)
    loop_times = length // 40
    rest = length % 40

    def track_info_loop(waybill_numbers):
        logger.error(waybill_numbers)
        res = requests.post(
            url=f"{endpoint}/getTrackInfo",
            json=[{"number": number} for number in waybill_numbers],
            headers=headers,
        )
        res = res.json()
        if res["code"] != 0:
            raise Exception(
                {
                    "code": 501,
                    "message": "17track registration failed",
                    "data": res["code"],
                }
            )
        if len(res["data"]["rejected"]) != 0:
            logger.error("getTrackInfo")
            logger.error(f"rejeted list: {res['data']['rejected']}")

            return res["data"]["accepted"]
        if len(res.get("errors", [])) != 0:
            raise Exception(
                {"code": 503, "message": "17track error", "data": res["data"]["errors"]}
            )
        return res["data"]["accepted"]

    result = []

    for l in range(loop_times):
        number_list = _waybill_numbers[l * 40 : (l + 1) * 40]
        result.extend(track_info_loop(number_list))

    result.extend(track_info_loop(_waybill_numbers[-rest:]))

    return result


class TrackingQueryError(Exception):
    """A controlled tracking failure that contains no request credentials."""

    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code
        self.msg = msg

    @classmethod
    def from_provider_code(cls, code):
        if code == 429:
            return cls(429, "物流服务请求过于频繁，请稍后重试")
        if code == -18019902:
            return cls(404, "此转单号尚未注册物流追踪")
        if code in {-18010010, -18010011, -18010012, -18010013, -18019903}:
            return cls(400, "转单号或承运商参数无效")
        return cls(502, "物流服务暂时不可用，请稍后重试")


def query_tracking_info(waybill_id: str, carrier: int | None = None) -> dict:
    """Query one number without registration, retries, cache or database writes.

    Keep accepted and rejected results intact so the service can distinguish
    missing registrations from invalid inputs and usable tracking results.
    """
    number = {"number": waybill_id}
    if carrier is not None:
        number["carrier"] = carrier
    return _query_tracking_numbers([number])


def query_tracking_infos(waybill_ids: list[str]) -> dict:
    """Query one batch of 1–40 numbers without registration or retries."""
    if (not isinstance(waybill_ids, list) or not 1 <= len(waybill_ids) <= 40
            or any(not isinstance(number, str) or not number.strip() for number in waybill_ids)):
        raise TrackingQueryError(400, "每批物流查询需要1到40个转单号")
    return _query_tracking_numbers([{"number": number} for number in waybill_ids])


def _query_tracking_numbers(numbers: list[dict]) -> dict:
    try:
        response = requests.post(
            url=f"{endpoint}/getTrackInfo",
            json=numbers,
            headers=headers,
            timeout=(3, 10),
            allow_redirects=False,
        )
    except requests.Timeout:
        raise TrackingQueryError(504, "物流查询超时，请稍后重试") from None
    except requests.RequestException:
        raise TrackingQueryError(502, "物流服务暂时不可用，请稍后重试") from None
    if response.status_code == 429:
        raise TrackingQueryError.from_provider_code(429)
    if not 200 <= response.status_code < 300:
        raise TrackingQueryError(502, "物流服务暂时不可用，请稍后重试")
    try:
        result = response.json()
    except ValueError:
        raise TrackingQueryError(502, "物流服务返回无效响应") from None
    if not isinstance(result, dict) or type(result.get("code")) is not int:
        raise TrackingQueryError(502, "物流服务返回无效响应")
    if result["code"] != 0:
        raise TrackingQueryError.from_provider_code(result["code"])
    data = result.get("data")
    if not isinstance(data, dict):
        raise TrackingQueryError(502, "物流服务返回无效响应")
    for field in ("accepted", "rejected"):
        rows = data.get(field)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise TrackingQueryError(502, "物流服务返回无效响应")
    for collection in (result, data):
        errors = collection.get("errors", [])
        if not isinstance(errors, list) or any(
                not isinstance(error, dict) or type(error.get("code")) is not int
                for error in errors):
            raise TrackingQueryError(502, "物流服务返回无效响应")
    return result
