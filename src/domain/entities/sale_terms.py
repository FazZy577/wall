"""Conservative, marketplace-independent evidence about a sale's units and price."""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import DetectedGame


class PriceBasis(StrEnum):
    TOTAL = "total"
    PER_UNIT = "per_unit"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class SaleTerms:
    quantities: tuple[int, ...]
    price_basis: PriceBasis
    content_resolved: bool

    @property
    def total_units(self) -> int:
        return sum(self.quantities)

    @property
    def resolved(self) -> bool:
        return self.content_resolved and self.price_basis is PriceBasis.TOTAL


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return " ".join(
        re.sub(
            r"[^a-z0-9]", " ", "".join(char for char in text if not unicodedata.combining(char))
        ).split()
    )


_NUMBERS = {
    "un": 1,
    "una": 1,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
}
_NUMBER = r"(?:\d+|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)"
_UNIT_PRICE = re.compile(
    r"\b(?:cada uno|cada una|cada juego|cada copia|cada unidad|"
    r"por unidad|por juego|por copia|precio unitario|unidad a|each)\b"
)
_UNCERTAIN_PRICE = re.compile(
    r"\b(?:desde|a partir de|precio a consultar|consultar precio|"
    r"precio orientativo|precio simbolico|precio por separado|"
    r"precios individuales|a elegir|por separado)\b"
)
_TOGETHER = re.compile(
    r"\b(?:lote|lot|pack|bundle|juntos|juntas|ambos|ambas|"
    r"incluye|contiene|todo por|precio total|en total)\b"
)
_CONTEXT = re.compile(
    r"\b(?:busco|buscando|cambio por|tambien vendo|no incluye|"
    r"no viene con|compatible con|referencia a)\b"
)


def _count(value: str) -> int:
    return int(value) if value.isdecimal() else _NUMBERS[value]


