#!/bin/bash
#
# Script de nettoyage pour supprimer les métriques, résultats et fichiers temporaires.
#
# Usage:
#   ./cleanup.sh              # Supprime tous les fichiers temporaires et résultats
#   ./cleanup.sh --keep-models # Supprime les résultats mais conserve les modèles ML
#

set -e

KEEP_MODELS=false

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --keep-models) KEEP_MODELS=true ;;
        *) echo "Unknown parameter: $1"; exit 1 ;;
    esac
    shift
done

echo ""
echo "========================================"
echo "  NETTOYAGE DU PROJET"
echo "========================================"
echo ""

DELETED_COUNT=0
TOTAL_SIZE=0

# Fonction pour supprimer un dossier et compter la taille
remove_directory() {
    local path="$1"
    local description="$2"
    
    if [ -d "$path" ]; then
        local size=$(du -sb "$path" 2>/dev/null | cut -f1)
        local size_mb=$(echo "scale=2; $size / 1024 / 1024" | bc 2>/dev/null || echo "0")
        
        if rm -rf "$path" 2>/dev/null; then
            echo "[OK] $description supprimé (${size_mb} MB)"
            DELETED_COUNT=$((DELETED_COUNT + 1))
            TOTAL_SIZE=$((TOTAL_SIZE + size))
        else
            echo "[ERREUR] Impossible de supprimer $description"
        fi
    else
        echo "[SKIP] $description n'existe pas"
    fi
}

# Fonction pour supprimer un fichier
remove_file() {
    local path="$1"
    local description="$2"
    
    if [ -f "$path" ]; then
        local size=$(stat -f%z "$path" 2>/dev/null || stat -c%s "$path" 2>/dev/null || echo "0")
        local size_kb=$(echo "scale=2; $size / 1024" | bc 2>/dev/null || echo "0")
        
        if rm -f "$path" 2>/dev/null; then
            echo "[OK] $description supprimé (${size_kb} KB)"
            DELETED_COUNT=$((DELETED_COUNT + 1))
            TOTAL_SIZE=$((TOTAL_SIZE + size))
        else
            echo "[ERREUR] Impossible de supprimer $description"
        fi
    else
        echo "[SKIP] $description n'existe pas"
    fi
}

# Supprimer les dossiers de résultats
echo ""
echo "Suppression des dossiers de résultats..."
remove_directory "results_default" "Résultats scheduler par défaut"
remove_directory "results_ml" "Résultats scheduler ML"
remove_directory "comparison_results" "Résultats de comparaison"
remove_directory "img" "Ancien dossier img"

# Supprimer les fichiers de données d'entraînement
echo ""
echo "Suppression des fichiers de données..."
remove_file "training_data.csv" "Données d'entraînement"

# Supprimer les modèles ML (optionnel)
if [ "$KEEP_MODELS" = false ]; then
    echo ""
    echo "Suppression des modèles ML..."
    if [ -d "scheduler/models" ]; then
        for model in scheduler/models/*.pkl; do
            if [ -f "$model" ]; then
                remove_file "$model" "Modèle ML: $(basename "$model")"
            fi
        done
    else
        echo "[SKIP] Dossier scheduler/models n'existe pas"
    fi
else
    echo ""
    echo "[SKIP] Conservation des modèles ML (--keep-models)"
fi

# Résumé
echo ""
echo "========================================"
echo "  NETTOYAGE TERMINÉ"
echo "========================================"
echo ""
echo "Fichiers/dossiers supprimés : $DELETED_COUNT"
TOTAL_SIZE_MB=$(echo "scale=2; $TOTAL_SIZE / 1024 / 1024" | bc 2>/dev/null || echo "0")
echo "Espace libéré : ${TOTAL_SIZE_MB} MB"
echo ""

