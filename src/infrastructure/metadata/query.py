"""Conservative extraction shared by fresh observations and backlog migration."""

import re

from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import Platform
from infrastructure.matching.platform_lexical_matcher import PlatformLexicalMatcher


def extract_metadata_query(listing: CandidateListing) -> tuple[str, Platform] | None:
    matcher = PlatformLexicalMatcher()
    title = matcher.normalize_text(listing.title)
    mentions = matcher.find_mentions(title)
    all_platforms = {m.platform for m in matcher.find_mentions(listing.title + " " + listing.description)}
    if not mentions or len(all_platforms) != 1:
        return None
    for mention in reversed(mentions):
        title = title[:mention.start] + " " + title[mention.end:]
    # Keep all numerals, subtitles and edition words; strip only an anchored selling prefix.
    query = re.sub(r"^(?:vendo|se vende|videojuego|juego)\s+", "", title.strip())
    query = " ".join(query.split())
    if not 2 <= len(query) <= 200:
        return None
    return query, mentions[0].platform


def unsupported_metadata_listing(listing: CandidateListing) -> bool:
    return bool(re.search(
        r"\b(?:digital|codigo|codigos|cuenta|descarga|dlc|demo|busco|buscando|compro)\b",
        PlatformLexicalMatcher.normalize_text(listing.title + " " + listing.description),
    ))
