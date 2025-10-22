<#
Script d'amorçage pour l'environnement de développement (PowerShell).

Ce script réalise les opérations suivantes :
- crée un cluster Kind (utilise infra/kind-config.yaml)
- configure le contexte kubectl vers le cluster créé
- déploie une stack monitoring minimale (Prometheus + Grafana)
- déploie un workload d'exemple (pods simulant UPF)

Prérequis :
- Docker en fonctionnement
- kind (https://kind.sigs.k8s.io/) installé et accessible
- kubectl installé et accessible

Usage :
    .\infra\bootstrap.ps1

Remarques :
- Les manifests monitoring fournis sont un point de départ minimal. Pour un test plus complet, utilisez
    les Helm charts officiels (prometheus-operator / kube-prometheus-stack) et déployez node-exporter, cAdvisor, kube-state-metrics.
- Le script applique des manifests locaux ; adaptez les chemins si vous déplacez le repo.
#>

param(
        [string]$ClusterName = "scheduler5g-dev",
        [string]$Kubeconfig = "$env:USERPROFILE\.kube\config"
)

Write-Host "Création du cluster kind '$ClusterName'..."
kind create cluster --name $ClusterName --config "$(Split-Path -Path $MyInvocation.MyCommand.Definition -Parent)\kind-config.yaml"

Write-Host "Contexte kubectl : kind-$ClusterName"
kubectl cluster-info --context "kind-$ClusterName"

Write-Host "Déploiement de la stack monitoring (Prometheus + Grafana)..."
# Applique les manifests minimalistes situés sous monitoring/
kubectl apply -f "$(Split-Path -Path $MyInvocation.MyCommand.Definition -Parent)\..\monitoring\prometheus\" 
kubectl apply -f "$(Split-Path -Path $MyInvocation.MyCommand.Definition -Parent)\..\monitoring\grafana\"

Write-Host "Déploiement du workload d'exemple..."
kubectl apply -f "$(Split-Path -Path $MyInvocation.MyCommand.Definition -Parent)\..\workloads\sample-workload.yaml"

Write-Host "Bootstrap terminé. Vérifiez les ressources avec 'kubectl get nodes' et 'kubectl get pods -A'"
