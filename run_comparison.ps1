<#
.SYNOPSIS
    Script PowerShell pour exécuter la comparaison complète entre kube-scheduler et scheduler ML
    
.DESCRIPTION
    Ce script automatise le workflow complet de comparaison :
    1. Vérifie que Prometheus est accessible
    2. Crée des workloads de test
    3. Collecte les métriques du scheduler par défaut
    4. Collecte les métriques du scheduler ML
    5. Génère les graphiques de comparaison
    
.PARAMETER DurationMinutes
    Durée de collecte en minutes (défaut: 10)
    Pour plus de données, augmentez cette valeur (ex: 15, 30, 60)
    
.PARAMETER Scenario
    Scénario de test à utiliser (balanced, high_latency, resource_intensive, mixed)
    
.PARAMETER PrometheusUrl
    URL de Prometheus (défaut: http://localhost:9090)
    
.EXAMPLE
    .\run_comparison.ps1 -DurationMinutes 15
    Exécute une collecte de 15 minutes pour chaque scheduler
    
.EXAMPLE
    .\run_comparison.ps1 -DurationMinutes 30 -Scenario resource_intensive
    Exécute une collecte de 30 minutes avec un scénario intensif
#>

param(
    [int]$DurationMinutes = 10,
    [string]$Scenario = "balanced",
    [string]$PrometheusUrl = "http://localhost:9090"
)

$ErrorActionPreference = "Stop"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  COMPARAISON SCHEDULERS - WORKFLOW COMPLET" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# Vérifier que Prometheus est accessible
Write-Host "[1/6] Vérification de Prometheus..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$PrometheusUrl/api/v1/query?query=up" -UseBasicParsing -TimeoutSec 3
    Write-Host "[OK] Prometheus accessible" -ForegroundColor Green
} catch {
    Write-Host "[ATTENTION] Prometheus non accessible, demarrage du port-forward..." -ForegroundColor Yellow
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "kubectl port-forward -n monitoring svc/prometheus 9090:9090" -WindowStyle Minimized
    Start-Sleep -Seconds 5
    Write-Host "[OK] Port-forward demarre" -ForegroundColor Green
}

# Créer le namespace workloads si nécessaire
Write-Host "`n[2/6] Préparation du namespace workloads..." -ForegroundColor Yellow
kubectl create namespace workloads --dry-run=client -o yaml | kubectl apply -f - | Out-Null
Write-Host "[OK] Namespace pret" -ForegroundColor Green

# Nettoyer les anciens workloads
Write-Host "`n[3/6] Nettoyage des anciens workloads..." -ForegroundColor Yellow
try {
    $null = python scheduler/testing/test_scenarios.py --cleanup --namespace workloads 2>&1 | Out-String
    Write-Host "[OK] Nettoyage termine" -ForegroundColor Green
} catch {
    Write-Host "[ATTENTION] Erreur lors du nettoyage (peut etre ignoree)" -ForegroundColor Yellow
}
Start-Sleep -Seconds 3

# ÉTAPE 1 : Collecte avec scheduler par défaut
Write-Host "`n========================================" -ForegroundColor Magenta
Write-Host "  ÉTAPE 1 : SCHEDULER PAR DÉFAUT" -ForegroundColor Magenta
Write-Host "========================================`n" -ForegroundColor Magenta

Write-Host "[4/6] Création du scénario de test ($Scenario)..." -ForegroundColor Yellow
python scheduler/testing/test_scenarios.py --scenario $Scenario --namespace workloads
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERREUR] Erreur lors de la creation du scenario" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Scenario cree" -ForegroundColor Green

Write-Host "`nAttente du déploiement des pods (30 secondes)..." -ForegroundColor Cyan
Start-Sleep -Seconds 30

Write-Host "`nCollecte des métriques du scheduler par défaut ($DurationMinutes minutes)..." -ForegroundColor Yellow
$defaultOutput = "results_default"
New-Item -ItemType Directory -Force -Path $defaultOutput | Out-Null

python scheduler/testing/compare_schedulers.py `
    --collect `
    --duration $DurationMinutes `
    --output $defaultOutput `
    --prometheus-url $PrometheusUrl

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERREUR] Erreur lors de la collecte des metriques par defaut" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Metriques collectees" -ForegroundColor Green

# Nettoyer les workloads
Write-Host "`nNettoyage des workloads..." -ForegroundColor Cyan
python scheduler/testing/test_scenarios.py --cleanup --namespace workloads 2>&1 | Out-Null
Start-Sleep -Seconds 10

