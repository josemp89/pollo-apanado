# -*- coding: utf-8 -*-
"""
auth.py - Router de Autenticación y Control de Usuarios
Pollo Apanado
Roles:
- 'admin': Dueño / Gerencia (Acceso completo a finanzas, compras, P&L, ventas)
- 'cajero': Vendedor / Asadero (Mostrador, caja operativa, rotación de presas)
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.database import get_db_connection

router = APIRouter(prefix="/api/auth", tags=["auth"])

class LoginRequest(BaseModel):
    username: str
    pin: str

class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3)
    display_name: str = Field(..., min_length=3)
    role: str = Field(..., pattern="^(admin|cajero)$")
    pin: str = Field(..., min_length=4, max_length=6)

class ChangePinRequest(BaseModel):
    username: str
    old_pin: str
    new_pin: str = Field(..., min_length=4, max_length=6)

@router.get("/users")
def get_users():
    """Retorna los usuarios activos disponibles para iniciar turno o cambiar de perfil."""
    conn = get_db_connection()
    try:
        rows = conn.execute("""
            SELECT id, username, display_name, role, is_active, created_at
            FROM app_users
            WHERE is_active = 1
            ORDER BY CASE role WHEN 'admin' THEN 1 ELSE 2 END, display_name ASC
        """).fetchall()
        return {"success": True, "users": [dict(r) for r in rows]}
    finally:
        conn.close()

@router.post("/login")
def login(payload: LoginRequest):
    """Valida el usuario y PIN para otorgar sesión y rol."""
    conn = get_db_connection()
    try:
        user = conn.execute("""
            SELECT id, username, display_name, role, pin, is_active
            FROM app_users
            WHERE LOWER(username) = LOWER(?) AND is_active = 1
        """, (payload.username.strip(),)).fetchone()

        if not user or user["pin"] != payload.pin.strip():
            raise HTTPException(status_code=401, detail="Usuario o PIN incorrecto.")

        return {
            "success": True,
            "message": f"Bienvenido, {user['display_name']}",
            "user": {
                "id": user["id"],
                "username": user["username"],
                "display_name": user["display_name"],
                "role": user["role"]
            }
        }
    finally:
        conn.close()

@router.post("/create-user")
def create_user(payload: CreateUserRequest):
    """Crea un nuevo usuario (solo administradores)."""
    conn = get_db_connection()
    try:
        now_str = datetime.now().isoformat()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO app_users (username, display_name, role, pin, is_active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
        """, (payload.username.strip().lower(), payload.display_name.strip(), payload.role, payload.pin.strip(), now_str))
        conn.commit()
        return {"success": True, "message": f"Usuario {payload.display_name} creado con éxito."}
    except Exception as e:
        conn.rollback()
        if "UNIQUE" in str(e):
            raise HTTPException(status_code=400, detail="El nombre de usuario ya existe.")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/change-pin")
def change_pin(payload: ChangePinRequest):
    """Permite cambiar el PIN de acceso."""
    conn = get_db_connection()
    try:
        user = conn.execute("SELECT id, pin FROM app_users WHERE LOWER(username) = LOWER(?)", (payload.username.strip(),)).fetchone()
        if not user or user["pin"] != payload.old_pin.strip():
            raise HTTPException(status_code=401, detail="PIN actual incorrecto.")

        conn.execute("UPDATE app_users SET pin = ? WHERE id = ?", (payload.new_pin.strip(), user["id"]))
        conn.commit()
        return {"success": True, "message": "PIN actualizado correctamente."}
    finally:
        conn.close()
