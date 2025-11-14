# Scheduler IA - Architecture

Ce répertoire contient l'implémentation du scheduler IA pour Kubernetes 5G.

## Architecture

```
kube-scheduler (par défaut)
    │
    ├─► Scheduler Extender (REST API)
    │       │
    │       └─► Inference Server (FastAPI)
    │               │
    │               └─► Modèle ML/RL
    │
    └─► Fallback vers logique par défaut si l'extender échoue
```

## Composants

### 1. Scheduler Extender (`extender/`)

Service REST qui implémente les endpoints `/filter` et `/prioritize` requis par kube-scheduler.

**Fonctionnalités** :
- Filtre les nodes candidats (vérifie les ressources, taints, etc.)
- Priorise les nodes en appelant le serveur d'inférence
- Gère les erreurs avec fallback vers kube-scheduler par défaut

**Endpoints** :
- `POST /filter` : Filtre les nodes candidats
- `POST /prioritize` : Priorise les nodes en utilisant l'IA
- `POST /bind` : Binding optionnel (non utilisé par défaut)
- `GET /health` : Vérification de santé

### 2. Inference Server (`inference/`)

Serveur FastAPI qui expose le modèle ML/RL pour prédire le meilleur placement.

**Fonctionnalités** :
- Charge le modèle ML/RL (ou utilise un stub par défaut)
- Extrait les features depuis Kubernetes et Prometheus
- Prédit les scores de priorité pour chaque node candidat
- Expose des métriques Prometheus

**Endpoints** :
- `POST /predict` : Prédit le meilleur placement pour un pod
- `GET /health` : Vérification de santé
- `GET /metrics` : Métriques Prometheus

**Modules** :
- `inference_server.py` : Serveur FastAPI principal
- `model_loader.py` : Chargeur de modèle ML (avec stub par défaut)
- `feature_extractor.py` : Extraction de features depuis K8s/Prometheus

### 3. Configuration (`config/`)

- `scheduler-policy.yaml` : Configuration pour kube-scheduler

## Déploiement

### Prérequis

1. **Construire les images Docker** :
```powershell
# Serveur d'inférence
docker build -t scheduler-inference:latest scheduler/inference/

# Scheduler extender
docker build -t scheduler-extender:latest scheduler/extender/
```

2. **Charger les images dans Kind** :
```powershell
kind load docker-image scheduler-inference:latest --name scheduler5g-dev
kind load docker-image scheduler-extender:latest --name scheduler5g-dev
```

3. **Déployer les composants** :
```powershell
kubectl apply -f scheduler/inference/inference-deployment.yaml
kubectl apply -f scheduler/extender/extender-deployment.yaml
```

### Configuration de kube-scheduler

Pour que kube-scheduler utilise l'extender, il faut modifier la configuration du scheduler.

**Option 1 : Modifier le kube-scheduler dans Kind** (recommandé pour le développement)

1. Créer un ConfigMap avec la configuration :
```powershell
kubectl create configmap scheduler-config -n kube-system --from-file=scheduler/config/scheduler-policy.yaml
```

2. Modifier le deployment de kube-scheduler pour utiliser cette config :
```powershell
kubectl edit deployment kube-scheduler -n kube-system
```

Ajouter dans les args :
```yaml
args:
  - --config=/etc/kubernetes/scheduler-config.yaml
  # ... autres args
volumeMounts:
  - name: scheduler-config
    mountPath: /etc/kubernetes
volumes:
  - name: scheduler-config
    configMap:
      name: scheduler-config
```

**Option 2 : Utiliser un scheduler personnalisé** (pour production)

Créer un deployment de kube-scheduler personnalisé avec la configuration.

## Utilisation

Une fois déployé, le scheduler extender sera automatiquement appelé par kube-scheduler pour chaque pod à placer.

### Vérifier le fonctionnement

1. **Vérifier que les services sont prêts** :
```powershell
kubectl get pods -n monitoring | grep scheduler
kubectl logs -n monitoring deployment/scheduler-extender
kubectl logs -n monitoring deployment/scheduler-inference
```

2. **Tester l'extender directement** :
```powershell
# Port-forward
kubectl port-forward -n monitoring svc/scheduler-extender 8080:8080

# Tester l'endpoint de santé
curl http://localhost:8080/health
```

3. **Créer un pod de test** :
```powershell
kubectl run test-pod --image=nginx --requests=cpu=100m,memory=128Mi
kubectl get pod test-pod -o wide  # Voir sur quel node il est placé
```

### Logs et débogage

Les logs des composants montrent :
- Les appels de filtrage et priorisation
- Les prédictions du modèle
- Les erreurs et fallbacks

```powershell
# Logs de l'extender
kubectl logs -n monitoring deployment/scheduler-extender -f

# Logs du serveur d'inférence
kubectl logs -n monitoring deployment/scheduler-inference -f
```

## Modèle ML

Actuellement, le système utilise un **modèle stub** qui implémente une heuristique simple :
- Priorise les nodes avec plus de ressources disponibles
- Prend en compte la latence réseau si disponible
- Équilibre la charge entre les nodes

Pour utiliser un vrai modèle ML/RL :
1. Entraîner le modèle (Phase 3)
2. Sauvegarder le modèle dans `/models/scheduler_model.pkl`
3. Le modèle sera automatiquement chargé au démarrage

## Métriques

Le serveur d'inférence expose des métriques Prometheus :
- `inference_predictions_total` : Nombre de prédictions
- `inference_prediction_duration_seconds` : Durée des prédictions

Accessibles via :
```powershell
kubectl port-forward -n monitoring svc/scheduler-inference 8080:8080
curl http://localhost:8080/metrics
```

## Prochaines étapes

- **Phase 3** : Entraîner un modèle ML/RL réel
- **Phase 4** : Tests et comparaison avec kube-scheduler par défaut

