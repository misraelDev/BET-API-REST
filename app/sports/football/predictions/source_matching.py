"""Comparación conservadora de equipos entre fuentes públicas."""

from __future__ import annotations

import re
import unicodedata

_IGNORED_TOKENS = {
    "ac",
    "afc",
    "cf",
    "club",
    "da",
    "de",
    "do",
    "fc",
    "the",
}


def normalize_team(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", text.casefold())
        if token not in _IGNORED_TOKENS
    ]
    return " ".join(tokens)


def same_team(left: str | None, right: str | None) -> bool:
    """Compara nombres sin depender de sufijos societarios.

    Acepta coincidencia exacta o que un nombre sea un subconjunto del otro
    (por ejemplo ``Pumas`` y ``Pumas UNAM``). La fecha y el partido completo
    se validan aparte para no confundir equipos distintos.
    """
    first = normalize_team(left)
    second = normalize_team(right)
    if not first or not second:
        return False
    if first == second:
        return True
    first_tokens = set(first.split())
    second_tokens = set(second.split())
    if first_tokens <= second_tokens or second_tokens <= first_tokens:
        return min(len(first_tokens), len(second_tokens)) >= 1
    union = first_tokens | second_tokens
    return bool(union) and len(first_tokens & second_tokens) / len(union) >= 0.6


def same_match(
    home_team: str | None,
    away_team: str | None,
    candidate_home: str | None,
    candidate_away: str | None,
) -> bool:
    return same_team(home_team, candidate_home) and same_team(
        away_team, candidate_away
    )


__all__ = ["normalize_team", "same_match", "same_team"]
