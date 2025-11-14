FROM python:3.11-slim

WORKDIR /app

# Installer les dépendances système nécessaires pour ping
RUN apt-get update && apt-get install -y \
    iputils-ping \
    curl \
    kubectl \
    && rm -rf /var/lib/apt/lists/*

# Installer les dépendances Python
RUN pip install --no-cache-dir prometheus-client

# Copier le script
COPY network-latency-exporter.py /app/

# Rendre le script exécutable
RUN chmod +x /app/network-latency-exporter.py

EXPOSE 8080

CMD ["python3", "/app/network-latency-exporter.py"]

