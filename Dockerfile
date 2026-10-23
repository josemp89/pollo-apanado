FROM python:3.12-slim

# Evitar prompts y configurar entorno
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Crear carpeta de base de datos SQL
RUN mkdir -p /app/data

# Instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código del proyecto
COPY . .

# Exponer el puerto
EXPOSE 8000

# Ejecutar con uvicorn respetando el puerto de Railway ($PORT)
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
