#!/usr/bin/env python3
"""
Script de comparaison entre kube-scheduler par défaut et le scheduler ML.
Génère des métriques et des graphiques de comparaison.
"""
import os
import json
import time
import logging
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from kubernetes import client, config
from kubernetes.client.rest import ApiException

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SchedulerComparator:
    """Comparateur entre kube-scheduler et scheduler ML"""
    
    def __init__(
        self,
        prometheus_url: str,
        k8s_api_url: Optional[str] = None
    ):
        """
        Args:
            prometheus_url: URL de Prometheus
            k8s_api_url: URL de l'API Kubernetes (optionnel)
        """
        self.prometheus_url = prometheus_url
        self.k8s_client = None
        self._init_k8s_client()
        self.metrics_data = []
    
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
        except Exception as e:
            logger.warning(f"Impossible d'initialiser le client Kubernetes: {e}")
    
    def collect_metrics(
        self,
        duration_minutes: int = 30,
        interval_seconds: int = 30
    ) -> pd.DataFrame:
        """
        Collecte les métriques pendant une période donnée.
        
        Args:
            duration_minutes: Durée de la collecte en minutes
            interval_seconds: Intervalle entre les collectes en secondes
        
        Returns:
            DataFrame avec les métriques collectées
        """
        logger.info(f"Collecte des métriques pendant {duration_minutes} minutes...")
        
        end_time = datetime.now()
        start_time = end_time - timedelta(minutes=duration_minutes)
        current_time = start_time
        
        records = []
        
        while current_time < end_time:
            try:
                # Collecter les métriques à ce moment
                metrics = self._collect_metrics_at_time(current_time)
                if metrics:
                    records.append(metrics)
                
                time.sleep(interval_seconds)
                current_time = datetime.now()
            except KeyboardInterrupt:
                logger.info("Collecte interrompue par l'utilisateur")
                break
            except Exception as e:
                logger.error(f"Erreur lors de la collecte: {e}")
                time.sleep(interval_seconds)
                current_time = datetime.now()
        
        df = pd.DataFrame(records)
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        return df
    
    def _collect_metrics_at_time(self, timestamp: datetime) -> Optional[Dict[str, Any]]:
        """Collecte les métriques à un moment donné"""
        try:
            timestamp_unix = int(timestamp.timestamp())
            
            # CPU moyen par node (utilisation CPU en pourcentage)
            # Pour une requête à un timestamp donné, on utilise rate avec une fenêtre
            # Calcul: 100 - (moyenne du CPU idle * 100)
            cpu_query = 'avg(100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[2m])) * 100))'
            cpu_usage = self._query_prometheus_at_time(cpu_query, timestamp_unix)
            # Si la requête avec rate ne fonctionne pas (pas assez de données), utiliser une requête instantanée
            if cpu_usage is None:
                # Requête instantanée basée sur la valeur actuelle
                cpu_query_simple = 'avg(1 - (node_cpu_seconds_total{mode="idle"} / node_cpu_seconds_total))'
                cpu_usage = self._query_prometheus_at_time(cpu_query_simple, timestamp_unix)
            # Normaliser en pourcentage (0-1) si nécessaire
            if cpu_usage is not None and cpu_usage > 1.0:
                cpu_usage = cpu_usage / 100.0
            
            # Mémoire moyenne par node (utilisation mémoire en pourcentage)
            mem_query = 'avg(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))'
            mem_usage = self._query_prometheus_at_time(mem_query, timestamp_unix)
            
            # Latence réseau moyenne (en secondes, puis converti en ms)
            # Essayer plusieurs métriques possibles
            latency = None
            latency_queries = [
                'avg(pod_network_rtt_ms) / 1000',  # Si l'exporter de latence fonctionne
                'avg(network_latency_rtt_seconds)',  # Autre format possible
                'avg(histogram_quantile(0.5, rate(network_latency_bucket[5m])))'  # Si disponible
            ]
            for latency_query in latency_queries:
                latency = self._query_prometheus_at_time(latency_query, timestamp_unix)
                if latency is not None:
                    break
            
            # Nombre de pods par node
            pods_per_node = self._get_pods_per_node()
            
            # Déséquilibre de charge (écart-type de l'utilisation CPU)
            # Calculer l'écart-type de l'utilisation CPU par node
            cpu_std_query = 'stddev(100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[2m])) * 100))'
            cpu_std = self._query_prometheus_at_time(cpu_std_query, timestamp_unix)
            # Normaliser en pourcentage (0-1) si nécessaire
            if cpu_std is not None and cpu_std > 1.0:
                cpu_std = cpu_std / 100.0
            
            # Déséquilibre mémoire (écart-type de l'utilisation mémoire)
            mem_std_query = 'stddev(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))'
            mem_std = self._query_prometheus_at_time(mem_std_query, timestamp_unix)
            
            return {
                'timestamp': timestamp.isoformat(),
                'cpu_usage_avg': cpu_usage if cpu_usage else 0.0,
                'memory_usage_avg': mem_usage if mem_usage else 0.0,
                'network_latency_avg': latency * 1000 if latency else 0.0,  # en ms
                'pods_per_node_avg': pods_per_node,
                'cpu_imbalance': cpu_std if cpu_std else 0.0,
                'memory_imbalance': mem_std if mem_std else 0.0
            }
        except Exception as e:
            logger.debug(f"Erreur lors de la collecte des métriques: {e}")
            return None
    
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
    
    def _get_pods_per_node(self) -> float:
        """Calcule le nombre moyen de pods par node"""
        if not self.k8s_client:
            return 0.0
        
        try:
            pods = self.k8s_client.list_pod_for_all_namespaces()
            nodes = self.k8s_client.list_node()
            
            if nodes.items:
                return len(pods.items) / len(nodes.items)
            return 0.0
        except:
            return 0.0
    
    def generate_comparison_report(
        self,
        df_default: pd.DataFrame,
        df_ml: pd.DataFrame,
        output_dir: str = 'comparison_results'
    ):
        """
        Génère un rapport de comparaison avec graphiques.
        
        Args:
            df_default: DataFrame avec métriques du kube-scheduler par défaut
            df_ml: DataFrame avec métriques du scheduler ML
            output_dir: Répertoire de sortie
        """
        os.makedirs(output_dir, exist_ok=True)
        
        logger.info("Génération du rapport de comparaison...")
        
        # Générer les graphiques
        self._plot_cpu_comparison(df_default, df_ml, output_dir)
        self._plot_memory_comparison(df_default, df_ml, output_dir)
        self._plot_latency_comparison(df_default, df_ml, output_dir)
        self._plot_imbalance_comparison(df_default, df_ml, output_dir)
        
        # Générer le rapport texte
        self._generate_text_report(df_default, df_ml, output_dir)
        
        logger.info(f"Rapport généré dans {output_dir}/")
    
    def _plot_cpu_comparison(
        self,
        df_default: pd.DataFrame,
        df_ml: pd.DataFrame,
        output_dir: str
    ):
        """Génère le graphique de comparaison CPU"""
        fig, ax = plt.subplots(figsize=(12, 6))
        
        if not df_default.empty:
            ax.plot(
                df_default['timestamp'],
                df_default['cpu_usage_avg'] * 100,
                label='kube-scheduler (par défaut)',
                marker='o',
                markersize=3
            )
        
        if not df_ml.empty:
            ax.plot(
                df_ml['timestamp'],
                df_ml['cpu_usage_avg'] * 100,
                label='Scheduler ML',
                marker='s',
                markersize=3
            )
        
        ax.set_xlabel('Temps')
        ax.set_ylabel('Utilisation CPU (%)')
        ax.set_title('Comparaison de l\'utilisation CPU')
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        plt.savefig(f'{output_dir}/cpu_comparison.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def _plot_memory_comparison(
        self,
        df_default: pd.DataFrame,
        df_ml: pd.DataFrame,
        output_dir: str
    ):
        """Génère le graphique de comparaison mémoire"""
        fig, ax = plt.subplots(figsize=(12, 6))
        
        if not df_default.empty:
            ax.plot(
                df_default['timestamp'],
                df_default['memory_usage_avg'] * 100,
                label='kube-scheduler (par défaut)',
                marker='o',
                markersize=3
            )
        
        if not df_ml.empty:
            ax.plot(
                df_ml['timestamp'],
                df_ml['memory_usage_avg'] * 100,
                label='Scheduler ML',
                marker='s',
                markersize=3
            )
        
        ax.set_xlabel('Temps')
        ax.set_ylabel('Utilisation Mémoire (%)')
        ax.set_title('Comparaison de l\'utilisation mémoire')
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        plt.savefig(f'{output_dir}/memory_comparison.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def _plot_latency_comparison(
        self,
        df_default: pd.DataFrame,
        df_ml: pd.DataFrame,
        output_dir: str
    ):
        """Génère le graphique de comparaison latence"""
        fig, ax = plt.subplots(figsize=(12, 6))
        
        if not df_default.empty:
            ax.plot(
                df_default['timestamp'],
                df_default['network_latency_avg'],
                label='kube-scheduler (par défaut)',
                marker='o',
                markersize=3
            )
        
        if not df_ml.empty:
            ax.plot(
                df_ml['timestamp'],
                df_ml['network_latency_avg'],
                label='Scheduler ML',
                marker='s',
                markersize=3
            )
        
        ax.set_xlabel('Temps')
        ax.set_ylabel('Latence réseau (ms)')
        ax.set_title('Comparaison de la latence réseau')
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        plt.savefig(f'{output_dir}/latency_comparison.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def _plot_imbalance_comparison(
        self,
        df_default: pd.DataFrame,
        df_ml: pd.DataFrame,
        output_dir: str
    ):
        """Génère le graphique de comparaison du déséquilibre"""
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))
        
        # CPU imbalance
        if not df_default.empty:
            ax1.plot(
                df_default['timestamp'],
                df_default['cpu_imbalance'] * 100,
                label='kube-scheduler (par défaut)',
                marker='o',
                markersize=3
            )
        
        if not df_ml.empty:
            ax1.plot(
                df_ml['timestamp'],
                df_ml['cpu_imbalance'] * 100,
                label='Scheduler ML',
                marker='s',
                markersize=3
            )
        
        ax1.set_ylabel('Déséquilibre CPU (%)')
        ax1.set_title('Comparaison du déséquilibre de charge')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        
        # Memory imbalance
        if not df_default.empty:
            ax2.plot(
                df_default['timestamp'],
                df_default['memory_imbalance'] * 100,
                label='kube-scheduler (par défaut)',
                marker='o',
                markersize=3
            )
        
        if not df_ml.empty:
            ax2.plot(
                df_ml['timestamp'],
                df_ml['memory_imbalance'] * 100,
                label='Scheduler ML',
                marker='s',
                markersize=3
            )
        
        ax2.set_xlabel('Temps')
        ax2.set_ylabel('Déséquilibre Mémoire (%)')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        plt.savefig(f'{output_dir}/imbalance_comparison.png', dpi=300, bbox_inches='tight')
        plt.close()
    
    def _generate_text_report(
        self,
        df_default: pd.DataFrame,
        df_ml: pd.DataFrame,
        output_dir: str
    ):
        """Génère un rapport texte avec les statistiques"""
        report_lines = []
        report_lines.append("=" * 60)
        report_lines.append("RAPPORT DE COMPARAISON : kube-scheduler vs Scheduler ML")
        report_lines.append("=" * 60)
        report_lines.append("")
        
        if not df_default.empty:
            report_lines.append("kube-scheduler (par défaut) :")
            report_lines.append(f"  CPU moyen : {df_default['cpu_usage_avg'].mean() * 100:.2f}%")
            report_lines.append(f"  Mémoire moyenne : {df_default['memory_usage_avg'].mean() * 100:.2f}%")
            report_lines.append(f"  Latence moyenne : {df_default['network_latency_avg'].mean():.2f} ms")
            report_lines.append(f"  Déséquilibre CPU : {df_default['cpu_imbalance'].mean() * 100:.2f}%")
            report_lines.append(f"  Déséquilibre Mémoire : {df_default['memory_imbalance'].mean() * 100:.2f}%")
            report_lines.append("")
        
        if not df_ml.empty:
            report_lines.append("Scheduler ML :")
            report_lines.append(f"  CPU moyen : {df_ml['cpu_usage_avg'].mean() * 100:.2f}%")
            report_lines.append(f"  Mémoire moyenne : {df_ml['memory_usage_avg'].mean() * 100:.2f}%")
            report_lines.append(f"  Latence moyenne : {df_ml['network_latency_avg'].mean():.2f} ms")
            report_lines.append(f"  Déséquilibre CPU : {df_ml['cpu_imbalance'].mean() * 100:.2f}%")
            report_lines.append(f"  Déséquilibre Mémoire : {df_ml['memory_imbalance'].mean() * 100:.2f}%")
            report_lines.append("")
        
        if not df_default.empty and not df_ml.empty:
            report_lines.append("Améliorations du Scheduler ML :")
            cpu_improvement = ((df_default['cpu_imbalance'].mean() - df_ml['cpu_imbalance'].mean()) / df_default['cpu_imbalance'].mean()) * 100
            mem_improvement = ((df_default['memory_imbalance'].mean() - df_ml['memory_imbalance'].mean()) / df_default['memory_imbalance'].mean()) * 100
            latency_improvement = ((df_default['network_latency_avg'].mean() - df_ml['network_latency_avg'].mean()) / df_default['network_latency_avg'].mean()) * 100
            
            report_lines.append(f"  Réduction du déséquilibre CPU : {cpu_improvement:.2f}%")
            report_lines.append(f"  Réduction du déséquilibre Mémoire : {mem_improvement:.2f}%")
            report_lines.append(f"  Réduction de la latence : {latency_improvement:.2f}%")
        
        report_text = "\n".join(report_lines)
        
        with open(f'{output_dir}/comparison_report.txt', 'w', encoding='utf-8') as f:
            f.write(report_text)
        
        print(report_text)


