"""
Adversarial Empirical Challenge Suite — Milestone M2 (Payment Mechanics)
Challenger: challenger_m2_1

Focus Areas:
1. Cash underpayment edge cases: total - 1, 0, -1000, -999999, None, etc. -> All MUST fail HTTP 400.
2. Payment method whitelist: strictly only 'efectivo', 'nequi_daviplata', 'datafono' permitted.
   Normalization: whitespace/casing permitted if resolving to valid key; all other variations fail HTTP 400.
3. Zero inventory leakage and zero sale recording on underpayment rejection across single presas,
   combos (POL-ENT, POL-12, POL-14), and almuerzos (ALM-COMP).
4. Digital payments invariant: change_returned == 0 regardless of cash_received, notes/voucher persistence.
5. Concurrent underpayment resilience: multiple simultaneous invalid checkouts cause zero leaks and no db lock.
"""

import pytest
import concurrent.futures
from fastapi.testclient import TestClient

class TestCashUnderpaymentRejections:
    """Tests verifying cash underpayment boundary conditions strictly fail with HTTP 400."""

    @pytest.mark.parametrize("cash_val,desc", [
        (15999, "total - 1 COP"),
        (0, "zero cash"),
        (-1, "negative 1 COP"),
        (-1000, "negative 1000 COP"),
        (-99999999, "large negative cash"),
        (None, "None / null cash"),
    ])
    def test_cash_underpayment_variations_fail_http_400(self, client: TestClient, helpers, cash_val, desc):
        prod_id = helpers.get_product_id("ALM-COMP") # 16,000 COP
        initial_pechuga = helpers.get_stock("pechuga_vitrina")
        initial_caldo = helpers.get_stock("caldo_raciones")
        initial_sales = helpers.count_sales()

        payload = {
            "items": [{"product_id": prod_id, "quantity": 1, "chosen_presa": "Pechuga"}],
            "payment_method": "efectivo",
            "cash_received": cash_val
        }

        res = client.post("/api/pos/checkout", json=payload)
        assert res.status_code == 400, f"Failed for {desc}: expected 400, got {res.status_code}. Body: {res.text}"
        detail = res.json().get("detail", "")
        assert "insuficiente" in detail.lower(), f"Unexpected error detail for {desc}: {detail}"

        # Invariance check: zero state alteration
        assert helpers.get_stock("pechuga_vitrina") == initial_pechuga
        assert helpers.get_stock("caldo_raciones") == initial_caldo
        assert helpers.count_sales() == initial_sales

    def test_cash_underpayment_exact_minus_one_on_various_items(self, client: TestClient, helpers):
        """Test total - 1 on different products with different price points."""
        cases = [
            ("POL-PEC", None, 9000, 8999),
            ("GAS-COL-400", None, 3500, 3499),
            ("POL-14", None, 13000, 12999),
            ("POL-12", None, 20000, 19999),
            ("POL-ENT", None, 36000, 35999),
        ]
        for sku, chosen_presa, price, tender in cases:
            prod_id = helpers.get_product_id(sku)
            item = {"product_id": prod_id, "quantity": 1}
            if chosen_presa:
                item["chosen_presa"] = chosen_presa

            res = client.post("/api/pos/checkout", json={
                "items": [item],
                "payment_method": "efectivo",
                "cash_received": tender
            })
            assert res.status_code == 400
            assert "insuficiente" in res.json().get("detail", "").lower()


