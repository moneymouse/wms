"""Enrich extracted order address fields using the server-side postal API.

The API contract was checked at https://api-ninjas.com/api/postalcode on
2026-10-03. The lookup never changes the original postal code or contact data.
"""

from __future__ import annotations

import json
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from services import intake_recognition


POSTALCODE_URL = "https://api.api-ninjas.com/v1/postalcode"
MAX_RESPONSE_BYTES = 128 * 1024
LOOKUP_TIMEOUT_SECONDS = 10
MISSING_FIELDS_WARNING = "缺少国家或邮编"
MISSING_CONFIG_WARNING = "邮编查询未配置"
BAD_CONFIG_WARNING = "邮编查询配置异常"
FAILED_LOOKUP_WARNING = "邮编查询失败"
EMPTY_LOOKUP_WARNING = "邮编无匹配结果"
BAD_RESPONSE_WARNING = "邮编查询结果异常"
AMBIGUOUS_LOOKUP_WARNING = "邮编对应多个城市"


def _normalized(value: str) -> str:
    return "".join(
        character for character in unicodedata.normalize("NFKC", value).casefold()
        if not character.isspace() and not unicodedata.category(character).startswith("P")
    )


def _warnings(value) -> list[str]:
    items = value if isinstance(value, list) else []
    return list(dict.fromkeys(
        item.strip()[:60] for item in items if isinstance(item, str) and item.strip()
    ))[:3]


def _warn(result: dict, warning: str) -> dict:
    # Keep the lookup warning visible even when extraction supplied the limit.
    warnings = result["warnings"]
    if warning not in warnings:
        result["warnings"] = warnings[:2] + [warning]
    return result


def _field(value) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return value if len(value) <= 128 and _normalized(value) else ""


def _rows(body, country: str) -> list[dict]:
    """Validate the whole response before treating a candidate as unique.

    Discarding a malformed row could leave a misleading single candidate, so
    incomplete city/region fields or mismatched countries make lookup fail.
    Duplicate city/region pairs are combined, including their region codes.
    """
    if not isinstance(body, list):
        raise ValueError()
    unique = {}
    for row in body:
        if not isinstance(row, dict) or not isinstance(row.get("country"), str):
            raise ValueError()
        if row["country"].strip().upper() != country:
            raise ValueError()
        city, region = _field(row.get("city")), _field(row.get("region"))
        if not city or not region:
            raise ValueError()
        pair = (_normalized(city), _normalized(region))
        if pair not in unique:
            unique[pair] = {"city": city, "region": region, "region_codes": set()}
        region_code = _field(row.get("region_code"))
        if region_code:
            unique[pair]["region_codes"].add(_normalized(region_code))
    return list(unique.values())


def _select(rows: list[dict], city: str, province: str):
    if len(rows) == 1:
        return rows[0]
    city = _normalized(city)
    province = _normalized(province)
    matching_cities = [row for row in rows if city and _normalized(row["city"]) == city]
    # A unique city is sufficient even if the source's province is incorrect.
    if len(matching_cities) == 1:
        return matching_cities[0]
    candidates = matching_cities or rows
    matching_regions = [
        row for row in candidates
        if province and (province == _normalized(row["region"]) or province in row["region_codes"])
    ]
    return matching_regions[0] if len(matching_regions) == 1 else None


def enrich_address(result: dict) -> dict:
    """Return a shallow copy with verified city/province and separate warnings.

    The caller supplies already grounded fields. Failures retain every field;
    only city/province are replaced by a uniquely selected postal API result.
    """
    enriched = {**result, "warnings": _warnings(result.get("warnings"))}
    if enriched["warnings"] and not any(result.get(field) for field in (
        "country", "province", "city", "zip_code", "receiver", "receiver_phone", "mail",
    )):
        # Extraction already explains an empty result; a missing-postcode
        # warning would only repeat it.
        return enriched
    country, postal_code = result.get("country"), result.get("zip_code")
    if not isinstance(country, str) or not isinstance(postal_code, str):
        return _warn(enriched, MISSING_FIELDS_WARNING)
    country, postal_code = country.strip().upper(), postal_code.strip()
    if len(country) != 2 or not country.isascii() or not country.isalpha() or not postal_code or len(postal_code) > 64:
        return _warn(enriched, MISSING_FIELDS_WARNING)
    try:
        key = intake_recognition._config("API_NINJAS_API_KEY")
    except intake_recognition.IntakeRecognitionError:
        return _warn(enriched, BAD_CONFIG_WARNING)
    if not key:
        return _warn(enriched, MISSING_CONFIG_WARNING)
    if not key.isascii() or any(ord(character) < 32 or ord(character) == 127 for character in key):
        return _warn(enriched, BAD_CONFIG_WARNING)
    request = Request(
        POSTALCODE_URL + "?" + urlencode({"country": country, "postal_code": postal_code}),
        headers={"X-Api-Key": key},
        method="GET",
    )
    try:
        with urlopen(request, timeout=LOOKUP_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            return _warn(enriched, BAD_RESPONSE_WARNING)
        rows = _rows(json.loads(raw), country)
    except HTTPError as error:
        if error.code in {401, 403}:
            warning = "邮编查询密钥无效"
        elif error.code == 429:
            warning = "邮编查询限流"
        else:
            warning = FAILED_LOOKUP_WARNING
        return _warn(enriched, warning)
    except (URLError, OSError, TimeoutError):
        return _warn(enriched, FAILED_LOOKUP_WARNING)
    except (ValueError, TypeError):
        return _warn(enriched, BAD_RESPONSE_WARNING)
    if not rows:
        return _warn(enriched, EMPTY_LOOKUP_WARNING)
    original_city, original_province = _field(result.get("city")), _field(result.get("province"))
    chosen = _select(rows, original_city, original_province)
    if chosen is not None:
        enriched["city"], enriched["province"] = chosen["city"], chosen["region"]
        return enriched
    # All candidates agreeing on a region can verify it without selecting a
    # city. Preserve both source fields if their regions still disagree.
    if len({_normalized(row["region"]) for row in rows}) == 1:
        enriched["province"] = rows[0]["region"]
    return _warn(enriched, AMBIGUOUS_LOOKUP_WARNING)
