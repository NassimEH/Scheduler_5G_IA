<#
.SYNOPSIS
    Script PowerShell pour executer la comparaison complete entre kube-scheduler et scheduler ML
    
.DESCRIPTION
    Ce script automatise le workflow complet de comparaison :
    1. Verifie que Prometheus est accessible
    2. Cree des workloads de test
    3. Collecte les metriques du scheduler par defaut
    4. Collecte les metriques du scheduler ML
    5. Genere les graphiques de comparaison
    
.PARAMETER DurationMinutes
    Duree de collecte en minutes (defaut: 10)
    Pour plus de donnees, augmentez cette valeur (ex: 15, 30, 60)
    
.PARAMETER Scenario
    Scenario de test a utiliser (balanced, high_latency, resource_intensive, mixed)
    
.PARAMETER PrometheusUrl
    URL de Prometheus (defaut: http://localhost:9090)
    
.EXAMPLE
    .\run_comparison.ps1 -DurationMinutes 15
    Execute une collecte de 15 minutes pour chaque scheduler
    
.EXAMPLE
    .\run_comparison.ps1 -DurationMinutes 30 -Scenario resource_intensive
    Execute une collecte de 30 minutes avec un scenario intensif
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

# Verifier que Prometheus est accessible
Write-Host "[1/6] Verification de Prometheus..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$PrometheusUrl/api/v1/query?query=up" -UseBasicParsing -TimeoutSec 3
    Write-Host "[OK] Prometheus accessible" -ForegroundColor Green
} catch {
    Write-Host "[ATTENTION] Prometheus non accessible, demarrage du port-forward..." -ForegroundColor Yellow
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "kubectl port-forward -n monitoring svc/prometheus 9090:9090" -WindowStyle Minimized
    Start-Sleep -Seconds 5
    Write-Host "[OK] Port-forward demarre" -ForegroundColor Green
}

# Creer le namespace workloads si necessaire
Write-Host "`n[2/6] Preparation du namespace workloads..." -ForegroundColor Yellow
kubectl create namespace workloads --dry-run=client -o yaml | kubectl apply -f - | Out-Null
Write-Host "[OK] Namespace pret" -ForegroundColor Green

# Nettoyer les anciens workloads
Write-Host "`n[3/6] Nettoyage des anciens workloads..." -ForegroundColor Yellow
try {
    $oldErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $null = python scheduler/testing/test_scenarios.py --cleanup --namespace workloads 2>&1 | Out-String
    $ErrorActionPreference = $oldErrorAction
    Write-Host "[OK] Nettoyage termine" -ForegroundColor Green
} catch {
    Write-Host "[ATTENTION] Erreur lors du nettoyage (peut etre ignoree)" -ForegroundColor Yellow
}
Start-Sleep -Seconds 3

# ETAPE 1 : Collecte avec scheduler par defaut
Write-Host "`n========================================" -ForegroundColor Magenta
Write-Host "  ETAPE 1 : SCHEDULER PAR DEFAUT" -ForegroundColor Magenta
Write-Host "========================================`n" -ForegroundColor Magenta

