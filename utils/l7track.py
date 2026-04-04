import logging
import requests
import json
import os

# env = tomllib.load("./env.toml")
endpoint = "https://api.17track.net/track/v2.2"
token = os.environ.get("17token","SAFE_HISTORY_VALUE")# SAFE_HISTORY_VALUE
logger = logging.getLogger(__name__)

headers = {
    'Content-Type': 'application/json',
    '17token': token,
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
        print(numbers)
        res = requests.post(url=f"{endpoint}/register",
                      json=[{"number":waybill_id, "tag": cargo_uid} for (cargo_uid, waybill_id) in numbers], headers=headers)
        res = res.json()

        if res['code'] != 0:
            raise Exception({
                "code": 501,
                "message": "17track registration failed",
                "data": res['code']
            })
        if len(res['data']['rejected']) != 0:
            raise Exception({
                "code": 502,
                "message": "17track rejected",
                "data": res['data']['rejected'],
                "accepted": res['data']['accepted']
            })
        return True

    for l in range(loop_times):
        number_list = _numbers[l * 40: (l + 1) * 40]
        register_loop(number_list)

    register_loop(_numbers[-rest:])

def getTrackInfo(_waybill_numbers: list):
    length = len(_waybill_numbers)
    loop_times = length // 40
    rest = length % 40

    def track_info_loop(waybill_numbers):
        res = requests.post(url=f"{endpoint}/getTrackInfo",
                            json=[{"number": number} for number in waybill_numbers], headers=headers)
        res = res.json()
        if res['code'] != 0:
            raise Exception({
                "code": 501,
                "message": "17track registration failed",
                "data": res['code']
            })
        if len(res['data']['rejected']) != 0:
            logger.error('getTrackInfo')
            logger.error(f"rejeted list: {res['data']['rejected']}")

            return res['data']['accepted']
        if len(res.get('errors',[])) != 0:
            raise Exception({
                "code": 503,
                "message": "17track error",
                "data": res['data']['errors']
            })
        return res['data']['accepted']

    result = []

    for l in range(loop_times):
        number_list = _waybill_numbers[l * 40: (l + 1) * 40]
        result.extend(track_info_loop(number_list))

    result.extend(track_info_loop(_waybill_numbers[-rest:]))

    return result