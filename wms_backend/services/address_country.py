"""Validate country names and spelling corrections against source evidence."""

from __future__ import annotations

from functools import lru_cache
import re
import unicodedata

import pycountry


MAX_COUNTRY_NAME_CHARS = 128


def evidence_text(value: str) -> str:
    """Compare names using the address recognizer's existing normalization."""
    return "".join(
        char for char in unicodedata.normalize("NFKC", value).casefold()
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    )


def verbatim_occurs(value: str, source: str) -> bool:
    """Require a source token rather than a substring inside another word."""
    prefix = r"(?<![A-Za-z0-9])" if value[:1].isascii() and value[:1].isalnum() else ""
    suffix = r"(?![A-Za-z0-9])" if value[-1:].isascii() and value[-1:].isalnum() else ""
    return bool(value) and re.search(prefix + re.escape(value) + suffix, source, re.IGNORECASE) is not None


def clear_country_line(value: str, candidate: dict, source: str) -> bool:
    """Disambiguate state codes with a country label or final country line."""
    label = r"(?:\bcountry(?:\s*(?:code|name))?|国家(?:/地区)?|国别)\s*[:：]\s*"
    if re.search(label + re.escape(value) + r"\s*(?:$|[,;\n])", source, re.IGNORECASE):
        return True
    contact = {
        evidence_text(candidate[field]) for field in ("mail", "receiver_phone")
        if isinstance(candidate.get(field), str) and candidate[field].strip()
    }
    lines = [line.strip() for line in source.splitlines() if line.strip() and evidence_text(line) not in contact]
    return bool(lines) and evidence_text(lines[-1]) == evidence_text(value)


@lru_cache(maxsize=1)
def _iso_catalogue() -> dict[str, tuple[str, ...]]:
    return {
        country.alpha_2: tuple(
            name for attribute in ("name", "official_name", "common_name")
            if isinstance(name := getattr(country, attribute, None), str) and name
        )
        for country in pycountry.countries
    }


def _name_catalogue(aliases: dict) -> dict[str, set[str]]:
    names: dict[str, set[str]] = {}
    for code, iso_names in _iso_catalogue().items():
        for name in (*iso_names, *aliases.get(code, ())):
            if isinstance(name, str) and name:
                names.setdefault(evidence_text(name), set()).add(code)
    return names


def _within_one_edit(first: str, second: str) -> bool:
    """Allow one insertion, deletion, substitution or adjacent transposition."""
    if abs(len(first) - len(second)) > 1:
        return False
    if len(first) == len(second):
        differences = [index for index, pair in enumerate(zip(first, second)) if pair[0] != pair[1]]
        if len(differences) <= 1:
            return True
        if len(differences) != 2:
            return False
        left, right = differences
        return right == left + 1 and first[left] == second[right] and first[right] == second[left]
    shorter, longer = (first, second) if len(first) < len(second) else (second, first)
    index = next((index for index, pair in enumerate(zip(shorter, longer)) if pair[0] != pair[1]), len(shorter))
    return shorter[index:] == longer[index + 1:]


def _country_evidence_source(source: str) -> str:
    # Country words inside contact details and links are not address evidence.
    return re.sub(r"https?://\S+|[^\s@]+@[^\s@]+", " ", source, flags=re.IGNORECASE)


def country_grounded(country: str, candidate: dict, source: str, aliases: dict) -> bool:
    """Verify the ISO/name pair and its verbatim, optionally misspelled source.

    Corrections require a unique one-edit match to a complete ASCII country
    name. Short codes never use fuzzy matching. Exact names support the ISO
    catalogue and supplied language/shipping aliases.
    """
    if not isinstance(country, str) or not isinstance(candidate, dict) or not isinstance(source, str):
        return False
    country = country.upper()
    if country not in _iso_catalogue():
        return False
    name, proof = candidate.get("country_name"), candidate.get("country_source")
    if not all(isinstance(value, str) and 0 < len(value.strip()) <= MAX_COUNTRY_NAME_CHARS for value in (name, proof)):
        return False
    name, proof = name.strip(), proof.strip()
    names = _name_catalogue(aliases)
    if names.get(evidence_text(name)) != {country}:
        return False

    evidence_source = _country_evidence_source(source)
    if not verbatim_occurs(proof, evidence_source):
        return False
    other_components = {
        evidence_text(candidate[field]) for field in ("province", "city", "address", "receiver")
        if isinstance(candidate.get(field), str) and candidate[field].strip()
    }
    normalized_proof = evidence_text(proof)
    short_code = (
        len(proof) == 2 and proof.isascii() and proof.isalpha()
    ) or len(normalized_proof) == 2 and normalized_proof.upper() in _iso_catalogue()
    if (short_code or evidence_text(proof) in other_components) and not clear_country_line(proof, candidate, evidence_source):
        return False

    exact = names.get(normalized_proof, set()) | {
        code for code in _iso_catalogue() if code.casefold() == normalized_proof
    }
    if exact:
        return exact == {country}
    if len(normalized_proof) < 4 or not normalized_proof.isascii() or not normalized_proof.isalpha():
        return False
    matching_codes = {
        code for alias, codes in names.items()
        if len(alias) >= 4 and alias.isascii() and alias.isalpha() and _within_one_edit(normalized_proof, alias)
        for code in codes
    }
    return matching_codes == {country}
