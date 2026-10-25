from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
from app.database import get_db_connection

router = APIRouter(prefix="/api/kitchen", tags=["Cocina & Tiempos"])

class DespieceRequest(BaseModel):
    whole_chickens: int
    operator: Optional[str] = "Santiago"
    notes: Optional[str] = None

class SurtirPresasRequest(BaseModel):
    pechugas: int = 0
    contramuslos: int = 0
    muslos: int = 0
    alas: int = 0
    operator: Optional[str] = "Santiago"
    notes: Optional[str] = "Refuerzo presas"

class BatchTimerRequest(BaseModel):
    stage: str  # 'salmuera', 'adobo', 'fritura'
    total_presas: int
    duration_hours: Optional[float] = None
    notes: Optional[str] = None

class SettingUpdateRequest(BaseModel):
    key: str
    value: str

VALID_BATCH_STAGES = ("salmuera", "adobo", "fritura")
STAGE_TRANSITIONS = {
    "salmuera": "adobo",
    "adobo": "fritura",
    "fritura": "terminado"
}

def get_next_batch_code(cursor, stage: str, now: datetime) -> str:
    stage_prefix = stage[:3].upper()
    date_code = now.strftime('%d%m')
    counter_name = f"batch_{now.strftime('%Y-%m-%d')}"
    today_prefix = f"{now.strftime('%Y-%m-%d')}%"
    
    while True:
        cursor.execute("""
            INSERT INTO order_counters (counter_name, last_value)
            VALUES (?, (SELECT COALESCE(COUNT(*), 0) FROM cooking_batches WHERE started_at LIKE ?) + 1)
            ON CONFLICT(counter_name) DO UPDATE SET last_value = order_counters.last_value + 1
            RETURNING last_value;
        """, (counter_name, today_prefix))
        seq = cursor.fetchone()[0]
        code = f"LOTE-{stage_prefix}-{date_code}-{seq:03d}"
        exists = cursor.execute("SELECT 1 FROM cooking_batches WHERE batch_code = ?", (code,)).fetchone()
        if not exists:
            return code

