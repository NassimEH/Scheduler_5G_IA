<#
.SYNOPSIS
    Script de configuration initiale du projet (Windows)
    
.DESCRIPTION
    Ce script prépare l'environnement pour le projet :
    1. Construit les images Docker nécessaires
    2. Crée le cluster Kind
    3. Déploie la stack monitoring
    4. Déploie le scheduler ML
#>

$ErrorActionPreference = "Stop"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  CONFIGURATION INITIALE DU PROJET" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# Vérifier Docker
Write-Host "[1/5] Vérification de Docker..." -ForegroundColor Yellow
try {
    docker ps | Out-Null
    Write-Host "✅ Docker fonctionne" -ForegroundColor Green
} catch {
    Write-Host "❌ Docker n'est pas démarré ou accessible" -ForegroundColor Red
    exit 1
}

# Construire les images Docker
Write-Host "`n[2/5] Construction des images Docker..." -ForegroundColor Yellow

Write-Host "  - network-latency-exporter..." -ForegroundColor Cyan
docker build -t network-latency-exporter:latest monitoring/network-latency-exporter/
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Erreur lors de la construction de network-latency-exporter" -ForegroundColor Red
    exit 1
}

Write-Host "  - scheduler-inference..." -ForegroundColor Cyan
docker build -t scheduler-inference:latest scheduler/inference/
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Erreur lors de la construction de scheduler-inference" -ForegroundColor Red
    exit 1
}

Write-Host "  - scheduler-extender..." -ForegroundColor Cyan
docker build -t scheduler-extender:latest scheduler/extender/
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Erreur lors de la construction de scheduler-extender" -ForegroundColor Red
    exit 1
}

Write-Host "✅ Images construites" -ForegroundColor Green

# Créer le cluster et déployer
Write-Host "`n[3/5] Création du cluster et déploiement..." -ForegroundColor Yellow
& "$PSScriptRoot\infra\bootstrap.ps1"
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Erreur lors du bootstrap" -ForegroundColor Red
    exit 1
}

# Charger les images dans Kind
Write-Host "`n[4/5] Chargement des images dans Kind..." -ForegroundColor Yellow
$CLUSTER_NAME = "scheduler5g-dev"

kind load docker-image network-latency-exporter:latest --name $CLUSTER_NAME
kind load docker-image scheduler-inference:latest --name $CLUSTER_NAME
kind load docker-image scheduler-extender:latest --name $CLUSTER_NAME

Write-Host "✅ Images chargées dans Kind" -ForegroundColor Green

# Attendre que les pods soient prêts
Write-Host "`n[5/5] Attente de la stabilisation des pods (60 secondes)..." -ForegroundColor Yellow
Start-Sleep -Seconds 60

Write-Host "`nVérification de l'état des pods..." -ForegroundColor Cyan
kubectl get pods -n monitoring

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  ✅ CONFIGURATION TERMINÉE !" -ForegroundColor Green
Write-Host "========================================`n" -ForegroundColor Green

Write-Host "Prochaines étapes :" -ForegroundColor Cyan
Write-Host "  1. Entraîner le modèle ML (optionnel) :" -ForegroundColor White
Write-Host "     python scheduler/training/train_model.py --data training_data.csv --output scheduler_model.pkl" -ForegroundColor Gray
Write-Host "  2. Lancer la comparaison :" -ForegroundColor White
Write-Host "     .\run_comparison.ps1 -DurationMinutes 10" -ForegroundColor Gray

