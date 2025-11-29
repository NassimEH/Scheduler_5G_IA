#!/bin/bash
#
# Script bash pour exécuter la comparaison complète entre kube-scheduler et scheduler ML
#
# Usage:
#   ./run_comparison.sh [--duration MINUTES] [--scenario SCENARIO]
#
# Exemples:
#   ./run_comparison.sh --duration 15
#   ./run_comparison.sh --duration 30 --scenario resource_intensive
#

set -e

# Paramètres par défaut
DURATION_MINUTES=10
SCENARIO="balanced"
PROMETHEUS_URL="http://localhost:9090"

# Parsing des arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --duration)
            DURATION_MINUTES="$2"
            shift 2
            ;;
        --scenario)
            SCENARIO="$2"
            shift 2
            ;;
        --prometheus-url)
            PROMETHEUS_URL="$2"
            shift 2
            ;;
        *)
            echo "Option inconnue: $1"
            echo "Usage: $0 [--duration MINUTES] [--scenario SCENARIO] [--prometheus-url URL]"
            exit 1
            ;;
    esac
done

echo ""
echo "========================================"
echo "  COMPARAISON SCHEDULERS - WORKFLOW COMPLET"
echo "========================================"
echo ""

# Vérifier que Prometheus est accessible
echo "[1/6] Vérification de Prometheus..."
if curl -s --max-time 3 "${PROMETHEUS_URL}/api/v1/query?query=up" > /dev/null; then
    echo "[OK] Prometheus accessible"
else
    echo "[ATTENTION] Prometheus non accessible, demarrage du port-forward..."
    kubectl port-forward -n monitoring svc/prometheus 9090:9090 &
    PORT_FORWARD_PID=$!
    sleep 5
    echo "[OK] Port-forward demarre (PID: $PORT_FORWARD_PID)"
    trap "kill $PORT_FORWARD_PID 2>/dev/null" EXIT
fi

# Créer le namespace workloads si nécessaire
echo ""
echo "[2/6] Préparation du namespace workloads..."
kubectl create namespace workloads --dry-run=client -o yaml | kubectl apply -f - > /dev/null
echo "[OK] Namespace pret"

# Nettoyer les anciens workloads
echo ""
echo "[3/6] Nettoyage des anciens workloads..."
python scheduler/testing/test_scenarios.py --cleanup --namespace workloads 2>/dev/null || true
echo "[OK] Nettoyage termine"
sleep 3

# ÉTAPE 1 : Collecte avec scheduler par défaut
echo ""
echo "========================================"
echo "  ÉTAPE 1 : SCHEDULER PAR DÉFAUT"
echo "========================================"
echo ""

echo "[4/6] Création du scénario de test ($SCENARIO)..."
python scheduler/testing/test_scenarios.py --scenario "$SCENARIO" --namespace workloads
if [ $? -ne 0 ]; then
    echo "[ERREUR] Erreur lors de la creation du scenario"
    exit 1
fi
echo "[OK] Scenario cree"

echo ""
echo "Attente du déploiement des pods (30 secondes)..."
sleep 30

echo ""
echo "Collecte des métriques du scheduler par défaut ($DURATION_MINUTES minutes)..."
mkdir -p results_default

python scheduler/testing/compare_schedulers.py \
    --collect \
    --duration "$DURATION_MINUTES" \
    --output results_default \
    --prometheus-url "$PROMETHEUS_URL"

if [ $? -ne 0 ]; then
    echo "[ERREUR] Erreur lors de la collecte des metriques par defaut"
    exit 1
fi
echo "[OK] Metriques collectees"

# Nettoyer les workloads
echo ""
echo "Nettoyage des workloads..."
python scheduler/testing/test_scenarios.py --cleanup --namespace workloads 2>/dev/null || true
sleep 10

# ÉTAPE 2 : Collecte avec scheduler ML
echo ""
echo "========================================"
echo "  ÉTAPE 2 : SCHEDULER ML"
echo "========================================"
echo ""

echo "[5/6] Vérification de l'extender ML..."
EXTENDER_POD=$(kubectl get pods -n monitoring -l app=scheduler-extender -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -n "$EXTENDER_POD" ]; then
    echo "[OK] Extender ML actif: $EXTENDER_POD"
else
    echo "[ATTENTION] Extender ML non trouve. Assurez-vous qu'il est deploye."
fi

echo ""
echo "Création du scénario de test ($SCENARIO)..."
python scheduler/testing/test_scenarios.py --scenario "$SCENARIO" --namespace workloads
if [ $? -ne 0 ]; then
    echo "[ERREUR] Erreur lors de la creation du scenario"
    exit 1
fi

echo ""
echo "Attente du déploiement des pods (30 secondes)..."
sleep 30

echo ""
echo "Collecte des métriques du scheduler ML ($DURATION_MINUTES minutes)..."
mkdir -p results_ml

python scheduler/testing/compare_schedulers.py \
    --collect \
    --duration "$DURATION_MINUTES" \
    --output results_ml \
    --prometheus-url "$PROMETHEUS_URL"

if [ $? -ne 0 ]; then
    echo "[ERREUR] Erreur lors de la collecte des metriques ML"
    exit 1
fi
echo "[OK] Metriques collectees"

# Nettoyer les workloads
echo ""
echo "Nettoyage des workloads..."
python scheduler/testing/test_scenarios.py --cleanup --namespace workloads 2>/dev/null || true

# ÉTAPE 3 : Comparaison
echo ""
echo "========================================"
echo "  ÉTAPE 3 : COMPARAISON ET GRAPHIQUES"
echo "========================================"
echo ""

echo "[6/6] Génération des graphiques de comparaison..."

# Trouver les fichiers CSV
DEFAULT_CSV=$(ls -t results_default/metrics_*.csv 2>/dev/null | head -n 1)
ML_CSV=$(ls -t results_ml/metrics_*.csv 2>/dev/null | head -n 1)

if [ -z "$DEFAULT_CSV" ] || [ -z "$ML_CSV" ]; then
    echo "[ERREUR] Fichiers CSV non trouves"
    echo "   Default: $DEFAULT_CSV"
    echo "   ML: $ML_CSV"
    exit 1
fi

echo "Fichiers trouvés:"
echo "  Default: $(basename "$DEFAULT_CSV")"
echo "  ML: $(basename "$ML_CSV")"

# Générer le rapport de comparaison
mkdir -p comparison_results

python scheduler/testing/compare_schedulers.py \
    --default-data "$DEFAULT_CSV" \
    --ml-data "$ML_CSV" \
    --output img \
    --prometheus-url "$PROMETHEUS_URL"

if [ $? -ne 0 ]; then
    echo "[ERREUR] Erreur lors de la generation du rapport"
    exit 1
fi

echo ""
echo "========================================"
echo "  [OK] COMPARAISON TERMINEE !"
echo "========================================"
echo ""

echo "Résultats disponibles dans : img"
echo ""
echo "Fichiers générés :"
ls -1 comparison_results/

echo ""
echo "Pour visualiser les graphiques, ouvrez les fichiers PNG dans le dossier comparison_results"

