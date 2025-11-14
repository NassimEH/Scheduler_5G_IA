# Script de test simplifie pour la Phase 2

param(
    [string]$ClusterName = "scheduler5g-dev"
)

$ScriptDir = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$RootDir = Split-Path -Path $ScriptDir -Parent -Parent

Write-Host "=== Test Phase 2 ===" -ForegroundColor Cyan

# 1. Construire les images
Write-Host "1. Construction des images Docker..." -ForegroundColor Yellow
docker build -t scheduler-inference:latest "$RootDir\scheduler\inference\"
docker build -t scheduler-extender:latest "$RootDir\scheduler\extender\"

# 2. Charger dans Kind
Write-Host "2. Chargement dans Kind..." -ForegroundColor Yellow
kind load docker-image scheduler-inference:latest --name $ClusterName
kind load docker-image scheduler-extender:latest --name $ClusterName

# 3. Deployer
Write-Host "3. Deploiement..." -ForegroundColor Yellow
kubectl apply -f "$RootDir\scheduler\inference\inference-deployment.yaml"
kubectl apply -f "$RootDir\scheduler\extender\extender-deployment.yaml"

# 4. Attendre
Write-Host "4. Attente du demarrage..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

# 5. Verifier
Write-Host "5. Verification des pods..." -ForegroundColor Yellow
kubectl get pods -n monitoring -l 'app in (scheduler-inference,scheduler-extender)'

Write-Host ""
Write-Host "Test termine!" -ForegroundColor Green
Write-Host "Pour voir les logs: kubectl logs -n monitoring -l app=scheduler-inference" -ForegroundColor White