Write-Host "[4/6] Creation du scenario de test ($Scenario)..." -ForegroundColor Yellow
$oldErrorAction = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
$pythonOutput = python scheduler/testing/test_scenarios.py --scenario $Scenario --namespace workloads 2>&1 | Out-String
$pythonExitCode = $LASTEXITCODE
$ErrorActionPreference = $oldErrorAction
if ($pythonExitCode -ne 0) {
    Write-Host "[ERREUR] Erreur lors de la creation du scenario" -ForegroundColor Red
    Write-Host $pythonOutput -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Scenario cree" -ForegroundColor Green

Write-Host "`nAttente du deploiement des pods (30 secondes)..." -ForegroundColor Cyan
Start-Sleep -Seconds 30

Write-Host "`nCollecte des metriques du scheduler par defaut ($DurationMinutes minutes)..." -ForegroundColor Yellow
$defaultOutput = "results_default"
New-Item -ItemType Directory -Force -Path $defaultOutput | Out-Null

$oldErrorAction = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
$pythonOutput = python scheduler/testing/compare_schedulers.py `
    --collect `
    --duration $DurationMinutes `
    --output $defaultOutput `
    --prometheus-url $PrometheusUrl 2>&1 | Out-String
$pythonExitCode = $LASTEXITCODE
$ErrorActionPreference = $oldErrorAction

if ($pythonExitCode -ne 0) {
    Write-Host "[ERREUR] Erreur lors de la collecte des metriques par defaut" -ForegroundColor Red
    Write-Host $pythonOutput -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Metriques collectees" -ForegroundColor Green

# Nettoyer les workloads
Write-Host "`nNettoyage des workloads..." -ForegroundColor Cyan
$oldErrorAction = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
$null = python scheduler/testing/test_scenarios.py --cleanup --namespace workloads 2>&1 | Out-String
$ErrorActionPreference = $oldErrorAction
Start-Sleep -Seconds 10

# ETAPE 2 : Collecte avec scheduler ML
Write-Host "`n========================================" -ForegroundColor Magenta
Write-Host "  ETAPE 2 : SCHEDULER ML" -ForegroundColor Magenta
Write-Host "========================================`n" -ForegroundColor Magenta

Write-Host "[5/6] Verification de l'extender ML..." -ForegroundColor Yellow
$extenderPod = kubectl get pods -n monitoring -l app=scheduler-extender -o jsonpath='{.items[0].metadata.name}' 2>$null
if ($extenderPod) {
    Write-Host "[OK] Extender ML actif: $extenderPod" -ForegroundColor Green
} else {
    Write-Host "[ATTENTION] Extender ML non trouve. Assurez-vous qu'il est deploye." -ForegroundColor Yellow
}

Write-Host "`nCreation du scenario de test ($Scenario)..." -ForegroundColor Cyan
$oldErrorAction = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
$pythonOutput = python scheduler/testing/test_scenarios.py --scenario $Scenario --namespace workloads 2>&1 | Out-String
$pythonExitCode = $LASTEXITCODE
$ErrorActionPreference = $oldErrorAction
if ($pythonExitCode -ne 0) {
    Write-Host "[ERREUR] Erreur lors de la creation du scenario" -ForegroundColor Red
    Write-Host $pythonOutput -ForegroundColor Red
    exit 1
}

Write-Host "`nAttente du deploiement des pods (30 secondes)..." -ForegroundColor Cyan
Start-Sleep -Seconds 30

Write-Host "`nCollecte des metriques du scheduler ML ($DurationMinutes minutes)..." -ForegroundColor Yellow
$mlOutput = "results_ml"
New-Item -ItemType Directory -Force -Path $mlOutput | Out-Null

$oldErrorAction = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
$pythonOutput = python scheduler/testing/compare_schedulers.py `
    --collect `
    --duration $DurationMinutes `
    --output $mlOutput `
    --prometheus-url $PrometheusUrl 2>&1 | Out-String
$pythonExitCode = $LASTEXITCODE
$ErrorActionPreference = $oldErrorAction

if ($pythonExitCode -ne 0) {
    Write-Host "[ERREUR] Erreur lors de la collecte des metriques ML" -ForegroundColor Red
    Write-Host $pythonOutput -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Metriques collectees" -ForegroundColor Green

# Nettoyer les workloads
Write-Host "`nNettoyage des workloads..." -ForegroundColor Cyan
$oldErrorAction = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
$null = python scheduler/testing/test_scenarios.py --cleanup --namespace workloads 2>&1 | Out-String
$ErrorActionPreference = $oldErrorAction

# ETAPE 3 : Comparaison
Write-Host "`n========================================" -ForegroundColor Magenta
Write-Host "  ETAPE 3 : COMPARAISON ET GRAPHIQUES" -ForegroundColor Magenta
Write-Host "========================================`n" -ForegroundColor Magenta

Write-Host "[6/6] Generation des graphiques de comparaison..." -ForegroundColor Yellow

# Trouver les fichiers CSV
if (-not (Test-Path $defaultOutput)) {
    Write-Host "[ERREUR] Dossier $defaultOutput n'existe pas" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $mlOutput)) {
    Write-Host "[ERREUR] Dossier $mlOutput n'existe pas" -ForegroundColor Red
    exit 1
}

$defaultCsv = Get-ChildItem -Path $defaultOutput -Filter "metrics_*.csv" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$mlCsv = Get-ChildItem -Path $mlOutput -Filter "metrics_*.csv" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1

if (-not $defaultCsv -or -not $mlCsv) {
    Write-Host "[ERREUR] Fichiers CSV non trouves" -ForegroundColor Red
    Write-Host "   Default: $defaultOutput" -ForegroundColor Yellow
    Write-Host "   ML: $mlOutput" -ForegroundColor Yellow
    exit 1
}

Write-Host "Fichiers trouves:" -ForegroundColor Cyan
Write-Host "  Default: $($defaultCsv.Name)" -ForegroundColor White
Write-Host "  ML: $($mlCsv.Name)" -ForegroundColor White

# Generer le rapport de comparaison
$comparisonOutput = "comparison_results"
New-Item -ItemType Directory -Force -Path $comparisonOutput | Out-Null

$oldErrorAction = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
$pythonOutput = python scheduler/testing/compare_schedulers.py `
    --default-data $defaultCsv.FullName `
    --ml-data $mlCsv.FullName `
    --output $comparisonOutput `
    --prometheus-url $PrometheusUrl 2>&1 | Out-String
$pythonExitCode = $LASTEXITCODE
$ErrorActionPreference = $oldErrorAction

if ($pythonExitCode -ne 0) {
    Write-Host "[ERREUR] Erreur lors de la generation du rapport" -ForegroundColor Red
    Write-Host $pythonOutput -ForegroundColor Red
    exit 1
}

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  [OK] COMPARAISON TERMINEE !" -ForegroundColor Green
Write-Host "========================================`n" -ForegroundColor Green

Write-Host "Resultats disponibles dans : $comparisonOutput" -ForegroundColor Cyan
Write-Host "`nFichiers generes :" -ForegroundColor Yellow
Get-ChildItem -Path $comparisonOutput | ForEach-Object {
    Write-Host "  - $($_.Name)" -ForegroundColor White
}

Write-Host "`nPour visualiser les graphiques, ouvrez les fichiers PNG dans le dossier $comparisonOutput" -ForegroundColor Cyan

