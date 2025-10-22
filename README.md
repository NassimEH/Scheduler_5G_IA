# Scheduler 5G IA - Bootstrap

This repository contains an actionable roadmap and initial scaffolding to build an AI-driven Kubernetes scheduler for 5G slices.

Files added in this step:

- `infra/kind-config.yaml` - kind cluster with 1 control-plane and 3 workers.
- `infra/bootstrap.ps1` - PowerShell bootstrap script to create the cluster and deploy monitoring + sample workload.
- `monitoring/prometheus/` - minimal Prometheus manifests (deployment + configmap + service).
- `monitoring/grafana/` - minimal Grafana deployment + service.
- `workloads/sample-workload.yaml` - sample workload simulating UPF pods with a probe sidecar.

Next suggested actions:

1. Run the bootstrap script from PowerShell (requires `kind`, `kubectl` on PATH):

   .\infra\bootstrap.ps1

2. Inspect pods/services: `kubectl get pods -n monitoring`, `kubectl get pods -n workloads`.
3. Replace minimal manifests with production-ready Helm charts (Prometheus Operator / Grafana) as needed.

---

Explications (FR) & prochaines activités :

- `infra/` : contient la configuration Kind et le script de bootstrap. Utilisez-le pour créer un cluster local multi-nœuds pour vos expérimentations.
- `monitoring/` : manifests minimalistes pour Prometheus et Grafana. Ils servent de point de départ; vous devrez configurer les scrape targets (node-exporter, cAdvisor, kube-state-metrics) et provisionner des dashboards.
- `workloads/` : exemples de workload (pods UPF simulated) avec un sidecar probe. Remplacez le probe par un exporter Prometheus pour mesurer `pod_network_rtt_ms`.

Prochaines activités (todo list actuelle) :

1. Scaffold de l'inference server (FastAPI + Dockerfile)
2. Scaffold du scheduler extender (Python REST) ou plugin scheduler (Go)
3. Scripts de préparation des données et entraînement (notebook + scripts)
4. Construire une image de workload custom (probe + exporter) et CI pour la builder
5. Créer `experiments/` avec scénarios YAML reproductibles

Si tu veux que je commence par un des éléments ci-dessus, dis lequel (par exemple: `inference_server`). Je peux générer les fichiers et les tests associés.
