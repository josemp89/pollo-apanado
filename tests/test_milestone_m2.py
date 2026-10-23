import pytest
import os
from fastapi.testclient import TestClient

def test_cash_underpayment_rejected_with_400(client: TestClient, helpers):
    """
    Validation Guard: Cash payment with cash_received < total_amount
    must be strictly rejected with HTTP 400 and detail:
    'Monto en efectivo insuficiente para cubrir el total de la orden.'
    Zero stock deduction or database mutation must take place.
    """
    prod_id = helpers.get_product_id("ALM-COMP") # 16,000 COP
    initial_pechuga = helpers.get_stock("pechuga_vitrina")
    initial_sales_count = helpers.count_sales()

    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1, "chosen_presa": "Pechuga"}],
        "payment_method": "efectivo",
        "cash_received": 10000 # Underpayment by 6,000 COP
    })

    assert res.status_code == 400
    assert res.json()["detail"] == "Monto en efectivo insuficiente para cubrir el total de la orden."

    # Verify no inventory was deducted
    assert helpers.get_stock("pechuga_vitrina") == initial_pechuga
    # Verify no sale was registered
    assert helpers.count_sales() == initial_sales_count


def test_cash_underpayment_zero_or_null_rejected(client: TestClient, helpers):
    """Cash received as 0 or None must be strictly rejected with HTTP 400."""
    prod_id = helpers.get_product_id("POL-PEC") # 9,000 COP

    # Case 1: cash_received = 0
    res_zero = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": 0
    })
    assert res_zero.status_code == 400
    assert res_zero.json()["detail"] == "Monto en efectivo insuficiente para cubrir el total de la orden."

    # Case 2: cash_received = None
    res_none = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "efectivo",
        "cash_received": None
    })
    assert res_none.status_code == 400
    assert res_none.json()["detail"] == "Monto en efectivo insuficiente para cubrir el total de la orden."


def test_cash_underpayment_boundary_one_cop_short(client: TestClient, helpers):
    """Boundary test: exactly 1 COP short of the total must be rejected."""
    prod_id = helpers.get_product_id("ALM-COMP") # 16,000 COP
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1, "chosen_presa": "Pechuga"}],
        "payment_method": "efectivo",
        "cash_received": 15999
    })
    assert res.status_code == 400
    assert res.json()["detail"] == "Monto en efectivo insuficiente para cubrir el total de la orden."


def test_exact_cash_payment_accepted_with_zero_change(client: TestClient, helpers, db_conn):
    """Exact cash payment: total_amount == cash_received -> change_returned == 0."""
    prod_id = helpers.get_product_id("ALM-COMP") # 16,000 COP
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1, "chosen_presa": "Muslo"}],
        "payment_method": "efectivo",
        "cash_received": 16000
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["total_amount"] == 16000
    assert data["cash_received"] == 16000
    assert data["change_returned"] == 0
    assert data["payment_method"] == "efectivo"

    # Verify persisted in database
    row = db_conn.execute("SELECT * FROM sales WHERE sale_code = ?", (data["sale_code"],)).fetchone()
    assert row is not None
    assert row["total_amount"] == 16000
    assert row["cash_received"] == 16000
    assert row["change_returned"] == 0
    assert row["payment_method"] == "efectivo"


def test_cash_overpayment_accepted_with_exact_change(client: TestClient, helpers, db_conn):
    """Overpayment: exact integer change calculation."""
    prod_id1 = helpers.get_product_id("POL-PEC") # 9,000 COP
    prod_id2 = helpers.get_product_id("GAS-COL-400") # 3,500 COP
    # Total = 12,500 COP

    res = client.post("/api/pos/checkout", json={
        "items": [
            {"product_id": prod_id1, "quantity": 1},
            {"product_id": prod_id2, "quantity": 1}
        ],
        "payment_method": "efectivo",
        "cash_received": 20000 # Paying with 20,000 COP bill
    })
    assert res.status_code == 200
    data = res.json()
    assert data["total_amount"] == 12500
    assert data["cash_received"] == 20000
    assert data["change_returned"] == 7500 # Exactly 20,000 - 12,500

    row = db_conn.execute("SELECT * FROM sales WHERE sale_code = ?", (data["sale_code"],)).fetchone()
    assert row["total_amount"] == 12500
    assert row["cash_received"] == 20000
    assert row["change_returned"] == 7500


def test_invalid_payment_methods_rejected_with_400(client: TestClient, helpers):
    """
    Payment method whitelist validation: only 'efectivo', 'nequi_daviplata', 'datafono'
    are permitted. All other strings must be rejected with HTTP 400.
    """
    prod_id = helpers.get_product_id("POL-PEC")
    invalid_methods = ["bitcoin", "cheque", "credito", "fiado", "tarjeta", "paypal", ""]

    for inv_method in invalid_methods:
        res = client.post("/api/pos/checkout", json={
            "items": [{"product_id": prod_id, "quantity": 1}],
            "payment_method": inv_method,
            "cash_received": 50000
        })
        assert res.status_code == 400, f"Expected 400 for method '{inv_method}', got {res.status_code}"
        assert "no válido" in res.json()["detail"] or "permitidos" in res.json()["detail"]


def test_valid_payment_methods_with_case_and_whitespace_normalization(client: TestClient, helpers):
    """Valid payment methods should tolerate leading/trailing whitespace and uppercase."""
    prod_id = helpers.get_product_id("POL-PEC")

    methods_to_test = [
        ("  efectivo  ", 20000, "efectivo"),
        ("NEQUI_DAVIPLATA", 0, "nequi_daviplata"),
        ("  Datafono  ", 0, "datafono")
    ]

    for raw_m, cash, expected_m in methods_to_test:
        res = client.post("/api/pos/checkout", json={
            "items": [{"product_id": prod_id, "quantity": 1}],
            "payment_method": raw_m,
            "cash_received": cash
        })
        assert res.status_code == 200
        assert res.json()["payment_method"] == expected_m


