FROM python:3.11-slim

WORKDIR /app

# Copier et installer les dépendances
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code
COPY extender_server.py ./

# Variables d'environnement
ENV PORT=8080
ENV HOST=0.0.0.0
ENV INFERENCE_SERVER_URL=http://scheduler-inference.monitoring.svc.cluster.local:8080

EXPOSE 8080

# Healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/health')"

# Utiliser gunicorn pour la production
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8080", "extender_server:app"]

