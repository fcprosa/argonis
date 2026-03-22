# ARGONIS — Project Context

## What Argonis Is
Argonis is an AI-powered investigation agent that automates AML (Anti-Money Laundering) compliance investigations for financial institutions. It takes a raw transaction monitoring alert and produces a complete, regulator-ready investigation narrative in under 60 seconds — a process that currently takes human analysts 2 to 22 hours per case.

Argonis is NOT a chatbot. NOT a copilot. It is an autonomous agent that receives a goal (investigate this alert), then executes a multi-step workflow: pulling customer data, screening against global sanctions lists, analyzing transaction patterns, detecting money laundering typologies, scoring risk, and generating a structured investigation narrative with every finding cited to verifiable evidence. The human analyst reviews, edits, and approves. The agent does the work.

## The Problem We Solve
- Global AML compliance spending: $206-274 billion/year, 75% is labor costs
- 95% of transaction monitoring alerts are false positives — pure waste
- Each SAR (Suspicious Activity Report) takes 2-22 hours of analyst time
- 4.6 million SARs filed with FinCEN annually (10,000+/day), each requiring a defensible investigation
- $4.5 billion in AML fines in 2024 alone (TD Bank: $3B record penalty)
- Chronic analyst burnout, high turnover, growing talent gap
- The problem is mandatory (regulated), massive, growing, and painful

## Critical Architecture Decision — Evidence-First, LLM-Last
Hummingbird (a respected compliance tech company) tested AI narrative generation and found compliance leaders called it "low-impact." The LLM hallucinated facts in complex cases. They pivoted to AI-as-editor.

**Our architecture solves this by separating investigation from writing:**

| Step | What Happens | Uses LLM? |
|------|-------------|-----------|
| 1. PARSE | Parse alert into structured schema | NO |
| 2. GATHER | Pull KYC, transactions, account data via API/DB | NO |
| 3. SCREEN | Hit OFAC, OpenSanctions, PEP, adverse media APIs | NO |
| 4. ANALYZE | Python functions detect structuring, layering, funnel patterns | NO |
| 5. NARRATE | LLM writes prose FROM verified evidence only | YES |

**Steps 1-4 are deterministic. No LLM. Zero hallucination possible.**
Step 5 uses the LLM ONLY to write prose from verified data. Every factual claim in the narrative references a specific evidence_id. If the evidence doesn't exist, the claim doesn't appear in the narrative.

The prompt for Step 5 explicitly instructs: "Do not include any information not present in the evidence package. If evidence is insufficient for a section, write: INSUFFICIENT EVIDENCE — REQUIRES HUMAN INPUT."

## Who It's For
1. **Primary:** Mid-size European EMIs (Electronic Money Institutions) and banks with 5-50 person compliance teams navigating AMLD6, MiCA, DORA
2. **Secondary:** Scaling fintechs, neobanks, payment processors, crypto exchanges
3. **Distribution:** Compliance consulting firms (resell to multiple clients)

## Revenue Model
- Per-investigation: $50-200 per completed narrative (API cost: $2-5, margin: 90%+)
- Platform SaaS: $3,000-15,000/month for dashboard, case management, audit trail
- Year 1 target: 10 customers × $8K/month = $960K ARR

## Competitive Landscape
| Competitor | Funding | Their Focus | Our Edge |
|-----------|---------|-------------|----------|
| Greenlite / Bretton AI | ~$10M+ (YC) | US fintechs, alerts, KYC, narratives | We target Europe (AMLD6 greenfield). Domain depth from JPMorgan. |
| Lucinity | $27M+ | Full platform, AI agent "Luci" | Full platform = long sales cycle. We deploy in days, not months. |
| SymphonyAI | $200M+ rev | Enterprise AML suite | Enterprise pricing ($500K+). We serve mid-market at 1/10th cost. |
| Nasdaq Verafin | Nasdaq-backed | 2,500+ US banks | US-focused. We go where they don't: European EMIs, crypto, consultancies. |

## Tech Stack
- **LLM:** Claude API (Anthropic) — reasoning + narrative generation via structured outputs
- **Backend:** Python (FastAPI) — agent pipeline, API endpoints, async processing
- **Database:** Supabase (PostgreSQL) — cases, audit logs, auth, row-level security
- **Frontend:** Next.js 14 (App Router) — investigation dashboard, narrative editor
- **Sanctions:** OFAC SDN (free), OpenSanctions (40+ global lists)
- **Media:** Serper.dev API — adverse media detection (Google search results)
- **Infra:** Vercel (frontend) + Railway (backend), auto-deploy on push

## Key Database Tables
- `organizations`, `users` — multi-tenant with RLS
- `alerts` — ingested from TMS (CSV/API/manual)
- `cases` — investigation instances
- `investigation_steps` — each pipeline step with source_data JSON + confidence_score
- `narratives` — versioned, section-level approval status
- `screening_results` — match_confidence + source_url per list
- `evidence_links` — maps narrative sentences to specific data sources (CRITICAL for anti-hallucination)
- `audit_log` — every action, every actor, every timestamp (regulatory requirement)

## UI Design Principles
- **Active review, not rubber-stamping** (Hummingbird lesson)
- Section-by-section narrative approval (no "Approve All" shortcut)
- Inline evidence links: click any claim → see source data
- Confidence indicators: green/yellow/red per claim
- "INSUFFICIENT EVIDENCE" sections require human writing
- Track changes: AI-generated vs human-edited text (different colors)
- Audit trail visible at all times
- Information density over aesthetics — compliance people use Bloomberg, not Instagram
- Copy-to-clipboard for pasting into bank's existing case management system

## Founder's Edge
Daniel has 2 internships at JPMorgan GFCC (Sanctions Investigations + Blocked Assets & Licensing), a degree in Financial Forensics & Fraud Examination, EU citizenship (Portugal + Spain), and is trilingual (EN/PT/ES). He has actually written SAR narratives, reviewed sanctions cases, and knows what regulators expect. This domain depth is what makes the prompts and output quality different from generic AI compliance tools.

## Current Phase
Building the MVP. 21-day execution plan:
- Week 1: Agent pipeline (evidence-first architecture, real sanctions APIs, pattern detection)
- Week 2: Dashboard UI (anti-rubber-stamp narrative reviewer, audit trail, PDF export)
- Week 3: Landing page, demos, outreach to European EMI compliance directors

## Validation Threshold
A real compliance officer looks at an Argonis narrative and says "I would submit this." Not "interesting." Not "has potential." **"I would submit this."** That is the only metric that matters.

## Repo Structure
```
argonis/
├── apps/
│   ├── web/          → Next.js 14 (App Router) dashboard
│   └── api/          → FastAPI backend + agent pipeline
├── packages/
│   ├── agent/        → Core investigation agent (5-step pipeline)
│   │   ├── prompts/  → System prompts per pipeline step (THE IP)
│   │   ├── screening/→ OFAC, OpenSanctions, PEP, media integrations
│   │   ├── analysis/ → Pattern detection (structuring, layering, funnel, etc.)
│   │   └── core.py   → Pipeline orchestrator
│   ├── db/           → Supabase schema, migrations, seed data
│   └── shared/       → Types, constants, utils
├── scripts/          → Setup, deployment, seed data
├── ARGONIS.md        → This file
├── .env.example      → All env vars documented
└── .gitignore
```
