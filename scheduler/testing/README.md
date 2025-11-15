# Phase 4 : Tests et comparaison

Ce répertoire contient les scripts pour tester et comparer le scheduler ML avec le kube-scheduler par défaut.

## Objectifs

- Comparer les performances entre kube-scheduler et scheduler ML
- Générer des graphiques de comparaison (CPU, mémoire, latence)
- Mesurer l'amélioration du déséquilibre de charge
- Valider que le scheduler ML réduit la latence (UPF proche de l'UE)

## Scripts

### 1. `test_scenarios.py`

Crée des scénarios de test reproductibles avec différents workloads 5G.

**Utilisation :**
```powershell
# Créer un scénario équilibré
python scheduler/testing/test_scenarios.py --scenario balanced

# Créer un scénario avec focus sur la latence
python scheduler/testing/test_scenarios.py --scenario high_latency

# Nettoyer les deployments de test
python scheduler/testing/test_scenarios.py --cleanup
```

**Scénarios disponibles :**
- `balanced` : Mix équilibré de pods UPF, SMF, CU, DU
- `high_latency` : Beaucoup de pods UPF pour tester l'optimisation de latence
- `resource_intensive` : Pods gourmands en ressources
- `mixed` : Mix avec différentes tailles de pods

### 2. `compare_schedulers.py`

Compare les métriques entre kube-scheduler et scheduler ML, et génère des graphiques.

**Utilisation :**

#### Étape 1 : Collecter les métriques avec kube-scheduler par défaut

```powershell
# Désactiver le scheduler ML (retirer la config de l'extender)
# Puis collecter les métriques
python scheduler/testing/compare_schedulers.py --collect --duration 30 --output results_default
```

#### Étape 2 : Collecter les métriques avec le scheduler ML

```powershell
# Activer le scheduler ML
.\scheduler\scripts\configure-scheduler.ps1

# Collecter les métriques
python scheduler/testing/compare_schedulers.py --collect --duration 30 --output results_ml
```

#### Étape 3 : Générer le rapport de comparaison

```powershell
python scheduler/testing/compare_schedulers.py `
    --default-data results_default/metrics_*.csv `
    --ml-data results_ml/metrics_*.csv `
    --output comparison_results
```

## Workflow complet de test

### 1. Préparation

```powershell
# S'assurer que le cluster est prêt
kubectl get nodes

# Vérifier que Prometheus est accessible
kubectl port-forward -n monitoring svc/prometheus 9090:9090
```

### 2. Test avec kube-scheduler par défaut

```powershell
# S'assurer que le scheduler ML est désactivé
# (ne pas exécuter configure-scheduler.ps1 ou le désactiver)

# Créer un scénario de test
python scheduler/testing/test_scenarios.py --scenario balanced

# Attendre que les pods soient déployés
kubectl get pods -n workloads -w

# Collecter les métriques pendant 30 minutes
python scheduler/testing/compare_schedulers.py --collect --duration 30 --output results_default

# Nettoyer
python scheduler/testing/test_scenarios.py --cleanup
```

### 3. Test avec scheduler ML

```powershell
# Activer le scheduler ML
.\scheduler\scripts\configure-scheduler.ps1

# Vérifier que l'extender fonctionne
kubectl logs -n monitoring deployment/scheduler-extender

# Créer le même scénario de test
python scheduler/testing/test_scenarios.py --scenario balanced

# Attendre que les pods soient déployés
kubectl get pods -n workloads -w

# Collecter les métriques pendant 30 minutes
python scheduler/testing/compare_schedulers.py --collect --duration 30 --output results_ml

# Nettoyer
python scheduler/testing/test_scenarios.py --cleanup
```

### 4. Génération du rapport

```powershell
python scheduler/testing/compare_schedulers.py `
    --default-data results_default/metrics_*.csv `
    --ml-data results_ml/metrics_*.csv `
    --output comparison_results
```

## Résultats attendus

Le script génère :

1. **Graphiques** :
   - `cpu_comparison.png` : Comparaison de l'utilisation CPU
   - `memory_comparison.png` : Comparaison de l'utilisation mémoire
   - `latency_comparison.png` : Comparaison de la latence réseau
   - `imbalance_comparison.png` : Comparaison du déséquilibre de charge

2. **Rapport texte** :
   - `comparison_report.txt` : Statistiques et améliorations

## Métriques comparées

- **Utilisation CPU moyenne** : Doit être similaire ou meilleure
- **Utilisation mémoire moyenne** : Doit être similaire ou meilleure
- **Latence réseau moyenne** : Doit être réduite (objectif : UPF proche de l'UE)
- **Déséquilibre CPU** : Doit être réduit (meilleur équilibre entre nodes)
- **Déséquilibre mémoire** : Doit être réduit (meilleur équilibre entre nodes)

## Interprétation des résultats

### Amélioration du déséquilibre
- **Réduction > 10%** : Excellent résultat
- **Réduction 5-10%** : Bon résultat
- **Réduction < 5%** : Résultat modeste, peut nécessiter un réentraînement

### Réduction de la latence
- **Réduction > 15%** : Excellent pour les pods UPF
- **Réduction 5-15%** : Bon résultat
- **Réduction < 5%** : Peut nécessiter plus de données d'entraînement

## Notes

- Les tests doivent être exécutés dans les mêmes conditions (même cluster, même charge)
- Il est recommandé d'exécuter plusieurs fois et de faire la moyenne
- Les scénarios peuvent être adaptés selon les besoins spécifiques


