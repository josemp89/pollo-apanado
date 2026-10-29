# -*- coding: utf-8 -*-
"""
accounting.py - Router del Libro Contable y Gerencia Financiera
Pollo Apanado
Permite al Dueño/Gerente (Alejandro):
- Ver la hoja de cálculo / sábana contable diaria y mensual
- Apuntar pagos a proveedores (Pollo, Bebidas, Insumos) y gastos operativos
- Registrar / Sincronizar con 1 click los ingresos brutos del cierre de caja del asadero
- Calcular la utilidad neta real, margen % y cruce de tesorería (Caja vs Cuentas Digitales)
- Exportar reporte completo a Excel (CSV con formato latino)
"""

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
import calendar
import io
import csv

from app.database import get_db_connection

router = APIRouter(prefix="/api/accounting", tags=["accounting"])

class DailyIncomeRequest(BaseModel):
    date_str: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    income_cash: int = Field(ge=0)
    income_digital: int = Field(ge=0)
    income_datafono: int = Field(ge=0)
    notes: Optional[str] = None

class SyncPosRequest(BaseModel):
    date_str: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")

class CreateAccountingExpenseRequest(BaseModel):
    date_str: Optional[str] = None
    amount: int = Field(gt=0)
    category: str
    concept: str
    payment_source: str = "banco_transferencia" # 'banco_transferencia' o 'caja_efectivo'
    recipient: Optional[str] = None
    receipt_number: Optional[str] = None
    authorized_by: str = "Alejandro"

SPANISH_DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
SPANISH_MONTHS = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
]

