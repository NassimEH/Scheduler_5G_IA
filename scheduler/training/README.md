# Phase 3 : Entraînement du modèle ML/RL

Ce répertoire contient les scripts pour entraîner un modèle de machine learning qui prédit le meilleur placement de pods dans le cluster Kubernetes 5G.

## Architecture

Le modèle ML apprend à prédire un score de qualité de placement (0-1) basé sur :
- **Features des nodes** : CPU/mémoire disponibles, charge, latence réseau, densité de pods
- **Features des pods** : Ressources demandées, type de pod (UPF, SMF, CU, DU)

## Scripts

### 1. `data_collector.py`

Collecte les données historiques depuis Prometheus et Kubernetes pour créer un dataset d'entraînement.

**Utilisation :**
```powershell
python scheduler/training/data_collector.py --prometheus-url http://localhost:9090 --output training_data.csv --days 7
```

**Options :**
- `--prometheus-url` : URL de Prometheus (défaut : depuis variable d'environnement)
- `--output` : Fichier CSV de sortie (défaut : `training_data.csv`)
- `--days` : Nombre de jours de données à collecter (défaut : 7)

### 2. `train_model.py`

Entraîne un modèle ML (Random Forest ou Gradient Boosting) sur les données collectées.

**Utilisation :**
```powershell
python scheduler/training/train_model.py --data training_data.csv --output scheduler_model.pkl --model-type random_forest
```

**Options :**
- `--data` : Fichier CSV avec les données d'entraînement (défaut : `training_data.csv`)
- `--output` : Fichier de sortie pour le modèle (défaut : `scheduler_model.pkl`)
- `--model-type` : Type de modèle (`random_forest` ou `gradient_boosting`, défaut : `random_forest`)
- `--test-size` : Proportion des données de test (défaut : 0.2)

## Workflow complet

### Étape 1 : Collecte de données

```powershell
# Depuis le cluster (port-forward Prometheus si nécessaire)
kubectl port-forward -n monitoring svc/prometheus 9090:9090

# Dans un autre terminal
python scheduler/training/data_collector.py --prometheus-url http://localhost:9090 --output training_data.csv --days 7
```

### Étape 2 : Entraînement du modèle

```powershell
python scheduler/training/train_model.py --data training_data.csv --output scheduler_model.pkl
```

### Étape 3 : Déployer le modèle

Une fois le modèle entraîné, il faut le déployer dans le cluster :

```powershell
# Créer un ConfigMap avec le modèle
kubectl create configmap scheduler-model -n monitoring --from-file=scheduler_model.pkl=scheduler_model.pkl

# Modifier le deployment pour monter le ConfigMap
# (ou utiliser un volume persistant)
```

**Alternative :** Copier le modèle dans le pod

```powershell
# Trouver le pod
kubectl get pods -n monitoring -l app=scheduler-inference

# Copier le modèle
kubectl cp scheduler_model.pkl monitoring/<pod-name>:/models/scheduler_model.pkl
```

## Modèles disponibles

### Random Forest (par défaut)
- **Avantages** : Rapide, robuste, gère bien les features non linéaires
- **Utilisation** : Bon pour commencer, résultats interprétables

### Gradient Boosting
- **Avantages** : Meilleure précision potentielle, meilleur pour les patterns complexes
- **Utilisation** : Si Random Forest ne donne pas assez de précision

## Features utilisées

Le modèle utilise les features suivantes :

1. `cpu_available_ratio` : Ratio de CPU disponible sur le node
2. `memory_available_ratio` : Ratio de mémoire disponible sur le node
3. `cpu_load_avg` : Charge CPU moyenne
4. `memory_load_avg` : Charge mémoire moyenne
5. `network_latency_normalized` : Latence réseau normalisée
6. `pod_density` : Densité de pods sur le node
7. `pod_cpu_request` : CPU demandé par le pod
8. `pod_memory_request` : Mémoire demandée par le pod
9. `pod_type_score` : Score encodé du type de pod (UPF, SMF, CU, DU)

## Métriques d'évaluation

Le script d'entraînement affiche :
- **MSE** (Mean Squared Error) : Erreur quadratique moyenne
- **R²** (Coefficient of determination) : Qualité de l'ajustement (plus proche de 1 = mieux)
- **MAE** (Mean Absolute Error) : Erreur absolue moyenne
- **CV R²** : R² avec validation croisée (5 folds)

## Améliorations futures

- **Reinforcement Learning** : Implémenter un algorithme RL (DQN, PPO) pour l'apprentissage en ligne
- **Features supplémentaires** : Ajouter plus de features (topologie réseau, affinités, etc.)
- **Hyperparameter tuning** : Optimisation automatique des hyperparamètres
- **Online learning** : Mise à jour du modèle en temps réel


