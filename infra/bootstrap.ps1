<#
Script d'amorcage pour l'environnement de developpement (PowerShell).

Ce script realise les operations suivantes :
- cree un cluster Kind (utilise infra/kind-config.yaml)
- configure le contexte kubectl vers le cluster cree
- deploie une stack monitoring complete (Prometheus + Grafana + exporters)
- deploie un workload d'exemple (pods simulant UPF)

Prerequis :
- Docker en fonctionnement
- kind (https://kind.sigs.k8s.io/) installe et accessible
- kubectl installe et accessible

Usage :
    .\infra\bootstrap.ps1

Remarques :
- Les manifests monitoring sont maintenant complets avec node-exporter, cAdvisor, kube-state-metrics
- L'exporter de latence reseau necessite une image Docker buildee localement (voir README)
#>

param(
        [string]$ClusterName = "scheduler5g-dev",
        [string]$Kubeconfig = "$env:USERPROFILE\.kube\config"
)

$ScriptDir = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$RootDir = Split-Path -Path $ScriptDir -Parent

Write-Host "Creation du cluster kind '$ClusterName'..."
kind create cluster --name $ClusterName --config "$ScriptDir\kind-config.yaml"

Write-Host "Contexte kubectl : kind-$ClusterName"
kubectl cluster-info --context "kind-$ClusterName"

Write-Host "Deploiement de la stack monitoring (Prometheus + Grafana + exporters)..."

# ServiceAccount et RBAC pour Prometheus
Write-Host "  - ServiceAccount Prometheus..."
kubectl apply -f "$RootDir\monitoring\prometheus\prometheus-serviceaccount.yaml"

# Prometheus
Write-Host "  - Prometheus..."
kubectl apply -f "$RootDir\monitoring\prometheus\prometheus-config.yaml"
kubectl apply -f "$RootDir\monitoring\prometheus\prometheus-deployment.yaml"

# Exporters
Write-Host "  - node-exporter..."
kubectl apply -f "$RootDir\monitoring\node-exporter\node-exporter-daemonset.yaml"

Write-Host "  - cAdvisor..."
kubectl apply -f "$RootDir\monitoring\cadvisor\cadvisor-daemonset.yaml"

Write-Host "  - kube-state-metrics..."
kubectl apply -f "$RootDir\monitoring\kube-state-metrics\kube-state-metrics-deployment.yaml"

# Network Latency Exporter (necessite une image buildee - voir README)
Write-Host "  - network-latency-exporter..."
Write-Host "    ATTENTION: L'image Docker doit etre buildee avant le deploiement"
Write-Host "    Commande: docker build -t network-latency-exporter:latest monitoring/network-latency-exporter/"
Write-Host "    Puis charger dans kind: kind load docker-image network-latency-exporter:latest --name $ClusterName"
kubectl apply -f "$RootDir\monitoring\network-latency-exporter\network-latency-exporter-daemonset.yaml"

# Grafana
Write-Host "  - Grafana..."
kubectl apply -f "$RootDir\monitoring\grafana\grafana-datasource.yaml"
kubectl apply -f "$RootDir\monitoring\grafana\grafana-dashboards-provisioning.yaml"
kubectl apply -f "$RootDir\monitoring\grafana\grafana-dashboards-configmap.yaml"
kubectl apply -f "$RootDir\monitoring\grafana\grafana-deployment.yaml"

# Scheduler IA (Phase 2)
Write-Host "Deploiement du scheduler IA..."
Write-Host "  - Serveur d'inference..."
kubectl apply -f "$RootDir\scheduler\inference\inference-deployment.yaml"

Write-Host "  - Scheduler extender..."
kubectl apply -f "$RootDir\scheduler\extender\extender-deployment.yaml"

Write-Host "  ATTENTION: Les images Docker doivent etre buildees avant le deploiement"
Write-Host "    - scheduler-inference: docker build -t scheduler-inference:latest scheduler/inference/"
Write-Host "    - scheduler-extender: docker build -t scheduler-extender:latest scheduler/extender/"
Write-Host "    Puis charger dans kind:"
Write-Host "      kind load docker-image scheduler-inference:latest --name $ClusterName"
Write-Host "      kind load docker-image scheduler-extender:latest --name $ClusterName"

Write-Host "Deploiement du workload d'exemple..."
kubectl apply -f "$RootDir\workloads\sample-workload.yaml"

Write-Host ""
Write-Host "Bootstrap termine !"
Write-Host ""
Write-Host "Verifiez les ressources avec :"
Write-Host "  kubectl get nodes"
Write-Host "  kubectl get pods -n monitoring"
Write-Host "  kubectl get pods -n workloads"
Write-Host ""
Write-Host "Accedez a Grafana :"
Write-Host "  kubectl port-forward -n monitoring svc/grafana 3000:3000"
Write-Host "  Puis ouvrez http://localhost:3000 (admin/admin)"
Write-Host ""
Write-Host "Accedez a Prometheus :"
Write-Host "  kubectl port-forward -n monitoring svc/prometheus 9090:9090"
Write-Host "  Puis ouvrez http://localhost:9090"
