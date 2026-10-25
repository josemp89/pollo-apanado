"""
Empirical Adversarial Test Suite — Milestone 2-4 (Cash Register Redesign & Closing Reconciliation)
Agent: challenger_m4_1 (critic, specialist)

Verifies:
1. Core Financial Closing Scenarios (Exact Cash Match, Shortage, Surplus, Multi-payment partition, Expenses).
2. SQLite Database Persistence in `daily_closing_receipts`, receipt_code format `REC-CIERRE-YYMMDD-XXXX`, monotonic sequence, and retrieval endpoints.
3. Edge cases and attack vectors: negative cash, double-closing, unopen shifts, invalid IDs, negative inventory counts, unknown item keys, adjust_inventory flag.
4. Cross-reconciliation status matrix (cuadrada_total, faltante_efectivo, merma_inventario, descuadre_mixto).
5. Template UI sanitization: removal of Punto de Equilibrio / Margen Bruto, preservation of Cancellations alert, presence of 3-step modal and digital receipt voucher.
"""

import re
import json
import pytest
from datetime import datetime
from fastapi.testclient import TestClient


class TestFinancialClosingCoreScenarios:
    """Empirical verification of the 3 core cash closing scenarios and financial invariants."""

    def test_exact_cash_match(self, client: TestClient, helpers):
        """
        Exact Cash Match: actual_cash == expected_cash
        Must yield difference == 0 and status == "cuadrada".
        """
        open_res = client.post("/api/cash/open-shift", json={
            "cashier_name": "Auditor-Cuadre",
            "base_inicial": 80000,
            "notes": "Prueba exacta"
        })
        assert open_res.status_code == 200
        shift_id = open_res.json()["shift"]["id"]

        # Venta en efectivo de 36,000 COP
        prod_ent = helpers.get_product_id("POL-ENT")
        sale_res = client.post("/api/pos/checkout", json={
            "items": [{"product_id": prod_ent, "quantity": 1}],
            "payment_method": "efectivo",
            "cash_received": 40000
        })
        assert sale_res.status_code == 200

        # Gasto menor de 15,000 COP
        exp_res = client.post("/api/cash/expense", json={
            "shift_id": shift_id,
            "amount": 15000,
            "category": "servicios",
            "concept": "Pago recibo agua parcial",
            "authorized_by": "Santiago"
        })
        assert exp_res.status_code == 200

        # expected_cash = 80,000 + 36,000 - 15,000 = 101,000
        expected = 101000
        close_res = client.post("/api/cash/close-shift", json={
            "shift_id": shift_id,
            "actual_cash": expected,
            "notes": "Cuadre exacto"
        })
        assert close_res.status_code == 200
        data = close_res.json()
        rec = data["reconciliation"]

        assert rec["expected_cash"] == expected
        assert rec["actual_cash"] == expected
        assert rec["difference"] == 0
        assert rec["cash_status"] == "cuadrada"
        assert data["shift"]["status"] == "cerrado"
        assert data["shift"]["difference"] == 0

    def test_cash_shortage(self, client: TestClient, helpers):
        """
        Cash Shortage: actual_cash < expected_cash
        Must yield negative difference and status == "faltante".
        """
        open_res = client.post("/api/cash/open-shift", json={
            "cashier_name": "Auditor-Faltante",
            "base_inicial": 50000
        })
        shift_id = open_res.json()["shift"]["id"]

        # Venta en efectivo de 20,000 COP (POL-12)
        prod_12 = helpers.get_product_id("POL-12")
        client.post("/api/pos/checkout", json={
            "items": [{"product_id": prod_12, "quantity": 1}],
            "payment_method": "efectivo",
            "cash_received": 20000
        })

        # expected_cash = 50,000 + 20,000 = 70,000
        # Cajero entrega 62,500 COP (Faltante de 7,500 COP)
        close_res = client.post("/api/cash/close-shift", json={
            "shift_id": shift_id,
            "actual_cash": 62500,
            "notes": "Faltante auditado"
        })
        assert close_res.status_code == 200
        data = close_res.json()
        rec = data["reconciliation"]

        assert rec["expected_cash"] == 70000
        assert rec["actual_cash"] == 62500
        assert rec["difference"] == -7500
        assert rec["difference"] < 0
        assert rec["cash_status"] == "faltante"
        assert data["shift"]["status"] == "cerrado"
        assert data["shift"]["difference"] == -7500

    def test_cash_surplus(self, client: TestClient, helpers):
        """
        Cash Surplus: actual_cash > expected_cash
        Must yield positive difference and status == "sobrante".
        """
        open_res = client.post("/api/cash/open-shift", json={
            "cashier_name": "Auditor-Sobrante",
            "base_inicial": 60000
        })
        shift_id = open_res.json()["shift"]["id"]

        # Venta en efectivo de 9,000 COP (POL-PEC)
        prod_pec = helpers.get_product_id("POL-PEC")
        client.post("/api/pos/checkout", json={
            "items": [{"product_id": prod_pec, "quantity": 1}],
            "payment_method": "efectivo",
            "cash_received": 10000
        })

        # expected_cash = 60,000 + 9,000 = 69,000
        # Cajero entrega 74,000 COP (Sobrante de 5,000 COP)
        close_res = client.post("/api/cash/close-shift", json={
            "shift_id": shift_id,
            "actual_cash": 74000,
            "notes": "Sobrante auditado"
        })
        assert close_res.status_code == 200
        data = close_res.json()
        rec = data["reconciliation"]

        assert rec["expected_cash"] == 69000
        assert rec["actual_cash"] == 74000
        assert rec["difference"] == 5000
        assert rec["difference"] > 0
        assert rec["cash_status"] == "sobrante"
        assert data["shift"]["status"] == "cerrado"
        assert data["shift"]["difference"] == 5000

    def test_multi_payment_methods_partition_integrity(self, client: TestClient, helpers):
        """
        Strict partition test:
        Only cash sales must enter expected_cash. Digital and datáfono sales must NOT enter expected_cash.
        """
        open_res = client.post("/api/cash/open-shift", json={
            "cashier_name": "Auditor-MultiPago",
            "base_inicial": 100000
        })
        shift_id = open_res.json()["shift"]["id"]

        pec_id = helpers.get_product_id("POL-PEC") # 9000
        half_id = helpers.get_product_id("POL-12") # 20000
        ent_id = helpers.get_product_id("POL-ENT") # 36000

        # Venta 1: Efectivo 9,000
        client.post("/api/pos/checkout", json={
            "items": [{"product_id": pec_id, "quantity": 1}],
            "payment_method": "efectivo",
            "cash_received": 10000
        })

        # Venta 2: Nequi 20,000
        client.post("/api/pos/checkout", json={
            "items": [{"product_id": half_id, "quantity": 1}],
            "payment_method": "nequi_daviplata",
            "cash_received": 20000
        })

        # Venta 3: Datáfono 36,000
        client.post("/api/pos/checkout", json={
            "items": [{"product_id": ent_id, "quantity": 1}],
            "payment_method": "datafono",
            "cash_received": 36000
        })

        # Gasto menor: 10,000
        client.post("/api/cash/expense", json={
            "shift_id": shift_id,
            "amount": 10000,
            "category": "insumos",
            "concept": "Bolsas y servilletas",
            "authorized_by": "Santiago"
        })

        # Total sales = 9000 + 20000 + 36000 = 65000
        # Expected cash = Base (100000) + Cash Sales (9000) - Expenses (10000) = 99000
        close_res = client.post("/api/cash/close-shift", json={
            "shift_id": shift_id,
            "actual_cash": 99000
        })
        assert close_res.status_code == 200
        rec = close_res.json()["reconciliation"]

        assert rec["base_inicial"] == 100000
        assert rec["cash_sales"] == 9000
        assert rec["digital_sales"] == 20000
        assert rec["datafono_sales"] == 36000
        assert rec["total_sales"] == 65000
        assert rec["total_expenses"] == 10000
        assert rec["expected_cash"] == 99000
        assert rec["actual_cash"] == 99000
        assert rec["difference"] == 0
        assert rec["cash_status"] == "cuadrada"

    def test_zero_base_inicial_shift(self, client: TestClient, helpers):
        """Turno con base inicial 0 COP."""
        open_res = client.post("/api/cash/open-shift", json={
            "cashier_name": "ZeroBaseCashier",
            "base_inicial": 0
        })
        assert open_res.status_code == 200
        shift_id = open_res.json()["shift"]["id"]

        # Venta 9,000
        pec_id = helpers.get_product_id("POL-PEC")
        client.post("/api/pos/checkout", json={
            "items": [{"product_id": pec_id, "quantity": 1}],
            "payment_method": "efectivo",
            "cash_received": 10000
        })

        # expected_cash = 0 + 9000 - 0 = 9000
        close_res = client.post("/api/cash/close-shift", json={
            "shift_id": shift_id,
            "actual_cash": 9000
        })
        assert close_res.status_code == 200
        assert close_res.json()["reconciliation"]["expected_cash"] == 9000
        assert close_res.json()["reconciliation"]["cash_status"] == "cuadrada"


