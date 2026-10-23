# Orchestration Plan — Cash Cycle, Antifraud PIN & Vitrina Physical Arqueo

## Objectives
Implement, audit, and certify:
1. R1: Cash cycle with explicit initial base and closing arqueo formula (`Efectivo Esperado = Base Inicial + Ventas Efectivo - Gastos`).
2. R2: Complete and exhaustive breakdown of presas, combos, portions, and drinks in closing report.
3. R3: Antifraud security module with Admin PIN required for sales cancellation (HTTP 403 on invalid/missing PIN) and immutable forensic audit log table.
4. R4: Physical showcase (vitrina) arqueo and discrepancy/shrinkage report comparing theoretical vs physical counts.
5. R5: Comprehensive pytest automated test suite covering all security, math, and cancellation flows.

## Detailed Steps
- **Step 1: Exploration**: Dispatch 2 parallel Explorers to inspect current database schemas, existing cash routes, sales cancellation logic, templates (`cash.html`, `pos.html`), and existing test suite.
- **Step 2: Architecture Synthesis**: Synthesize findings, define interface contracts, schema migrations/additions, and dispatch guidelines.
- **Step 3: Implementation (Worker)**: Dispatch Worker to implement DB tables, backend endpoints, security PIN validation, cash reporting calculations, and UI enhancements.
- **Step 4: Review**: Dispatch 2 independent Reviewers to audit implementation correctness, completeness, and interface compliance.
- **Step 5: Adversarial Stress (Challengers)**: Dispatch 2 Challengers to test PIN bypass attempts, concurrent sales/cancellations, mathematical drift, and edge cases.
- **Step 6: Forensic Integrity Audit**: Dispatch Forensic Auditor to verify no hardcoding, dummy logic, or facade implementations.
- **Step 7: Gate Evaluation & Certification**: Synthesize all verdicts into `GATE_STATUS.md`. On PASS, run final verification suite and report completion to Sentinel.
