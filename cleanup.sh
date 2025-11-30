#!/bin/bash
#
# Script de nettoyage pour supprimer les metriques, resultats et fichiers temporaires.
#
# Usage:
#   ./cleanup.sh              # Supprime tous les fichiers temporaires et resultats
#   ./cleanup.sh --keep-models # Supprime les resultats mais conserve les modeles ML
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
            echo "[OK] $description supprime (${size_mb} MB)"
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
            echo "[OK] $description supprime (${size_kb} KB)"
            DELETED_COUNT=$((DELETED_COUNT + 1))
            TOTAL_SIZE=$((TOTAL_SIZE + size))
        else
            echo "[ERREUR] Impossible de supprimer $description"
        fi
    else
        echo "[SKIP] $description n'existe pas"
    fi
}

# Supprimer les dossiers de resultats
echo ""
echo "Suppression des dossiers de resultats..."
remove_directory "results_default" "Resultats scheduler par defaut"
remove_directory "results_ml" "Resultats scheduler ML"
remove_directory "comparison_results" "Resultats de comparaison"

# Supprimer les fichiers de donnees d'entrainement
echo ""
echo "Suppression des fichiers de donnees..."
remove_file "training_data.csv" "Donnees d'entrainement"

# Supprimer les modeles ML (optionnel)
if [ "$KEEP_MODELS" = false ]; then
    echo ""
    echo "Suppression des modeles ML..."
    if [ -d "scheduler/models" ]; then
        for model in scheduler/models/*.pkl; do
            if [ -f "$model" ]; then
                remove_file "$model" "Modele ML: $(basename "$model")"
            fi
        done
    else
        echo "[SKIP] Dossier scheduler/models n'existe pas"
    fi
else
    echo ""
    echo "[SKIP] Conservation des modeles ML (--keep-models)"
fi

# Resume
echo ""
echo "========================================"
echo "  NETTOYAGE TERMINE"
echo "========================================"
echo ""
echo "Fichiers/dossiers supprimes : $DELETED_COUNT"
TOTAL_SIZE_MB=$(echo "scale=2; $TOTAL_SIZE / 1024 / 1024" | bc 2>/dev/null || echo "0")
echo "Espace libere : ${TOTAL_SIZE_MB} MB"
echo ""

