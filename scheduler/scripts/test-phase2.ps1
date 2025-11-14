<#
Script de test pour la Phase 2 - Scheduler IA
Ce script teste le déploiement et le fonctionnement du scheduler extender et du serveur d'inférence.
#>

param(
    [string]$ClusterName = "scheduler5g-dev"
)

$ErrorActionPreference = "Stop"

Write-Host "=== Test de la Phase 2 : Scheduler IA ===" -ForegroundColor Cyan
Write-Host ""

# Vérifier que le cluster existe
Write-Host "1. Vérification du cluster Kind..." -ForegroundColor Yellow
$clusterExists = kind get clusters 2>$null | Select-String -Pattern $ClusterName
if (-not $clusterExists) {
    Write-Host "   ERREUR: Le cluster '$ClusterName' n'existe pas!" -ForegroundColor Red
    Write-Host "   Créez-le d'abord avec: .\infra\bootstrap.ps1" -ForegroundColor Yellow
    exit 1
}
Write-Host "   ✓ Cluster trouvé" -ForegroundColor Green

# Vérifier que kubectl pointe vers le bon cluster
Write-Host "2. Vérification du contexte kubectl..." -ForegroundColor Yellow
$context = kubectl config current-context
if ($context -ne "kind-$ClusterName") {
    Write-Host "   ATTENTION: Le contexte actuel est '$context', pas 'kind-$ClusterName'" -ForegroundColor Yellow
    Write-Host "   Utilisez: kubectl config use-context kind-$ClusterName" -ForegroundColor Yellow
}
Write-Host "   ✓ Contexte: $context" -ForegroundColor Green

# Vérifier que les images Docker existent
Write-Host "3. Vérification des images Docker..." -ForegroundColor Yellow
$images = @("scheduler-inference:latest", "scheduler-extender:latest")
$missingImages = @()

foreach ($image in $images) {
    $exists = docker images --format "{{.Repository}}:{{.Tag}}" | Select-String -Pattern $image
    if (-not $exists) {
        Write-Host "   ✗ Image manquante: $image" -ForegroundColor Red
        $missingImages += $image
    } else {
        Write-Host "   ✓ Image trouvée: $image" -ForegroundColor Green
    }
}

if ($missingImages.Count -gt 0) {
    Write-Host ""
    Write-Host "   Construction des images manquantes..." -ForegroundColor Yellow
    $ScriptDir = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
    $RootDir = Split-Path -Path $ScriptDir -Parent -Parent
    
    foreach ($image in $missingImages) {
        if ($image -eq "scheduler-inference:latest") {
            Write-Host "   Construction de scheduler-inference..." -ForegroundColor Yellow
            docker build -t scheduler-inference:latest "$RootDir\scheduler\inference\"
        } elseif ($image -eq "scheduler-extender:latest") {
            Write-Host "   Construction de scheduler-extender..." -ForegroundColor Yellow
            docker build -t scheduler-extender:latest "$RootDir\scheduler\extender\"
        }
    }
}

# Charger les images dans Kind
Write-Host ""
Write-Host "4. Chargement des images dans Kind..." -ForegroundColor Yellow
foreach ($image in $images) {
    Write-Host "   Chargement de $image..." -ForegroundColor Yellow
    kind load docker-image $image --name $ClusterName
    if ($LASTEXITCODE -eq 0) {
        Write-Host "   ✓ Image chargée: $image" -ForegroundColor Green
    } else {
        Write-Host "   ✗ Erreur lors du chargement de $image" -ForegroundColor Red
    }
}

# Vérifier que le namespace monitoring existe
Write-Host ""
Write-Host "5. Vérification du namespace monitoring..." -ForegroundColor Yellow
$ns = kubectl get namespace monitoring 2>$null
if (-not $ns) {
    Write-Host "   Création du namespace monitoring..." -ForegroundColor Yellow
    kubectl create namespace monitoring
}
Write-Host "   ✓ Namespace monitoring prêt" -ForegroundColor Green

# Déployer les composants
Write-Host ""
Write-Host "6. Déploiement des composants..." -ForegroundColor Yellow
$ScriptDir = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$RootDir = Split-Path -Path $ScriptDir -Parent -Parent

Write-Host "   Déploiement du serveur d'inférence..." -ForegroundColor Yellow
kubectl apply -f "$RootDir\scheduler\inference\inference-deployment.yaml"
Start-Sleep -Seconds 2

Write-Host "   Déploiement du scheduler extender..." -ForegroundColor Yellow
kubectl apply -f "$RootDir\scheduler\extender\extender-deployment.yaml"
Start-Sleep -Seconds 2

# Attendre que les pods soient prêts
Write-Host ""
Write-Host "7. Attente du démarrage des pods..." -ForegroundColor Yellow
$timeout = 120
$elapsed = 0
$interval = 5

