#!/usr/bin/env python3
"""
Scripts de test reproductibles pour comparer kube-scheduler et scheduler ML.
Crée des scénarios de test avec différents workloads 5G (UPF, SMF, CU, DU).
"""
import os
import yaml
import time
import logging
import argparse
from typing import List, Dict, Any
from kubernetes import client, config
from kubernetes.client.rest import ApiException

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TestScenarioRunner:
    """Exécuteur de scénarios de test"""
    
    def __init__(self):
        self.k8s_client = None
        self.apps_client = None
        self._init_k8s_client()
    
    def _init_k8s_client(self):
        """Initialise le client Kubernetes"""
        try:
            config.load_incluster_config()
        except:
            try:
                config.load_kube_config()
            except Exception as e:
                logger.warning(f"Impossible de charger la config Kubernetes: {e}")
        
        try:
            self.k8s_client = client.CoreV1Api()
            self.apps_client = client.AppsV1Api()
        except Exception as e:
            logger.warning(f"Impossible d'initialiser le client Kubernetes: {e}")
    
    def create_scenario(
        self,
        scenario_name: str,
        namespace: str = 'workloads'
    ) -> Dict[str, Any]:
        """
        Crée un scénario de test avec différents types de pods 5G.
        
        Args:
            scenario_name: Nom du scénario ('balanced', 'high_latency', 'resource_intensive')
            namespace: Namespace pour créer les pods
        
        Returns:
            Dictionnaire avec les informations du scénario
        """
        logger.info(f"Création du scénario : {scenario_name}")
        
        scenarios = {
            'balanced': self._create_balanced_scenario,
            'high_latency': self._create_high_latency_scenario,
            'resource_intensive': self._create_resource_intensive_scenario,
            'mixed': self._create_mixed_scenario
        }
        
        if scenario_name not in scenarios:
            raise ValueError(f"Scénario inconnu : {scenario_name}")
        
        return scenarios[scenario_name](namespace)
    
    def _create_balanced_scenario(self, namespace: str) -> Dict[str, Any]:
        """Scénario équilibré : mix de pods UPF, SMF, CU, DU avec ressources modérées"""
        deployments = []
        
        pod_types = [
            {'name': 'upf', 'type': 'UPF', 'replicas': 3, 'cpu': '200m', 'memory': '256Mi'},
            {'name': 'smf', 'type': 'SMF', 'replicas': 2, 'cpu': '150m', 'memory': '192Mi'},
            {'name': 'cu', 'type': 'CU', 'replicas': 2, 'cpu': '100m', 'memory': '128Mi'},
            {'name': 'du', 'type': 'DU', 'replicas': 3, 'cpu': '150m', 'memory': '192Mi'}
        ]
        
        for pod_type in pod_types:
            deployment = self._create_deployment(
                name=f"test-{pod_type['name']}",
                namespace=namespace,
                pod_type=pod_type['type'],
                replicas=pod_type['replicas'],
                cpu_request=pod_type['cpu'],
                memory_request=pod_type['memory']
            )
            deployments.append(deployment)
        
        return {
            'name': 'balanced',
            'deployments': deployments,
            'description': 'Scénario équilibré avec mix de pods 5G'
        }
    
    def _create_high_latency_scenario(self, namespace: str) -> Dict[str, Any]:
        """Scénario avec focus sur la latence : beaucoup de pods UPF (proche de l'UE)"""
        deployments = []
        
        # Beaucoup de pods UPF pour tester l'optimisation de latence
        for i in range(5):
            deployment = self._create_deployment(
                name=f"test-upf-{i}",
                namespace=namespace,
                pod_type='UPF',
                replicas=2,
                cpu_request='200m',
                memory_request='256Mi'
            )
            deployments.append(deployment)
        
        return {
            'name': 'high_latency',
            'deployments': deployments,
            'description': 'Scénario avec focus sur la latence (beaucoup de pods UPF)'
        }
    
    def _create_resource_intensive_scenario(self, namespace: str) -> Dict[str, Any]:
        """Scénario avec pods gourmands en ressources"""
        deployments = []
        
        pod_types = [
            {'name': 'upf-heavy', 'type': 'UPF', 'replicas': 2, 'cpu': '500m', 'memory': '512Mi'},
            {'name': 'smf-heavy', 'type': 'SMF', 'replicas': 2, 'cpu': '400m', 'memory': '512Mi'},
            {'name': 'cu-heavy', 'type': 'CU', 'replicas': 2, 'cpu': '300m', 'memory': '384Mi'}
        ]
        
        for pod_type in pod_types:
            deployment = self._create_deployment(
                name=f"test-{pod_type['name']}",
                namespace=namespace,
                pod_type=pod_type['type'],
                replicas=pod_type['replicas'],
                cpu_request=pod_type['cpu'],
                memory_request=pod_type['memory']
            )
            deployments.append(deployment)
        
        return {
            'name': 'resource_intensive',
            'deployments': deployments,
            'description': 'Scénario avec pods gourmands en ressources'
        }
    
    def _create_mixed_scenario(self, namespace: str) -> Dict[str, Any]:
        """Scénario mixte : combinaison de différents types"""
        deployments = []
        
        # Mix de pods avec différentes caractéristiques
        configs = [
            {'name': 'upf-small', 'type': 'UPF', 'replicas': 4, 'cpu': '100m', 'memory': '128Mi'},
            {'name': 'smf-medium', 'type': 'SMF', 'replicas': 3, 'cpu': '200m', 'memory': '256Mi'},
            {'name': 'cu-large', 'type': 'CU', 'replicas': 2, 'cpu': '400m', 'memory': '512Mi'},
            {'name': 'du-small', 'type': 'DU', 'replicas': 5, 'cpu': '100m', 'memory': '128Mi'}
        ]
        
        for config in configs:
            deployment = self._create_deployment(
                name=f"test-{config['name']}",
                namespace=namespace,
                pod_type=config['type'],
                replicas=config['replicas'],
                cpu_request=config['cpu'],
                memory_request=config['memory']
            )
            deployments.append(deployment)
        
        return {
            'name': 'mixed',
            'deployments': deployments,
            'description': 'Scénario mixte avec différentes tailles de pods'
        }
    
    def _create_deployment(
        self,
        name: str,
        namespace: str,
        pod_type: str,
        replicas: int,
        cpu_request: str,
        memory_request: str
    ) -> Dict[str, Any]:
        """Crée un deployment Kubernetes"""
        if not self.apps_client:
            logger.warning("Client Kubernetes non disponible, création simulée")
            return {
                'name': name,
                'namespace': namespace,
                'status': 'simulated'
            }
        
        # Créer le namespace si nécessaire
        try:
            self.k8s_client.create_namespace(
                client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
            )
        except ApiException as e:
            if e.status != 409:  # Namespace existe déjà
                raise
        
        # Créer le deployment
        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(
                name=name,
                namespace=namespace,
                labels={'app': name, 'scenario': 'test'}
            ),
            spec=client.V1DeploymentSpec(
                replicas=replicas,
                selector=client.V1LabelSelector(
                    match_labels={'app': name}
                ),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={
                            'app': name,
                            'pod_type': pod_type
                        }
                    ),
                    spec=client.V1PodSpec(
                        containers=[
                            client.V1Container(
                                name='app',
                                image='nginx:latest',
                                resources=client.V1ResourceRequirements(
                                    requests={
                                        'cpu': cpu_request,
                                        'memory': memory_request
                                    },
                                    limits={
                                        'cpu': str(int(cpu_request.replace('m', '')) * 2) + 'm' if 'm' in cpu_request else str(float(cpu_request) * 2),
                                        'memory': str(int(memory_request.replace('Mi', '')) * 2) + 'Mi' if 'Mi' in memory_request else memory_request
                                    }
                                )
                            )
                        ]
                    )
                )
            )
        )
        
        try:
            result = self.apps_client.create_namespaced_deployment(
                namespace=namespace,
                body=deployment
            )
            logger.info(f"Deployment {name} créé avec {replicas} replicas")
            return {
                'name': name,
                'namespace': namespace,
                'status': 'created',
                'replicas': replicas
            }
        except ApiException as e:
            logger.error(f"Erreur lors de la création du deployment {name}: {e}")
            return {
                'name': name,
                'namespace': namespace,
                'status': 'error',
                'error': str(e)
            }
    
    def cleanup_scenario(self, namespace: str = 'workloads'):
        """Nettoie tous les deployments de test dans un namespace"""
        if not self.apps_client:
            return
        
        try:
            deployments = self.apps_client.list_namespaced_deployment(namespace)
            for deployment in deployments.items:
                if deployment.metadata.labels.get('scenario') == 'test':
                    self.apps_client.delete_namespaced_deployment(
                        name=deployment.metadata.name,
                        namespace=namespace
                    )
                    logger.info(f"Deployment {deployment.metadata.name} supprimé")
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage: {e}")


def main():
    parser = argparse.ArgumentParser(description='Exécuter des scénarios de test')
    parser.add_argument(
        '--scenario',
        choices=['balanced', 'high_latency', 'resource_intensive', 'mixed'],
        default='balanced',
        help='Scénario à exécuter'
    )
    parser.add_argument(
        '--namespace',
        default='workloads',
        help='Namespace pour les pods de test'
    )
    parser.add_argument(
        '--cleanup',
        action='store_true',
        help='Nettoyer les deployments de test'
    )
    
    args = parser.parse_args()
    
    runner = TestScenarioRunner()
    
    if args.cleanup:
        runner.cleanup_scenario(args.namespace)
    else:
        scenario = runner.create_scenario(args.scenario, args.namespace)
        logger.info(f"Scénario créé : {scenario['description']}")
        logger.info(f"Deployments créés : {len(scenario['deployments'])}")


if __name__ == '__main__':
    main()