def test_digital_payment_nequi_daviplata_change_zero_and_notes_stored(client: TestClient, helpers, db_conn):
    """Digital payment Nequi/Daviplata: change is always 0, optional notes/voucher persisted."""
    prod_id = helpers.get_product_id("POL-14") # 13,000 COP
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "nequi_daviplata",
        "cash_received": 0,
        "notes": "Comprobante: NQ-98765432"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["change_returned"] == 0
    assert data["payment_method"] == "nequi_daviplata"

    row = db_conn.execute("SELECT * FROM sales WHERE sale_code = ?", (data["sale_code"],)).fetchone()
    assert row["payment_method"] == "nequi_daviplata"
    assert row["change_returned"] == 0
    assert row["notes"] == "Comprobante: NQ-98765432"


def test_digital_payment_datafono_change_zero(client: TestClient, helpers, db_conn):
    """Digital payment Datáfono: change is always 0, even if client sends cash_received."""
    prod_id = helpers.get_product_id("POL-12") # 25,000 COP
    res = client.post("/api/pos/checkout", json={
        "items": [{"product_id": prod_id, "quantity": 1}],
        "payment_method": "datafono",
        "cash_received": 25000,
        "notes": "Comprobante: VOUCHER-DF-4412"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["change_returned"] == 0
    assert data["payment_method"] == "datafono"

    row = db_conn.execute("SELECT * FROM sales WHERE sale_code = ?", (data["sale_code"],)).fetchone()
    assert row["payment_method"] == "datafono"
    assert row["change_returned"] == 0
    assert row["notes"] == "Comprobante: VOUCHER-DF-4412"


def test_presa_selection_stock_boundary_depletion(client: TestClient, helpers):
    """
    Presa selection stock boundary:
    If a presa's vitrina stock is depleted to 0, ordering an Almuerzo with that presa
    must be rejected with HTTP 400. Ordering with an available presa succeeds.
    """
    alm_id = helpers.get_product_id("ALM-COMP")

    helpers.set_stock("pechuga_vitrina", 1.0)
    helpers.set_stock("muslo_vitrina", 0.0)

    # 1. Attempt checkout with exhausted Muslo -> 400 rejected
    res_muslo = client.post("/api/pos/checkout", json={
        "items": [{"product_id": alm_id, "quantity": 1, "chosen_presa": "Muslo"}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    assert res_muslo.status_code == 400
    assert "Stock insuficiente" in res_muslo.json()["detail"]

    # 2. Checkout with available Pechuga -> 200 success
    res_pechuga = client.post("/api/pos/checkout", json={
        "items": [{"product_id": alm_id, "quantity": 1, "chosen_presa": "Pechuga"}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    assert res_pechuga.status_code == 200
    assert helpers.get_stock("pechuga_vitrina") == 0.0

    # 3. Subsequent checkout with Pechuga -> now 400 rejected
    res_pechuga_second = client.post("/api/pos/checkout", json={
        "items": [{"product_id": alm_id, "quantity": 1, "chosen_presa": "Pechuga"}],
        "payment_method": "efectivo",
        "cash_received": 20000
    })
    assert res_pechuga_second.status_code == 400
    assert "Stock insuficiente" in res_pechuga_second.json()["detail"]


def test_frontend_stock_summary_endpoint(client: TestClient):
    """Verify /api/pos/stock-summary returns expected live inventory keys."""
    res = client.get("/api/pos/stock-summary")
    assert res.status_code == 200
    data = res.json()
    assert "pechuga_vitrina" in data
    assert "muslo_vitrina" in data
    assert "contramuslo_vitrina" in data
    assert "ala_vitrina" in data
    assert "caldo_raciones" in data
    assert "papas_raciones" in data


def test_html_template_m2_elements():
    """
    Verify template contains all M2 interactive elements:
    - Presa buttons with explicit IDs: btn-presa-pechuga, btn-presa-muslo, etc.
    - Digital payment modal: digitalModal, digitalVoucherInput, btnConfirmDigital
    - Cumulative cash functions: addCashAmount, clearCashAmount, setExactCash
    - Touch targets and classes
    """
    template_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "templates", "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Presa choice buttons with explicit IDs
    assert 'id="btn-presa-pechuga"' in html
    assert 'id="btn-presa-muslo"' in html
    assert 'id="btn-presa-contramuslo"' in html
    assert 'id="btn-presa-ala"' in html

    # Digital payment modal and controls
    assert 'id="digitalModal"' in html
    assert 'id="digitalVoucherInput"' in html
    assert 'id="btnConfirmDigital"' in html

    # Cumulative cash and reset buttons
    assert 'addCashAmount(10000)' in html
    assert 'addCashAmount(50000)' in html
    assert 'clearCashAmount()' in html
    assert 'setExactCash()' in html


def test_static_js_m2_features():
    """Verify static JS pos.js contains M2 logic and functions."""
    js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "static", "js", "pos.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    assert "PRESA_MAP" in js
    assert "btn-presa-pechuga" in js
    assert "addCashAmount" in js
    assert "clearCashAmount" in js
    assert "openDigitalModal" in js
    assert "confirmDigitalPayment" in js
    assert "getProductStockInfo" in js
    assert "w-11 h-11" in js


def test_static_css_tablet_ergonomics():
    """Verify static CSS style.css contains tablet touch classes."""
    css_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    assert ".touch-target-44" in css
    assert "min-width: 44px" in css
    assert ".touch-manipulation" in css
