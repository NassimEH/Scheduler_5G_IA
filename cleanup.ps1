#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Script de nettoyage pour supprimer les métriques, résultats et fichiers temporaires.

.DESCRIPTION
    Supprime les dossiers et fichiers générés lors des tests et comparaisons :
    - results_default/ : Métriques du scheduler par défaut
    - results_ml/ : Métriques du scheduler ML
    - comparison_results/ : Résultats de comparaison (graphiques et rapports)
    - img/ : Ancien dossier de résultats (si présent)
    - training_data.csv : Données d'entraînement
    - scheduler/models/*.pkl : Modèles ML (optionnel)

.PARAMETER KeepModels
    Conserve les modèles ML entraînés dans scheduler/models/

.EXAMPLE
    .\cleanup.ps1
    Supprime tous les fichiers temporaires et résultats.

.EXAMPLE
    .\cleanup.ps1 -KeepModels
    Supprime les résultats mais conserve les modèles ML.
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
            Write-Host "[OK] $Description supprimé ($sizeMB MB)" -ForegroundColor Green
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
            Write-Host "[OK] $Description supprimé ($sizeKB KB)" -ForegroundColor Green
            $script:deletedCount++
            $script:totalSize += $size
        } catch {
            Write-Host "[ERREUR] Impossible de supprimer $Description : $_" -ForegroundColor Red
        }
    } else {
        Write-Host "[SKIP] $Description n'existe pas" -ForegroundColor Gray
    }
}

# Supprimer les dossiers de résultats
Write-Host "`nSuppression des dossiers de résultats..." -ForegroundColor Yellow
Remove-DirectoryWithSize -Path "results_default" -Description "Résultats scheduler par défaut"
Remove-DirectoryWithSize -Path "results_ml" -Description "Résultats scheduler ML"
Remove-DirectoryWithSize -Path "comparison_results" -Description "Résultats de comparaison"
Remove-DirectoryWithSize -Path "img" -Description "Ancien dossier img"

# Supprimer les fichiers de données d'entraînement
Write-Host "`nSuppression des fichiers de données..." -ForegroundColor Yellow
Remove-FileWithSize -Path "training_data.csv" -Description "Données d'entraînement"

# Supprimer les modèles ML (optionnel)
if (-not $KeepModels) {
    Write-Host "`nSuppression des modèles ML..." -ForegroundColor Yellow
    if (Test-Path "scheduler/models") {
        $models = Get-ChildItem -Path "scheduler/models" -Filter "*.pkl" -ErrorAction SilentlyContinue
        foreach ($model in $models) {
            Remove-FileWithSize -Path $model.FullName -Description "Modèle ML: $($model.Name)"
        }
    } else {
        Write-Host "[SKIP] Dossier scheduler/models n'existe pas" -ForegroundColor Gray
    }
} else {
    Write-Host "`n[SKIP] Conservation des modèles ML (--KeepModels)" -ForegroundColor Cyan
}

# Résumé
Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  NETTOYAGE TERMINÉ" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "`nFichiers/dossiers supprimés : $deletedCount" -ForegroundColor Cyan
$totalSizeMB = [math]::Round($totalSize / 1MB, 2)
Write-Host "Espace libéré : $totalSizeMB MB" -ForegroundColor Cyan
Write-Host ""