def main():
    parser = argparse.ArgumentParser(description='Comparaison entre kube-scheduler et scheduler ML')
    parser.add_argument(
        '--prometheus-url',
        default=os.getenv('PROMETHEUS_URL', 'http://prometheus.monitoring.svc.cluster.local:9090'),
        help='URL de Prometheus'
    )
    parser.add_argument(
        '--default-data',
        help='Fichier CSV avec métriques du kube-scheduler par défaut'
    )
    parser.add_argument(
        '--ml-data',
        help='Fichier CSV avec métriques du scheduler ML'
    )
    parser.add_argument(
        '--collect',
        action='store_true',
        help='Collecter les métriques maintenant'
    )
    parser.add_argument(
        '--duration',
        type=int,
        default=30,
        help='Durée de la collecte en minutes'
    )
    parser.add_argument(
        '--output',
        default='comparison_results',
        help='Répertoire de sortie'
    )
    
    args = parser.parse_args()
    
    comparator = SchedulerComparator(args.prometheus_url)
    
    if args.collect:
        # Collecter les métriques
        df = comparator.collect_metrics(duration_minutes=args.duration)
        if not df.empty:
            output_file = f'{args.output}/metrics_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            df.to_csv(output_file, index=False)
            logger.info(f"Métriques sauvegardées dans {output_file}")
    else:
        # Charger les données et générer le rapport
        if not args.default_data or not args.ml_data:
            logger.error("Les fichiers --default-data et --ml-data sont requis")
            return
        
        df_default = pd.read_csv(args.default_data)
        df_ml = pd.read_csv(args.ml_data)
        
        df_default['timestamp'] = pd.to_datetime(df_default['timestamp'])
        df_ml['timestamp'] = pd.to_datetime(df_ml['timestamp'])
        
        comparator.generate_comparison_report(df_default, df_ml, args.output)


if __name__ == '__main__':
    main()