def assess_sale_terms(listing: CandidateListing, games: tuple[DetectedGame, ...]) -> SaleTerms:
    """Require clear total pricing and explicit quantity evidence; never infer copies
    from repeated mentions. Unsupported wording remains unresolved.
    """
    raw = f"{listing.title}\n{listing.description}"
    text = _normalize(raw)
    active_clauses: list[str] = []
    names = {
        _normalize(value) for game in games for value in (game.matched_text, game.canonical_name)
    } - {""}
    for clause in re.split(r"[;\n]|\.(?!\d)", raw):
        normalized = _normalize(clause)
        if _CONTEXT.match(normalized):
            continue
        if re.search(r"\b(?:vendido|disponible) por separado\b", normalized) and not any(
            re.search(rf"\b{re.escape(name)}\b", normalized) for name in names
        ):
            continue
        active_clauses.append(clause)
    price_text = _normalize(" ".join(active_clauses))
    price_text = re.sub(r"\bdlcs? (?:disponible|vendido) por separado\b", "", price_text)
    price_basis = PriceBasis.TOTAL
    if _UNIT_PRICE.search(price_text):
        price_basis = PriceBasis.PER_UNIT
    elif _UNCERTAIN_PRICE.search(price_text) or listing.price <= 0:
        price_basis = PriceBasis.UNRESOLVED
    # An explicit textual total must agree with the structured asking price.
    for value in re.findall(
        r"(\d+(?:[.,]\d{1,2})?)\s*(?:€|euros?|EUR)(?!\w)", " ".join(active_clauses), re.I
    ):
        if Decimal(value.replace(",", ".")) != listing.price:
            price_basis = PriceBasis.UNRESOLVED

    quantities: list[int] = []
    resolved = re.search(
        r"(?:[-−]\s*\d+|\d+[.,]\d+)\s*(?:copias|unidades|ejemplares)\b", raw, re.I
    ) is None
    for game in games:
        variants = {_normalize(game.matched_text), _normalize(game.canonical_name)} - {""}
        pattern = re.compile(
            r"\b(?:"
            + "|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True))
            + r")\b"
        )
        counts: set[int] = set()
        reliable_occurrence = False
        contextual_occurrence = False
        for section in (listing.title, listing.description):
            for raw_clause in re.split(r"[.;\n]", section):
                clause = _normalize(raw_clause)
                for mention in pattern.finditer(clause):
                    before, after = clause[: mention.start()], clause[mention.end() :]
                    if _CONTEXT.search(before):
                        contextual_occurrence = True
                        continue
                    reliable_occurrence = True
                    for platform_name in (game.platform.value, game.platform.value.removeprefix("Nintendo ")):
                        after = re.sub(rf"^\s+{re.escape(_normalize(platform_name))}\b", "", after)
                    prefix = re.search(
                        rf"\b({_NUMBER})\s+(?:copias|unidades|ejemplares)\s+(?:de\s+)?$", before
                    )
                    suffix = re.match(
                        rf"\s+(?:x\s*({_NUMBER})|({_NUMBER})\s+(?:copias|unidades|ejemplares))\b",
                        after,
                    )
                    multiplier = re.search(rf"\b({_NUMBER})\s*x\s*$", before)
                    quantity_prefix = prefix or multiplier
                    if quantity_prefix is not None:
                        counts.add(_count(quantity_prefix.group(1)))
                    if suffix:
                        counts.add(_count(suffix.group(1) or suffix.group(2)))
        if contextual_occurrence and not reliable_occurrence:
            resolved = False
        if len(counts) > 1 or any(count < 1 or count > 100 for count in counts):
            resolved = False
        quantities.append(
            next(iter(counts)) if len(counts) == 1 and all(1 <= n <= 100 for n in counts) else 1
        )

    units = sum(quantities)
    if units > 1 and not (
        _TOGETHER.search(text)
        or "+" in raw
        or any(q > 1 for q in quantities)
        or re.search(rf"\b{_NUMBER}\s+(?:juegos|games)\b", text)
    ):
        resolved = False
    # Quantities stated for the whole bundle must match its resolved contents.
    for section in (listing.title, listing.description):
        for raw_clause in re.split(r"[.;\n]", section):
            clause = _normalize(raw_clause)
            if _CONTEXT.search(clause):
                continue
            for match in re.finditer(rf"\b({_NUMBER})\s+juegos\b", clause):
                if _count(match.group(1)) != units:
                    resolved = False
            if re.search(
                r"\b(?:otros? juegos?|mas juegos|varias copias|varias unidades|etc)\b", clause
            ):
                resolved = False
    # Unassigned copy counts must not silently become one copy of each title.
    declared_copies = re.findall(rf"\b({_NUMBER})\s+(?:copias|unidades|ejemplares)\b", text)
    unassigned_multiplier = re.search(r"\b(?:x\s*\d+|\d+\s*x)\b", text)
    if (declared_copies or unassigned_multiplier) and all(q == 1 for q in quantities):
        resolved = False
    # Inspect explicit item lists for unmatched content. Known names are removed
    # before sale vocabulary, so there is no whitelist of supported game titles.
    for section in (listing.title, listing.description):
        for clause in re.split(r"[.;\n]", section):
            normalized = _normalize(clause)
            if _CONTEXT.search(normalized):
                continue
            if not (_TOGETHER.search(normalized) or "+" in clause):
                continue
            remaining = normalized
            for name in sorted(names, key=len, reverse=True):
                remaining = re.sub(rf"\b{re.escape(name)}\b", "knownitem", remaining)
            if "knownitem" not in remaining:
                if re.match(r"^(?:incluye|contiene)\b", remaining) and not re.fullmatch(
                    r"(?:incluye|contiene) (?:la |el )?(?:caja|manual|caja y manual)", remaining
                ):
                    resolved = False
                continue
            for game in games:
                remaining = re.sub(
                    rf"\b{re.escape(_normalize(game.platform.value))}\b", "", remaining
                )
                short_platform = _normalize(game.platform.value.removeprefix("Nintendo "))
                remaining = re.sub(rf"\b{re.escape(short_platform)}\b", "", remaining)
            remaining = re.sub(r"\b(?:nintendo|playstation|play station)\b", "", remaining)
            remaining = re.sub(
                rf"\b(?:{_NUMBER}|x\d+|\d+x|knownitem|lote|lot|pack|bundle|juegos|juego|"
                r"incluye|contiene|vendo|venta|de|del|el|la|los|las|y|para|en|con|"
                r"copias|unidades|ejemplares|juntos|juntas|ambos|ambas|todo|todos|por|"
                r"total|precio|euros|euro|eur|completo|completos|buen|perfecto|estado)\b",
                "",
                remaining,
            )
            if remaining.strip():
                resolved = False
    return SaleTerms(tuple(quantities), price_basis, resolved)
