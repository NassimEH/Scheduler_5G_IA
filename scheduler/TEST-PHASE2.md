# Guide de test pour la Phase 2

Ce guide vous explique comment tester le scheduler IA de la Phase 2.

## Prérequis

Assurez-vous d'avoir :
- Docker installé et en cours d'exécution
- `kind` installé et dans le PATH
- `kubectl` installé et dans le PATH
- Un cluster Kind créé (exécutez `.\infra\bootstrap.ps1` si nécessaire)

## Étapes de test

### 1. Construire les images Docker

Ouvrez un terminal PowerShell dans le répertoire du projet et exécutez :

```powershell
# Serveur d'inférence
docker build -t scheduler-inference:latest scheduler/inference/

# Scheduler extender
docker build -t scheduler-extender:latest scheduler/extender/
```

### 2. Charger les images dans Kind

```powershell
kind load docker-image scheduler-inference:latest --name scheduler5g-dev
kind load docker-image scheduler-extender:latest --name scheduler5g-dev
```

### 3. Déployer les composants

```powershell
kubectl apply -f scheduler/inference/inference-deployment.yaml
kubectl apply -f scheduler/extender/extender-deployment.yaml
```

### 4. Vérifier le déploiement

```powershell
# Vérifier que les pods sont en cours d'exécution
kubectl get pods -n monitoring -l 'app in (scheduler-inference,scheduler-extender)'

# Vérifier les services
kubectl get svc -n monitoring -l 'app in (scheduler-inference,scheduler-extender)'
```

### 5. Tester les endpoints de santé

#### Serveur d'inférence

```powershell
# Port-forward
kubectl port-forward -n monitoring svc/scheduler-inference 8080:8080

# Dans un autre terminal, tester
curl http://localhost:8080/health
# Ou avec PowerShell
Invoke-WebRequest -Uri http://localhost:8080/health
```

#### Scheduler extender

```powershell
# Port-forward
kubectl port-forward -n monitoring svc/scheduler-extender 8081:8080

# Tester
curl http://localhost:8081/health
# Ou avec PowerShell
Invoke-WebRequest -Uri http://localhost:8081/health
```

### 6. Vérifier les logs

```powershell
# Logs du serveur d'inférence
kubectl logs -n monitoring -l app=scheduler-inference --tail=50

# Logs du scheduler extender
kubectl logs -n monitoring -l app=scheduler-extender --tail=50
```

### 7. Tester une prédiction (optionnel)

```powershell
# Port-forward vers le serveur d'inférence
kubectl port-forward -n monitoring svc/scheduler-inference 8080:8080

# Dans un autre terminal, créer un fichier de test
$testRequest = @{
    pod = @{
        name = "test-pod"
        namespace = "default"
        cpu_request = 0.1
        memory_request = 128000000
        labels = @{}
        annotations = @{}
        pod_type = "UPF"
    }
    candidate_nodes = @(
        @{
            name = "scheduler5g-dev-worker"
            cpu_available = 2.0
            memory_available = 4000000000
            cpu_capacity = 4.0
            memory_capacity = 8000000000
            labels = @{}
            taints = @()
            network_latency = 5.0
        }
    )
    existing_pods = @()
} | ConvertTo-Json -Depth 10

# Envoyer la requête
Invoke-RestMethod -Uri http://localhost:8080/predict -Method POST -Body $testRequest -ContentType "application/json"
```

### 8. Configurer kube-scheduler (optionnel)

Pour que kube-scheduler utilise réellement l'extender, vous devez le configurer :

```powershell
.\scheduler\scripts\configure-scheduler.ps1
```

**Note** : Cette étape modifie le deployment de kube-scheduler dans Kind. Vous pouvez la sauter pour l'instant si vous voulez juste tester que les services fonctionnent.

### 9. Créer un pod de test

Une fois kube-scheduler configuré, créez un pod pour voir si l'extender est appelé :

```powershell
kubectl run test-pod --image=nginx --requests=cpu=100m,memory=128Mi
kubectl get pod test-pod -o wide
```

Vérifiez les logs de l'extender pour voir s'il a été appelé :

```powershell
kubectl logs -n monitoring -l app=scheduler-extender --tail=20
```

## Dépannage

### Les pods ne démarrent pas

1. Vérifiez les événements :
```powershell
kubectl describe pod -n monitoring -l app=scheduler-inference
kubectl describe pod -n monitoring -l app=scheduler-extender
```

2. Vérifiez que les images sont chargées dans Kind :
```powershell
docker exec -it scheduler5g-dev-control-plane crictl images | grep scheduler
```

### Erreur "ImagePullBackOff"

Les images doivent être chargées dans Kind. Vérifiez que vous avez bien exécuté :
```powershell
kind load docker-image scheduler-inference:latest --name scheduler5g-dev
kind load docker-image scheduler-extender:latest --name scheduler5g-dev
```

### Le serveur d'inférence ne répond pas

1. Vérifiez les logs :
```powershell
kubectl logs -n monitoring -l app=scheduler-inference
```

2. Vérifiez que le service est créé :
```powershell
kubectl get svc -n monitoring scheduler-inference
```

### L'extender n'est pas appelé par kube-scheduler

1. Vérifiez que kube-scheduler est configuré :
```powershell
kubectl get deployment kube-scheduler -n kube-system -o yaml | Select-String "extender"
```

2. Vérifiez les logs de kube-scheduler :
```powershell
kubectl logs -n kube-system deployment/kube-scheduler | Select-String "extender"
```

## Résultats attendus

- ✅ Les pods `scheduler-inference` et `scheduler-extender` sont en état `Running`
- ✅ Les endpoints `/health` retournent `200 OK`
- ✅ Les logs montrent que les services démarrent correctement
- ✅ (Si kube-scheduler est configuré) Les logs de l'extender montrent des appels de `/filter` et `/prioritize`

## Prochaines étapes

Une fois la Phase 2 testée et validée, vous pouvez passer à la Phase 3 pour entraîner un vrai modèle ML/RL.