class TestDatabasePersistenceAndReceiptAuditing:
    """Verifies SQLite persistence in daily_closing_receipts table and receipt code standards."""

    def test_sqlite_persistence_daily_closing_receipts_table(self, client: TestClient, db_conn, helpers):
        """
        Verify that daily_closing_receipts table stores all columns accurately,
        and foreign key links to cash_shifts table.
        """
        open_res = client.post("/api/cash/open-shift", json={
            "cashier_name": "Maria-Auditor",
            "base_inicial": 150000,
            "notes": "Turno para persistencia SQLite"
        })
        shift_id = open_res.json()["shift"]["id"]

        # Venta 13,000 (POL-14)
        prod_14 = helpers.get_product_id("POL-14")
        client.post("/api/pos/checkout", json={
            "items": [{"product_id": prod_14, "quantity": 1}],
            "payment_method": "efectivo",
            "cash_received": 15000
        })

        # Close shift with inventory counts
        close_res = client.post("/api/cash/close-shift", json={
            "shift_id": shift_id,
            "actual_cash": 163000,
            "inventory_counts": [
                {"item_key": "pechuga_vitrina", "physical_count": 10.0},
                {"item_key": "ala_vitrina", "physical_count": 8.0}
            ],
            "notes": "Cierre persistido en DB"
        })
        assert close_res.status_code == 200
        receipt_code = close_res.json()["receipt_code"]

        # Direct SQL query to check SQLite table daily_closing_receipts
        row = db_conn.execute("""
            SELECT * FROM daily_closing_receipts WHERE receipt_code = ?
        """, (receipt_code,)).fetchone()

        assert row is not None, f"Receipt {receipt_code} was not persisted in daily_closing_receipts table"
        assert row["shift_id"] == shift_id
        assert row["cashier_name"] == "Maria-Auditor"
        assert row["base_inicial"] == 150000
        assert row["cash_sales"] == 13000
        assert row["expected_cash"] == 163000
        assert row["actual_cash"] == 163000
        assert row["cash_difference"] == 0
        assert row["cash_status"] == "cuadrada"
        assert row["total_items_counted"] == 2
        assert row["notes"] == "Cierre persistido en DB"

        # Verify JSON breakdown is valid JSON and parseable
        breakdown = json.loads(row["inventory_breakdown_json"])
        assert len(breakdown) == 2
        keys = [it["item_key"] for it in breakdown]
        assert "pechuga_vitrina" in keys
        assert "ala_vitrina" in keys

    def test_receipt_code_format_and_monotonicity(self, client: TestClient, db_conn):
        """
        Verify generated receipt_code follows format REC-CIERRE-YYMMDD-XXXX
        and monotonic incremental numbering (e.g. 0001, 0002).
        """
        code_regex = re.compile(r"^REC-CIERRE-\d{6}-\d{4}$")

        codes = []
        for i in range(2):
            open_res = client.post("/api/cash/open-shift", json={
                "cashier_name": f"Cashier-{i}",
                "base_inicial": 50000
            })
            shift_id = open_res.json()["shift"]["id"]

            close_res = client.post("/api/cash/close-shift", json={
                "shift_id": shift_id,
                "actual_cash": 50000,
                "inventory_counts": [{"item_key": "pechuga_vitrina", "physical_count": 5.0}]
            })
            assert close_res.status_code == 200
            code = close_res.json()["receipt_code"]
            assert code_regex.match(code), f"Receipt code {code} does not match REC-CIERRE-YYMMDD-XXXX"
            codes.append(code)

        # Verify sequential increment
        seq0 = int(codes[0].split("-")[-1])
        seq1 = int(codes[1].split("-")[-1])
        assert seq1 == seq0 + 1, f"Receipt sequence did not increment monotonically: {codes}"

    def test_digital_receipt_retrieval_endpoint(self, client: TestClient):
        """
        Verify endpoint GET /api/cash/closing-receipt/{receipt_id_or_code}
        works by both code and primary key id, and handles 404 for nonexistent receipts.
        """
        open_res = client.post("/api/cash/open-shift", json={
            "cashier_name": "RetrievalTester",
            "base_inicial": 75000
        })
        shift_id = open_res.json()["shift"]["id"]

        close_res = client.post("/api/cash/close-shift", json={
            "shift_id": shift_id,
            "actual_cash": 75000,
            "inventory_counts": [{"item_key": "pechuga_vitrina", "physical_count": 12.0}]
        })
        receipt_code = close_res.json()["receipt_code"]

        # 1. Retrieve by code string
        res_code = client.get(f"/api/cash/closing-receipt/{receipt_code}")
        assert res_code.status_code == 200
        data_code = res_code.json()
        assert data_code["success"] is True
        assert data_code["receipt"]["receipt_code"] == receipt_code
        assert data_code["receipt"]["cashier_name"] == "RetrievalTester"
        assert len(data_code["receipt"]["inventory_breakdown"]) == 1

        # 2. Retrieve by integer ID
        receipt_id = data_code["receipt"]["id"]
        res_id = client.get(f"/api/cash/closing-receipt/{receipt_id}")
        assert res_id.status_code == 200
        assert res_id.json()["receipt"]["receipt_code"] == receipt_code

        # 3. Nonexistent code returns 404
        res_404 = client.get("/api/cash/closing-receipt/REC-CIERRE-000000-9999")
        assert res_404.status_code == 404
        assert "no encontrado" in res_404.json()["detail"].lower()