@router.post("/despiece")
def record_despiece(payload: DespieceRequest):
    if payload.whole_chickens <= 0:
        raise HTTPException(status_code=400, detail="La cantidad de pollos debe ser mayor a 0.")

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        now = datetime.now()
        n = payload.whole_chickens

        # Validar existencia de pollos enteros crudos en bodega
        row = cursor.execute("SELECT stock, name FROM inventory WHERE item_key = 'pollo_entero_crudo'").fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="El ítem 'pollo_entero_crudo' no existe en inventario.")

        available = row["stock"]
        if available < n:
            avail_disp = int(available) if float(available).is_integer() else available
            raise HTTPException(
                status_code=400,
                detail=f"Stock insuficiente de pollos crudos en bodega. Disponibles: {avail_disp}, requeridos: {n}."
            )

        # 1. Descontar pollos crudos de bodega con verificación atómica de piso
        cursor.execute("""
            UPDATE inventory 
            SET stock = stock - ?, updated_at = ? 
            WHERE item_key = 'pollo_entero_crudo' AND stock >= ?
        """, (n, now.isoformat(), n))
        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=400,
                detail="Stock insuficiente de pollos crudos en bodega. Operación rechazada."
            )

        # Rendimientos estándar de 8 presas por pollo + 2 raciones de caldo
        pechugas = 2 * n
        muslos = 2 * n
        contramuslos = 2 * n
        alas = 2 * n
        caldo_raciones = 2 * n

        # 2. Sumar presas listas y raciones de caldo a cocina/vitrina
        now_str = now.isoformat()
        cursor.execute("UPDATE inventory SET stock = stock + ?, updated_at = ? WHERE item_key = 'pechuga_vitrina'", (pechugas, now_str))
        cursor.execute("UPDATE inventory SET stock = stock + ?, updated_at = ? WHERE item_key = 'muslo_vitrina'", (muslos, now_str))
        cursor.execute("UPDATE inventory SET stock = stock + ?, updated_at = ? WHERE item_key = 'contramuslo_vitrina'", (contramuslos, now_str))
        cursor.execute("UPDATE inventory SET stock = stock + ?, updated_at = ? WHERE item_key = 'ala_vitrina'", (alas, now_str))
        cursor.execute("UPDATE inventory SET stock = stock + ?, updated_at = ? WHERE item_key = 'caldo_raciones'", (caldo_raciones, now_str))

        # 3. Guardar registro histórico de despiece con trazabilidad de auditoría
        cursor.execute("""
            INSERT INTO butchering_logs (
                timestamp, operator, whole_chickens, pechugas_yield, muslos_yield, 
                contramuslos_yield, alas_yield, caldo_bases_yield, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now_str, payload.operator, n, pechugas, muslos, contramuslos, alas, caldo_raciones, payload.notes
        ))

        conn.commit()

        return {
            "success": True,
            "message": f"¡Despiece de {n} pollos registrado exitosamente!",
            "yields": {
                "pechugas": pechugas,
                "muslos": muslos,
                "contramuslos": contramuslos,
                "alas": alas,
                "total_presas": pechugas + muslos + contramuslos + alas,
                "caldo_raciones": caldo_raciones
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

@router.post("/surtir-presas")
def surtir_presas(payload: SurtirPresasRequest):
    """
    Permite surtir presas específicas de pollo directamente a vitrina (ej. refuerzo de pechugas en la tarde).
    Actualiza el stock disponible en mostrador y registra la producción en butchering_logs.
    """
    total = payload.pechugas + payload.contramuslos + payload.muslos + payload.alas
    if total <= 0:
        raise HTTPException(status_code=400, detail="Debes ingresar al menos una presa para surtir a vitrina.")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        now = datetime.now()
        now_str = now.isoformat()

        # 1. Descontar presas de las canecas crudas en Nevera y sumarlas a Vitrina
        if payload.pechugas > 0:
            cursor.execute("UPDATE inventory SET stock = MAX(0, stock - ?), updated_at = ? WHERE item_key = 'pechuga_nevera'", (payload.pechugas, now_str))
            cursor.execute("UPDATE inventory SET stock = stock + ?, updated_at = ? WHERE item_key = 'pechuga_vitrina'", (payload.pechugas, now_str))
        if payload.muslos > 0:
            cursor.execute("UPDATE inventory SET stock = MAX(0, stock - ?), updated_at = ? WHERE item_key = 'muslo_nevera'", (payload.muslos, now_str))
            cursor.execute("UPDATE inventory SET stock = stock + ?, updated_at = ? WHERE item_key = 'muslo_vitrina'", (payload.muslos, now_str))
        if payload.contramuslos > 0:
            cursor.execute("UPDATE inventory SET stock = MAX(0, stock - ?), updated_at = ? WHERE item_key = 'contramuslo_nevera'", (payload.contramuslos, now_str))
            cursor.execute("UPDATE inventory SET stock = stock + ?, updated_at = ? WHERE item_key = 'contramuslo_vitrina'", (payload.contramuslos, now_str))
        if payload.alas > 0:
            cursor.execute("UPDATE inventory SET stock = MAX(0, stock - ?), updated_at = ? WHERE item_key = 'ala_nevera'", (payload.alas, now_str))
            cursor.execute("UPDATE inventory SET stock = stock + ?, updated_at = ? WHERE item_key = 'ala_vitrina'", (payload.alas, now_str))

        cursor.execute("""
            INSERT INTO butchering_logs (
                timestamp, operator, whole_chickens, pechugas_yield, muslos_yield, 
                contramuslos_yield, alas_yield, caldo_bases_yield, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
        """, (
            now_str, payload.operator, 0, payload.pechugas, payload.muslos, payload.contramuslos, payload.alas, payload.notes or "Pase de caneca en nevera a vitrina"
        ))

        conn.commit()

        # Obtener nuevo stock de cada presa (vitrina y canecas en nevera)
        rows = cursor.execute("""
            SELECT item_key, stock 
            FROM inventory 
            WHERE item_key IN ('pechuga_vitrina', 'muslo_vitrina', 'contramuslo_vitrina', 'ala_vitrina',
                               'pechuga_nevera', 'muslo_nevera', 'contramuslo_nevera', 'ala_nevera')
        """).fetchall()
        stock_map = {r["item_key"]: float(r["stock"]) for r in rows}

        return {
            "success": True,
            "message": f"¡Se surtieron {total} presas a la vitrina con éxito!",
            "added": {
                "pechugas": payload.pechugas,
                "contramuslos": payload.contramuslos,
                "muslos": payload.muslos,
                "alas": payload.alas,
                "total": total
            },
            "new_stock": stock_map
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.get("/hourly-demand")
def get_hourly_demand():
    """
    Analiza la demanda real de presas por hora (incluyendo presas dentro de combos)
    y genera una recomendación predictiva para freír con 15 minutos de anticipación.
    """
    conn = get_db_connection()
    now = datetime.now()
    current_hour = now.hour
    next_hour = (current_hour + 1) % 24

    # Consulta con desglose exacto de presas por hora (sueltas, almuerzos y dentro de combos)
    rows = conn.execute("""
        SELECT 
            s.hour_of_day,
            COUNT(DISTINCT s.id) as total_tickets,
            SUM(si.quantity) as total_items,
            SUM(
                CASE 
                    WHEN p.sku = 'POL-PEC' OR si.chosen_presa = 'Pechuga' THEN si.quantity
                    WHEN p.sku = 'POL-12' THEN 1.0 * si.quantity
                    WHEN p.sku = 'POL-ENT' THEN 2.0 * si.quantity
                    ELSE 0.0
                END
            ) as pechugas_count,
            SUM(
                CASE 
                    WHEN p.sku = 'POL-MUS' OR si.chosen_presa = 'Muslo' THEN si.quantity
                    WHEN p.sku = 'POL-14' THEN 1.0 * si.quantity
                    WHEN p.sku = 'POL-12' THEN 1.0 * si.quantity
                    WHEN p.sku = 'POL-ENT' THEN 2.0 * si.quantity
                    ELSE 0.0
                END
            ) as muslos_count,
            SUM(
                CASE 
                    WHEN p.sku = 'POL-CON' OR si.chosen_presa = 'Contramuslo' THEN si.quantity
                    WHEN p.sku = 'POL-14' THEN 1.0 * si.quantity
                    WHEN p.sku = 'POL-12' THEN 1.0 * si.quantity
                    WHEN p.sku = 'POL-ENT' THEN 2.0 * si.quantity
                    ELSE 0.0
                END
            ) as contramuslos_count,
            SUM(
                CASE 
                    WHEN p.sku = 'POL-ALA' OR si.chosen_presa = 'Ala' THEN si.quantity
                    WHEN p.sku = 'POL-12' THEN 1.0 * si.quantity
                    WHEN p.sku = 'POL-ENT' THEN 2.0 * si.quantity
                    ELSE 0.0
                END
            ) as alas_count
        FROM sales s
        JOIN sale_items si ON s.id = si.sale_id
        JOIN products p ON si.product_id = p.id
        WHERE s.status = 'completada'
        GROUP BY s.hour_of_day
        ORDER BY s.hour_of_day ASC
    """).fetchall()

    settings_rows = conn.execute("SELECT key, value FROM system_settings").fetchall()
    settings = {r["key"]: r["value"] for r in settings_rows}

    # Stock actual en vitrina para contrastar necesidad de fritura
    vitrina_rows = conn.execute("""
        SELECT item_key, stock FROM inventory 
        WHERE item_key IN ('pechuga_vitrina', 'muslo_vitrina', 'contramuslo_vitrina', 'ala_vitrina')
    """).fetchall()
    vitrina_stock = {r["item_key"]: r["stock"] for r in vitrina_rows}

    # Algoritmo Predictivo de Fritura para la siguiente hora
    hourly_dict = {r["hour_of_day"]: dict(r) for r in rows}
    next_hour_data = hourly_dict.get(next_hour, {})

    target_pechugas = max(4, int(next_hour_data.get("pechugas_count", 6)))
    target_muslos = max(4, int(next_hour_data.get("muslos_count", 6)))
    target_contramuslos = max(4, int(next_hour_data.get("contramuslos_count", 6)))
    target_alas = max(4, int(next_hour_data.get("alas_count", 4)))

    cur_p = vitrina_stock.get("pechuga_vitrina", 0)
    cur_m = vitrina_stock.get("muslo_vitrina", 0)
    cur_c = vitrina_stock.get("contramuslo_vitrina", 0)
    cur_a = vitrina_stock.get("ala_vitrina", 0)

    suggested_fry = {
        "pechugas": max(0, int(target_pechugas - cur_p)),
        "muslos": max(0, int(target_muslos - cur_m)),
        "contramuslos": max(0, int(target_contramuslos - cur_c)),
        "alas": max(0, int(target_alas - cur_a)),
    }
    suggested_fry["total"] = sum(suggested_fry.values())

    lead_time_min = 15
    fry_start_time = (now + timedelta(minutes=lead_time_min)).strftime("%I:%M %p")

    conn.close()
    return {
        "hourly_data": [dict(r) for r in rows],
        "settings": settings,
        "fryer_recommendation": {
            "current_hour": current_hour,
            "next_hour": next_hour,
            "lead_time_minutes": lead_time_min,
            "fry_start_recommended_at": fry_start_time,
            "vitrina_current": {
                "pechugas": cur_p,
                "muslos": cur_m,
                "contramuslos": cur_c,
                "alas": cur_a
            },
            "suggested_to_fry": suggested_fry,
            "status_message": (
                f"Tirar tanda de {suggested_fry['total']} presas a freidora a las {fry_start_time} "
                f"para cubrir la demanda proyectada de las {next_hour}:00."
                if suggested_fry['total'] > 0 else "Stock en vitrina suficiente para la próxima hora."
            )
        }
    }

@router.post("/batch-timer")
def start_batch_timer(payload: BatchTimerRequest):
    # 1. Validar etapa permitida
    stage_norm = (payload.stage or "").strip().lower()
    if stage_norm not in VALID_BATCH_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Etapa inválida '{payload.stage}'. Debe ser una de: {list(VALID_BATCH_STAGES)}"
        )

    # 2. Validar que la cantidad de presas sea estrictamente mayor a 0
    if payload.total_presas <= 0:
        raise HTTPException(
            status_code=400,
            detail="El total de presas debe ser mayor a 0."
        )

    # 3. Validar duración si se proporciona explícitamente
    if payload.duration_hours is not None and payload.duration_hours <= 0:
        raise HTTPException(
            status_code=400,
            detail="La duración debe ser mayor a 0 horas."
        )

    payload.stage = stage_norm
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        now = datetime.now()

        # Si no se envía duración, tomar la configuración estándar
        duration = payload.duration_hours
        if duration is None:
            if payload.stage == "fritura":
                row = cursor.execute("SELECT value FROM system_settings WHERE key = 'fritura_minutes'").fetchone()
                minutes = float(row["value"]) if row else 14.0
                duration = minutes / 60.0
            else:
                setting_key = f"{payload.stage}_hours"
                row = cursor.execute("SELECT value FROM system_settings WHERE key = ?", (setting_key,)).fetchone()
                duration = float(row["value"]) if row else (6.0 if payload.stage == "salmuera" else 4.0)

        target_time = now + timedelta(hours=duration)
        batch_code = get_next_batch_code(cursor, payload.stage, now)

        cursor.execute("""
            INSERT INTO cooking_batches (
                batch_code, stage, total_presas, started_at, target_finished_at, notes
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            batch_code, payload.stage, payload.total_presas, now.isoformat(), target_time.isoformat(), payload.notes
        ))

        # Consumo de insumos secos en etapa de fritura
        if payload.stage == "fritura" and payload.total_presas > 0:
            harina_used = round(payload.total_presas * 0.025, 3)
            aceite_used = round(payload.total_presas * 0.02, 3)
            now_str = now.isoformat()
            cursor.execute("""
                UPDATE inventory 
                SET stock = MAX(0.0, stock - ?), updated_at = ? 
                WHERE item_key = 'harina_apanar_kg'
            """, (harina_used, now_str))
            cursor.execute("""
                UPDATE inventory 
                SET stock = MAX(0.0, stock - ?), updated_at = ? 
                WHERE item_key = 'aceite_fritura_lt'
            """, (aceite_used, now_str))

        conn.commit()

        return {
            "success": True,
            "batch_code": batch_code,
            "stage": payload.stage,
            "started_at": now.strftime("%I:%M %p"),
            "target_finished_at": target_time.strftime("%I:%M %p"),
            "duration_hours": duration
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/advance-batch/{batch_id}")
def advance_batch(batch_id: int):
    """Avanza un lote a la siguiente etapa (Salmuera -> Adobo -> Fritura -> Terminado)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        batch = cursor.execute("SELECT * FROM cooking_batches WHERE id = ?", (batch_id,)).fetchone()
        if not batch:
            raise HTTPException(status_code=404, detail="Lote no encontrado.")

        current_stage = batch["stage"]
        if current_stage not in STAGE_TRANSITIONS:
            raise HTTPException(status_code=400, detail=f"El lote ya se encuentra en estado '{current_stage}'.")

        next_stage = STAGE_TRANSITIONS[current_stage]
        now = datetime.now()

        # Calcular nueva duración según la siguiente etapa
        if next_stage == "fritura":
            row = cursor.execute("SELECT value FROM system_settings WHERE key = 'fritura_minutes'").fetchone()
            dur = (float(row["value"]) if row else 14.0) / 60.0
        elif next_stage == "adobo":
            row = cursor.execute("SELECT value FROM system_settings WHERE key = 'adobo_hours'").fetchone()
            dur = float(row["value"]) if row else 4.0
        else: # terminado
            dur = 0.0

        target_time = now + timedelta(hours=dur)

        cursor.execute("""
            UPDATE cooking_batches
            SET stage = ?, started_at = ?, target_finished_at = ?, 
                completed_at = CASE WHEN ? = 'terminado' THEN ? ELSE completed_at END
            WHERE id = ?
        """, (next_stage, now.isoformat(), target_time.isoformat(), next_stage, now.isoformat(), batch_id))

        # Si avanza a terminado desde fritura, sumar presas fritas a vitrina
        if current_stage == "fritura" and next_stage == "terminado":
            per_type = batch["total_presas"] // 4
            now_str = now.isoformat()
            cursor.execute("UPDATE inventory SET stock = stock + ?, updated_at = ? WHERE item_key = 'pechuga_vitrina'", (per_type, now_str))
            cursor.execute("UPDATE inventory SET stock = stock + ?, updated_at = ? WHERE item_key = 'muslo_vitrina'", (per_type, now_str))
            cursor.execute("UPDATE inventory SET stock = stock + ?, updated_at = ? WHERE item_key = 'contramuslo_vitrina'", (per_type, now_str))
            cursor.execute("UPDATE inventory SET stock = stock + ?, updated_at = ? WHERE item_key = 'ala_vitrina'", (per_type, now_str))

        conn.commit()
        return {
            "success": True,
            "batch_id": batch_id,
            "previous_stage": current_stage,
            "new_stage": next_stage,
            "target_finished_at": target_time.strftime("%I:%M %p") if next_stage != "terminado" else "Listo"
        }
    finally:
        conn.close()

@router.get("/batch-timers")
def get_batch_timers():
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT * FROM cooking_batches 
        WHERE stage != 'terminado' 
        ORDER BY id DESC LIMIT 10
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@router.get("/settings")
def get_settings():
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM system_settings").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@router.put("/settings")
def update_setting(payload: SettingUpdateRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE system_settings SET value = ? WHERE key = ?", (payload.value, payload.key))
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Parámetro {payload.key} actualizado a {payload.value}."}
