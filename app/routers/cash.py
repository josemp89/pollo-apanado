from fastapi import APIRouter, Query, HTTPException, Header
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import json
from app.database import get_db_connection

router = APIRouter(prefix="/api/cash", tags=["Caja & Finanzas"])

class StockAdjustRequest(BaseModel):
    item_key: str
    new_stock: float
    reason: Optional[str] = "Ajuste manual"

class OpenShiftRequest(BaseModel):
    cashier_name: str = Field(..., min_length=2, description="Nombre del cajero responsable")
    base_inicial: int = Field(..., ge=0, description="Base inicial de efectivo en pesos COP")
    notes: Optional[str] = None

class CloseShiftRequest(BaseModel):
    shift_id: Optional[int] = None
    actual_cash: int = Field(..., ge=0, description="Conteo físico real de efectivo en el cajón")
    notes: Optional[str] = None

class CreateExpenseRequest(BaseModel):
    shift_id: Optional[int] = None
    amount: int = Field(..., gt=0, description="Monto del gasto menor en pesos COP")
    category: str = Field(..., description="insumos, servicios, transporte, mantenimiento, otro")
    concept: str = Field(..., min_length=2, description="Detalle o justificación del gasto")
    authorized_by: str = Field(..., min_length=2, description="Nombre de quien autoriza")
    recipient: Optional[str] = None
    receipt_number: Optional[str] = None

class VitrinaAuditRequest(BaseModel):
    auditor: str = Field("Santiago", min_length=2, description="Nombre del auditor responsable")
    pechugas_fisico: float = Field(..., ge=0)
    muslos_fisico: float = Field(..., ge=0)
    contramuslos_fisico: float = Field(..., ge=0)
    alas_fisico: float = Field(..., ge=0)
    adjust_inventory: bool = True
    notes: Optional[str] = None

def get_next_shift_code(cursor, now: datetime) -> str:
    date_code = now.strftime("%y%m%d")
    counter_name = f"shift_{now.strftime('%Y-%m-%d')}"
    cursor.execute("""
        INSERT INTO order_counters (counter_name, last_value)
        VALUES (?, 1)
        ON CONFLICT(counter_name) DO UPDATE SET last_value = order_counters.last_value + 1
        RETURNING last_value;
    """, (counter_name,))
    seq = cursor.fetchone()[0]
    return f"TURNO-{date_code}-{seq:04d}"

# ==================== ENDPOINTS DE CICLO DE CAJA (R1) ====================