class TestEdgeCasesAndValidationDefense:
    """Adversarial testing of failure modes, boundary limits, and input validation."""

    def test_negative_actual_cash_rejected_http_400(self, client: TestClient):
        """Conteo de efectivo negativo debe ser rechazado con HTTP 400."""
        # Abrir turno
        client.post("/api/cash/open-shift", json={"cashier_name": "NegTester", "base_inicial": 50000})

        neg_payloads = [
            {"actual_cash": -1},
            {"actual_cash": -10000},
            {"actual_cash": -999999999}
        ]

        for payload in neg_payloads:
            res = client.post("/api/cash/close-shift", json=payload)
            assert res.status_code == 400, f"Expected 400 for {payload}, got {res.status_code}: {res.text}"
            assert "actual_cash" in str(res.json())

    def test_closing_already_closed_shift_rejected_http_400(self, client: TestClient):
        """Intentar cerrar un turno ya cerrado debe ser rechazado con HTTP 400."""
        open_res = client.post("/api/cash/open-shift", json={"cashier_name": "DoubleCloser", "base_inicial": 30000})
        shift_id = open_res.json()["shift"]["id"]

        # First close: success
        res1 = client.post("/api/cash/close-shift", json={"shift_id": shift_id, "actual_cash": 30000})
        assert res1.status_code == 200

        # Second close: rejection
        res2 = client.post("/api/cash/close-shift", json={"shift_id": shift_id, "actual_cash": 30000})
        assert res2.status_code == 400
        assert "ya se encuentra cerrado" in res2.json()["detail"].lower()

    def test_closing_when_no_shift_is_open_rejected_http_400(self, client: TestClient):
        """Intentar cerrar cuando no existe ningún turno abierto debe arrojar HTTP 400."""
        res = client.post("/api/cash/close-shift", json={"actual_cash": 50000})
        assert res.status_code == 400
        assert "no se encontró ningún turno" in res.json()["detail"].lower()

    def test_closing_nonexistent_shift_id_rejected_http_400(self, client: TestClient):
        """shift_id inexistente debe arrojar HTTP 400."""
        client.post("/api/cash/open-shift", json={"cashier_name": "ActiveShift", "base_inicial": 20000})
        res = client.post("/api/cash/close-shift", json={"shift_id": 999999, "actual_cash": 20000})
        assert res.status_code == 400
        assert "no se encontró ningún turno" in res.json()["detail"].lower()

    def test_negative_physical_inventory_count_rejected_http_400(self, client: TestClient):
        """Conteo de inventario negativo debe ser rechazado con HTTP 400."""
        open_res = client.post("/api/cash/open-shift", json={"cashier_name": "NegInvTester", "base_inicial": 40000})
        shift_id = open_res.json()["shift"]["id"]

        res = client.post("/api/cash/close-shift", json={
            "shift_id": shift_id,
            "actual_cash": 40000,
            "inventory_counts": [{"item_key": "pechuga_vitrina", "physical_count": -2.5}]
        })
        assert res.status_code == 400
        assert "physical_count" in str(res.json())

    def test_empty_inventory_counts_list_handled_gracefully(self, client: TestClient):
        """
        Si se envía inventory_counts: [], debe completarse exitosamente y persistir el recibo con 0 conteos.
        """
        open_res = client.post("/api/cash/open-shift", json={"cashier_name": "EmptyListTester", "base_inicial": 45000})
        shift_id = open_res.json()["shift"]["id"]

        res = client.post("/api/cash/close-shift", json={
            "shift_id": shift_id,
            "actual_cash": 45000,
            "inventory_counts": []
        })
        assert res.status_code == 200
        data = res.json()
        assert data["receipt_code"] is not None
        assert data["inventory_reconciliation"]["total_items_counted"] == 0

    def test_unknown_inventory_item_key_handled_without_crash(self, client: TestClient):
        """
        Si se envía un item_key que no está en CLOSING_ZONES_SPEC ni en inventario,
        el sistema no debe generar error 500, sino manejar valores predeterminados (stock 0).
        """
        open_res = client.post("/api/cash/open-shift", json={"cashier_name": "GhostItemTester", "base_inicial": 35000})
        shift_id = open_res.json()["shift"]["id"]

        res = client.post("/api/cash/close-shift", json={
            "shift_id": shift_id,
            "actual_cash": 35000,
            "inventory_counts": [{"item_key": "item_desconocido_xyz", "physical_count": 3.0}]
        })
        assert res.status_code == 200
        data = res.json()
        assert data["receipt_code"] is not None
        breakdown = data["inventory_reconciliation"]["breakdown"]
        assert len(breakdown) == 1
        assert breakdown[0]["item_key"] == "item_desconocido_xyz"

    def test_adjust_inventory_to_physical_flag_behavior(self, client: TestClient, db_conn):
        """
        Verifica que:
        - adjust_inventory_to_physical == False NO modifica inventory.stock.
        - adjust_inventory_to_physical == True SÍ actualiza inventory.stock al conteo físico.
        """
        target_key = "ala_vitrina"
        initial_stock = db_conn.execute("SELECT stock FROM inventory WHERE item_key = ?", (target_key,)).fetchone()["stock"]

        # Case 1: adjust_inventory_to_physical = False
        open_1 = client.post("/api/cash/open-shift", json={"cashier_name": "NoAdjustTester", "base_inicial": 50000})
        shift_1_id = open_1.json()["shift"]["id"]

        client.post("/api/cash/close-shift", json={
            "shift_id": shift_1_id,
            "actual_cash": 50000,
            "inventory_counts": [{"item_key": target_key, "physical_count": 99.0}],
            "adjust_inventory_to_physical": False
        })
        stock_after_false = db_conn.execute("SELECT stock FROM inventory WHERE item_key = ?", (target_key,)).fetchone()["stock"]
        assert stock_after_false == initial_stock, "Stock should NOT have been updated when adjust_inventory_to_physical is False"

        # Case 2: adjust_inventory_to_physical = True
        open_2 = client.post("/api/cash/open-shift", json={"cashier_name": "YesAdjustTester", "base_inicial": 50000})
        shift_2_id = open_2.json()["shift"]["id"]

        client.post("/api/cash/close-shift", json={
            "shift_id": shift_2_id,
            "actual_cash": 50000,
            "inventory_counts": [{"item_key": target_key, "physical_count": 14.5}],
            "adjust_inventory_to_physical": True
        })
        stock_after_true = db_conn.execute("SELECT stock FROM inventory WHERE item_key = ?", (target_key,)).fetchone()["stock"]
        assert stock_after_true == 14.5, "Stock MUST be updated to 14.5 when adjust_inventory_to_physical is True"

    def test_invalid_data_types_rejected_http_400(self, client: TestClient):
        """Tipos inválidos para actual_cash deben fallar con HTTP 400."""
        client.post("/api/cash/open-shift", json={"cashier_name": "TypeTester", "base_inicial": 50000})

        res_str = client.post("/api/cash/close-shift", json={"actual_cash": "no_es_un_numero"})
        assert res_str.status_code == 400

        res_null = client.post("/api/cash/close-shift", json={"actual_cash": None})
        assert res_null.status_code == 400