class TestPaymentMethodWhitelist:
    """Tests verifying payment method whitelisting and input sanitization."""

    @pytest.mark.parametrize("invalid_method", [
        "crypto",
        "bitcoin",
        "tarjeta_credito",
        "tarjeta_debito",
        "tarjeta",
        "credito",
        "fiado",
        "vales",
        "",
        "   ",
        "efec tivo",
        "efectivo1",
        "nequi",
        "daviplata",
        "datafono_redeban",
        "null",
        "undefined",
        "EFECTIVO CON PROPINA",
    ])
    def test_invalid_payment_methods_rejected(self, client: TestClient, helpers, invalid_method):
        prod_id = helpers.get_product_id("POL-PEC")
        initial_stock = helpers.get_stock("pechuga_vitrina")
        initial_sales = helpers.count_sales()

        res = client.post("/api/pos/checkout", json={
            "items": [{"product_id": prod_id, "quantity": 1}],
            "payment_method": invalid_method,
            "cash_received": 100000
        })

        assert res.status_code == 400, f"Expected 400 for method '{invalid_method}', got {res.status_code}"
        assert "no válido" in res.json().get("detail", "").lower() or "permitidos" in res.json().get("detail", "").lower()

        # Verify no side effects
        assert helpers.get_stock("pechuga_vitrina") == initial_stock
        assert helpers.count_sales() == initial_sales

    @pytest.mark.parametrize("raw_method,expected_saved", [
        ("efectivo", "efectivo"),
        ("EFECTIVO", "efectivo"),
        ("  efectivo  ", "efectivo"),
        ("\t\nEFECTIVO\r\n", "efectivo"),
        ("nequi_daviplata", "nequi_daviplata"),
        ("NEQUI_DAVIPLATA", "nequi_daviplata"),
        ("  Nequi_Daviplata  ", "nequi_daviplata"),
        ("datafono", "datafono"),
        ("DATAFONO", "datafono"),
        ("  Datafono \t", "datafono"),
    ])
    def test_valid_payment_methods_normalized(self, client: TestClient, helpers, db_conn, raw_method, expected_saved):
        prod_id = helpers.get_product_id("POR-AREP") # 1,000 COP
        helpers.set_stock("arepas_unidades", 100.0)

        res = client.post("/api/pos/checkout", json={
            "items": [{"product_id": prod_id, "quantity": 1}],
            "payment_method": raw_method,
            "cash_received": 5000
        })

        assert res.status_code == 200, f"Failed for '{raw_method}': {res.text}"
        data = res.json()
        assert data["payment_method"] == expected_saved

        # Verify in DB
        row = db_conn.execute("SELECT payment_method FROM sales WHERE sale_code = ?", (data["sale_code"],)).fetchone()
        assert row["payment_method"] == expected_saved


class TestZeroInventoryLeakageOnRejection:
    """Verifies that rejected checkouts leave zero inventory deducted and zero records in sales/sale_items."""

    def test_combo_pollo_entero_rejected_underpayment_leaves_stock_untouched(self, client: TestClient, helpers, db_conn):
        """POL-ENT requires 2 pechugas, 2 alas, 2 muslos, 2 contramuslos, 2 papas."""
        prod_id = helpers.get_product_id("POL-ENT") # 45,000 COP
        
        initial_stocks = {
            "pechuga_vitrina": helpers.get_stock("pechuga_vitrina"),
            "ala_vitrina": helpers.get_stock("ala_vitrina"),
            "muslo_vitrina": helpers.get_stock("muslo_vitrina"),
            "contramuslo_vitrina": helpers.get_stock("contramuslo_vitrina"),
            "papas_raciones": helpers.get_stock("papas_raciones"),
        }
        initial_sales_count = helpers.count_sales()
        initial_sale_items_count = db_conn.execute("SELECT COUNT(*) FROM sale_items").fetchone()[0]

        # Attempt with underpayment (35,999 COP for POL-ENT which is 36,000 COP)
        res = client.post("/api/pos/checkout", json={
            "items": [{"product_id": prod_id, "quantity": 1}],
            "payment_method": "efectivo",
            "cash_received": 35999
        })
        assert res.status_code == 400

        # Check all stocks unchanged
        for k, v in initial_stocks.items():
            current_v = helpers.get_stock(k)
            assert current_v == v, f"Stock leak for {k}: expected {v}, got {current_v}"

        # Check DB tables
        assert helpers.count_sales() == initial_sales_count
        new_items_count = db_conn.execute("SELECT COUNT(*) FROM sale_items").fetchone()[0]
        assert new_items_count == initial_sale_items_count

    def test_multi_item_order_rejected_underpayment(self, client: TestClient, helpers, db_conn):
        """Multi-item cart: Almuerzo + Gaseosa + Porción Arepas with underpayment."""
        id_alm = helpers.get_product_id("ALM-COMP") # 16,000
        id_gas = helpers.get_product_id("GAS-COL-400") # 3,500
        id_arep = helpers.get_product_id("POR-AREP") # 1,000
        total = 16000 + 3500 + 1000 # 20,500 COP

        initial_sales = helpers.count_sales()
        initial_pec = helpers.get_stock("pechuga_vitrina")
        initial_gas = helpers.get_stock("GAS-COL-400")
        initial_arep = helpers.get_stock("arepas_unidades")

        res = client.post("/api/pos/checkout", json={
            "items": [
                {"product_id": id_alm, "quantity": 1, "chosen_presa": "Pechuga"},
                {"product_id": id_gas, "quantity": 1},
                {"product_id": id_arep, "quantity": 1}
            ],
            "payment_method": "efectivo",
            "cash_received": total - 500 # 20,000 COP
        })
        assert res.status_code == 400
        assert helpers.count_sales() == initial_sales
        assert helpers.get_stock("pechuga_vitrina") == initial_pec
        assert helpers.get_stock("GAS-COL-400") == initial_gas
        assert helpers.get_stock("arepas_unidades") == initial_arep


