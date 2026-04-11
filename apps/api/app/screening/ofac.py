"""
OFAC SDN integration — download, parse, load, and fuzzy-match.

Data sources (FREE, public domain):
  - SDN primary list:    https://www.treasury.gov/ofac/downloads/sdn.csv
  - Alternate names:     https://www.treasury.gov/ofac/downloads/alt.csv

The CSV files are pipe-delimited (|), not comma-delimited.

Architecture:
  1. download_sdn() — fetch SDN + ALT CSVs into memory
  2. load_sdn_to_db() — upsert into ofac_sdn_entries / ofac_sdn_alternates
  3. search_ofac() — fuzzy match using pg_trgm + name normalization + composite scoring

Fuzzy matching: NOT exact match. Uses Levenshtein distance, trigram similarity,
Soundex phonetic matching, AND transliteration normalization. Mohamed/Muhammad/
Mohammed all match because the name_utils layer normalizes them to the same
canonical form BEFORE comparison.

Weekly auto-update: call refresh_sdn() from a cron endpoint.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
from datetime import datetime
from typing import Any

import httpx

from app.screening.models import ScreeningMatch
from app.screening.name_utils import compute_match_confidence, normalize_name

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OFAC download URLs
# ---------------------------------------------------------------------------

SDN_CSV_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"
ALT_CSV_URL = "https://www.treasury.gov/ofac/downloads/alt.csv"
OFAC_SEARCH_BASE_URL = "https://sanctionslist.ofac.treas.gov/Home/SdnList"

# Match confidence threshold — 0.85 per spec
MATCH_THRESHOLD = 0.85


# ---------------------------------------------------------------------------
# Download SDN files
# ---------------------------------------------------------------------------


async def download_sdn_csv(
    url: str = SDN_CSV_URL,
    timeout: float = 60.0,
) -> str:
    """Download the OFAC SDN CSV file. Returns raw text content."""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


def _detect_delimiter(raw_csv: str) -> str:
    """Auto-detect CSV delimiter: pipe for legacy Treasury.gov, comma for new API."""
    first_line = raw_csv.split("\n", 1)[0]
    if "|" in first_line:
        return "|"
    return ","


def parse_sdn_csv(raw_csv: str) -> list[dict[str, str]]:
    """
    Parse the SDN CSV (auto-detects pipe or comma delimiter).

    Columns (from OFAC documentation):
      0: ent_num — Entity number (unique per entry)
      1: SDN_Name — Primary name
      2: SDN_Type — individual, entity, vessel, aircraft
      3: Program — Sanctions program (e.g., SDGT, IRAN)
      4: Title
      5: Call_Sign
      6: Vess_type
      7: Tonnage
      8: GRT
      9: Vess_flag
     10: Vess_owner
     11: Remarks
    """
    delimiter = _detect_delimiter(raw_csv)
    reader = csv.reader(io.StringIO(raw_csv), delimiter=delimiter)
    entries: list[dict[str, str]] = []

    for row in reader:
        if len(row) < 2:
            continue
        ent_num = row[0].strip()
        if not ent_num.isdigit():
            continue

        sdn_name = row[1].strip().rstrip('"').lstrip('"')
        if not sdn_name or sdn_name == "-0-":
            continue

        entry = {
            "ent_num": ent_num,
            "sdn_name": sdn_name,
            "sdn_name_normalized": normalize_name(sdn_name),
            "sdn_type": _classify_type(row[2].strip() if len(row) > 2 else ""),
            "program": row[3].strip() if len(row) > 3 else "",
            "title": row[4].strip() if len(row) > 4 else "",
            "remarks": row[11].strip() if len(row) > 11 else "",
        }
        entries.append(entry)

    return entries


def parse_alt_csv(raw_csv: str) -> list[dict[str, str]]:
    """
    Parse the alternate names CSV (auto-detects pipe or comma delimiter).

    Columns:
      0: ent_num — Entity number (FK to sdn_entries)
      1: alt_num — Alternate name number
      2: alt_type — 'aka', 'fka', 'nka'
      3: alt_name — The alternate name
      4: alt_remarks
    """
    delimiter = _detect_delimiter(raw_csv)
    reader = csv.reader(io.StringIO(raw_csv), delimiter=delimiter)
    entries: list[dict[str, str]] = []

    for row in reader:
        if len(row) < 4:
            continue
        ent_num = row[0].strip()
        if not ent_num.isdigit():
            continue

        alt_name = row[3].strip().rstrip('"').lstrip('"')
        if not alt_name or alt_name == "-0-":
            continue

        entry = {
            "ent_num": ent_num,
            "alt_num": row[1].strip(),
            "alternate_type": row[2].strip().lower(),
            "alternate_name": alt_name,
            "alternate_name_normalized": normalize_name(alt_name),
        }
        entries.append(entry)

    return entries


def _classify_type(raw: str) -> str:
    """Map OFAC SDN_Type field to a canonical type."""
    raw_lower = raw.strip(' "').lower()
    if "individual" in raw_lower:
        return "individual"
    if "entity" in raw_lower:
        return "entity"
    if "vessel" in raw_lower:
        return "vessel"
    if "aircraft" in raw_lower:
        return "aircraft"
    return raw_lower or "unknown"


# ---------------------------------------------------------------------------
# Load into Supabase
# ---------------------------------------------------------------------------


async def load_sdn_to_db(
    supabase_url: str,
    supabase_key: str,
    sdn_entries: list[dict[str, str]],
    alt_entries: list[dict[str, str]],
) -> dict[str, int]:
    """
    Upsert SDN entries and alternates into Supabase.

    Performs a full refresh: truncate + insert for atomicity.
    Returns counts of entries loaded.
    """
    try:
        from supabase import acreate_client
    except ImportError:
        logger.error("supabase-py not installed — cannot load SDN data")
        return {"entries": 0, "alternates": 0}

    db = await acreate_client(supabase_url, supabase_key)

    # Truncate existing data (atomic refresh)
    await db.table("ofac_sdn_alternates").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    await db.table("ofac_sdn_entries").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()

    # Insert primary entries in batches
    batch_size = 500
    entry_count = 0
    for i in range(0, len(sdn_entries), batch_size):
        batch = sdn_entries[i : i + batch_size]
        rows = [
            {
                "ent_num": int(e["ent_num"]),
                "sdn_name": e["sdn_name"],
                "sdn_name_normalized": e["sdn_name_normalized"],
                "sdn_type": e["sdn_type"],
                "program": e["program"],
                "title": e["title"],
                "remarks": e["remarks"],
            }
            for e in batch
        ]
        await db.table("ofac_sdn_entries").upsert(rows, on_conflict="ent_num").execute()
        entry_count += len(rows)

    # Build set of valid ent_nums for FK constraint
    valid_ent_nums = {int(e["ent_num"]) for e in sdn_entries}

    # Insert alternates in batches (only for valid ent_nums)
    alt_count = 0
    for i in range(0, len(alt_entries), batch_size):
        batch = alt_entries[i : i + batch_size]
        rows = [
            {
                "ent_num": int(a["ent_num"]),
                "alt_num": int(a["alt_num"]),
                "alternate_name": a["alternate_name"],
                "alternate_name_normalized": a["alternate_name_normalized"],
                "alternate_type": a["alternate_type"],
            }
            for a in batch
            if int(a["ent_num"]) in valid_ent_nums
        ]
        if rows:
            await db.table("ofac_sdn_alternates").upsert(
                rows, on_conflict="ent_num,alt_num"
            ).execute()
            alt_count += len(rows)

    # Update metadata
    source_hash = hashlib.sha256(
        f"{entry_count}:{alt_count}:{datetime.utcnow().isoformat()}".encode()
    ).hexdigest()

    await db.table("ofac_sdn_meta").upsert(
        {
            "id": 1,
            "last_refreshed": datetime.utcnow().isoformat(),
            "entry_count": entry_count,
            "alt_count": alt_count,
            "source_hash": source_hash,
            "updated_at": datetime.utcnow().isoformat(),
        },
        on_conflict="id",
    ).execute()

    logger.info(
        "OFAC SDN loaded: %d entries, %d alternates",
        entry_count,
        alt_count,
    )
    return {"entries": entry_count, "alternates": alt_count}


# ---------------------------------------------------------------------------
# Full refresh: download + load
# ---------------------------------------------------------------------------


async def refresh_sdn(
    supabase_url: str,
    supabase_key: str,
) -> dict[str, int]:
    """Download fresh SDN data from OFAC and reload into Supabase."""
    logger.info("Starting OFAC SDN refresh…")

    sdn_raw = await download_sdn_csv(SDN_CSV_URL)
    alt_raw = await download_sdn_csv(ALT_CSV_URL)

    sdn_entries = parse_sdn_csv(sdn_raw)
    alt_entries = parse_alt_csv(alt_raw)

    logger.info("Parsed %d SDN entries, %d alternates", len(sdn_entries), len(alt_entries))

    counts = await load_sdn_to_db(supabase_url, supabase_key, sdn_entries, alt_entries)
    logger.info("OFAC SDN refresh complete: %s", counts)
    return counts


# ---------------------------------------------------------------------------
# Fuzzy search
# ---------------------------------------------------------------------------


async def search_ofac(
    name: str,
    supabase_url: str,
    supabase_key: str,
    threshold: float = MATCH_THRESHOLD,
) -> list[ScreeningMatch]:
    """
    Fuzzy-match a name against the OFAC SDN list.

    Returns matches above the confidence threshold (default 85%).
    Uses PostgreSQL pg_trgm + Soundex for candidate retrieval, then
    Python-side name normalization + composite scoring for final ranking.

    This catches Mohamed/Muhammad/Mohammed because both sides are
    normalized to the same canonical form before scoring.
    """
    try:
        from supabase import acreate_client
    except ImportError:
        logger.error("supabase-py not installed — OFAC search unavailable")
        return []

    normalized_query = normalize_name(name)
    if not normalized_query:
        return []

    db = await acreate_client(supabase_url, supabase_key)

    # Call the PostgreSQL fuzzy search function
    # Low DB threshold (0.20) to catch phonetic/transliteration matches;
    # Python re-scores with full name normalization
    try:
        response = await db.rpc(
            "search_ofac_sdn",
            {
                "query_name": normalized_query,
                "min_similarity": 0.20,
                "max_results": 50,
            },
        ).execute()
    except Exception as exc:
        logger.error("OFAC SDN search failed: %s", exc)
        return []

    if not response.data:
        return []

    # Re-score with full Python name normalization + composite scoring
    matches: list[ScreeningMatch] = []
    for row in response.data:
        confidence = compute_match_confidence(
            query_name=name,
            candidate_name=row["matched_name"],
            trigram_similarity=float(row.get("trigram_similarity", 0)),
            levenshtein_distance=int(row["levenshtein_dist"]) if row.get("levenshtein_dist") is not None else None,
            soundex_match=bool(row.get("soundex_match", False)),
        )

        if confidence < threshold:
            continue

        ent_num = row["ent_num"]
        source_url = f"https://sanctionslist.ofac.treas.gov/Home/SdnList?id={ent_num}"

        matches.append(
            ScreeningMatch(
                matched=True,
                confidence=confidence,
                matched_entry={
                    "ent_num": ent_num,
                    "sdn_name": row["matched_name"],
                    "sdn_type": row.get("sdn_type"),
                    "program": row.get("program"),
                    "title": row.get("title"),
                    "remarks": row.get("remarks"),
                    "match_source": row.get("match_source"),
                },
                source_url=source_url,
                list_name="OFAC_SDN",
                match_type="exact" if confidence >= 0.99 else "fuzzy",
                entity_name_queried=name,
                entity_name_matched=row["matched_name"],
            )
        )

    # Sort by confidence descending
    matches.sort(key=lambda m: m.confidence, reverse=True)
    return matches


async def get_sdn_meta(
    supabase_url: str,
    supabase_key: str,
) -> dict[str, Any]:
    """Get OFAC SDN metadata (last refresh, counts)."""
    try:
        from supabase import acreate_client
    except ImportError:
        return {"error": "supabase-py not installed"}

    db = await acreate_client(supabase_url, supabase_key)
    response = await db.table("ofac_sdn_meta").select("*").eq("id", 1).single().execute()
    return response.data or {}
