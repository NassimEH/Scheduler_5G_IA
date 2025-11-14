FROM python:3.11-slim

WORKDIR /app

# Installer les dépendances système
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copier et installer les dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code de l'application
COPY inference_server.py model_loader.py feature_extractor.py ./

# Créer le répertoire pour les modèles
RUN mkdir -p /models

# Variables d'environnement
ENV PORT=8080
ENV HOST=0.0.0.0
ENV MODEL_PATH=/models/scheduler_model.pkl
ENV KUBERNETES_API_URL=https://kubernetes.default.svc
ENV PROMETHEUS_URL=http://prometheus.monitoring.svc.cluster.local:9090

EXPOSE 8080

# Healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/health')"

CMD ["python", "inference_server.py"]

