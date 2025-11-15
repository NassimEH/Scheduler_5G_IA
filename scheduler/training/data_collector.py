#!/usr/bin/env python3
"""
Script de collecte de données depuis Prometheus et Kubernetes pour l'entraînement du modèle.
Collecte les métriques historiques et les placements de pods pour créer un dataset d'entraînement.
"""
import os
import json
import logging
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import requests
import pandas as pd
from kubernetes import client, config
from kubernetes.client.rest import ApiException

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DataCollector:
    """Collecteur de données pour l'entraînement du modèle"""
    
    def __init__(self, prometheus_url: str, k8s_api_url: Optional[str] = None):
        """
        Args:
            prometheus_url: URL de Prometheus
            k8s_api_url: URL de l'API Kubernetes (optionnel)
        """
        self.prometheus_url = prometheus_url
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
    
    def collect_training_data(
        self,
        start_time: datetime,
        end_time: datetime,
        output_file: str
    ) -> pd.DataFrame:
        """
        Collecte les données d'entraînement sur une période donnée.
        
        Args:
            start_time: Date de début
            end_time: Date de fin
            output_file: Fichier de sortie (CSV)
        
        Returns:
            DataFrame avec les données collectées
        """
        logger.info(f"Collecte de données de {start_time} à {end_time}")
        
        records = []
        
        # Récupérer les événements de placement de pods depuis Kubernetes
        if self.k8s_client:
            try:
                events = self.k8s_client.list_event_for_all_namespaces(
                    field_selector='reason=Scheduled',
                    watch=False
                )
                
                for event in events.items:
                    event_time = event.first_timestamp
                    if event_time and start_time <= event_time <= end_time:
                        # Extraire les informations du pod
                        pod_name = event.involved_object.name
                        namespace = event.involved_object.namespace
                        node_name = event.message.split(" on ")[-1] if " on " in event.message else None
                        
                        if node_name:
                            # Récupérer les métriques du node au moment du placement
                            node_features = self._extract_node_features_at_time(
                                node_name, event_time
                            )
                            pod_features = self._extract_pod_features(
                                pod_name, namespace
                            )
                            
                            if node_features and pod_features:
                                record = {
                                    'timestamp': event_time.isoformat(),
                                    'pod_name': pod_name,
                                    'namespace': namespace,
                                    'node_name': node_name,
                                    **node_features,
                                    **pod_features,
                                    'label': 1.0  # Placement réussi = label positif
                                }
                                records.append(record)
            except Exception as e:
                logger.error(f"Erreur lors de la collecte des événements: {e}")
        
        # Si pas assez de données, générer des données synthétiques basées sur les métriques actuelles
        if len(records) < 100:
            logger.info("Génération de données synthétiques supplémentaires...")
            synthetic_records = self._generate_synthetic_data(start_time, end_time)
            records.extend(synthetic_records)
        
        df = pd.DataFrame(records)
        
        if not df.empty:
            df.to_csv(output_file, index=False)
            logger.info(f"Données sauvegardées dans {output_file} ({len(df)} enregistrements)")
        else:
            logger.warning("Aucune donnée collectée")
        
        return df
    
    def _extract_node_features_at_time(
        self,
        node_name: str,
        timestamp: datetime
    ) -> Optional[Dict[str, float]]:
        """Extrait les features d'un node à un moment donné"""
        try:
            # Récupérer les métriques depuis Prometheus (requête instantanée au timestamp)
            timestamp_unix = int(timestamp.timestamp())
            
            # CPU disponible
            cpu_query = f'node:node_cpu_utilisation:ratio{{instance=~"{node_name}.*"}} @ {timestamp_unix}'
            cpu_usage = self._query_prometheus_at_time(cpu_query, timestamp_unix)
            
            # Mémoire disponible
            mem_query = f'(1 - (node_memory_MemAvailable_bytes{{instance=~"{node_name}.*"}} / node_memory_MemTotal_bytes{{instance=~"{node_name}.*"}})) @ {timestamp_unix}'
            mem_usage = self._query_prometheus_at_time(mem_query, timestamp_unix)
            
            # Capacités du node (depuis Kubernetes)
            if self.k8s_client:
                try:
                    node = self.k8s_client.read_node(node_name)
                    cpu_capacity = self._parse_cpu(node.status.capacity.get('cpu', '0'))
                    mem_capacity = self._parse_memory(node.status.capacity.get('memory', '0'))
                    cpu_allocatable = self._parse_cpu(node.status.allocatable.get('cpu', '0'))
                    mem_allocatable = self._parse_memory(node.status.allocatable.get('memory', '0'))
                except:
                    cpu_capacity = cpu_allocatable = 4.0
                    mem_capacity = mem_allocatable = 8.0 * 1024**3  # 8Gi par défaut
            else:
                cpu_capacity = cpu_allocatable = 4.0
                mem_capacity = mem_allocatable = 8.0 * 1024**3
            
            cpu_available_ratio = 1.0 - (cpu_usage if cpu_usage else 0.5)
            mem_available_ratio = 1.0 - (mem_usage if mem_usage else 0.5)
            
            # Latence réseau moyenne (si disponible)
            latency_query = f'avg(network_latency_rtt_seconds{{source_node="{node_name}"}}) @ {timestamp_unix}'
            latency = self._query_prometheus_at_time(latency_query, timestamp_unix)
            latency_normalized = min(1.0, (latency * 1000 / 100.0)) if latency else 0.5
            
            # Densité de pods
            pod_density = self._get_pod_density_at_time(node_name, timestamp)
            
            return {
                'cpu_available_ratio': cpu_available_ratio,
                'memory_available_ratio': mem_available_ratio,
                'cpu_capacity': cpu_capacity,
                'memory_capacity': mem_capacity,
                'cpu_load_avg': cpu_usage if cpu_usage else 0.5,
                'memory_load_avg': mem_usage if mem_usage else 0.5,
                'network_latency_normalized': latency_normalized,
                'pod_density': pod_density
            }
        except Exception as e:
            logger.debug(f"Erreur lors de l'extraction des features du node: {e}")
            return None
    
    def _extract_pod_features(
        self,
        pod_name: str,
        namespace: str
    ) -> Optional[Dict[str, Any]]:
        """Extrait les features d'un pod"""
        if not self.k8s_client:
            return {
                'pod_cpu_request': 0.1,
                'pod_memory_request': 128 * 1024 * 1024,
                'pod_type_score': 0.5
            }
        
        try:
            pod = self.k8s_client.read_namespaced_pod(pod_name, namespace)
            
            # Extraire les ressources demandées
            cpu_request = 0.0
            memory_request = 0.0
            
            for container in pod.spec.containers:
                resources = container.resources.requests or {}
                if 'cpu' in resources:
                    cpu_request += self._parse_cpu(resources['cpu'])
                if 'memory' in resources:
                    memory_request += self._parse_memory(resources['memory'])
            
            # Type de pod
            pod_type = pod.metadata.labels.get('pod_type')
            pod_type_score = self._get_pod_type_score(pod_type)
            
            return {
                'pod_cpu_request': cpu_request,
                'pod_memory_request': memory_request,
                'pod_type_score': pod_type_score
            }
        except Exception as e:
            logger.debug(f"Erreur lors de l'extraction des features du pod: {e}")
            return {
                'pod_cpu_request': 0.1,
                'pod_memory_request': 128 * 1024 * 1024,
                'pod_type_score': 0.5
            }
    
    def _generate_synthetic_data(
        self,
        start_time: datetime,
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        """Génère des données synthétiques basées sur les métriques actuelles"""
        records = []
        
        # Récupérer la liste des nodes
        nodes = []
        if self.k8s_client:
            try:
                node_list = self.k8s_client.list_node()
                nodes = [node.metadata.name for node in node_list.items]
            except:
                nodes = ['scheduler5g-dev-worker', 'scheduler5g-dev-worker2']
        else:
            nodes = ['scheduler5g-dev-worker', 'scheduler5g-dev-worker2']
        
        if not nodes:
            return records
        
        # Générer des exemples variés
        import random
        current_time = start_time
        pod_types = ['UPF', 'SMF', 'CU', 'DU', None]
        
        while current_time < end_time and len(records) < 200:
            node_name = random.choice(nodes)
            pod_type = random.choice(pod_types)
            
            # Features aléatoires mais réalistes
            cpu_available_ratio = random.uniform(0.1, 0.9)
            memory_available_ratio = random.uniform(0.1, 0.9)
            latency_normalized = random.uniform(0.0, 1.0)
            pod_density = random.uniform(0.0, 0.8)
            cpu_load = 1.0 - cpu_available_ratio
            memory_load = 1.0 - memory_available_ratio
            
            pod_cpu_request = random.uniform(0.05, 0.5)
            pod_memory_request = random.uniform(64 * 1024 * 1024, 512 * 1024 * 1024)
            pod_type_score = self._get_pod_type_score(pod_type)
            
            record = {
                'timestamp': current_time.isoformat(),
                'pod_name': f'synthetic-pod-{len(records)}',
                'namespace': 'workloads',
                'node_name': node_name,
                'cpu_available_ratio': cpu_available_ratio,
                'memory_available_ratio': memory_available_ratio,
                'cpu_capacity': 4.0,
                'memory_capacity': 8.0 * 1024**3,
                'cpu_load_avg': cpu_load,
                'memory_load_avg': memory_load,
                'network_latency_normalized': latency_normalized,
                'pod_density': pod_density,
                'pod_cpu_request': pod_cpu_request,
                'pod_memory_request': pod_memory_request,
                'pod_type_score': pod_type_score,
                'label': 1.0
            }
            records.append(record)
            
            current_time += timedelta(minutes=random.randint(1, 10))
        
        return records
    
    def _query_prometheus_at_time(
        self,
        query: str,
        timestamp: int
    ) -> Optional[float]:
        """Exécute une requête PromQL à un timestamp donné"""
        try:
            url = f"{self.prometheus_url}/api/v1/query"
            params = {
                'query': query,
                'time': timestamp
            }
            
            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            
            data = response.json()
            if data['status'] == 'success' and data['data']['result']:
                value = data['data']['result'][0]['value'][1]
                return float(value)
            
            return None
        except Exception as e:
            logger.debug(f"Erreur lors de la requête Prometheus: {e}")
            return None
    
    def _get_pod_density_at_time(
        self,
        node_name: str,
        timestamp: datetime
    ) -> float:
        """Calcule la densité de pods à un moment donné"""
        if not self.k8s_client:
            return 0.0
        
        try:
            pods = self.k8s_client.list_pod_for_all_namespaces(
                field_selector=f'spec.nodeName={node_name}'
            )
            density = len(pods.items) / 100.0
            return min(1.0, density)
        except:
            return 0.0
    
    def _get_pod_type_score(self, pod_type: Optional[str]) -> float:
        """Encode le type de pod en score"""
        type_scores = {
            'UPF': 0.9,
            'SMF': 0.7,
            'CU': 0.6,
            'DU': 0.8,
            None: 0.5
        }
        return type_scores.get(pod_type, 0.5)
    
    def _parse_cpu(self, cpu_str: str) -> float:
        """Parse une chaîne CPU en float"""
        if not cpu_str:
            return 0.0
        if cpu_str.endswith('m'):
            return float(cpu_str[:-1]) / 1000.0
        return float(cpu_str)
    
    def _parse_memory(self, memory_str: str) -> float:
        """Parse une chaîne mémoire en bytes"""
        if not memory_str:
            return 0.0
        
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


def main():
    parser = argparse.ArgumentParser(description='Collecte des données pour l\'entraînement')
    parser.add_argument(
        '--prometheus-url',
        default=os.getenv('PROMETHEUS_URL', 'http://prometheus.monitoring.svc.cluster.local:9090'),
        help='URL de Prometheus'
    )
    parser.add_argument(
        '--output',
        default='training_data.csv',
        help='Fichier de sortie CSV'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=7,
        help='Nombre de jours de données à collecter'
    )
    
    args = parser.parse_args()
    
    end_time = datetime.now()
    start_time = end_time - timedelta(days=args.days)
    
    collector = DataCollector(args.prometheus_url)
    df = collector.collect_training_data(start_time, end_time, args.output)
    
    if not df.empty:
        print(f"\nDonnées collectées : {len(df)} enregistrements")
        print(f"Colonnes : {', '.join(df.columns)}")
        print(f"\nStatistiques :")
        print(df.describe())


if __name__ == '__main__':
    main()