class TestDigitalPaymentsInvariants:
    """Verifies digital payments invariants: change_returned == 0 and voucher note recording."""

    @pytest.mark.parametrize("method", ["nequi_daviplata", "datafono"])
    @pytest.mark.parametrize("cash_input", [0, None, 16000, 50000, 100000])
    def test_digital_change_always_zero_regardless_of_cash_input(self, client: TestClient, helpers, db_conn, method, cash_input):
        prod_id = helpers.get_product_id("ALM-COMP") # 16,000 COP
        voucher_text = f"Voucher-{method}-TX12345"

        res = client.post("/api/pos/checkout", json={
            "items": [{"product_id": prod_id, "quantity": 1, "chosen_presa": "Ala"}],
            "payment_method": method,
            "cash_received": cash_input,
            "notes": voucher_text
        })

        assert res.status_code == 200
        data = res.json()
        assert data["change_returned"] == 0, f"Expected change 0 for {method}, got {data['change_returned']}"
        assert data["payment_method"] == method

        # DB assertion
        row = db_conn.execute("SELECT * FROM sales WHERE sale_code = ?", (data["sale_code"],)).fetchone()
        assert row["change_returned"] == 0
        assert row["notes"] == voucher_text
        assert row["payment_method"] == method

    def test_digital_payment_with_empty_or_null_notes(self, client: TestClient, helpers, db_conn):
        """Digital checkout without voucher notes should still succeed and store change 0."""
        prod_id = helpers.get_product_id("POR-PAPAS")
        res = client.post("/api/pos/checkout", json={
            "items": [{"product_id": prod_id, "quantity": 1}],
            "payment_method": "datafono",
            "cash_received": 0,
            "notes": None
        })
        assert res.status_code == 200
        data = res.json()
        assert data["change_returned"] == 0
        row = db_conn.execute("SELECT * FROM sales WHERE sale_code = ?", (data["sale_code"],)).fetchone()
        assert row["change_returned"] == 0
        assert row["notes"] is None


class TestConcurrentUnderpaymentStress:
    """Stress test: concurrent rapid underpayment attempts do not deadlock or leak stock."""

    def test_20_concurrent_underpayment_attempts(self, client: TestClient, helpers, db_conn):
        prod_id = helpers.get_product_id("ALM-COMP")
        initial_stock = helpers.get_stock("pechuga_vitrina")
        initial_sales = helpers.count_sales()

        def try_underpaid_checkout(idx):
            return client.post("/api/pos/checkout", json={
                "items": [{"product_id": prod_id, "quantity": 1, "chosen_presa": "Pechuga"}],
                "payment_method": "efectivo",
                "cash_received": 15000 # Short by 1,000 COP
            })

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(try_underpaid_checkout, i) for i in range(20)]
            results = [f.result() for f in futures]

        # Every single attempt must return HTTP 400
        for r in results:
            assert r.status_code == 400

        # Stock and sales must be completely unchanged
        assert helpers.get_stock("pechuga_vitrina") == initial_stock
        assert helpers.count_sales() == initial_sales
