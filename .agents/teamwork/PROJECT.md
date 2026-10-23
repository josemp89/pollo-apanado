# Project: Pollo Apanado — Full System Audit, Quality Certification & Hardening

## Architecture
- **Framework**: FastAPI (Python 3.12) with Uvicorn ASGI server.
- **Database**: SQLite3 in Write-Ahead Logging (`WAL`) mode with `busy_timeout=10000`, `synchronous=NORMAL`, and foreign key constraints enabled.
- **Frontend**: Jinja2 server-rendered templates styled with Tailwind CSS, customized mobile touch styles (`app/static/css/style.css`), and Vanilla JavaScript with haptic feedback (`app/static/js/pos.js`).
- **Data Flow**:
  1. Bodega (`pollo_entero_crudo`, insumos secos) ->
  2. Kitchen Despiece (`1 Pollo Crudo -> 2 Pechugas + 2 Muslos + 2 Contramuslos + 2 Alas + 2 Caldo`) ->
  3. Kitchen Stages (Salmuera [6h] -> Adobo [4h] -> Fritura [14m]) ->
  4. Vitrina Térmica (Holding max 45 min) ->
  5. POS Mostrador Checkout (Atomic stock deduction from vitrina/raciones/nevera) ->
  6. Financial Ledger & Cash Balance (`sales`, `sale_items`, `cash_summary`, partner metrics).

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Concurrency-Safe Order IDs | Atomic generation of `sale_code` preventing collisions under concurrent checkouts | M1 | Survey 1, 2 |
| 2 | SQLite WAL & Transaction Safety | WAL journal mode, 10s timeout, synchronous NORMAL, immediate write transactions | M1 | Survey 1 |
| 3 | Symmetrical Sale Cancellation | Full inventory restoration for combos (`POL-14`, `POL-12`, `POL-ENT`), presas, and sides | M1 | Survey 1, 2, 3 |
| 4 | Non-Negative Stock Floor | Strict atomic stock deduction enforcing `stock >= qty` with 400 error on depletion | M1 | Survey 1, 2 |
| 5 | Despiece Mathematical Integrity | Formula `1 -> 2P + 2M + 2C + 2A + 2 Caldo` with bodega stock validation & audit logging | M1 | Survey 1 |
| 6 | Insumos Secos & Arepas Tracking | Inventory tracking and deduction for harina, aceite, and arepas (`POR-AREP`) | M1 | Survey 1, 3 |
| 7 | Mandatory Presa Selection | Modal enforcement for Almuerzo Completo ($16,000 COP) with server-side validation | M2 | R1, Survey 2 |
| 8 | Live Stock Validation in POS | Disable exhausted presas in modal and items in grid; real-time stock refresh | M2 | R1, Survey 2 |
| 9 | Cash Change & Underpayment Guard | Exact change calculation and strict server-side validation `cash_received >= total` | M2 | R1, Survey 2 |
| 10 | Digital Payment Reconciliations | Nequi, Daviplata, and Datáfono transaction confirmation with receipt/dialog | M2 | R1, Survey 2 |
| 11 | Tablet UI Ergonomics | Touch targets >= 44px for comanda steppers, cumulative cash buttons, responsive keyboard | M2 | R1, Survey 2 |
| 12 | Kitchen Timers Lifecycle | Accurate salmuera (6h), adobo (4h), and fritura (14m) timers with batch state transitions | M3 | R3, Survey 1, 3 |
| 13 | Kitchen Expiration & Visual Alerts | Countdown timers, sound/visual expiration alerts, and completed batch archiving | M3 | R3, Survey 3 |
| 14 | Predictive Fryer Recommendation | Forward-looking algorithm anticipating frying batches based on hourly demand curves & combo presas | M3 | R3, Survey 1, 3 |
| 15 | Break-Even Financial Integrity | Daily break-even comparison against Gross Contribution Margin ($258,462 COP/day) | M4 | R4, Survey 1, 3 |
| 16 | Gross Margin Visibility | Display gross margin in cash balance dashboard (`cash.html`) alongside sales | M4 | R4, Survey 1, 3 |
| 17 | Partner Profit Distribution | Automatic Cap Table calculation (40% Partner 1, 40% Partner 2, 20% Santiago, Reserves) | M4 | R4, Survey 3 |
| 18 | Accurate Presa Sales Summary | Account for presas sold individually, in lunch specials, and inside all combos | M4 | R4, Survey 1, 3 |
| 19 | Supplier Stock Alerts | Low-stock triggers for critical ingredients (chicken, drinks, flour, oil, arepas) | M4 | R4, Survey 1, 3 |
| 20 | Comprehensive Pytest Suite | Unit, integration, and E2E test suite in isolated test database covering 100% critical flows | M5, E2E | R5, Survey 1, 3 |
| 21 | Concurrency Stress Test | >= 50 rapid concurrent transactions with 0 database locks and 0 inventory drift | M5, E2E | R5, Survey 1, 2 |
| 22 | Closed Inventory Math Verification | Verified formula: `Initial + Cuts - Sales = Final Physical Stock` with 0 drift | M5, E2E | R5, Survey 1, 2 |
| 23 | Docker & Deployment Hardening | Clean Docker container build, `.dockerignore`, and persistent volume configuration | M5 | R5, Survey 1, 3 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Core Data Integrity & Concurrency | Atomic `sale_code` / `batch_code`, SQLite WAL optimizations, symmetrical `cancel_sale`, non-negative stock floor, despiece validation, and dry goods tracking | none | DONE |
| M2 | POS Tablet UI & Payment Robustness | Live stock checks, disabled buttons for 0-stock presas, cash underpayment rejection, digital payment dialogs, and touch ergonomics (steppers >=44px) | M1 | IN_PROGRESS |
| M3 | Kitchen Timers & Fryer Algorithm | Fritura 14m fix, batch transitions (`salmuera`->`adobo`->`fritura`->`terminado`), timer visual/sound alerts, and predictive frying recommendation algorithm | M1 | PLANNED |
| M4 | Cash Balancing, Margins & Partner Metrics | Break-even evaluated against Gross Margin ($258,462 COP/day), gross margin UI card, 40/40/20 partner split, combo presas aggregation, and supplier alerts | M1, M2 | PLANNED |
| M_CASH_ANTIFRAUD | Cash Cycle, Antifraud PIN & Vitrina Arqueo | R1 (Base + Cash Arqueo), R2 (Full Breakdown), R3 (Admin PIN & Forensic Log), R4 (Vitrina Arqueo & Theft Alerts), R5 (Pytest Suite) | M1 | IN_PROGRESS |
| M5 | Test Suite, Concurrency Stress & Docker | Isolated pytest test suite, >=50 concurrent stress test, closed inventory formula verification, `.dockerignore`, and Docker deployment test | M1, M2, M3, M4 | PLANNED |
| FINAL | E2E Certification & Adversarial Hardening | 100% pass of E2E Test Suite (Tiers 1-4) + Tier 5 Adversarial Coverage Hardening with Challengers + Forensic Integrity Audit | M1..M5, E2E | PLANNED |

## Milestone M1 Outputs (Certified)
- **Files Modified**: `app/main.py`, `app/routers/pos.py`, `app/routers/kitchen.py`, `app/database.py`.
- **Test Modules**: `tests/test_milestone_m1.py`, `tests/test_adversarial_m1.py`, `tests/test_challenger_m1_2.py`, `tests/test_challenger_verification_2.py`, `tests/test_challenger_m1_r2_concurrency.py`.
- **Test Verdict**: 112 passed, 0 failed in pytest.
- **Key Invariants Certified**: Zero duplicate `sale_code` or `batch_code` under 50 threads; zero duplicate stock return in `cancel_sale` under 50 simultaneous cancellations; non-negative stock floor (`CHECK (stock >= 0)`); positive cart quantities strictly enforced; despiece formula `1 -> 2P+2M+2C+2A+2 Caldo` with `butchering_logs` audit trail; dry supplies and arepas tracked.
