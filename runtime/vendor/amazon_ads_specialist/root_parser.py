"""Literal-compatible search-term tokenization used by the existing root tool."""

from __future__ import annotations

import re


_NON_DECIMAL_PERIOD = re.compile(r"\.\D|\.$")
_PUNCTUATION = "\\`~-_=+{}|'\"[] ,/<>?;:!@#$%^&*()"
_JAPANESE_REPLACEMENTS = (
    "かしら", "までに", "くらい", "ぐらい", "だって", "ばかり", "である", "そうだ",
    "ようだ", "でおく", "ねえ", "なあ", "とも", "から", "のに", "ので", "きり",
    "より", "まで", "ほど", "だけ", "でも", "さえ", "こそ", "しか", "など", "なり",
    "やら", "ずつ", "とか", "たら", "なら", "ない", "ぬん", "です", "ごろ", "たい",
    "は", "も", "が", "を", "か", "よ", "な", "ぞ", "ぜ", "わ", "さ", "て", "と",
    "で", "に", "へ", "や", "の", "し", "ば", "ね", "だ", "た", "ありません",
    "ください", "あります", "によって", "けれども", "として", "または", "により",
    "くせに", "たって", "ながら", "ある", "けど", "では", "には", "たり", "すら",
    "なし", "ご",
)
_REPLACEMENTS = re.compile(
    f"[{re.escape(_PUNCTUATION)}]|" + "|".join(re.escape(value) for value in _JAPANESE_REPLACEMENTS)
)


def split_words(value: object) -> list[str]:
    word = "" if value is None else str(value)
    matches = list(_NON_DECIMAL_PERIOD.finditer(word))
    if matches:
        start_index = 0
        kept: list[str] = []
        for match in matches:
            kept.append(word[start_index:match.start()])
            start_index = match.start() + 1
        word = "".join(f" {part}" for part in kept)
    parts = _REPLACEMENTS.sub(" ", word).split(" ")
    result: list[str] = []
    word_location = 0
    for part in parts:
        if not part:
            continue
        word_location += 1
        if word_location > 1 and part in parts[: word_location - 1]:
            continue
        result.append(part)
    return result
