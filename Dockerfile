FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py iot_routes.py iot_commands.py machines_config.py devices_store.py firmware_manifest.py energy_daily.py ./

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]