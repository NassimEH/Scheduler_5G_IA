#!/usr/bin/env python3
"""
Scheduler Extender REST API pour Kubernetes.
Implémente les endpoints /filter et /prioritize requis par kube-scheduler.
"""
import os
import logging
import json
from typing import List, Dict, Any, Optional
from flask import Flask, request, jsonify
import requests
from kubernetes import client, config
from kubernetes.client.rest import ApiException

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# URL du serveur d'inférence
INFERENCE_SERVER_URL = os.getenv(
    'INFERENCE_SERVER_URL',
    'http://scheduler-inference.monitoring.svc.cluster.local:8080'
)

# URL de Prometheus
PROMETHEUS_URL = os.getenv(
    'PROMETHEUS_URL',
    'http://prometheus.monitoring.svc.cluster.local:9090'
)


class ExtenderServer:
    """Serveur extender pour le scheduler Kubernetes"""
    
    def __init__(self, inference_url: str, prometheus_url: Optional[str] = None):
        self.inference_url = inference_url
        self.prometheus_url = prometheus_url or PROMETHEUS_URL
        self.k8s_client = None
        self._init_k8s_client()
    
    def _init_k8s_client(self):
        """Initialise le client Kubernetes"""
        try:
            config.load_incluster_config()
            logger.info("Configuration Kubernetes chargée depuis le cluster")
        except:
            try:
                config.load_kube_config()
                logger.info("Configuration Kubernetes chargée depuis kubeconfig")
            except Exception as e:
                logger.warning(f"Impossible de charger la config Kubernetes: {e}")
        
        try:
            self.k8s_client = client.CoreV1Api()
        except Exception as e:
            logger.warning(f"Impossible d'initialiser le client Kubernetes: {e}")
    
    def filter_nodes(
        self,
        pod: Dict[str, Any],
        nodes: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Filtre les nodes candidats.
        Retourne les nodes qui passent les critères de filtrage.
        
        Args:
            pod: Informations sur le pod à placer
            nodes: Liste des nodes candidats
        
        Returns:
            Réponse avec les nodes filtrés
        """
        logger.info(f"Filtrage des nodes pour le pod {pod.get('metadata', {}).get('name')}")
        
        # Pour l'instant, on ne filtre pas (tous les nodes passent)
        # On pourrait ajouter des filtres basés sur:
        # - Taints et tolerations
        # - Node selectors
        # - Affinity rules
        # - Ressources disponibles
        
        filtered_nodes = []
        failed_nodes = []
        
        for node in nodes:
            # Vérifier les ressources minimales
            if self._has_sufficient_resources(node, pod):
                filtered_nodes.append(node)
            else:
                failed_nodes.append({
                    'name': node.get('metadata', {}).get('name'),
                    'reason': 'InsufficientResources'
                })
        
        logger.info(f"Nodes filtrés: {len(filtered_nodes)}/{len(nodes)}")
        
        return {
            'nodes': {
                'items': filtered_nodes
            },
            'failedNodes': failed_nodes,
            'error': None
        }
    
    def prioritize_nodes(
        self,
        pod: Dict[str, Any],
        nodes: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Priorise les nodes candidats en utilisant le serveur d'inférence.
        
        Args:
            pod: Informations sur le pod à placer
            nodes: Liste des nodes candidats (déjà filtrés)
        
        Returns:
            Réponse avec les scores de priorité pour chaque node
        """
        logger.info(f"Priorisation des nodes pour le pod {pod.get('metadata', {}).get('name')}")
        
        try:
            # Préparer la requête pour le serveur d'inférence
            prediction_request = self._prepare_prediction_request(pod, nodes)
            
            # Appeler le serveur d'inférence
            response = requests.post(
                f"{self.inference_url}/predict",
                json=prediction_request,
                timeout=5
            )
            response.raise_for_status()
            
            prediction = response.json()
            
            # Convertir les scores en format attendu par Kubernetes
            host_priorities = []
            for node in nodes:
                node_name = node.get('metadata', {}).get('name')
                score = int(prediction['node_scores'].get(node_name, 0) * 10)  # Scale 0-10
                
                host_priorities.append({
                    'host': node_name,
                    'score': score
                })
            
            logger.info(f"Priorisation terminée pour {len(host_priorities)} nodes")
            
            return {
                'hostPriorities': host_priorities,
                'error': None
            }
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur lors de l'appel au serveur d'inférence: {e}")
            # Fallback : priorité uniforme
            return self._default_prioritization(nodes)
        except Exception as e:
            logger.error(f"Erreur lors de la priorisation: {e}", exc_info=True)
            return self._default_prioritization(nodes)
    
    def _prepare_prediction_request(
        self,
        pod: Dict[str, Any],
        nodes: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Prépare la requête pour le serveur d'inférence"""
        pod_metadata = pod.get('metadata', {})
        pod_spec = pod.get('spec', {})
        
        # Extraire les ressources demandées
        containers = pod_spec.get('containers', [])
        cpu_request = 0.0
        memory_request = 0.0
        
        for container in containers:
            resources = container.get('resources', {}).get('requests', {})
            if 'cpu' in resources:
                cpu_str = resources['cpu']
                # Convertir "100m" en 0.1, "1" en 1.0, etc.
                if cpu_str.endswith('m'):
                    cpu_request += float(cpu_str[:-1]) / 1000.0
                else:
                    cpu_request += float(cpu_str)
            
            if 'memory' in resources:
                memory_str = resources['memory']
                # Convertir "128Mi" en bytes, etc.
                memory_request += self._parse_memory(memory_str)
        
        # Extraire les informations des nodes
        candidate_nodes = []
        for node in nodes:
            node_metadata = node.get('metadata', {})
            node_status = node.get('status', {})
            
            # Extraire les capacités et allocations
            capacity = node_status.get('capacity', {})
            allocatable = node_status.get('allocatable', {})
            
            cpu_capacity = self._parse_cpu(capacity.get('cpu', '0'))
            memory_capacity = self._parse_memory(capacity.get('memory', '0'))
            cpu_available = self._parse_cpu(allocatable.get('cpu', '0'))
            memory_available = self._parse_memory(allocatable.get('memory', '0'))
            
            # Récupérer la latence réseau depuis Prometheus
            network_latency = self._get_network_latency(node_metadata.get('name'))
            
            node_spec = node.get('spec', {})
            candidate_nodes.append({
                'name': node_metadata.get('name'),
                'cpu_available': cpu_available,
                'memory_available': memory_available,
                'cpu_capacity': cpu_capacity,
                'memory_capacity': memory_capacity,
                'labels': node_metadata.get('labels', {}),
                'taints': node_spec.get('taints', []),
                'network_latency': network_latency
            })
        
        # Récupérer les pods existants depuis l'API Kubernetes
        existing_pods = self._get_existing_pods(pod_metadata.get('namespace'))
        
        return {
            'pod': {
                'name': pod_metadata.get('name'),
                'namespace': pod_metadata.get('namespace'),
                'cpu_request': cpu_request,
                'memory_request': memory_request,
                'labels': pod_metadata.get('labels', {}),
                'annotations': pod_metadata.get('annotations', {}),
                'pod_type': pod_metadata.get('labels', {}).get('pod_type')
            },
            'candidate_nodes': candidate_nodes,
            'existing_pods': existing_pods
        }
    
    def _has_sufficient_resources(
        self,
        node: Dict[str, Any],
        pod: Dict[str, Any]
    ) -> bool:
        """Vérifie si un node a suffisamment de ressources pour le pod"""
        node_status = node.get('status', {})
        allocatable = node_status.get('allocatable', {})
        
        pod_spec = pod.get('spec', {})
        containers = pod_spec.get('containers', [])
        
        total_cpu_request = 0.0
        total_memory_request = 0.0
        
        for container in containers:
            resources = container.get('resources', {}).get('requests', {})
            if 'cpu' in resources:
                total_cpu_request += self._parse_cpu(resources['cpu'])
            if 'memory' in resources:
                total_memory_request += self._parse_memory(resources['memory'])
        
        cpu_available = self._parse_cpu(allocatable.get('cpu', '0'))
        memory_available = self._parse_memory(allocatable.get('memory', '0'))
        
        return (cpu_available >= total_cpu_request and
                memory_available >= total_memory_request)
    
    def _parse_cpu(self, cpu_str: str) -> float:
        """Parse une chaîne CPU (ex: "100m", "1", "2.5") en float"""
        if not cpu_str:
            return 0.0
        if cpu_str.endswith('m'):
            return float(cpu_str[:-1]) / 1000.0
        return float(cpu_str)
    
    def _parse_memory(self, memory_str: str) -> float:
        """Parse une chaîne mémoire (ex: "128Mi", "1Gi") en bytes"""
        if not memory_str:
            return 0.0
        
        # Extraire le nombre et l'unité
        import re
        match = re.match(r'(\d+)([KMGT]?i?)?', memory_str)
        if not match:
            return 0.0
        
        value = float(match.group(1))
        unit = match.group(2) or ''
        
        multipliers = {
            'Ki': 1024,
            'Mi': 1024 ** 2,
            'Gi': 1024 ** 3,
            'Ti': 1024 ** 4,
            'K': 1000,
            'M': 1000 ** 2,
            'G': 1000 ** 3,
            'T': 1000 ** 4
        }
        
        return value * multipliers.get(unit, 1)
    
    def _get_network_latency(self, node_name: str) -> Optional[float]:
        """Récupère la latence réseau moyenne pour un node depuis Prometheus"""
        try:
            # Requête PromQL pour obtenir la latence moyenne
            query = f'avg(network_latency_rtt_seconds{{target_node="{node_name}"}})'
            url = f"{self.prometheus_url}/api/v1/query"
            params = {'query': query}
            
            response = requests.get(url, params=params, timeout=2)
            response.raise_for_status()
            
            data = response.json()
            if data['status'] == 'success' and data['data']['result']:
                value = data['data']['result'][0]['value'][1]
                latency_seconds = float(value)
                # Convertir en millisecondes
                return latency_seconds * 1000.0
            
            return None
        except Exception as e:
            logger.debug(f"Erreur lors de la récupération de la latence réseau: {e}")
            return None
    
    def _get_existing_pods(self, namespace: Optional[str] = None) -> List[Dict[str, Any]]:
        """Récupère les pods existants depuis l'API Kubernetes"""
        if not self.k8s_client:
            return []
        
        try:
            if namespace:
                pods = self.k8s_client.list_namespaced_pod(namespace)
            else:
                pods = self.k8s_client.list_pod_for_all_namespaces()
            
            existing_pods = []
            for pod in pods.items:
                # Extraire les informations pertinentes
                pod_info = {
                    'name': pod.metadata.name,
                    'namespace': pod.metadata.namespace,
                    'node': pod.spec.node_name,
                    'type': pod.metadata.labels.get('pod_type'),
                    'cpu_request': 0.0,
                    'memory_request': 0.0
                }
                
                # Calculer les ressources demandées
                for container in pod.spec.containers:
                    resources = container.resources.requests or {}
                    if 'cpu' in resources:
                        pod_info['cpu_request'] += self._parse_cpu(resources['cpu'])
                    if 'memory' in resources:
                        pod_info['memory_request'] += self._parse_memory(resources['memory'])
                
                existing_pods.append(pod_info)
            
            return existing_pods
        except Exception as e:
            logger.debug(f"Erreur lors de la récupération des pods existants: {e}")
            return []
    
    def _default_prioritization(self, nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Priorisation par défaut (uniforme) en cas d'erreur"""
        host_priorities = [
            {
                'host': node.get('metadata', {}).get('name'),
                'score': 5  # Score moyen
            }
            for node in nodes
        ]
        
        return {
            'hostPriorities': host_priorities,
            'error': None
        }


# Initialiser le serveur extender
extender = ExtenderServer(INFERENCE_SERVER_URL, PROMETHEUS_URL)


@app.route('/filter', methods=['POST'])
def filter():
    """Endpoint de filtrage des nodes"""
    try:
        data = request.get_json()
        pod = data.get('pod', {})
        nodes = data.get('nodes', {}).get('items', [])
        
        result = extender.filter_nodes(pod, nodes)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Erreur dans /filter: {e}", exc_info=True)
        return jsonify({
            'nodes': {'items': []},
            'failedNodes': [],
            'error': str(e)
        }), 500


@app.route('/prioritize', methods=['POST'])
def prioritize():
    """Endpoint de priorisation des nodes"""
    try:
        data = request.get_json()
        pod = data.get('pod', {})
        nodes = data.get('nodes', {}).get('items', [])
        
        result = extender.prioritize_nodes(pod, nodes)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Erreur dans /prioritize: {e}", exc_info=True)
        return jsonify({
            'hostPriorities': [],
            'error': str(e)
        }), 500


@app.route('/bind', methods=['POST'])
def bind():
    """
    Endpoint optionnel pour le binding.
    Par défaut, Kubernetes gère le binding, mais on peut l'intercepter ici.
    """
    try:
        data = request.get_json()
        logger.info(f"Binding request: {data}")
        return jsonify({'error': None})
    except Exception as e:
        logger.error(f"Erreur dans /bind: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    """Endpoint de santé"""
    try:
        # Vérifier que le serveur d'inférence est accessible
        response = requests.get(f"{INFERENCE_SERVER_URL}/health", timeout=2)
        inference_healthy = response.status_code == 200
    except:
        inference_healthy = False
    
    return jsonify({
        'status': 'healthy',
        'inference_server_available': inference_healthy
    })


@app.route('/', methods=['GET'])
def root():
    """Endpoint racine"""
    return jsonify({
        'service': 'Kubernetes Scheduler Extender',
        'version': '1.0.0',
        'endpoints': {
            'filter': '/filter',
            'prioritize': '/prioritize',
            'bind': '/bind',
            'health': '/health'
        }
    })


if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    host = os.getenv('HOST', '0.0.0.0')
    
    logger.info(f"Démarrage du scheduler extender sur {host}:{port}")
    logger.info(f"URL du serveur d'inférence: {INFERENCE_SERVER_URL}")
    
    app.run(host=host, port=port, debug=False)