@router.get("/current-shift")
def get_current_shift():
    conn = get_db_connection()
    try:
        shift = conn.execute("""
            SELECT * FROM cash_shifts WHERE status = 'abierto' ORDER BY id DESC LIMIT 1
        """).fetchone()
        if not shift:
            return {"active_shift": None}
        shift_dict = dict(shift)
        
        live_cash = conn.execute("""
            SELECT COALESCE(SUM(total_amount), 0) FROM sales 
            WHERE (shift_id = ? OR (shift_id IS NULL AND date_str = ?))
              AND payment_method = 'efectivo' AND status = 'completada'
        """, (shift["id"], shift["date_str"])).fetchone()[0]
        
        live_expenses = conn.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM cash_expenses
            WHERE shift_id = ? OR (shift_id IS NULL AND date_str = ?)
        """, (shift["id"], shift["date_str"])).fetchone()[0]

        shift_dict["current_cash_sales"] = live_cash
        shift_dict["current_expenses"] = live_expenses
        shift_dict["current_expected_cash"] = shift["base_inicial"] + live_cash - live_expenses
        return {"active_shift": shift_dict}
    finally:
        conn.close()

@router.post("/open-shift")
def open_shift(payload: OpenShiftRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        existing = cursor.execute("SELECT id, shift_code FROM cash_shifts WHERE status = 'abierto'").fetchone()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Ya existe un turno de caja abierto ({existing['shift_code']}). Debe cerrarlo antes de iniciar uno nuevo."
            )

        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        now_str = now.isoformat()
        shift_code = get_next_shift_code(cursor, now)

        cursor.execute("""
            INSERT INTO cash_shifts (
                shift_code, date_str, opened_at, cashier_name, base_inicial,
                expected_cash, closing_notes, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'abierto')
        """, (
            shift_code, date_str, now_str, payload.cashier_name.strip(),
            payload.base_inicial, payload.base_inicial, payload.notes
        ))
        shift_id = cursor.lastrowid
        conn.commit()

        created_shift = cursor.execute("SELECT * FROM cash_shifts WHERE id = ?", (shift_id,)).fetchone()
        return {
            "success": True,
            "message": f"Turno de caja {shift_code} abierto con éxito.",
            "shift": dict(created_shift)
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/close-shift")
def close_shift(payload: CloseShiftRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if payload.shift_id:
            shift = cursor.execute("SELECT * FROM cash_shifts WHERE id = ?", (payload.shift_id,)).fetchone()
        else:
            shift = cursor.execute("SELECT * FROM cash_shifts WHERE status = 'abierto' ORDER BY id DESC LIMIT 1").fetchone()

        if not shift:
            raise HTTPException(status_code=400, detail="No se encontró ningún turno de caja abierto para cerrar.")

        if shift["status"] == "cerrado":
            raise HTTPException(status_code=400, detail=f"El turno {shift['shift_code']} ya se encuentra cerrado.")

        shift_id = shift["id"]
        date_str = shift["date_str"]
        base_inicial = shift["base_inicial"]
        now = datetime.now()
        now_str = now.isoformat()

        # Ventas en efectivo asociadas
        cash_sales = cursor.execute("""
            SELECT COALESCE(SUM(total_amount), 0) FROM sales 
            WHERE (shift_id = ? OR (shift_id IS NULL AND date_str = ?))
              AND payment_method = 'efectivo' AND status = 'completada'
        """, (shift_id, date_str)).fetchone()[0]

        # Ventas digitales (Nequi / Daviplata)
        digital_sales = cursor.execute("""
            SELECT COALESCE(SUM(total_amount), 0) FROM sales 
            WHERE (shift_id = ? OR (shift_id IS NULL AND date_str = ?))
              AND payment_method = 'nequi_daviplata' AND status = 'completada'
        """, (shift_id, date_str)).fetchone()[0]

        # Ventas Datáfono
        datafono_sales = cursor.execute("""
            SELECT COALESCE(SUM(total_amount), 0) FROM sales 
            WHERE (shift_id = ? OR (shift_id IS NULL AND date_str = ?))
              AND payment_method = 'datafono' AND status = 'completada'
        """, (shift_id, date_str)).fetchone()[0]

        total_sales = cash_sales + digital_sales + datafono_sales

        # Gastos menores de caja menor
        total_expenses = cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) FROM cash_expenses 
            WHERE (shift_id = ? OR (shift_id IS NULL AND date_str = ?))
        """, (shift_id, date_str)).fetchone()[0]

        # Fórmula R1: Efectivo Final Esperado en Cajón = Base Inicial + Ventas Efectivo - Gastos Menores
        expected_cash = base_inicial + cash_sales - total_expenses
        actual_cash = payload.actual_cash
        difference = actual_cash - expected_cash

        closing_notes = payload.notes or shift["closing_notes"]

        cursor.execute("""
            UPDATE cash_shifts SET
                closed_at = ?,
                cash_sales = ?,
                digital_sales = ?,
                datafono_sales = ?,
                total_sales = ?,
                total_expenses = ?,
                expected_cash = ?,
                actual_cash = ?,
                difference = ?,
                closing_notes = ?,
                status = 'cerrado'
            WHERE id = ?
        """, (
            now_str, cash_sales, digital_sales, datafono_sales, total_sales,
            total_expenses, expected_cash, actual_cash, difference,
            closing_notes, shift_id
        ))
        conn.commit()

        updated_shift = cursor.execute("SELECT * FROM cash_shifts WHERE id = ?", (shift_id,)).fetchone()
        return {
            "success": True,
            "message": f"Turno {shift['shift_code']} cerrado correctamente.",
            "shift": dict(updated_shift),
            "reconciliation": {
                "base_inicial": base_inicial,
                "cash_sales": cash_sales,
                "total_expenses": total_expenses,
                "expected_cash": expected_cash,
                "actual_cash": actual_cash,
                "difference": difference,
                "digital_sales": digital_sales,
                "datafono_sales": datafono_sales,
                "total_sales": total_sales
            }
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# ==================== ENDPOINTS DE GASTOS MENORES (R1) ====================

@router.post("/expense")
def create_expense(payload: CreateExpenseRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        now = datetime.now()
        now_str = now.isoformat()
        date_str = now.strftime("%Y-%m-%d")

        shift_id = payload.shift_id
        if shift_id is None:
            active = cursor.execute("SELECT id FROM cash_shifts WHERE status = 'abierto' ORDER BY id DESC LIMIT 1").fetchone()
            if active:
                shift_id = active["id"]

        cursor.execute("""
            INSERT INTO cash_expenses (
                shift_id, timestamp, date_str, amount, category, concept,
                authorized_by, recipient, receipt_number
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            shift_id, now_str, date_str, payload.amount, payload.category.strip(),
            payload.concept.strip(), payload.authorized_by.strip(),
            payload.recipient.strip() if payload.recipient else None,
            payload.receipt_number.strip() if payload.receipt_number else None
        ))
        expense_id = cursor.lastrowid
        conn.commit()

        created = cursor.execute("SELECT * FROM cash_expenses WHERE id = ?", (expense_id,)).fetchone()
        return {
            "success": True,
            "message": f"Gasto menor de ${payload.amount:,} COP registrado con éxito.",
            "expense": dict(created)
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.get("/expenses")
def list_expenses(date_str: Optional[str] = None, shift_id: Optional[int] = None):
    conn = get_db_connection()
    try:
        query = "SELECT * FROM cash_expenses WHERE 1=1"
        params = []
        if shift_id is not None:
            query += " AND shift_id = ?"
            params.append(shift_id)
        elif date_str is not None:
            query += " AND date_str = ?"
            params.append(date_str)
        else:
            today = datetime.now().strftime("%Y-%m-%d")
            query += " AND date_str = ?"
            params.append(today)

        query += " ORDER BY id DESC"
        rows = conn.execute(query, tuple(params)).fetchall()
        expenses = [dict(r) for r in rows]
        total_expenses = sum(e["amount"] for e in expenses)
        return {
            "count": len(expenses),
            "total_expenses": total_expenses,
            "expenses": expenses
        }
    finally:
        conn.close()

# ==================== ENDPOINTS DE ARQUEO FÍSICO DE VITRINA (R4) ====================

@router.get("/vitrina-status")
def get_vitrina_status(date_str: Optional[str] = None):
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    try:
        stock_rows = conn.execute("""
            SELECT item_key, stock FROM inventory 
            WHERE item_key IN ('pechuga_vitrina', 'muslo_vitrina', 'contramuslo_vitrina', 'ala_vitrina')
        """).fetchall()
        stock_map = {r["item_key"]: float(r["stock"]) for r in stock_rows}

        theoretical = {
            "pechuga": stock_map.get("pechuga_vitrina", 0.0),
            "muslo": stock_map.get("muslo_vitrina", 0.0),
            "contramuslo": stock_map.get("contramuslo_vitrina", 0.0),
            "ala": stock_map.get("ala_vitrina", 0.0),
            "total": sum(stock_map.get(k, 0.0) for k in ('pechuga_vitrina', 'muslo_vitrina', 'contramuslo_vitrina', 'ala_vitrina'))
        }

        cancellations = conn.execute("""
            SELECT restored_presas_summary, total_amount FROM sale_cancellation_audit
            WHERE date_str = ?
        """, (date_str,)).fetchall()

        cancelled_presas = {"pechuga": 0.0, "muslo": 0.0, "contramuslo": 0.0, "ala": 0.0, "total": 0.0}
        total_refunded = 0
        for c in cancellations:
            total_refunded += c["total_amount"]
            try:
                p_data = json.loads(c["restored_presas_summary"])
                cancelled_presas["pechuga"] += float(p_data.get("pechugas", 0))
                cancelled_presas["muslo"] += float(p_data.get("muslos", 0))
                cancelled_presas["contramuslo"] += float(p_data.get("contramuslos", 0))
                cancelled_presas["ala"] += float(p_data.get("alas", 0))
                cancelled_presas["total"] += float(p_data.get("total_presas", 0))
            except Exception:
                pass

        return {
            "theoretical": theoretical,
            "today_cancelled_presas": {
                **cancelled_presas,
                "cancelled_sales_count": len(cancellations),
                "cancelled_amount_cop": total_refunded
            }
        }
    finally:
        conn.close()

@router.post("/vitrina-audit")
def create_vitrina_audit(payload: VitrinaAuditRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        now = datetime.now()
        now_str = now.isoformat()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        stock_rows = cursor.execute("""
            SELECT item_key, stock FROM inventory 
            WHERE item_key IN ('pechuga_vitrina', 'muslo_vitrina', 'contramuslo_vitrina', 'ala_vitrina')
        """).fetchall()
        stock_map = {r["item_key"]: float(r["stock"]) for r in stock_rows}

        pechugas_teorico = stock_map.get("pechuga_vitrina", 0.0)
        muslos_teorico = stock_map.get("muslo_vitrina", 0.0)
        contramuslos_teorico = stock_map.get("contramuslo_vitrina", 0.0)
        alas_teorico = stock_map.get("ala_vitrina", 0.0)
        total_teorico = pechugas_teorico + muslos_teorico + contramuslos_teorico + alas_teorico

        pechugas_fisico = payload.pechugas_fisico
        muslos_fisico = payload.muslos_fisico
        contramuslos_fisico = payload.contramuslos_fisico
        alas_fisico = payload.alas_fisico
        total_fisico = pechugas_fisico + muslos_fisico + contramuslos_fisico + alas_fisico

        pechugas_diff = pechugas_fisico - pechugas_teorico
        muslos_diff = muslos_fisico - muslos_teorico
        contramuslos_diff = contramuslos_fisico - contramuslos_teorico
        alas_diff = alas_fisico - alas_teorico
        total_diff = total_fisico - total_teorico

        has_discrepancy = bool(
            pechugas_diff != 0 or muslos_diff != 0 or
            contramuslos_diff != 0 or alas_diff != 0 or total_diff != 0
        )

        cancellations = cursor.execute("""
            SELECT restored_presas_summary, total_amount FROM sale_cancellation_audit
            WHERE date_str = ?
        """, (date_str,)).fetchall()

        cancelled_presas = {"pechuga": 0.0, "muslo": 0.0, "contramuslo": 0.0, "ala": 0.0}
        total_cancelled_cop = 0
        for c in cancellations:
            total_cancelled_cop += c["total_amount"]
            try:
                p_data = json.loads(c["restored_presas_summary"])
                cancelled_presas["pechuga"] += float(p_data.get("pechugas", 0))
                cancelled_presas["muslo"] += float(p_data.get("muslos", 0))
                cancelled_presas["contramuslo"] += float(p_data.get("contramuslos", 0))
                cancelled_presas["ala"] += float(p_data.get("alas", 0))
            except Exception:
                pass

        # Si hay faltante físico (diff < 0), correlacionar con presas devueltas por anulaciones
        theft_pechuga = min(abs(min(0.0, pechugas_diff)), cancelled_presas["pechuga"])
        theft_muslo = min(abs(min(0.0, muslos_diff)), cancelled_presas["muslo"])
        theft_contramuslo = min(abs(min(0.0, contramuslos_diff)), cancelled_presas["contramuslo"])
        theft_ala = min(abs(min(0.0, alas_diff)), cancelled_presas["ala"])
        total_theft_suspect = theft_pechuga + theft_muslo + theft_contramuslo + theft_ala

        has_theft_alert = total_theft_suspect > 0
        theft_alert_detail = None
        if has_theft_alert:
            theft_alert_detail = (
                f"🚨 ALERTA ROJA DE SUSTRACCIÓN NO AUTORIZADA: "
                f"Se detectó un faltante de {int(total_theft_suspect)} presas en vitrina que coincide con presas "
                f"reingresadas por ventas anuladas hoy (Pechugas: {int(theft_pechuga)}, Muslos: {int(theft_muslo)}, "
                f"Contramuslos: {int(theft_contramuslo)}, Alas: {int(theft_ala)}). "
                f"Total de dinero revertido por anulaciones: ${total_cancelled_cop:,} COP."
            )

        cursor.execute("""
            INSERT INTO vitrina_audits (
                timestamp, date_str, time_str, auditor,
                pechugas_teorico, pechugas_fisico, pechugas_diff,
                muslos_teorico, muslos_fisico, muslos_diff,
                contramuslos_teorico, contramuslos_fisico, contramuslos_diff,
                alas_teorico, alas_fisico, alas_diff,
                total_teorico, total_fisico, total_diff,
                has_discrepancy, has_theft_alert, theft_alert_detail,
                notes, inventory_adjusted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now_str, date_str, time_str, payload.auditor.strip(),
            pechugas_teorico, pechugas_fisico, pechugas_diff,
            muslos_teorico, muslos_fisico, muslos_diff,
            contramuslos_teorico, contramuslos_fisico, contramuslos_diff,
            alas_teorico, alas_fisico, alas_diff,
            total_teorico, total_fisico, total_diff,
            1 if has_discrepancy else 0,
            1 if has_theft_alert else 0,
            theft_alert_detail,
            payload.notes,
            1 if payload.adjust_inventory else 0
        ))
        audit_id = cursor.lastrowid

        if payload.adjust_inventory:
            for key, count in [
                ("pechuga_vitrina", pechugas_fisico),
                ("muslo_vitrina", muslos_fisico),
                ("contramuslo_vitrina", contramuslos_fisico),
                ("ala_vitrina", alas_fisico)
            ]:
                cursor.execute("""
                    UPDATE inventory SET stock = ?, updated_at = ? WHERE item_key = ?
                """, (count, now_str, key))

        conn.commit()

        audit_record = cursor.execute("SELECT * FROM vitrina_audits WHERE id = ?", (audit_id,)).fetchone()
        return {
            "success": True,
            "message": "Arqueo físico de vitrina registrado con éxito.",
            "audit": dict(audit_record),
            "has_discrepancy": has_discrepancy,
            "has_theft_alert": has_theft_alert,
            "theft_alert_detail": theft_alert_detail
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.get("/vitrina-audits")
def list_vitrina_audits(date_str: Optional[str] = None, limit: int = 10):
    conn = get_db_connection()
    try:
        query = "SELECT * FROM vitrina_audits WHERE 1=1"
        params = []
        if date_str:
            query += " AND date_str = ?"
            params.append(date_str)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

# ==================== RESUMEN DIARIO INTEGRAL (R1, R2, R3, R4) ====================

@router.get("/daily-summary")
def get_daily_summary(date_str: Optional[str] = None, shift_id: Optional[int] = None):
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    try:
        # 1. Turno de caja relevante
        shift_row = None
        if shift_id is not None:
            shift_row = conn.execute("SELECT * FROM cash_shifts WHERE id = ?", (shift_id,)).fetchone()
        else:
            shift_row = conn.execute("""
                SELECT * FROM cash_shifts 
                WHERE date_str = ? 
                ORDER BY CASE WHEN status = 'abierto' THEN 1 ELSE 2 END, id DESC 
                LIMIT 1
            """, (date_str,)).fetchone()

        shift_info = dict(shift_row) if shift_row else None
        base_inicial = shift_info["base_inicial"] if shift_info else 0

        # Filtro base para ventas del turno/día
        sales_filter = "date_str = ? AND status = 'completada'"
        sales_params = [date_str]
        if shift_id is not None:
            sales_filter = "shift_id = ? AND status = 'completada'"
            sales_params = [shift_id]

        # 2. Ventas por método de pago
        sales_by_method = conn.execute(f"""
            SELECT 
                payment_method, 
                COUNT(*) as tickets, 
                SUM(total_amount) as total
            FROM sales 
            WHERE {sales_filter}
            GROUP BY payment_method
        """, tuple(sales_params)).fetchall()

        totals_dict = {"efectivo": 0, "nequi_daviplata": 0, "datafono": 0, "gran_total": 0, "total_tickets": 0}
        for row in sales_by_method:
            method = row["payment_method"]
            totals_dict[method] = row["total"] or 0
            totals_dict["gran_total"] += (row["total"] or 0)
            totals_dict["total_tickets"] += row["tickets"]

        # 3. Gastos menores autorizados
        expense_filter = "date_str = ?"
        expense_params = [date_str]
        if shift_id is not None:
            expense_filter = "shift_id = ?"
            expense_params = [shift_id]

        expenses_rows = conn.execute(f"""
            SELECT * FROM cash_expenses WHERE {expense_filter} ORDER BY id ASC
        """, tuple(expense_params)).fetchall()
        expenses_list = [dict(r) for r in expenses_rows]
        total_expenses = sum(e["amount"] for e in expenses_list)

        # 4. Fórmula R1: Conciliación de Efectivo
        expected_cash = base_inicial + totals_dict["efectivo"] - total_expenses
        actual_cash = shift_info["actual_cash"] if shift_info else None
        difference = (actual_cash - expected_cash) if actual_cash is not None else None

        cash_reconciliation = {
            "base_inicial": base_inicial,
            "cash_sales": totals_dict["efectivo"],
            "total_expenses": total_expenses,
            "expected_cash": expected_cash,
            "actual_cash": actual_cash,
            "difference": difference,
            "digital_transfers": totals_dict["nequi_daviplata"],
            "card_vouchers": totals_dict["datafono"],
            "gran_total_sales": totals_dict["gran_total"],
            "total_liquidity": expected_cash + totals_dict["nequi_daviplata"] + totals_dict["datafono"]
        }

        # 5. Margen de Contribución Bruta Real del día
        margin_row = conn.execute(f"""
            SELECT SUM(si.quantity * (p.price - p.cost)) as total_margin
            FROM sales s
            JOIN sale_items si ON s.id = si.sale_id
            JOIN products p ON si.product_id = p.id
            WHERE s.{sales_filter}
        """, tuple(sales_params)).fetchone()
        estimated_margin = margin_row["total_margin"] or 0

        # 6. Punto de equilibrio diario sobre Margen de Contribución ($258.462 COP/día)
        setting_row = conn.execute("SELECT value FROM system_settings WHERE key = 'daily_breakeven_cop'").fetchone()
        daily_breakeven = int(setting_row["value"]) if setting_row else 258462
        
        breakeven_percentage = round((totals_dict["gran_total"] / daily_breakeven) * 100, 1) if daily_breakeven > 0 else 0
        margin_breakeven_percentage = round((estimated_margin / daily_breakeven) * 100, 1) if daily_breakeven > 0 else 0
        is_profitable = totals_dict["gran_total"] >= daily_breakeven

        # 7. Distribución de utilidades entre socios (Cap Table)
        net_operating_profit = max(0, estimated_margin - daily_breakeven)
        reserve_fund = round(net_operating_profit * 0.05, 0)
        distributable_profit = net_operating_profit - reserve_fund

        partner_distribution = {
            "net_operating_profit": net_operating_profit,
            "reserve_fund_5pct": reserve_fund,
            "distributable_profit": distributable_profit,
            "partner_1_capital_40pct": round(distributable_profit * 0.40, 0),
            "partner_2_capital_40pct": round(distributable_profit * 0.40, 0),
            "partner_santiago_operativo_20pct": round(distributable_profit * 0.20, 0)
        }

        # 8. Unidades globales de presas vendidas (compatibilidad hacia atrás)
        presas_sold = conn.execute(f"""
            SELECT 
                SUM(
                    CASE 
                        WHEN p.sku = 'POL-PEC' OR si.chosen_presa = 'Pechuga' THEN si.quantity
                        WHEN p.sku = 'POL-12' THEN 1.0 * si.quantity
                        WHEN p.sku = 'POL-ENT' THEN 2.0 * si.quantity
                        ELSE 0.0
                    END
                ) as pechugas,
                SUM(
                    CASE 
                        WHEN p.sku = 'POL-MUS' OR si.chosen_presa = 'Muslo' THEN si.quantity
                        WHEN p.sku = 'POL-14' THEN 1.0 * si.quantity
                        WHEN p.sku = 'POL-12' THEN 1.0 * si.quantity
                        WHEN p.sku = 'POL-ENT' THEN 2.0 * si.quantity
                        ELSE 0.0
                    END
                ) as muslos,
                SUM(
                    CASE 
                        WHEN p.sku = 'POL-CON' OR si.chosen_presa = 'Contramuslo' THEN si.quantity
                        WHEN p.sku = 'POL-14' THEN 1.0 * si.quantity
                        WHEN p.sku = 'POL-12' THEN 1.0 * si.quantity
                        WHEN p.sku = 'POL-ENT' THEN 2.0 * si.quantity
                        ELSE 0.0
                    END
                ) as contramuslos,
                SUM(
                    CASE 
                        WHEN p.sku = 'POL-ALA' OR si.chosen_presa = 'Ala' THEN si.quantity
                        WHEN p.sku = 'POL-12' THEN 1.0 * si.quantity
                        WHEN p.sku = 'POL-ENT' THEN 2.0 * si.quantity
                        ELSE 0.0
                    END
                ) as alas,
                SUM(CASE WHEN p.sku = 'ALM-COMP' THEN si.quantity ELSE 0 END) as almuerzos,
                SUM(CASE WHEN p.category = 'gaseosas' THEN si.quantity ELSE 0 END) as gaseosas,
                SUM(CASE WHEN p.sku = 'POR-CALD' THEN si.quantity ELSE 0 END) as caldos_sueltos
            FROM sales s
            JOIN sale_items si ON s.id = si.sale_id
            JOIN products p ON si.product_id = p.id
            WHERE s.{sales_filter}
        """, tuple(sales_params)).fetchone()

        # 9. Desglose Exhaustivo de Productos (R2) con conciliación matemática al 100%
        items_query = conn.execute(f"""
            SELECT 
                p.category,
                p.sku,
                p.name as product_name,
                p.price as unit_price,
                SUM(si.quantity) as total_quantity,
                SUM(si.subtotal) as total_revenue
            FROM sales s
            JOIN sale_items si ON s.id = si.sale_id
            JOIN products p ON si.product_id = p.id
            WHERE s.{sales_filter}
            GROUP BY p.category, p.sku, p.name, p.price
            ORDER BY p.category, total_revenue DESC
        """, tuple(sales_params)).fetchall()

        product_breakdown = {
            "presas_solas": {"items": [], "total_qty": 0, "subtotal_cop": 0},
            "combos": {"items": [], "total_qty": 0, "subtotal_cop": 0},
            "almuerzos": {"items": [], "total_qty": 0, "subtotal_cop": 0, "by_presa": {}},
            "porciones": {"items": [], "total_qty": 0, "subtotal_cop": 0},
            "gaseosas_postobon": {"items": [], "total_qty": 0, "subtotal_cop": 0},
            "gaseosas_cocacola": {"items": [], "total_qty": 0, "subtotal_cop": 0},
            "total_revenue_sum": 0,
            "zero_drift_verified": False
        }

        for r in items_query:
            it = dict(r)
            sku = it["sku"]
            cat = it["category"]
            name = it["product_name"]
            qty = it["total_quantity"]
            rev = it["total_revenue"]
            
            product_breakdown["total_revenue_sum"] += rev

            if sku in ('POL-PEC', 'POL-MUS', 'POL-CON', 'POL-ALA'):
                product_breakdown["presas_solas"]["items"].append(it)
                product_breakdown["presas_solas"]["total_qty"] += qty
                product_breakdown["presas_solas"]["subtotal_cop"] += rev
            elif sku in ('POL-14', 'POL-12', 'POL-ENT'):
                product_breakdown["combos"]["items"].append(it)
                product_breakdown["combos"]["total_qty"] += qty
                product_breakdown["combos"]["subtotal_cop"] += rev
            elif sku == 'ALM-COMP':
                product_breakdown["almuerzos"]["items"].append(it)
                product_breakdown["almuerzos"]["total_qty"] += qty
                product_breakdown["almuerzos"]["subtotal_cop"] += rev
            elif cat == 'porciones':
                product_breakdown["porciones"]["items"].append(it)
                product_breakdown["porciones"]["total_qty"] += qty
                product_breakdown["porciones"]["subtotal_cop"] += rev
            elif cat == 'gaseosas':
                if 'Postob' in name or sku.startswith('GAS-COL') or sku.startswith('GAS-MAN'):
                    product_breakdown["gaseosas_postobon"]["items"].append(it)
                    product_breakdown["gaseosas_postobon"]["total_qty"] += qty
                    product_breakdown["gaseosas_postobon"]["subtotal_cop"] += rev
                else:
                    product_breakdown["gaseosas_cocacola"]["items"].append(it)
                    product_breakdown["gaseosas_cocacola"]["total_qty"] += qty
                    product_breakdown["gaseosas_cocacola"]["subtotal_cop"] += rev

        # Desglose de presas elegidas en Almuerzo Completo
        almuerzos_presas_query = conn.execute(f"""
            SELECT 
                COALESCE(si.chosen_presa, 'Sin Especificar') as chosen_presa,
                SUM(si.quantity) as quantity
            FROM sales s
            JOIN sale_items si ON s.id = si.sale_id
            JOIN products p ON si.product_id = p.id
            WHERE s.{sales_filter} AND p.sku = 'ALM-COMP'
            GROUP BY si.chosen_presa
        """, tuple(sales_params)).fetchall()

        for ap in almuerzos_presas_query:
            product_breakdown["almuerzos"]["by_presa"][ap["chosen_presa"]] = ap["quantity"]

        product_breakdown["zero_drift_verified"] = bool(
            product_breakdown["total_revenue_sum"] == totals_dict["gran_total"]
        )

        # 10. Auditoría Forense de Ventas Anuladas (R3)
        cancellations_query = conn.execute("""
            SELECT * FROM sale_cancellation_audit
            WHERE date_str = ?
            ORDER BY id DESC
        """, (date_str,)).fetchall()

        cancellations_list = []
        refunded_by_method = {"efectivo": 0, "nequi_daviplata": 0, "datafono": 0}
        returned_presas = {"pechugas": 0, "muslos": 0, "contramuslos": 0, "alas": 0, "total": 0}
        total_refunded_cop = 0

        for c in cancellations_query:
            c_dict = dict(c)
            total_refunded_cop += c_dict["total_amount"]
            method = c_dict["payment_method"]
            refunded_by_method[method] = refunded_by_method.get(method, 0) + c_dict["total_amount"]
            try:
                p_data = json.loads(c_dict["restored_presas_summary"])
                returned_presas["pechugas"] += p_data.get("pechugas", 0)
                returned_presas["muslos"] += p_data.get("muslos", 0)
                returned_presas["contramuslos"] += p_data.get("contramuslos", 0)
                returned_presas["alas"] += p_data.get("alas", 0)
                returned_presas["total"] += p_data.get("total_presas", 0)
            except Exception:
                pass

            c_dict["restored_items"] = json.loads(c_dict["restored_items_json"]) if c_dict.get("restored_items_json") else []
            c_dict["presas"] = json.loads(c_dict["restored_presas_summary"]) if c_dict.get("restored_presas_summary") else {}
            cancellations_list.append(c_dict)

        cancellations_audit = {
            "total_cancelled_count": len(cancellations_list),
            "total_refunded_cop": total_refunded_cop,
            "refunded_by_method": refunded_by_method,
            "returned_presas_summary": returned_presas,
            "records": cancellations_list
        }

        # 11. Alertas de inventario bajo para compras a proveedores
        low_stock = conn.execute("""
            SELECT item_key, name, category, stock, unit, min_threshold
            FROM inventory
            WHERE stock <= min_threshold
            ORDER BY (stock - min_threshold) ASC
        """).fetchall()

        # 12. Estado y último arqueo de vitrina
        latest_audit = conn.execute("""
            SELECT * FROM vitrina_audits WHERE date_str = ? ORDER BY id DESC LIMIT 1
        """, (date_str,)).fetchone()

        return {
            "date": date_str,
            "shift_info": shift_info,
            "cash_summary": totals_dict,
            "cash_reconciliation": cash_reconciliation,
            "expenses_list": expenses_list,
            "product_breakdown": product_breakdown,
            "cancellations_audit": cancellations_audit,
            "latest_vitrina_audit": dict(latest_audit) if latest_audit else None,
            "estimated_margin": estimated_margin,
            "daily_breakeven_target": daily_breakeven,
            "breakeven_percentage": breakeven_percentage,
            "margin_breakeven_percentage": margin_breakeven_percentage,
            "is_profitable_today": is_profitable,
            "partner_distribution": partner_distribution,
            "units_sold": dict(presas_sold) if presas_sold else {},
            "low_stock_alerts": [dict(r) for r in low_stock]
        }
    finally:
        conn.close()

# ==================== ENDPOINTS DE INVENTARIO GENERAL ====================

@router.get("/inventory-all")
def get_all_inventory():
    conn = get_db_connection()
    items = conn.execute("SELECT * FROM inventory ORDER BY category, name ASC").fetchall()
    conn.close()
    return [dict(i) for i in items]

@router.post("/adjust-stock")
def adjust_stock(payload: StockAdjustRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE inventory 
        SET stock = ?, updated_at = ? 
        WHERE item_key = ?
    """, (payload.new_stock, datetime.now().isoformat(), payload.item_key))
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Stock de {payload.item_key} ajustado a {payload.new_stock}."}
