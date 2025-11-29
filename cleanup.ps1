#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Script de nettoyage pour supprimer les metriques, resultats et fichiers temporaires.

.DESCRIPTION
    Supprime les dossiers et fichiers generes lors des tests et comparaisons :
    - results_default/ : Metriques du scheduler par defaut
    - results_ml/ : Metriques du scheduler ML
    - comparison_results/ : Resultats de comparaison (graphiques et rapports)
    - img/ : Ancien dossier de resultats (si present)
    - training_data.csv : Donnees d'entrainement
    - scheduler/models/*.pkl : Modeles ML (optionnel)

.PARAMETER KeepModels
    Conserve les modeles ML entraines dans scheduler/models/

.EXAMPLE
    .\cleanup.ps1
    Supprime tous les fichiers temporaires et resultats.

.EXAMPLE
    .\cleanup.ps1 -KeepModels
    Supprime les resultats mais conserve les modeles ML.
#>

param(
    [switch]$KeepModels
)

$ErrorActionPreference = "Continue"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  NETTOYAGE DU PROJET" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

$deletedCount = 0
$totalSize = 0

# Fonction pour supprimer un dossier et compter la taille
function Remove-DirectoryWithSize {
    param(
        [string]$Path,
        [string]$Description
    )
    
    if (Test-Path $Path) {
        $size = (Get-ChildItem -Path $Path -Recurse -ErrorAction SilentlyContinue | 
                 Measure-Object -Property Length -Sum -ErrorAction SilentlyContinue).Sum
        $sizeMB = [math]::Round($size / 1MB, 2)
        
        try {
            Remove-Item -Path $Path -Recurse -Force -ErrorAction Stop
            Write-Host "[OK] $Description supprime ($sizeMB MB)" -ForegroundColor Green
            $script:deletedCount++
            $script:totalSize += $size
        } catch {
            Write-Host "[ERREUR] Impossible de supprimer $Description : $_" -ForegroundColor Red
        }
    } else {
        Write-Host "[SKIP] $Description n'existe pas" -ForegroundColor Gray
    }
}

# Fonction pour supprimer un fichier
function Remove-FileWithSize {
    param(
        [string]$Path,
        [string]$Description
    )
    
    if (Test-Path $Path) {
        $size = (Get-Item $Path).Length
        $sizeKB = [math]::Round($size / 1KB, 2)
        
        try {
            Remove-Item -Path $Path -Force -ErrorAction Stop
            Write-Host "[OK] $Description supprime ($sizeKB KB)" -ForegroundColor Green
            $script:deletedCount++
            $script:totalSize += $size
        } catch {
            Write-Host "[ERREUR] Impossible de supprimer $Description : $_" -ForegroundColor Red
        }
    } else {
        Write-Host "[SKIP] $Description n'existe pas" -ForegroundColor Gray
    }
}

# Supprimer les dossiers de resultats
Write-Host "`nSuppression des dossiers de resultats..." -ForegroundColor Yellow
Remove-DirectoryWithSize -Path "results_default" -Description "Resultats scheduler par defaut"
Remove-DirectoryWithSize -Path "results_ml" -Description "Resultats scheduler ML"
Remove-DirectoryWithSize -Path "comparison_results" -Description "Resultats de comparaison"
Remove-DirectoryWithSize -Path "img" -Description "Ancien dossier img"

# Supprimer les fichiers de donnees d'entrainement
Write-Host "`nSuppression des fichiers de donnees..." -ForegroundColor Yellow
Remove-FileWithSize -Path "training_data.csv" -Description "Donnees d'entrainement"

# Supprimer les modeles ML (optionnel)
if (-not $KeepModels) {
    Write-Host "`nSuppression des modeles ML..." -ForegroundColor Yellow
    if (Test-Path "scheduler/models") {
        $models = Get-ChildItem -Path "scheduler/models" -Filter "*.pkl" -ErrorAction SilentlyContinue
        foreach ($model in $models) {
            Remove-FileWithSize -Path $model.FullName -Description "Modele ML: $($model.Name)"
        }
    } else {
        Write-Host "[SKIP] Dossier scheduler/models n'existe pas" -ForegroundColor Gray
    }
} else {
    Write-Host "`n[SKIP] Conservation des modeles ML (--KeepModels)" -ForegroundColor Cyan
}

# Resume
Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  NETTOYAGE TERMINE" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "`nFichiers/dossiers supprimes : $deletedCount" -ForegroundColor Cyan
$totalSizeMB = [math]::Round($totalSize / 1MB, 2)
Write-Host "Espace libere : $totalSizeMB MB" -ForegroundColor Cyan
Write-Host ""

