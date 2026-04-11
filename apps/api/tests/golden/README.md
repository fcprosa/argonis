# Golden-Set Regression Harness

Automated regression testing for the evidence-first AML investigation pipeline. Tracks whether Step 5 prompt changes break deterministic behavior or degrade narrative structure.

## Why this exists

Battle plan rule #6 requires running 5 canonical test investigations daily to catch narrative-quality regressions. Every prompt tweak to Step 5 (the Claude-powered narrative generator) was previously flying blind. This harness provides:

1. **Automated deterministic checks** (pytest) — verify that Steps 1-4 produce the correct pattern detections and evidence package for each typology.
2. **Human-reviewable narrative output** (CLI script) — write full narratives to markdown files for eyeball review of prose quality.

## What it tests vs. what it cannot test

| Layer | Tested by | Automated? |
|---|---|---|
| Step 4 detector fired/not-fired | `test_golden_set.py` | Yes |
| Detector confidence ranges | `test_golden_set.py` | Yes |
| Evidence item count minimums | `test_golden_set.py` | Yes |
| Narrative section presence (4 keys) | `test_golden_set.py` | Yes |
| Section content minimum length | `test_golden_set.py` | Yes |
| LLM cost budget ($5/case) | `test_golden_set.py` | Yes |
| **Narrative prose quality** | `run_golden_set.py` → human review | **No** |
| **Regulatory language accuracy** | `run_golden_set.py` → human review | **No** |
| **Citation correctness** | `run_golden_set.py` → human review | **No** |

**The harness does NOT and CANNOT test prose quality.** The LLM narrative (Step 5) is non-deterministic. Structural properties (sections present, content length, cost) are automated. Prose quality, regulatory language, and citation accuracy require a human reading the markdown output.

## The 5 canonical typologies

| Fixture | Typology | Primary detectors | Key signals |
|---|---|---|---|
| `structuring.json` | Structuring / smurfing | structuring, funnel, velocity | 12 cash deposits $9,200-$9,800 across 6 branches over 6 days |
| `tbml.json` | Trade-based ML | layering, velocity, geographic_risk | Round-dollar in/out wire pairs to shell entities, IR nationality |
| `funnel.json` | Funnel account | funnel, velocity | 30 inbound credits from 30 originators in 5 states, zero outbound |
| `velocity.json` | Velocity anomaly | velocity, layering | Dormant account, $450K across 8 transactions in 48 hours |
| `geographic.json` | Geographic risk | geographic_risk | 6 wires to Myanmar-based entities, MM beneficial owner nationality |

All fixture names are prefixed with `TESTCASE_` to avoid collisions with real OFAC SDN entries.

## Running the test suite (CI / automated)

```bash
cd apps/api

# All 5 typologies (requires ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY)
python -m pytest tests/test_golden_set.py -v -s

# Single typology
python -m pytest tests/test_golden_set.py -k structuring -v -s
```

The test suite uses the shared Supabase fixtures from `tests/conftest.py` (creates a throwaway org + user, cleans up on teardown). Each typology inserts a test alert for the gather step and deletes it after the pipeline completes.

## Running the CLI script (daily / pre-merge review)

```bash
cd apps/api

# All 5 typologies
python scripts/run_golden_set.py

# Single typology
python scripts/run_golden_set.py --typology structuring
```

The CLI script:
- Runs all 5 fixtures through `EvidencePipeline`
- Prints a summary table (typology, detectors fired, cost, duration, section lengths)
- Writes full narratives to `tests/golden/latest_run/<typology>.md`
- Exits 0 on success, 1 on any failure

The `latest_run/` directory is gitignored (add to `.gitignore` if not already present). It exists solely for human review and should not be committed.

## The rule

**No Step 5 prompt change ships without running the CLI script and reading the `latest_run/` narratives.**

The workflow:
1. Make your prompt change in `app/pipeline/step5_narrate.py`
2. Run `python scripts/run_golden_set.py`
3. Read each `latest_run/<typology>.md` — check that prose quality, regulatory language, and citation accuracy are acceptable
4. Run `python -m pytest tests/test_golden_set.py -v -s` to verify deterministic assertions still pass
5. Only then open a PR

## File layout

```
tests/golden/
  structuring.json     # Fixture: structuring / smurfing case
  tbml.json            # Fixture: trade-based money laundering
  funnel.json          # Fixture: funnel account
  velocity.json        # Fixture: velocity anomaly
  geographic.json      # Fixture: geographic risk
  expected.py          # Deterministic assertions per fixture
  README.md            # This file
  __init__.py
  latest_run/          # Written by CLI script (gitignored)
    structuring.md
    tbml.md
    funnel.md
    velocity.md
    geographic.md

tests/test_golden_set.py   # Parametrized pytest
scripts/run_golden_set.py  # Standalone CLI runner
```

## Adding a new typology

1. Create `tests/golden/<name>.json` with a realistic alert payload
2. Add an entry to `EXPECTATIONS` in `tests/golden/expected.py`
3. The parametrized test and CLI script pick it up automatically