@router.get("/ledger")
def get_accounting_ledger(month: Optional[str] = None):
    """
    Retorna la sábana contable tipo hoja de cálculo (Excel) para el mes indicado (YYYY-MM).
    Calcula día a día los ingresos brutos, compras COGS, gastos OPEX, utilidad neta y cruces.
    """
    now = datetime.now()
    if not month:
        month = now.strftime("%Y-%m")

    try:
        year_num, month_num = map(int, month.split("-"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de mes inválido. Debe ser YYYY-MM")

    num_days = calendar.monthrange(year_num, month_num)[1]
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 1. Obtener ingresos registrados en daily_income_ledger para este mes
        income_rows = cursor.execute("""
            SELECT date_str, income_cash, income_digital, income_datafono, income_total, source, notes
            FROM daily_income_ledger
            WHERE date_str LIKE ?
        """, (f"{month}%",)).fetchall()
        income_map = {r["date_str"]: dict(r) for r in income_rows}

        # 2. Obtener ventas reales en sales agrupadas por día y método de pago (para días sin override manual)
        pos_sales_rows = cursor.execute("""
            SELECT 
                date_str,
                COALESCE(SUM(CASE WHEN payment_method = 'efectivo' THEN total_amount ELSE 0 END), 0) AS pos_cash,
                COALESCE(SUM(CASE WHEN payment_method IN ('nequi_daviplata', 'digital', 'transferencia') THEN total_amount ELSE 0 END), 0) AS pos_digital,
                COALESCE(SUM(CASE WHEN payment_method = 'datafono' THEN total_amount ELSE 0 END), 0) AS pos_datafono,
                COALESCE(SUM(total_amount), 0) AS pos_total
            FROM sales
            WHERE date_str LIKE ? AND status = 'completada'
            GROUP BY date_str
        """, (f"{month}%",)).fetchall()
        pos_sales_map = {r["date_str"]: dict(r) for r in pos_sales_rows}

        # 3. Obtener todos los gastos y compras de este mes
        expense_rows = cursor.execute("""
            SELECT id, timestamp, date_str, amount, category, concept, payment_source, recipient, receipt_number, authorized_by
            FROM cash_expenses
            WHERE date_str LIKE ?
            ORDER BY timestamp ASC
        """, (f"{month}%",)).fetchall()

        expenses_by_day = {}
        for er in expense_rows:
            d_str = er["date_str"] or (er["timestamp"][:10] if er["timestamp"] else "")
            if not d_str:
                continue
            if d_str not in expenses_by_day:
                expenses_by_day[d_str] = []
            expenses_by_day[d_str].append(dict(er))

        # 4. Construir la cuadrícula de días del mes
        daily_ledger = []
        month_totals = {
            "income_cash": 0, "income_digital": 0, "income_datafono": 0, "income_total": 0,
            "purchases_cogs": 0, "operating_expenses": 0, "partner_withdrawals": 0, "total_expenses": 0,
            "expenses_cash": 0, "expenses_digital": 0,
            "net_cash_drawer": 0, "net_digital_balance": 0,
            "net_profit": 0
        }

        # Iteramos desde el día 1 hasta num_days
        for d in range(1, num_days + 1):
            date_obj = date(year_num, month_num, d)
            date_str = date_obj.strftime("%Y-%m-%d")
            day_name = SPANISH_DAYS[date_obj.weekday()]

            # Determinar ingresos: Si hay registro en daily_income_ledger se usa, si no, se usa POS sales
            has_ledger_entry = date_str in income_map
            if has_ledger_entry:
                inc_rec = income_map[date_str]
                inc_cash = inc_rec["income_cash"]
                inc_digital = inc_rec["income_digital"]
                inc_datafono = inc_rec["income_datafono"]
                inc_total = inc_cash + inc_digital + inc_datafono
                income_source = inc_rec["source"]
            elif date_str in pos_sales_map:
                pos_rec = pos_sales_map[date_str]
                inc_cash = pos_rec["pos_cash"]
                inc_digital = pos_rec["pos_digital"]
                inc_datafono = pos_rec["pos_datafono"]
                inc_total = pos_rec["pos_total"]
                income_source = "pos_live"
            else:
                inc_cash = inc_digital = inc_datafono = inc_total = 0
                income_source = "sin_ventas"

            # Sumar gastos de este día
            day_expenses = expenses_by_day.get(date_str, [])
            cogs = 0
            opex = 0
            withdrawals = 0
            exp_cash = 0
            exp_digital = 0

            for exp in day_expenses:
                amt = exp["amount"]
                cat = (exp["category"] or "").lower()
                src = (exp["payment_source"] or "caja_efectivo").lower()

                if cat.startswith("compra_"):
                    cogs += amt
                elif cat == "retiro_socio":
                    withdrawals += amt
                else:
                    opex += amt

                if src in ("banco_transferencia", "bancos"):
                    exp_digital += amt
                else:
                    exp_cash += amt

            tot_expenses = cogs + opex + withdrawals
            net_profit = inc_total - tot_expenses
            net_margin_pct = round((net_profit / inc_total * 100), 1) if inc_total > 0 else 0.0
            net_cash_drawer = inc_cash - exp_cash
            net_digital_balance = (inc_digital + inc_datafono) - exp_digital

            # Acumular mes
            month_totals["income_cash"] += inc_cash
            month_totals["income_digital"] += inc_digital
            month_totals["income_datafono"] += inc_datafono
            month_totals["income_total"] += inc_total
            month_totals["purchases_cogs"] += cogs
            month_totals["operating_expenses"] += opex
            month_totals["partner_withdrawals"] += withdrawals
            month_totals["total_expenses"] += tot_expenses
            month_totals["expenses_cash"] += exp_cash
            month_totals["expenses_digital"] += exp_digital
            month_totals["net_cash_drawer"] += net_cash_drawer
            month_totals["net_digital_balance"] += net_digital_balance
            month_totals["net_profit"] += net_profit

            daily_ledger.append({
                "day": d,
                "date_str": date_str,
                "day_name": day_name,
                "has_activity": (inc_total > 0 or tot_expenses > 0),
                "income_source": income_source,
                "income_cash": inc_cash,
                "income_digital": inc_digital,
                "income_datafono": inc_datafono,
                "income_total": inc_total,
                "purchases_cogs": cogs,
                "operating_expenses": opex,
                "partner_withdrawals": withdrawals,
                "total_expenses": tot_expenses,
                "expenses_cash": exp_cash,
                "expenses_digital": exp_digital,
                "net_profit": net_profit,
                "net_margin_pct": net_margin_pct,
                "net_cash_drawer": net_cash_drawer,
                "net_digital_balance": net_digital_balance,
                "expenses_count": len(day_expenses),
                "expenses": day_expenses
            })

        month_margin_pct = round((month_totals["net_profit"] / month_totals["income_total"] * 100), 1) if month_totals["income_total"] > 0 else 0.0
        month_totals["net_margin_pct"] = month_margin_pct

        return {
            "success": True,
            "month": month,
            "month_label": f"{SPANISH_MONTHS[month_num - 1]} {year_num}",
            "days_in_month": num_days,
            "month_totals": month_totals,
            "ledger": daily_ledger
        }
    finally:
        conn.close()

@router.post("/daily-income")
def update_daily_income(payload: DailyIncomeRequest):
    """Permite al dueño guardar o ajustar los ingresos brutos de un día específico."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        total = payload.income_cash + payload.income_digital + payload.income_datafono
        now_str = datetime.now().isoformat()

        cursor.execute("""
            INSERT INTO daily_income_ledger (date_str, income_cash, income_digital, income_datafono, income_total, source, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, 'manual', ?, ?)
            ON CONFLICT(date_str) DO UPDATE SET
                income_cash = excluded.income_cash,
                income_digital = excluded.income_digital,
                income_datafono = excluded.income_datafono,
                income_total = excluded.income_total,
                source = 'manual',
                notes = excluded.notes,
                updated_at = excluded.updated_at
        """, (payload.date_str, payload.income_cash, payload.income_digital, payload.income_datafono, total, payload.notes, now_str))
        conn.commit()

        return {
            "success": True,
            "message": f"Ingresos para el día {payload.date_str} guardados correctamente ($ {total:,} COP)."
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/sync-pos-day")
def sync_pos_day(payload: SyncPosRequest):
    """
    Sincroniza con 1 toque las ventas registradas en el POS para un día específico
    y las actualiza en el libro contable.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        date_str = payload.date_str

        row = cursor.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN payment_method = 'efectivo' THEN total_amount ELSE 0 END), 0) AS pos_cash,
                COALESCE(SUM(CASE WHEN payment_method IN ('nequi_daviplata', 'digital', 'transferencia') THEN total_amount ELSE 0 END), 0) AS pos_digital,
                COALESCE(SUM(CASE WHEN payment_method = 'datafono' THEN total_amount ELSE 0 END), 0) AS pos_datafono,
                COALESCE(SUM(total_amount), 0) AS pos_total
            FROM sales
            WHERE date_str = ? AND status = 'completada'
        """, (date_str,)).fetchone()

        pos_cash = row["pos_cash"]
        pos_digital = row["pos_digital"]
        pos_datafono = row["pos_datafono"]
        pos_total = row["pos_total"]
        now_str = datetime.now().isoformat()

        cursor.execute("""
            INSERT INTO daily_income_ledger (date_str, income_cash, income_digital, income_datafono, income_total, source, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, 'pos_sync', 'Sincronizado desde cierres del mostrador', ?)
            ON CONFLICT(date_str) DO UPDATE SET
                income_cash = excluded.income_cash,
                income_digital = excluded.income_digital,
                income_datafono = excluded.income_datafono,
                income_total = excluded.income_total,
                source = 'pos_sync',
                notes = excluded.notes,
                updated_at = excluded.updated_at
        """, (date_str, pos_cash, pos_digital, pos_datafono, pos_total, now_str))
        conn.commit()

        return {
            "success": True,
            "message": f"Día {date_str} sincronizado: $ {pos_total:,} COP (Efectivo: ${pos_cash:,}, Nequi: ${pos_digital:,}, Datáfono: ${pos_datafono:,})",
            "income": {
                "date_str": date_str,
                "cash": pos_cash,
                "digital": pos_digital,
                "datafono": pos_datafono,
                "total": pos_total
            }
        }
    finally:
        conn.close()

@router.post("/expense")
def create_accounting_expense(payload: CreateAccountingExpenseRequest):
    """
    Permite al dueño registrar un pago a proveedor (pollo, bebidas, etc.)
    o un gasto operativo desde su computador o teléfono celular.
    """
    conn = get_db_connection()
    try:
        now = datetime.now()
        now_str = now.isoformat()
        date_str = payload.date_str if payload.date_str else now.strftime("%Y-%m-%d")
        payment_source = payload.payment_source if payload.payment_source in ("banco_transferencia", "caja_efectivo") else "banco_transferencia"

        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO cash_expenses (
                shift_id, timestamp, date_str, amount, category, concept,
                authorized_by, recipient, receipt_number, payment_source
            ) VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now_str, date_str, payload.amount, payload.category.strip(),
            payload.concept.strip(), payload.authorized_by.strip(),
            payload.recipient.strip() if payload.recipient else None,
            payload.receipt_number.strip() if payload.receipt_number else None,
            payment_source
        ))
        expense_id = cursor.lastrowid
        conn.commit()

        return {
            "success": True,
            "message": f"Egreso de ${payload.amount:,} COP registrado con éxito para el día {date_str}.",
            "expense_id": expense_id
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.delete("/expense/{expense_id}")
def delete_accounting_expense(expense_id: int):
    """Permite al dueño eliminar un gasto si cometió un error de digitación."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        row = cursor.execute("SELECT id, amount, concept FROM cash_expenses WHERE id = ?", (expense_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Gasto no encontrado.")

        cursor.execute("DELETE FROM cash_expenses WHERE id = ?", (expense_id,))
        conn.commit()
        return {"success": True, "message": f"Egreso #{expense_id} eliminado correctamente."}
    finally:
        conn.close()

