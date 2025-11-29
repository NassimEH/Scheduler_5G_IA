#!/bin/bash
#
# Script de configuration initiale du projet (Linux/Mac)
#
# Ce script prepare l'environnement pour le projet :
# 1. Construit les images Docker necessaires
# 2. Cree le cluster Kind
# 3. Deploie la stack monitoring
# 4. Deploie le scheduler ML
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-scheduler5g-dev}"

echo ""
echo "========================================"
echo "  CONFIGURATION INITIALE DU PROJET"
echo "========================================"
echo ""

# Verifier Docker
echo "[1/5] Verification de Docker..."
if ! docker ps > /dev/null 2>&1; then
    echo "[ERREUR] Docker n'est pas demarre ou accessible"
    exit 1
fi
echo "[OK] Docker fonctionne"

# Construire les images Docker
echo ""
echo "[2/5] Construction des images Docker..."

echo "  - network-latency-exporter..."
docker build -t network-latency-exporter:latest monitoring/network-latency-exporter/
if [ $? -ne 0 ]; then
    echo "[ERREUR] Erreur lors de la construction de network-latency-exporter"
    exit 1
fi

echo "  - scheduler-inference..."
docker build -t scheduler-inference:latest scheduler/inference/
if [ $? -ne 0 ]; then
    echo "[ERREUR] Erreur lors de la construction de scheduler-inference"
    exit 1
fi

echo "  - scheduler-extender..."
docker build -t scheduler-extender:latest scheduler/extender/
if [ $? -ne 0 ]; then
    echo "[ERREUR] Erreur lors de la construction de scheduler-extender"
    exit 1
fi

echo "[OK] Images construites"

# Creer le cluster et deployer
echo ""
echo "[3/5] Creation du cluster et deploiement..."
"$SCRIPT_DIR/infra/bootstrap.sh"
if [ $? -ne 0 ]; then
    echo "[ERREUR] Erreur lors du bootstrap"
    exit 1
fi

# Charger les images dans Kind
echo ""
echo "[4/5] Chargement des images dans Kind..."
kind load docker-image network-latency-exporter:latest --name "$CLUSTER_NAME"
kind load docker-image scheduler-inference:latest --name "$CLUSTER_NAME"
kind load docker-image scheduler-extender:latest --name "$CLUSTER_NAME"

echo "[OK] Images chargees dans Kind"

# Attendre que les pods soient prets
echo ""
echo "[5/5] Attente de la stabilisation des pods (60 secondes)..."
sleep 60

echo ""
echo "Verification de l'etat des pods..."
kubectl get pods -n monitoring

echo ""
echo "========================================"
echo "  [OK] CONFIGURATION TERMINEE !"
echo "========================================"
echo ""

echo "Prochaines etapes :"
echo "  1. Entrainer le modele ML (optionnel) :"
echo "     python scheduler/training/train_model.py --data training_data.csv --output scheduler_model.pkl"
echo "  2. Lancer la comparaison :"
echo "     ./run_comparison.sh --duration 10"

