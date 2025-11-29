<#
.SYNOPSIS
    Script de configuration initiale du projet (Windows)
    
.DESCRIPTION
    Ce script prepare l'environnement pour le projet :
    1. Construit les images Docker necessaires
    2. Cree le cluster Kind
    3. Deploie la stack monitoring
    4. Deploie le scheduler ML
#>

$ErrorActionPreference = "Stop"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  CONFIGURATION INITIALE DU PROJET" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# Verifier Docker
Write-Host "[1/5] Verification de Docker..." -ForegroundColor Yellow
try {
    docker ps | Out-Null
    Write-Host "[OK] Docker fonctionne" -ForegroundColor Green
} catch {
    Write-Host "[ERREUR] Docker n'est pas demarre ou accessible" -ForegroundColor Red
    exit 1
}

# Construire les images Docker
Write-Host "`n[2/5] Construction des images Docker..." -ForegroundColor Yellow

Write-Host "  - network-latency-exporter..." -ForegroundColor Cyan
docker build -t network-latency-exporter:latest monitoring/network-latency-exporter/
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERREUR] Erreur lors de la construction de network-latency-exporter" -ForegroundColor Red
    exit 1
}

Write-Host "  - scheduler-inference..." -ForegroundColor Cyan
docker build -t scheduler-inference:latest scheduler/inference/
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERREUR] Erreur lors de la construction de scheduler-inference" -ForegroundColor Red
    exit 1
}

Write-Host "  - scheduler-extender..." -ForegroundColor Cyan
docker build -t scheduler-extender:latest scheduler/extender/
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERREUR] Erreur lors de la construction de scheduler-extender" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Images construites" -ForegroundColor Green

# Creer le cluster et deployer
Write-Host "`n[3/5] Creation du cluster et deploiement..." -ForegroundColor Yellow
& "$PSScriptRoot\infra\bootstrap.ps1"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERREUR] Erreur lors du bootstrap" -ForegroundColor Red
    exit 1
}

# Charger les images dans Kind
Write-Host "`n[4/5] Chargement des images dans Kind..." -ForegroundColor Yellow
$CLUSTER_NAME = "scheduler5g-dev"

kind load docker-image network-latency-exporter:latest --name $CLUSTER_NAME
kind load docker-image scheduler-inference:latest --name $CLUSTER_NAME
kind load docker-image scheduler-extender:latest --name $CLUSTER_NAME

Write-Host "[OK] Images chargees dans Kind" -ForegroundColor Green

# Attendre que les pods soient prets
Write-Host "`n[5/5] Attente de la stabilisation des pods (60 secondes)..." -ForegroundColor Yellow
Start-Sleep -Seconds 60

Write-Host "`nVerification de l'etat des pods..." -ForegroundColor Cyan
kubectl get pods -n monitoring

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  [OK] CONFIGURATION TERMINEE !" -ForegroundColor Green
Write-Host "========================================`n" -ForegroundColor Green

Write-Host "Prochaines etapes :" -ForegroundColor Cyan
Write-Host "  1. Entrainer le modele ML (optionnel) :" -ForegroundColor White
Write-Host "     python scheduler/training/train_model.py --data training_data.csv --output scheduler_model.pkl" -ForegroundColor Gray
Write-Host "  2. Lancer la comparaison :" -ForegroundColor White
Write-Host "     .\run_comparison.ps1 -DurationMinutes 10" -ForegroundColor Gray