@router.get("/export-ledger")
def export_accounting_ledger_csv(month: Optional[str] = None):
    """
    Descarga la hoja de cálculo contable del mes en formato CSV para Excel
    (separador ';' y UTF-8 BOM para apertura perfecta en Excel Windows/Mac).
    """
    ledger_data = get_accounting_ledger(month)
    ledger_rows = ledger_data["ledger"]
    month_totals = ledger_data["month_totals"]

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')

    # Encabezado
    writer.writerow([f"LIBRO CONTABLE Y CRUCE FINANCIERO - DON POLLO - {ledger_data['month_label']}"])
    writer.writerow([f"Generado el: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"])
    writer.writerow([])

    # Columnas de la Hoja de Cálculo
    writer.writerow([
        "Fecha", "Día", "Ingreso Efectivo", "Ingreso Nequi/Transf", "Ingreso Datáfono", "Total Ingresos Brutos",
        "Compras Mercancía (COGS)", "Gastos Operativos (OPEX)", "Retiro Socios", "Total Egresos",
        "Utilidad Neta Real", "Margen %", "Saldo Efectivo Caja", "Saldo Cuentas Digitales", "Origen Ingreso"
    ])

    for row in ledger_rows:
        writer.writerow([
            row["date_str"],
            row["day_name"],
            row["income_cash"],
            row["income_digital"],
            row["income_datafono"],
            row["income_total"],
            row["purchases_cogs"],
            row["operating_expenses"],
            row["partner_withdrawals"],
            row["total_expenses"],
            row["net_profit"],
            f"{row['net_margin_pct']}%",
            row["net_cash_drawer"],
            row["net_digital_balance"],
            row["income_source"]
        ])

    # Fila de Totales del Mes
    writer.writerow([])
    writer.writerow([
        "TOTAL MES", "-",
        month_totals["income_cash"],
        month_totals["income_digital"],
        month_totals["income_datafono"],
        month_totals["income_total"],
        month_totals["purchases_cogs"],
        month_totals["operating_expenses"],
        month_totals["partner_withdrawals"],
        month_totals["total_expenses"],
        month_totals["net_profit"],
        f"{month_totals['net_margin_pct']}%",
        month_totals["net_cash_drawer"],
        month_totals["net_digital_balance"],
        "-"
    ])

    content = "\ufeff" + output.getvalue()
    filename = f"Libro_Contable_DonPollo_{ledger_data['month']}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
