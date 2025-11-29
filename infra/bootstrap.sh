#!/bin/bash
#
# Script d'amorcage pour l'environnement de developpement (Linux/Mac).
#
# Ce script realise les operations suivantes :
# - cree un cluster Kind (utilise infra/kind-config.yaml)
# - configure le contexte kubectl vers le cluster cree
# - deploie une stack monitoring complete (Prometheus + Grafana + exporters)
# - deploie le scheduler ML (inference + extender)
# - deploie un workload d'exemple
#
# Prerequis :
# - Docker en fonctionnement
# - kind (https://kind.sigs.k8s.io/) installe et accessible
# - kubectl installe et accessible
#
# Usage :
#     ./infra/bootstrap.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-scheduler5g-dev}"

echo "Creation du cluster kind '$CLUSTER_NAME'..."
kind create cluster --name "$CLUSTER_NAME" --config "$SCRIPT_DIR/kind-config.yaml"

echo "Contexte kubectl : kind-$CLUSTER_NAME"
kubectl cluster-info --context "kind-$CLUSTER_NAME"

echo "Deploiement de la stack monitoring (Prometheus + Grafana + exporters)..."

# ServiceAccount et RBAC pour Prometheus
echo "  - ServiceAccount Prometheus..."
kubectl apply -f "$ROOT_DIR/monitoring/prometheus/prometheus-serviceaccount.yaml"

# Prometheus
echo "  - Prometheus..."
kubectl apply -f "$ROOT_DIR/monitoring/prometheus/prometheus-config.yaml"
kubectl apply -f "$ROOT_DIR/monitoring/prometheus/prometheus-deployment.yaml"

# Exporters
echo "  - node-exporter..."
kubectl apply -f "$ROOT_DIR/monitoring/node-exporter/node-exporter-daemonset.yaml"

echo "  - cAdvisor..."
kubectl apply -f "$ROOT_DIR/monitoring/cadvisor/cadvisor-daemonset.yaml"

echo "  - kube-state-metrics..."
kubectl apply -f "$ROOT_DIR/monitoring/kube-state-metrics/kube-state-metrics-deployment.yaml"

# Network Latency Exporter (necessite une image buildee)
echo "  - network-latency-exporter..."
echo "    ATTENTION: L'image Docker doit etre buildee avant le deploiement"
echo "    Commande: docker build -t network-latency-exporter:latest monitoring/network-latency-exporter/"
echo "    Puis charger dans kind: kind load docker-image network-latency-exporter:latest --name $CLUSTER_NAME"
kubectl apply -f "$ROOT_DIR/monitoring/network-latency-exporter/network-latency-exporter-daemonset.yaml"

# Grafana
echo "  - Grafana..."
kubectl apply -f "$ROOT_DIR/monitoring/grafana/grafana-datasource.yaml"
kubectl apply -f "$ROOT_DIR/monitoring/grafana/grafana-dashboards-provisioning.yaml"
kubectl apply -f "$ROOT_DIR/monitoring/grafana/grafana-dashboards-configmap.yaml"
kubectl apply -f "$ROOT_DIR/monitoring/grafana/grafana-deployment.yaml"

# Scheduler IA
echo "Deploiement du scheduler IA..."
echo "  - Serveur d'inference..."
kubectl apply -f "$ROOT_DIR/scheduler/inference/inference-deployment.yaml"

echo "  - Scheduler extender..."
kubectl apply -f "$ROOT_DIR/scheduler/extender/extender-deployment.yaml"

echo "  ATTENTION: Les images Docker doivent etre buildees avant le deploiement"
echo "    - scheduler-inference: docker build -t scheduler-inference:latest scheduler/inference/"
echo "    - scheduler-extender: docker build -t scheduler-extender:latest scheduler/extender/"
echo "    Puis charger dans kind:"
echo "      kind load docker-image scheduler-inference:latest --name $CLUSTER_NAME"
echo "      kind load docker-image scheduler-extender:latest --name $CLUSTER_NAME"

echo "Deploiement du workload d'exemple..."
kubectl apply -f "$ROOT_DIR/workloads/sample-workload.yaml"

echo ""
echo "Bootstrap termine !"
echo ""
echo "Verifiez les ressources avec :"
echo "  kubectl get nodes"
echo "  kubectl get pods -n monitoring"
echo "  kubectl get pods -n workloads"
echo ""
echo "Accedez a Grafana :"
echo "  kubectl port-forward -n monitoring svc/grafana 3000:3000"
echo "  Puis ouvrez http://localhost:3000 (admin/admin)"
echo ""
echo "Accedez a Prometheus :"
echo "  kubectl port-forward -n monitoring svc/prometheus 9090:9090"
echo "  Puis ouvrez http://localhost:9090"

