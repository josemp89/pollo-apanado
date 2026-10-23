# BRIEFING — 2026-10-21T01:52:00Z

## Mission
Survey backend architecture, database schema, transaction integrity, despiece logic, and multi-level inventory tracking for Pollo Apanado.

## 🔒 My Identity
- Archetype: explorer
- Roles: investigation, synthesis
- Working directory: c:\Users\Alejandro\Desktop\POLLO APANADO\.agents\teamwork\explorer_survey_1
- Original parent: e0991dd2-14f6-466f-a2b3-71ee70d307fd
- Milestone: backend-architecture-survey

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- Inspect codebase structure, DB schema, WAL mode, transaction isolation, concurrency handling
- Verify despiece yield formula (1 Pollo Crudo -> 2 Pechugas + 2 Muslos + 2 Contramuslos + 2 Alas + raciones de Caldo)
- Multi-level inventory tracking (drinks, sides, dry supplies, portions) and sale deduction flows
- Compare against requirements R2 and R5 in ORIGINAL_REQUEST.md

## Current Parent
- Conversation ID: e0991dd2-14f6-466f-a2b3-71ee70d307fd
- Updated: 2026-10-21T01:41:00Z

## Investigation State
- **Explored paths**:
  - `ORIGINAL_REQUEST.md`, `MASTER_CONTEXT.md`
  - `app/database.py`, `app/main.py`
  - `app/routers/pos.py`, `app/routers/kitchen.py`, `app/routers/cash.py`
  - `app/static/js/pos.js`, `app/templates/*.html`
  - `data/asadero.db`
  - `test_system.py`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `run_server.py`
- **Key findings**:
  - Concurrency crash empirically verified: `UNIQUE constraint failed: sales.sale_code` under concurrent requests.
  - Asymmetric inventory deduction: `cancel_sale` fails to restore combos (`POL-14`, `POL-12`, `POL-ENT`), causing permanent inventory loss.
  - Zero stock checks: Negative inventory is possible and confirmed (`ala_vitrina` is -973.0).
  - Despiece yield formula (1 -> 2P + 2M + 2C + 2A + 2 Caldo) matches mathematically, but instantly moves presas to vitrina, skipping raw kitchen inventory and stock availability checks.
  - Insumos secos (`harina_apanar_kg`, `aceite_fritura_lt`) are never deducted; `POR-AREP` has no inventory entry.
  - Fritura batch timer default bug: searches `fritura_hours` instead of `fritura_minutes`, resulting in a 4-hour timer instead of 14 minutes.
  - Combo presas are omitted from sales metrics and hourly kitchen demand queries.
  - `test_system.py` fails on Windows CP1252 emoji encoding and pollutes/depends on live DB data.
- **Unexplored areas**: None within the scope of this survey.

## Key Decisions Made
- All evidence has been empirically verified and cited with exact file paths and line numbers.

## Artifact Index
- DISPATCH.md — record of dispatch messages
- BRIEFING.md — working memory and context tracking
- progress.md — liveness heartbeat
- handoff.md — final 5-component handoff report
