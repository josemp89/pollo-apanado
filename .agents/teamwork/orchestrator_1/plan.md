# Master Plan — Pollo Apanado System Hardening & Quality Certification

## Goal
Comprehensive audit, quality certification, concurrency stress testing, bug fixes/hardening, and Docker verification for "Pollo Apanado" restaurant management system.

## Phase 0: Survey & Discovery
- Launch 3 parallel Explorers:
  - Explorer 1 (Architecture & Backend Engine): Inspect `app/`, database schema, SQLite WAL mode, models, despiece math, transactions.
  - Explorer 2 (Frontend & POS Touchscreen): Inspect tablet UI, comanda interactions (+, -, remove), presa selection for Almuerzo Completo ($16,000 COP), live stock checking, change calculation, payment modes.
  - Explorer 3 (Business Logic & Operations): Inspect kitchen timers, peak-hour frying recommendations, daily cash balance (cuadre de caja), break-even ($258,462 COP/day), supplier stock alerts, and Docker setup.
- Output: Synthesize reports into `PROJECT.md` with full Feature Inventory, Gap Analysis, Milestones, and Interface Contracts.

## Phase 1: Parallel Tracks
- **Track A: E2E Testing Track**:
  - Test writer creates comprehensive test harness and test cases (Tier 1-4) covering all features from ORIGINAL_REQUEST.md.
  - Produces `TEST_INFRA.md` and `TEST_READY.md`.
- **Track B: Implementation & Hardening Track**:
  - Milestone M1: Core Data Integrity, SQLite WAL Mode, Concurrency Safety, and Despiece Mathematical Precision (R2, R5).
  - Milestone M2: POS Tablet UI, Presa Live Validation, Comanda Controls, and Payment Integrity (R1).
  - Milestone M3: Kitchen Timers & Peak Hours Fryer Recommendation Algorithm (R3).
  - Milestone M4: Cash Balancing (Cuadre de Caja), Daily Break-Even & Supplier Alerts (R4).
  - Milestone M5: Docker Environment & Persistence Validation (R5).

## Phase 2: Final Verification & Adversarial Hardening
- Run full automated test suite (100% pass required).
- Concurrency stress test (>= 50 rapid concurrent transactions with 0 locks and 0 drift).
- Closed inventory verification: Initial + Cuts - Sales = Final Physical Stock (0 drift).
- Tier 5 Adversarial Coverage Hardening with Challengers.
- Independent Forensic Audit (teamwork_preview_auditor) for code integrity and quality certification.
- Deliver final completion report to caller agent.
