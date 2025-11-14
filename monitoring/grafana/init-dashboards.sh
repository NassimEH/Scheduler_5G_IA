#!/bin/sh
# Script init pour extraire les dashboards du ConfigMap et les placer dans le bon répertoire
mkdir -p /etc/grafana/provisioning/dashboards
for file in /dashboards-config/*.json; do
    if [ -f "$file" ]; then
        filename=$(basename "$file")
        cp "$file" "/etc/grafana/provisioning/dashboards/$filename"
    fi
done

