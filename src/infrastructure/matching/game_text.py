"""Shared lexical boundaries for game detection and inclusion context."""

import re

from infrastructure.matching.platform_lexical_matcher import PlatformLexicalMatcher


def split_game_text(
    text: str,
    separator: re.Pattern[str],
    protected_spans: tuple[tuple[int, int], ...],
) -> tuple[str, ...]:
    """Split clauses without cutting a known title at its internal punctuation.

    Protected spans refer to the normalized full text. Normalizing each prefix
    maps a raw separator back to that coordinate system, including accents and
    repeated whitespace. Returned chunks use the same lexical normalization.
    """
    normalize = PlatformLexicalMatcher.normalize_text
    chunks: list[str] = []
    start = 0
    for boundary in separator.finditer(text):
        position = len(normalize(text[: boundary.start()]))
        if any(left < position < right for left, right in protected_spans):
            continue
        chunk = normalize(text[start : boundary.start()])
        if chunk:
            chunks.append(chunk)
        start = boundary.end()
    chunk = normalize(text[start:])
    if chunk:
        chunks.append(chunk)
    return tuple(chunks)
