"""
Name normalization for sanctions screening.

CRITICAL: "Mohamed" vs "Muhammad" vs "Mohammed" MUST all match.
Pure Levenshtein distance fails here (Mohamed↔Muhammad = 62.5% similarity).
This module handles:
  1. Unicode normalization + diacritics stripping
  2. Transliteration variant mapping (Arabic, Russian, Chinese romanizations)
  3. Title/prefix/suffix removal
  4. Token-level matching for reordered names
  5. Composite scoring that combines multiple strategies

This is NOT optional cleanup — it's the difference between catching a
sanctioned entity and missing them entirely.
"""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Common transliteration variants
# ---------------------------------------------------------------------------
# Maps variant spellings → canonical form. Applied bidirectionally during
# comparison: both the query and the SDN entry are normalized.

_TRANSLITERATION_VARIANTS: dict[str, str] = {
    # Arabic name variants (the Mohamed/Muhammad problem)
    "mohamed": "muhammad",
    "mohammed": "muhammad",
    "mohamad": "muhammad",
    "mohammad": "muhammad",
    "muhamed": "muhammad",
    "muhammed": "muhammad",
    "mohamet": "muhammad",
    "mehmet": "muhammad",  # Turkish variant
    "mahmoud": "mahmud",
    "mahmood": "mahmud",
    "ahmed": "ahmad",
    "achmed": "ahmad",
    "abdel": "abd al",
    "abdul": "abd al",
    "abd-al": "abd al",
    "bin": "ibn",
    "ben": "ibn",
    "hussein": "husayn",
    "husain": "husayn",
    "hossein": "husayn",
    "hassan": "hasan",
    "hassen": "hasan",
    "ali": "ali",
    "ibrahim": "ibrahim",
    "ebrahim": "ibrahim",
    "ismail": "ismail",
    "ismael": "ismail",
    "yusuf": "yusuf",
    "yousef": "yusuf",
    "youssef": "yusuf",
    "josef": "yusuf",
    "omar": "umar",
    "osman": "uthman",
    "othman": "uthman",
    "mustafa": "mustafa",
    "mustapha": "mustafa",
    "khalil": "khalil",
    "halil": "khalil",
    # Russian transliteration variants
    "alexander": "aleksandr",
    "alexei": "aleksei",
    "alexey": "aleksei",
    "dmitry": "dmitriy",
    "dmitri": "dmitriy",
    "yuri": "yuriy",
    "yury": "yuriy",
    "sergei": "sergey",
    "sergey": "sergey",
    "mikhail": "mikhail",
    "michael": "mikhail",
    "vladimir": "vladimir",
    "volodymyr": "vladimir",  # Ukrainian variant
    "evgeny": "yevgeniy",
    "evgeni": "yevgeniy",
    # Common English variants
    "catherine": "katherine",
    "stephen": "steven",
    "geoffrey": "jeffrey",
    "philip": "phillip",
}

# Titles and prefixes to strip
_TITLES = frozenset([
    "mr", "mrs", "ms", "dr", "prof", "sir", "dame", "lord", "lady",
    "sheikh", "shaikh", "shaykh", "mullah", "haji", "hajj",
    "gen", "general", "col", "colonel", "maj", "major", "capt", "captain",
    "rev", "reverend", "hon", "honorable",
])

# Suffixes to strip
_SUFFIXES = frozenset([
    "jr", "sr", "ii", "iii", "iv", "esq", "phd", "md",
])


def normalize_name(name: str) -> str:
    """
    Normalize a name for sanctions matching.

    Steps:
      1. Unicode NFKD decomposition → strip combining marks (diacritics)
      2. Lowercase
      3. Remove punctuation (hyphens, periods, commas, quotes)
      4. Strip titles and suffixes
      5. Collapse whitespace
      6. Apply transliteration variant mapping

    Returns a canonical form suitable for comparison.
    """
    if not name:
        return ""

    # 1. Unicode normalization — strip diacritics
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))

    # 2. Lowercase
    text = text.lower()

    # 3. Remove punctuation but keep spaces
    text = re.sub(r"[^\w\s]", " ", text)

    # 4. Tokenize
    tokens = text.split()

    # 5. Strip titles and suffixes
    tokens = [t for t in tokens if t not in _TITLES and t not in _SUFFIXES]

    # 6. Apply transliteration variant mapping
    tokens = [_TRANSLITERATION_VARIANTS.get(t, t) for t in tokens]

    # 7. Collapse and return
    return " ".join(tokens).strip()


def normalize_name_tokens(name: str) -> list[str]:
    """Return sorted normalized tokens for token-level comparison."""
    normalized = normalize_name(name)
    return sorted(normalized.split())


def compute_match_confidence(
    query_name: str,
    candidate_name: str,
    trigram_similarity: float = 0.0,
    levenshtein_distance: int | None = None,
    soundex_match: bool = False,
) -> float:
    """
    Compute a composite match confidence from multiple signals.

    Strategy:
      1. Normalized exact match → 1.0
      2. Token overlap score (handles reordered names)
      3. Trigram similarity from PostgreSQL
      4. Levenshtein-based similarity on normalized forms
      5. Soundex bonus (phonetic match)

    The maximum score across all strategies wins.
    Mohamed vs Muhammad:
      - Raw Levenshtein: 62.5% (would miss at 85% threshold)
      - After normalization: both → "muhammad" → 100% (caught)
    """
    norm_query = normalize_name(query_name)
    norm_candidate = normalize_name(candidate_name)

    if not norm_query or not norm_candidate:
        return 0.0

    scores: list[float] = []

    # --- Strategy 1: Exact match after normalization ---
    if norm_query == norm_candidate:
        return 1.0

    # --- Strategy 2: Token overlap (Jaccard on sorted tokens) ---
    query_tokens = set(normalize_name_tokens(query_name))
    candidate_tokens = set(normalize_name_tokens(candidate_name))
    if query_tokens and candidate_tokens:
        intersection = query_tokens & candidate_tokens
        union = query_tokens | candidate_tokens
        jaccard = len(intersection) / len(union)
        scores.append(jaccard)

    # --- Strategy 3: Trigram similarity (from PostgreSQL) ---
    if trigram_similarity > 0:
        scores.append(trigram_similarity)

    # --- Strategy 4: Levenshtein on normalized forms ---
    if levenshtein_distance is not None:
        max_len = max(len(norm_query), len(norm_candidate), 1)
        lev_sim = 1.0 - (levenshtein_distance / max_len)
        scores.append(max(0.0, lev_sim))
    else:
        # Compute in Python if not provided by DB
        lev_dist = _levenshtein(norm_query, norm_candidate)
        max_len = max(len(norm_query), len(norm_candidate), 1)
        lev_sim = 1.0 - (lev_dist / max_len)
        scores.append(max(0.0, lev_sim))

    # --- Strategy 5: Soundex bonus ---
    if soundex_match:
        # Phonetic match adds a floor — two names that sound alike
        # should never score below 0.70
        scores.append(0.70)

    return round(max(scores) if scores else 0.0, 4)


def _levenshtein(s1: str, s2: str) -> int:
    """Pure-Python Levenshtein distance. Used as fallback when not provided by DB."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)

    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]
