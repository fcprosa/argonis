"""Pipeline-specific exceptions."""

from __future__ import annotations


class OfacDataUnavailableError(Exception):
    """OFAC SDN tables are empty — screening cannot proceed safely.

    Raised by Step 3 (SCREEN) when ofac_sdn_entries has zero rows.
    The pipeline MUST halt: returning zero matches from an empty table
    would silently clear sanctioned entities.
    """
