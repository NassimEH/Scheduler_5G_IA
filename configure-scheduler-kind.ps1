# Script pour configurer kube-scheduler dans Kind avec l'extender
$NodeName = "scheduler5g-dev-control-plane"
$ManifestPath = "/etc/kubernetes/manifests/kube-scheduler.yaml"
$ConfigPath = "/etc/kubernetes/scheduler-config.yaml"

Write-Host "Configuration de kube-scheduler pour utiliser l'extender dans Kind..." -ForegroundColor Green

# 1. Créer le ConfigMap (déjà fait, mais on vérifie)
Write-Host "`n1. Vérification du ConfigMap..." -ForegroundColor Yellow
kubectl get configmap scheduler-config -n kube-system
if ($LASTEXITCODE -ne 0) {
    Write-Host "Création du ConfigMap..." -ForegroundColor Yellow
    kubectl create configmap scheduler-config -n kube-system --from-file=scheduler/config/scheduler-policy.yaml
}

# 2. Copier le fichier de config dans le node
Write-Host "`n2. Copie du fichier de configuration dans le node..." -ForegroundColor Yellow
docker cp scheduler/config/scheduler-policy.yaml ${NodeName}:${ConfigPath}

# 3. Modifier le manifest pour ajouter --config et le volume
Write-Host "`n3. Modification du manifest kube-scheduler..." -ForegroundColor Yellow
Write-Host "ATTENTION: Cette opération va redémarrer kube-scheduler" -ForegroundColor Red

# Sauvegarder le manifest actuel
docker exec ${NodeName} cp ${ManifestPath} ${ManifestPath}.backup

# Créer un script Python pour modifier le YAML
$pythonScript = @"
import yaml
import sys

with open('$ManifestPath', 'r') as f:
    manifest = yaml.safe_load(f)

# Ajouter l'argument --config
container = manifest['spec']['containers'][0]
if '--config=/etc/kubernetes/scheduler-config.yaml' not in container['command']:
    container['command'].append('--config=/etc/kubernetes/scheduler-config.yaml')

# Ajouter le volume mount
if 'volumeMounts' not in container:
    container['volumeMounts'] = []
    
# Vérifier si le mount existe déjà
mount_exists = any(m['name'] == 'scheduler-config' for m in container['volumeMounts'])
if not mount_exists:
    container['volumeMounts'].append({
        'name': 'scheduler-config',
        'mountPath': '/etc/kubernetes',
        'readOnly': True
    })

# Ajouter le volume
if 'volumes' not in manifest['spec']:
    manifest['spec']['volumes'] = []
    
# Vérifier si le volume existe déjà
vol_exists = any(v['name'] == 'scheduler-config' for v in manifest['spec']['volumes'])
if not vol_exists:
    manifest['spec']['volumes'].append({
        'name': 'scheduler-config',
        'hostPath': {
            'path': '/etc/kubernetes',
            'type': 'DirectoryOrCreate'
        }
    })

with open('$ManifestPath', 'w') as f:
    yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)
"@

# Exécuter le script Python dans le container
docker exec ${NodeName} sh -c "echo '$pythonScript' > /tmp/modify_scheduler.py && python3 /tmp/modify_scheduler.py"

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✓ Configuration appliquée avec succès!" -ForegroundColor Green
    Write-Host "`nLe pod kube-scheduler va redémarrer automatiquement..." -ForegroundColor Yellow
    Write-Host "`nVérifiez dans quelques secondes:" -ForegroundColor Cyan
    Write-Host "  kubectl get pods -n kube-system | Select-String scheduler" -ForegroundColor White
    Write-Host "  kubectl logs -n kube-system kube-scheduler-${NodeName} | Select-String extender" -ForegroundColor White
} else {
    Write-Host "`n✗ Erreur lors de la modification. Restauration du backup..." -ForegroundColor Red
    docker exec ${NodeName} cp ${ManifestPath}.backup ${ManifestPath}
}


