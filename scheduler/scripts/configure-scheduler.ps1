<#
Script pour configurer kube-scheduler dans Kind pour utiliser l'extender.
Ce script modifie le deployment de kube-scheduler pour inclure la configuration de l'extender.
#>

param(
    [string]$ClusterName = "scheduler5g-dev"
)

$ScriptDir = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$RootDir = Split-Path -Path $ScriptDir -Parent -Parent

Write-Host "Configuration de kube-scheduler pour utiliser l'extender..."

# Créer le ConfigMap avec la configuration
Write-Host "Création du ConfigMap scheduler-config..."
kubectl create configmap scheduler-config -n kube-system `
    --from-file="$RootDir\scheduler\config\scheduler-policy.yaml" `
    --dry-run=client -o yaml | kubectl apply -f -

# Sauvegarder le deployment actuel
Write-Host "Sauvegarde du deployment kube-scheduler actuel..."
kubectl get deployment kube-scheduler -n kube-system -o yaml > "$env:TEMP\kube-scheduler-backup.yaml"
Write-Host "Backup sauvegardé dans $env:TEMP\kube-scheduler-backup.yaml"

# Modifier le deployment
Write-Host "Modification du deployment kube-scheduler..."
$deployment = kubectl get deployment kube-scheduler -n kube-system -o json | ConvertFrom-Json

# Ajouter l'argument --config
$configArg = "--config=/etc/kubernetes/scheduler-config.yaml"
if ($deployment.spec.template.spec.containers[0].args -notcontains $configArg) {
    $deployment.spec.template.spec.containers[0].args += $configArg
}

# Ajouter le volume mount
$volumeMount = @{
    name = "scheduler-config"
    mountPath = "/etc/kubernetes"
    readOnly = $true
}

$container = $deployment.spec.template.spec.containers[0]
if (-not $container.volumeMounts) {
    $container.volumeMounts = @()
}

$existingMount = $container.volumeMounts | Where-Object { $_.name -eq "scheduler-config" }
if (-not $existingMount) {
    $container.volumeMounts += $volumeMount
}

# Ajouter le volume
$volume = @{
    name = "scheduler-config"
    configMap = @{
        name = "scheduler-config"
    }
}

if (-not $deployment.spec.template.spec.volumes) {
    $deployment.spec.template.spec.volumes = @()
}

$existingVolume = $deployment.spec.template.spec.volumes | Where-Object { $_.name -eq "scheduler-config" }
if (-not $existingVolume) {
    $deployment.spec.template.spec.volumes += $volume
}

# Appliquer les modifications
$deployment | ConvertTo-Json -Depth 10 | kubectl apply -f -

Write-Host ""
Write-Host "Configuration terminée !"
Write-Host ""
Write-Host "Vérifiez que kube-scheduler redémarre :"
Write-Host "  kubectl get pods -n kube-system | grep scheduler"
Write-Host ""
Write-Host "Vérifiez les logs pour voir si l'extender est utilisé :"
Write-Host "  kubectl logs -n kube-system deployment/kube-scheduler"
Write-Host ""
Write-Host "Pour restaurer la configuration par défaut :"
Write-Host "  kubectl apply -f $env:TEMP\kube-scheduler-backup.yaml"