# ÉTAPE 2 : Collecte avec scheduler ML
Write-Host "`n========================================" -ForegroundColor Magenta
Write-Host "  ÉTAPE 2 : SCHEDULER ML" -ForegroundColor Magenta
Write-Host "========================================`n" -ForegroundColor Magenta

Write-Host "[5/6] Vérification de l'extender ML..." -ForegroundColor Yellow
$extenderPod = kubectl get pods -n monitoring -l app=scheduler-extender -o jsonpath='{.items[0].metadata.name}' 2>$null
if ($extenderPod) {
    Write-Host "[OK] Extender ML actif: $extenderPod" -ForegroundColor Green
} else {
    Write-Host "[ATTENTION] Extender ML non trouve. Assurez-vous qu'il est deploye." -ForegroundColor Yellow
}

Write-Host "`nCréation du scénario de test ($Scenario)..." -ForegroundColor Cyan
python scheduler/testing/test_scenarios.py --scenario $Scenario --namespace workloads
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERREUR] Erreur lors de la creation du scenario" -ForegroundColor Red
    exit 1
}

Write-Host "`nAttente du déploiement des pods (30 secondes)..." -ForegroundColor Cyan
Start-Sleep -Seconds 30

Write-Host "`nCollecte des métriques du scheduler ML ($DurationMinutes minutes)..." -ForegroundColor Yellow
$mlOutput = "results_ml"
New-Item -ItemType Directory -Force -Path $mlOutput | Out-Null

python scheduler/testing/compare_schedulers.py `
    --collect `
    --duration $DurationMinutes `
    --output $mlOutput `
    --prometheus-url $PrometheusUrl

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERREUR] Erreur lors de la collecte des metriques ML" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Metriques collectees" -ForegroundColor Green

# Nettoyer les workloads
Write-Host "`nNettoyage des workloads..." -ForegroundColor Cyan
python scheduler/testing/test_scenarios.py --cleanup --namespace workloads 2>&1 | Out-Null

# ÉTAPE 3 : Comparaison
Write-Host "`n========================================" -ForegroundColor Magenta
Write-Host "  ÉTAPE 3 : COMPARAISON ET GRAPHIQUES" -ForegroundColor Magenta
Write-Host "========================================`n" -ForegroundColor Magenta

Write-Host "[6/6] Génération des graphiques de comparaison..." -ForegroundColor Yellow

# Trouver les fichiers CSV
$defaultCsv = Get-ChildItem -Path $defaultOutput -Filter "metrics_*.csv" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$mlCsv = Get-ChildItem -Path $mlOutput -Filter "metrics_*.csv" | Sort-Object LastWriteTime -Descending | Select-Object -First 1

if (-not $defaultCsv -or -not $mlCsv) {
    Write-Host "[ERREUR] Fichiers CSV non trouves" -ForegroundColor Red
    Write-Host "   Default: $($defaultCsv.FullName)" -ForegroundColor Yellow
    Write-Host "   ML: $($mlCsv.FullName)" -ForegroundColor Yellow
    exit 1
}

Write-Host "Fichiers trouvés:" -ForegroundColor Cyan
Write-Host "  Default: $($defaultCsv.Name)" -ForegroundColor White
Write-Host "  ML: $($mlCsv.Name)" -ForegroundColor White

# Générer le rapport de comparaison
$comparisonOutput = "comparison_results"
New-Item -ItemType Directory -Force -Path $comparisonOutput | Out-Null

python scheduler/testing/compare_schedulers.py `
    --default-data $defaultCsv.FullName `
    --ml-data $mlCsv.FullName `
    --output $comparisonOutput `
    --prometheus-url $PrometheusUrl

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERREUR] Erreur lors de la generation du rapport" -ForegroundColor Red
    exit 1
}

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  [OK] COMPARAISON TERMINEE !" -ForegroundColor Green
Write-Host "========================================`n" -ForegroundColor Green

Write-Host "Résultats disponibles dans : $comparisonOutput" -ForegroundColor Cyan
Write-Host "`nFichiers générés :" -ForegroundColor Yellow
Get-ChildItem -Path $comparisonOutput | ForEach-Object {
    Write-Host "  - $($_.Name)" -ForegroundColor White
}

Write-Host "`nPour visualiser les graphiques, ouvrez les fichiers PNG dans le dossier $comparisonOutput" -ForegroundColor Cyan

