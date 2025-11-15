# Scheduler 5G IA - Bootstrap

This repository contains an actionable roadmap and initial scaffolding to build an AI-driven Kubernetes scheduler for 5G slices.

## Structure du projet

- `infra/` : Configuration Kind et script de bootstrap pour créer un cluster local multi-nœuds
- `monitoring/` : Stack de monitoring complète (Prometheus, Grafana, exporters)
- `workloads/` : Exemples de workloads simulant des pods 5G (UPF, SMF, CU/DU)

## Phase 1 : Infrastructure et collecte de métriques ✅

### Composants déployés

1. **Prometheus** : Collecte et stocke les métriques
   - Configuration complète avec service discovery Kubernetes
   - Collecte depuis node-exporter, cAdvisor, kube-state-metrics, et l'exporter de latence réseau

2. **Exporters** :
   - **node-exporter** : Métriques système des nodes (CPU, mémoire, disque, réseau)
   - **cAdvisor** : Métriques des conteneurs (CPU, mémoire, réseau, disque par conteneur)
   - **kube-state-metrics** : Métriques sur l'état des ressources Kubernetes
   - **network-latency-exporter** : Exporter custom pour mesurer la latence réseau entre pods

3. **Grafana** : Visualisation des métriques
   - Datasource Prometheus configurée automatiquement
   - Dashboards pré-configurés :
     - Node Metrics (CPU/Memory)
     - Pod Metrics (CPU/Memory)
     - Network Latency (RTT entre pods)
     - Scheduler Comparison (comparaison kube-scheduler vs ML)

### Déploiement

#### Prérequis
- Docker en fonctionnement
- `kind` installé et accessible
- `kubectl` installé et accessible

#### Étapes

1. **Construire l'image de l'exporter de latence réseau** :
```powershell
docker build -t network-latency-exporter:latest monitoring/network-latency-exporter/
```

2. **Créer le cluster et déployer tout** :
```powershell
.\infra\bootstrap.ps1
```

3. **Charger l'image dans Kind** (si nécessaire) :
```powershell
kind load docker-image network-latency-exporter:latest --name scheduler5g-dev
```

4. **Vérifier le déploiement** :
```powershell
kubectl get pods -n monitoring
kubectl get pods -n workloads
```

5. **Accéder aux interfaces** :
```powershell
# Grafana (admin/admin)
kubectl port-forward -n monitoring svc/grafana 3000:3000
# Ouvrir http://localhost:3000

# Prometheus
kubectl port-forward -n monitoring svc/prometheus 9090:9090
# Ouvrir http://localhost:9090
```

### Métriques collectées

- **CPU** : Utilisation CPU par node et par pod
- **Mémoire** : Utilisation mémoire par node et par pod
- **Réseau** : Latence (RTT) entre pods, perte de paquets
- **Kubernetes** : État des pods, nodes, deployments, etc.

## Phase 2 : Architecture du scheduler IA ✅

### Composants créés

1. **Scheduler Extender** (`scheduler/extender/`) :
   - Service REST Flask implémentant `/filter` et `/prioritize`
   - Interface avec kube-scheduler
   - Gestion des erreurs avec fallback

2. **Serveur d'inférence** (`scheduler/inference/`) :
   - Serveur FastAPI avec endpoint `/predict`
   - Module de chargement de modèle ML (avec stub par défaut)
   - Extracteur de features depuis Kubernetes et Prometheus
   - Métriques Prometheus

3. **Configuration** :
   - Configuration du scheduler extender pour kube-scheduler
   - Scripts de déploiement et configuration

### Déploiement

Voir `scheduler/README.md` pour les instructions détaillées.

## Phase 3 : Modèle ML/RL ✅

### Composants créés

1. **Collecteur de données** (`scheduler/training/data_collector.py`) :
   - Collecte les données historiques depuis Prometheus et Kubernetes
   - Génère un dataset d'entraînement avec features et labels
   - Support pour données synthétiques si nécessaire

2. **Entraîneur de modèle** (`scheduler/training/train_model.py`) :
   - Implémentation de Random Forest et Gradient Boosting
   - Validation croisée et métriques d'évaluation
   - Sauvegarde du modèle avec scaler

3. **Mise à jour du model_loader** :
   - Support pour charger les modèles entraînés avec scaler
   - Compatibilité avec l'ancien format (stub)

### Déploiement

Voir `scheduler/training/README.md` pour les instructions détaillées.

**Workflow rapide :**
```powershell
# 1. Collecter les données
python scheduler/training/data_collector.py --prometheus-url http://localhost:9090 --output training_data.csv

# 2. Entraîner le modèle
python scheduler/training/train_model.py --data training_data.csv --output scheduler_model.pkl

# 3. Déployer le modèle dans le cluster
kubectl cp scheduler_model.pkl monitoring/<pod-name>:/models/scheduler_model.pkl
```

## Phase 4 : Tests et comparaison ✅

### Composants créés

1. **Scénarios de test** (`scheduler/testing/test_scenarios.py`) :
   - Scénarios reproductibles (balanced, high_latency, resource_intensive, mixed)
   - Création automatique de deployments avec pods 5G (UPF, SMF, CU, DU)
   - Nettoyage automatique

2. **Comparateur de schedulers** (`scheduler/testing/compare_schedulers.py`) :
   - Collecte de métriques depuis Prometheus
   - Génération de graphiques de comparaison (CPU, mémoire, latence, déséquilibre)
   - Rapport texte avec statistiques et améliorations

### Utilisation

Voir `scheduler/testing/README.md` pour les instructions détaillées.

**Workflow rapide :**
```powershell
# 1. Test avec kube-scheduler par défaut
python scheduler/testing/test_scenarios.py --scenario balanced
python scheduler/testing/compare_schedulers.py --collect --duration 30 --output results_default

# 2. Activer le scheduler ML
.\scheduler\scripts\configure-scheduler.ps1

# 3. Test avec scheduler ML
python scheduler/testing/test_scenarios.py --scenario balanced
python scheduler/testing/compare_schedulers.py --collect --duration 30 --output results_ml

# 4. Générer le rapport de comparaison
python scheduler/testing/compare_schedulers.py --default-data results_default/metrics_*.csv --ml-data results_ml/metrics_*.csv --output comparison_results
```

### Résultats attendus

- **Graphiques** : Comparaison CPU, mémoire, latence, déséquilibre
- **Rapport** : Statistiques et pourcentage d'amélioration
- **Objectifs** : Réduction de la latence (UPF proche de l'UE) et meilleur équilibre de charge

## Références

- [Kubernetes Scheduler](https://kubernetes.io/docs/concepts/scheduling-eviction/kube-scheduler/)
- X. Wang, K. Zhao, and B. Qin, "Optimization of Task-Scheduling Strategy in Edge Kubernetes Clusters Based on Deep Reinforcement Learning," Mathematics, vol. 11, no. 20, p. 4269, 2023. [Online]. Available: https://doi.org/10.3390/math11204269
- Z. Jian, X. Xie, Y. Fang, Y. Jiang, Y. Lu, A. Dash, T. Li, and G. Wang, "DRS: A deep reinforcement learning enhanced Kubernetes scheduler for microservice-based system," Software: Practice and Experience, vol. 54, no. 10, pp. 2102–2126, 2024. Available: https://doi.org/10.1002/spe.3284