class TestCrossReconciliationMatrix:
    """Verifies complete 4-state cross reconciliation matrix (R4)."""

    @pytest.mark.parametrize("cash_diff,inv_diff,expected_status", [
        (0, 0, "cuadrada_total"),
        (-4000, 0, "faltante_efectivo"),
        (0, -3, "merma_inventario"),
        (-6000, -2, "descuadre_mixto"),
    ])
    def test_matrix_combinations(self, client: TestClient, cash_diff, inv_diff, expected_status):
        open_res = client.post("/api/cash/open-shift", json={
            "cashier_name": f"Tester-{expected_status}",
            "base_inicial": 100000
        })
        shift_id = open_res.json()["shift"]["id"]

        sheet = client.get("/api/cash/closing-inventory-sheet").json()
        target_item = sheet["zones"]["vitrina"][0]
        phys_stock = target_item["expected_stock"] + inv_diff

        actual_cash = 100000 + cash_diff

        close_res = client.post("/api/cash/close-shift", json={
            "shift_id": shift_id,
            "actual_cash": actual_cash,
            "inventory_counts": [{"item_key": target_item["item_key"], "physical_count": phys_stock}]
        })
        assert close_res.status_code == 200
        data = close_res.json()
        assert data["cross_reconciliation_status"] == expected_status
        assert data["receipt"]["cross_reconciliation_status"] == expected_status


class TestCajaTemplateRedesignContracts:
    """Verifies template contracts of /caja view per R2, R3, R4."""

    def test_caja_view_rendered_elements(self, client: TestClient):
        res = client.get("/caja")
        assert res.status_code == 200
        html = res.text

        # R2: Purged elements
        assert 'id="breakevenCard"' not in html, "Punto de equilibrio card must be removed"
        assert 'id="statEstimatedMargin"' not in html, "Gross margin card must be removed"

        # Preserved forensic elements
        assert 'id="cancellationsAlertCard"' in html, "Cancellations alert card must be preserved"

        # R2, R3: 3-step modal flow elements
        assert 'id="closeShiftModal"' in html
        assert 'id="closingStepContainer1"' in html
        assert 'id="closingStepContainer2"' in html
        assert 'id="closingStepContainer3"' in html

        # R4: Digital closing receipt modal and history modal
        assert 'id="digitalClosingReceiptModal"' in html
        assert 'id="closingReceiptsHistoryModal"' in html
        assert 'id="btnHistoryReceipts"' in html