while ($elapsed -lt $timeout) {
    $inferencePod = kubectl get pod -n monitoring -l app=scheduler-inference -o jsonpath='{.items[0].status.phase}' 2>$null
    $extenderPod = kubectl get pod -n monitoring -l app=scheduler-extender -o jsonpath='{.items[0].status.phase}' 2>$null
    
    if ($inferencePod -eq "Running" -and $extenderPod -eq "Running") {
        Write-Host "   ✓ Tous les pods sont en cours d'exécution" -ForegroundColor Green
        break
    }
    
    Write-Host "   Attente... (inference: $inferencePod, extender: $extenderPod)" -ForegroundColor Yellow
    Start-Sleep -Seconds $interval
    $elapsed += $interval
}

if ($elapsed -ge $timeout) {
    Write-Host "   ⚠ Timeout: Les pods ne sont pas tous prêts" -ForegroundColor Yellow
    Write-Host "   Vérifiez avec: kubectl get pods -n monitoring" -ForegroundColor Yellow
}

# Vérifier les pods
Write-Host ""
Write-Host "8. État des pods..." -ForegroundColor Yellow
kubectl get pods -n monitoring -l 'app in (scheduler-inference,scheduler-extender)'

# Tester les endpoints de santé
Write-Host ""
Write-Host "9. Test des endpoints de santé..." -ForegroundColor Yellow

# Port-forward pour tester
Write-Host "   Démarrage des port-forwards (en arrière-plan)..." -ForegroundColor Yellow

# Tester le serveur d'inférence
Write-Host "   Test du serveur d'inférence..." -ForegroundColor Yellow
$inferenceJob = Start-Job -ScriptBlock {
    kubectl port-forward -n monitoring svc/scheduler-inference 8081:8080 2>&1 | Out-Null
}
Start-Sleep -Seconds 3

try {
    $response = Invoke-WebRequest -Uri "http://localhost:8081/health" -TimeoutSec 5 -UseBasicParsing
    if ($response.StatusCode -eq 200) {
        Write-Host "   ✓ Serveur d'inférence: OK" -ForegroundColor Green
        $response.Content | ConvertFrom-Json | ConvertTo-Json
    }
} catch {
    Write-Host "   ✗ Serveur d'inférence: Erreur - $_" -ForegroundColor Red
} finally {
    Stop-Job $inferenceJob -ErrorAction SilentlyContinue
    Remove-Job $inferenceJob -ErrorAction SilentlyContinue
    Get-Process -Name kubectl -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*port-forward*scheduler-inference*" } | Stop-Process -Force -ErrorAction SilentlyContinue
}

# Tester le scheduler extender
Write-Host "   Test du scheduler extender..." -ForegroundColor Yellow
$extenderJob = Start-Job -ScriptBlock {
    kubectl port-forward -n monitoring svc/scheduler-extender 8082:8080 2>&1 | Out-Null
}
Start-Sleep -Seconds 3

try {
    $response = Invoke-WebRequest -Uri "http://localhost:8082/health" -TimeoutSec 5 -UseBasicParsing
    if ($response.StatusCode -eq 200) {
        Write-Host "   ✓ Scheduler extender: OK" -ForegroundColor Green
        $response.Content | ConvertFrom-Json | ConvertTo-Json
    }
} catch {
    Write-Host "   ✗ Scheduler extender: Erreur - $_" -ForegroundColor Red
} finally {
    Stop-Job $extenderJob -ErrorAction SilentlyContinue
    Remove-Job $extenderJob -ErrorAction SilentlyContinue
    Get-Process -Name kubectl -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*port-forward*scheduler-extender*" } | Stop-Process -Force -ErrorAction SilentlyContinue
}

# Vérifier les logs
Write-Host ""
Write-Host "10. Vérification des logs (dernières 10 lignes)..." -ForegroundColor Yellow
Write-Host "   Logs du serveur d'inférence:" -ForegroundColor Cyan
kubectl logs -n monitoring -l app=scheduler-inference --tail=10
Write-Host ""
Write-Host "   Logs du scheduler extender:" -ForegroundColor Cyan
kubectl logs -n monitoring -l app=scheduler-extender --tail=10

# Resume
Write-Host ""
Write-Host "=== Resume ===" -ForegroundColor Cyan
Write-Host "Pour tester manuellement:" -ForegroundColor Yellow
Write-Host '  1. Port-forward: kubectl port-forward -n monitoring svc/scheduler-inference 8080:8080' -ForegroundColor White
Write-Host '  2. Tester: curl http://localhost:8080/health' -ForegroundColor White
Write-Host ""
Write-Host "Pour configurer kube-scheduler:" -ForegroundColor Yellow
Write-Host '  .\scheduler\scripts\configure-scheduler.ps1' -ForegroundColor White
Write-Host ""
Write-Host "Pour creer un pod de test:" -ForegroundColor Yellow
Write-Host '  kubectl run test-pod --image=nginx --requests=cpu=100m,memory=128Mi' -ForegroundColor White
Write-Host '  kubectl get pod test-pod -o wide' -ForegroundColor White

