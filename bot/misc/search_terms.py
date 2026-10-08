"""Turning what a customer typed into search words."""
import re

MAX_TERMS = 6

# Romanian s/t with a comma are the right letters; many keyboards type the cedilla forms. Both are looked up.
_CEDILLA_TO_COMMA = str.maketrans({"ş": "ș", "Ş": "Ș", "ţ": "ț", "Ţ": "Ț"})
_COMMA_TO_CEDILLA = str.maketrans({"ș": "ş", "Ș": "Ş", "ț": "ţ", "Ț": "Ţ"})
_NUMBER_UNIT = re.compile(r"(?<=\d)(?=[^\W\d_])|(?<=[^\W\d_])(?=\d)")


def split_terms(query: str) -> list[str]:
    """The words of a query, lower case, without repeats, at most ``MAX_TERMS``."""
    seen: list[str] = []
    for word in (query or "").lower().split():
        word = word.strip(".,;:!?\"'«»„“”()[]{}")
        if word and word not in seen:
            seen.append(word)
    return seen[:MAX_TERMS]


def _like(term: str) -> str:
    """LIKE pattern for a word, wildcards escaped; ``50mg`` also finds ``50 mg`` (``%`` between digits and letters)."""
    esc = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + _NUMBER_UNIT.sub("%", esc) + "%"


def term_patterns(term: str) -> list[str]:
    """Every LIKE pattern that counts as a hit for one word (comma and cedilla spellings)."""
    forms = {term.translate(_CEDILLA_TO_COMMA), term.translate(_COMMA_TO_CEDILLA)}
    return sorted({_like(f) for f in forms})
