#!/usr/bin/env python3
"""
Module pour extraire les features depuis Kubernetes et Prometheus.
Utilisé pour préparer les données d'entrée du modèle ML.
"""
import os
import logging
from typing import List, Dict, Optional, Any
import numpy as np
import requests
from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)


class FeatureExtractor:
    """Extracteur de features depuis Kubernetes et Prometheus"""
    
    def __init__(self, k8s_api_url: str, prometheus_url: str):
        """
        Args:
            k8s_api_url: URL de l'API Kubernetes
            prometheus_url: URL de Prometheus
        """
        self.k8s_api_url = k8s_api_url
        self.prometheus_url = prometheus_url
        self.k8s_client = None
        self._init_k8s_client()
    
    def _init_k8s_client(self):
        """Initialise le client Kubernetes"""
        try:
            # Essayer de charger depuis le cluster (service account)
            config.load_incluster_config()
            logger.info("Configuration Kubernetes chargée depuis le cluster")
        except:
            try:
                # Fallback : configuration locale (kubeconfig)
                config.load_kube_config()
                logger.info("Configuration Kubernetes chargée depuis kubeconfig")
            except Exception as e:
                logger.warning(f"Impossible de charger la config Kubernetes: {e}")
                logger.warning("Les features Kubernetes ne seront pas disponibles")
        
        try:
            self.k8s_client = client.CoreV1Api()
        except Exception as e:
            logger.warning(f"Impossible d'initialiser le client Kubernetes: {e}")
    
    def extract_node_features(
        self,
        node: Any,  # NodeInfo
        pod: Any,   # PodInfo
        existing_pods: Optional[List[Dict[str, Any]]] = None,
        all_nodes: Optional[List[Any]] = None  # Nouveau : tous les nodes pour calculer l'équilibre
    ) -> List[float]:
        """
        Extrait les features pour un node donné.
        
        Args:
            node: Informations sur le node
            pod: Informations sur le pod à placer
            existing_pods: Liste des pods existants pour contexte
            all_nodes: Liste de tous les nodes pour calculer l'équilibre global
        
        Returns:
            Liste de features numériques
        """
        features = []
        
        # 1. Ratio de ressources disponibles
        cpu_ratio = node.cpu_available / node.cpu_capacity if node.cpu_capacity > 0 else 0.0
        memory_ratio = node.memory_available / node.memory_capacity if node.memory_capacity > 0 else 0.0
        
        features.append(cpu_ratio)
        features.append(memory_ratio)
        
        # 2. Latence réseau normalisée (si disponible)
        if node.network_latency is not None:
            # Normaliser entre 0 et 1 (assume max 100ms)
            latency_normalized = min(1.0, node.network_latency / 100.0)
        else:
            latency_normalized = 0.5  # Valeur par défaut si non disponible
        
        features.append(latency_normalized)
        
        # 3. Charge CPU moyenne (depuis Prometheus si disponible)
        cpu_load = self._get_node_cpu_load(node.name)
        features.append(cpu_load)
        
        # 4. Charge mémoire moyenne
        memory_load = self._get_node_memory_load(node.name)
        features.append(memory_load)
        
        # 5. Densité de pods sur le node
        pod_density = self._get_node_pod_density(node.name)
        features.append(pod_density)
        
        # 6. Score d'équilibre global : MINIMISER DIRECTEMENT L'ÉCART-TYPE FUTUR
        # Approche rigoureuse : calculer l'écart-type futur du cluster pour ce node
        if all_nodes and len(all_nodes) > 1:
            # Calculer la charge future du node actuel après placement du pod
            pod_cpu_request = pod.cpu_request if hasattr(pod, 'cpu_request') else 0.0
            pod_mem_request = pod.memory_request if hasattr(pod, 'memory_request') else 0.0
            
            # Calculer la charge future (normalisée entre 0 et 1)
            future_cpu_load = cpu_load
            future_mem_load = memory_load
            if node.cpu_capacity > 0:
                cpu_increase = pod_cpu_request / node.cpu_capacity
                future_cpu_load = min(1.0, cpu_load + cpu_increase)
            if node.memory_capacity > 0:
                mem_increase = pod_mem_request / node.memory_capacity
                future_mem_load = min(1.0, memory_load + mem_increase)
            
            # Construire le vecteur de charges futures pour TOUS les nodes
            future_cpu_loads = []
            future_mem_loads = []
            for n in all_nodes:
                if hasattr(n, 'name') and n.name == node.name:
                    # Pour le node actuel, utiliser la charge future
                    future_cpu_loads.append(future_cpu_load)
                    future_mem_loads.append(future_mem_load)
                else:
                    # Pour les autres nodes, utiliser la charge actuelle
                    n_cpu_load = self._get_node_cpu_load(n.name) if hasattr(n, 'name') else 0.0
                    n_mem_load = self._get_node_memory_load(n.name) if hasattr(n, 'name') else 0.0
                    future_cpu_loads.append(n_cpu_load)
                    future_mem_loads.append(n_mem_load)
            
            # Calculer l'écart-type futur du cluster (ce que nous voulons minimiser)
            if len(future_cpu_loads) > 1:
                cpu_std_future = np.std(future_cpu_loads)
                mem_std_future = np.std(future_mem_loads)
            else:
                cpu_std_future = 0.0
                mem_std_future = 0.0
            
            # Score d'équilibre : inverse de l'écart-type (plus l'écart-type est faible, meilleur est le score)
            # Normaliser : utiliser exp(-k * std) pour convertir en score entre 0 et 1
            # k élevé pour fortement pénaliser les grands écarts-types
            k_cpu = 25.0  # Facteur augmenté pour CPU (priorité sur l'équilibre CPU)
            k_mem = 25.0  # Facteur pour mémoire
            # Éviter division par zéro
            cpu_balance_score = np.exp(-k_cpu * cpu_std_future) if cpu_std_future >= 0 else 0.0
            mem_balance_score = np.exp(-k_mem * mem_std_future) if mem_std_future >= 0 else 0.0
            # Poids équilibré (50% CPU, 50% mémoire) pour améliorer les deux équilibres
            balance_score = (cpu_balance_score * 0.5 + mem_balance_score * 0.5)
            balance_score = max(0.0, min(1.0, balance_score))
        else:
            balance_score = 0.5  # Neutre si pas assez de données
        
        features.append(balance_score)
        
        # 7. NOUVEAU : Pénalité pour surcharge (charge élevée = pénalité)
        overload_penalty = max(0.0, (cpu_load + memory_load) / 2.0 - 0.7)  # Pénalité si > 70% de charge
        features.append(overload_penalty)
        
        # 8. Compatibilité avec les labels du pod
        label_compatibility = self._calculate_label_compatibility(node.labels, pod.labels)
        features.append(label_compatibility)
        
        # 9. Type de pod (encodage one-hot simplifié)
        pod_type_score = self._get_pod_type_score(pod.pod_type)
        features.append(pod_type_score)
        
        # 10. Nombre de pods du même type sur le node
        same_type_pods = self._count_same_type_pods(node.name, pod.pod_type, existing_pods)
        features.append(same_type_pods / 10.0)  # Normaliser
        
        return features
    
    def _get_node_cpu_load(self, node_name: str) -> float:
        """Récupère la charge CPU moyenne d'un node depuis Prometheus"""
        try:
            query = f'avg(rate(node_cpu_seconds_total{{instance=~"{node_name}.*",mode!="idle"}}[5m]))'
            result = self._query_prometheus(query)
            return float(result) if result else 0.0
        except Exception as e:
            logger.debug(f"Erreur lors de la récupération de la charge CPU: {e}")
            return 0.0
    
    def _get_node_memory_load(self, node_name: str) -> float:
        """Récupère la charge mémoire d'un node depuis Prometheus"""
        try:
            query = f'(1 - (node_memory_MemAvailable_bytes{{instance=~"{node_name}.*"}} / node_memory_MemTotal_bytes{{instance=~"{node_name}.*"}}))'
            result = self._query_prometheus(query)
            return float(result) if result else 0.0
        except Exception as e:
            logger.debug(f"Erreur lors de la récupération de la charge mémoire: {e}")
            return 0.0
    
    def _get_node_pod_density(self, node_name: str) -> float:
        """Calcule la densité de pods sur un node"""
        if not self.k8s_client:
            return 0.0
        
        try:
            pods = self.k8s_client.list_pod_for_all_namespaces(
                field_selector=f'spec.nodeName={node_name}'
            )
            # Normaliser (assume max 100 pods par node)
            density = len(pods.items) / 100.0
            return min(1.0, density)
        except Exception as e:
            logger.debug(f"Erreur lors du calcul de la densité de pods: {e}")
            return 0.0
    
    def _calculate_label_compatibility(
        self,
        node_labels: Dict[str, str],
        pod_labels: Dict[str, str]
    ) -> float:
        """
        Calcule la compatibilité entre les labels du node et du pod.
        Retourne un score entre 0 et 1.
        """
        if not pod_labels:
            return 0.5  # Neutre si pas de labels
        
        matches = 0
        total = 0
        
        for key, value in pod_labels.items():
            if key.startswith('node-selector/'):
                # Label de sélection de node
                selector_key = key.replace('node-selector/', '')
                if selector_key in node_labels and node_labels[selector_key] == value:
                    matches += 1
                total += 1
        
        return matches / total if total > 0 else 0.5
    
    def _get_pod_type_score(self, pod_type: Optional[str]) -> float:
        """Encode le type de pod en score (simplifié)"""
        type_scores = {
            'UPF': 0.9,  # Priorité haute pour UPF (proche de l'UE)
            'SMF': 0.7,
            'CU': 0.6,
            'DU': 0.8,   # Priorité haute pour DU
            None: 0.5
        }
        return type_scores.get(pod_type, 0.5)
    
    def _count_same_type_pods(
        self,
        node_name: str,
        pod_type: Optional[str],
        existing_pods: Optional[List[Dict[str, Any]]]
    ) -> float:
        """Compte le nombre de pods du même type sur le node"""
        if not pod_type or not existing_pods:
            return 0.0
        
        count = sum(
            1 for pod in existing_pods
            if pod.get('node') == node_name and pod.get('type') == pod_type
        )
        return float(count)
    
    def _query_prometheus(self, query: str) -> Optional[float]:
        """Exécute une requête PromQL et retourne la valeur"""
        try:
            url = f"{self.prometheus_url}/api/v1/query"
            params = {'query': query}
            
            response = requests.get(url, params=params, timeout=2)
            response.raise_for_status()
            
            data = response.json()
            if data['status'] == 'success' and data['data']['result']:
                value = data['data']['result'][0]['value'][1]
                return float(value)
            
            return None
        except Exception as e:
            logger.debug(f"Erreur lors de la requête Prometheus: {e}")
            return None
    
    def get_feature_names(self) -> List[str]:
        """Retourne la liste des noms de features"""
        return [
            'cpu_available_ratio',
            'memory_available_ratio',
            'network_latency_normalized',
            'cpu_load_avg',
            'memory_load_avg',
            'pod_density',
            'balance_score',  # NOUVEAU : score d'équilibre global
            'overload_penalty',  # NOUVEAU : pénalité pour surcharge
            'label_compatibility',
            'pod_type_score',
            'same_type_pods_count'
        ]

