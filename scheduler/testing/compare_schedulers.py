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
import re
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from kubernetes import client, config
from kubernetes.client.rest import ApiException

logging.basicConfig(
    level=logging.DEBUG,
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
        # toggles
        self.prefer_node_metrics = False
        self.dump_prom_responses = False
        self.output_dir_for_dumps = None
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
        logger.info(f"Collecte des métriques pendant {duration_minutes} minutes (intervalle: {interval_seconds}s)...")
        
        start_time = datetime.now()
        end_time = start_time + timedelta(minutes=duration_minutes)
        
        records = []
        iteration = 0
        
        while datetime.now() < end_time:
            try:
                current_time = datetime.now()
                iteration += 1
                
                # Collecter les métriques au moment actuel
                metrics = self._collect_metrics_at_time(current_time)
                if metrics:
                    records.append(metrics)
                    logger.info(f"Collecte #{iteration}: {len(records)} points collectés (temps restant: {(end_time - current_time).total_seconds() / 60:.1f} min)")
                else:
                    logger.warning(f"Collecte #{iteration}: Aucune métrique collectée")
                
                # Calculer le temps de sommeil jusqu'à la prochaine collecte
                sleep_time = interval_seconds
                next_collect_time = current_time + timedelta(seconds=interval_seconds)
                if next_collect_time > end_time:
                    # Si la prochaine collecte serait après la fin, on arrête
                    break
                
                time.sleep(sleep_time)
                
            except KeyboardInterrupt:
                logger.info("Collecte interrompue par l'utilisateur")
                break
            except Exception as e:
                logger.error(f"Erreur lors de la collecte: {e}")
                time.sleep(interval_seconds)
        
        logger.info(f"Collecte terminée: {len(records)} points collectés sur {iteration} itérations")
        
        df = pd.DataFrame(records)
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        return df
    
    def _collect_metrics_at_time(self, timestamp: datetime) -> Optional[Dict[str, Any]]:
        """Collecte les métriques à un moment donné"""
        try:
            # use float timestamp (may include fractional seconds) to increase chance of matching samples
            timestamp_unix = timestamp.timestamp()
            
            # CPU moyen par node (utilisation CPU en pourcentage)
            # Pour une requête à un timestamp donné, on utilise rate avec une fenêtre
            # Calcul: 100 - (moyenne du CPU idle * 100)
            cpu_query = 'avg(100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[2m])) * 100))'
            cpu_usage = self._query_prometheus_at_time(cpu_query, timestamp_unix)
            # Si la requête avec rate ne fonctionne pas (pas assez de données), essayer plusieurs fallback
            if cpu_usage is None or cpu_usage == 0.0:
                # Requête instantanée basée sur la valeur actuelle
                cpu_query_simple = 'avg(1 - (node_cpu_seconds_total{mode="idle"} / node_cpu_seconds_total))'
                cpu_usage = self._query_prometheus_at_time(cpu_query_simple, timestamp_unix)

            if cpu_usage is None or cpu_usage == 0.0:
                # Fallback: utiliser la charge système rapportée (node_load1) comme approximation
                try:
                    load_query = 'avg(node_load1)'
                    load_val = self._query_prometheus_at_time(load_query, timestamp_unix)
                    if load_val is not None:
                        # Normaliser grossièrement la charge en 0-1 (assume 1.0 ~= full load)
                        cpu_usage = min(1.0, float(load_val))
                except Exception:
                    cpu_usage = 0.0
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
            # Si on préfère les métriques node-exporter, éviter autant que possible
            # les métriques pod-level spécifiques et essayer des métriques node-level
            if self.prefer_node_metrics:
                latency_queries = [
                    'avg(pod_network_rtt_ms) / 1000',
                    'avg(node_network_receive_bytes_total)'
                ]
            for latency_query in latency_queries:
                latency = self._query_prometheus_at_time(latency_query, timestamp_unix)
                if latency is not None:
                    break

            # If latency remains None, try reading pod_network_rtt_ms without conversion
            if latency is None:
                alt = self._query_prometheus_at_time('avg(pod_network_rtt_ms)', timestamp_unix)
                if alt is not None:
                    # it's already in ms -> convert to seconds for consistency above
                    latency = float(alt) / 1000.0
            
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
        timestamp: float
    ) -> Optional[float]:
        """Exécute une requête PromQL à un timestamp donné"""
        try:
            url = f"{self.prometheus_url}/api/v1/query"
            params = {
                'query': query,
                'time': timestamp
            }
            
            # make request a bit more tolerant (some proxied setups are slow)
            logger.debug(f"Prometheus query (time): {query} @ {timestamp}")
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            # optional dump of Prometheus JSON for debugging
            try:
                if self.dump_prom_responses:
                    outdir = self.output_dir_for_dumps or 'prom_dumps'
                    os.makedirs(outdir, exist_ok=True)
                    safe_q = re.sub(r'[^0-9A-Za-z]+', '_', query)[:80]
                    fname = f"{outdir}/prom_time_{safe_q}_{int(time.time())}.json"
                    with open(fname, 'w', encoding='utf-8') as fh:
                        fh.write(response.text)
                    logger.debug(f"Wrote Prometheus time response to {fname}")
            except Exception:
                logger.debug("Failed to dump Prometheus time response")
            
            data = response.json()
            if data['status'] == 'success' and data['data']['result']:
                # support both vector and scalar-like payloads
                try:
                    value = data['data']['result'][0]['value'][1]
                    logger.debug(f"Prometheus returned value (time): {value}")
                    return float(value)
                except Exception:
                    logger.debug("Unable to parse Prometheus time-series value")

            # If no data for the exact timestamp, try an instant query (latest)
            try:
                logger.debug(f"Prometheus instant query fallback: {query}")
                response2 = requests.get(url, params={'query': query}, timeout=10)
                response2.raise_for_status()
                if self.dump_prom_responses:
                    try:
                        outdir = self.output_dir_for_dumps or 'prom_dumps'
                        os.makedirs(outdir, exist_ok=True)
                        safe_q = re.sub(r'[^0-9A-Za-z]+', '_', query)[:80]
                        fname2 = f"{outdir}/prom_instant_{safe_q}_{int(time.time())}.json"
                        with open(fname2, 'w', encoding='utf-8') as fh2:
                            fh2.write(response2.text)
                        logger.debug(f"Wrote Prometheus instant response to {fname2}")
                    except Exception:
                        logger.debug("Failed to dump Prometheus instant response")
                data2 = response2.json()
                if data2['status'] == 'success' and data2['data']['result']:
                    value = data2['data']['result'][0]['value'][1]
                    logger.debug(f"Prometheus returned value (instant): {value}")
                    return float(value)
            except Exception as e:
                logger.debug(f"Instant query fallback failed: {e}")

            # Final fallback: try a small range query around the timestamp and compute an average
            try:
                url_range = f"{self.prometheus_url.rstrip('/')}/api/v1/query_range"
                # take a short window ending at timestamp
                start = timestamp - 30
                end = timestamp
                params_range = {
                    'query': query,
                    'start': start,
                    'end': end,
                    'step': '15s'
                }
                logger.debug(f"Prometheus range query fallback: {query} start={start} end={end}")
                resp_range = requests.get(url_range, params=params_range, timeout=15)
                resp_range.raise_for_status()
                if self.dump_prom_responses:
                    try:
                        outdir = self.output_dir_for_dumps or 'prom_dumps'
                        os.makedirs(outdir, exist_ok=True)
                        safe_q = re.sub(r'[^0-9A-Za-z]+', '_', query)[:80]
                        fnamer = f"{outdir}/prom_range_{safe_q}_{int(time.time())}.json"
                        with open(fnamer, 'w', encoding='utf-8') as fhr:
                            fhr.write(resp_range.text)
                        logger.debug(f"Wrote Prometheus range response to {fnamer}")
                    except Exception:
                        logger.debug("Failed to dump Prometheus range response")
                data_range = resp_range.json()
                if data_range['status'] == 'success' and data_range['data']['result']:
                    # compute mean of the first series values
                    series = data_range['data']['result'][0]['values']
                    vals = [float(v[1]) for v in series if v and v[1] is not None]
                    if vals:
                        avg_val = sum(vals) / len(vals)
                        logger.debug(f"Prometheus range fallback avg: {avg_val}")
                        return float(avg_val)
            except Exception as e:
                logger.debug(f"Range query fallback failed: {e}")

            logger.debug("Prometheus query returned no data for any fallback")
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
        
        has_data = False
        default_value = None
        ml_value = None
        
        if not df_default.empty and len(df_default) > 0:
            default_value = df_default['cpu_usage_avg'].mean() * 100
            has_data = True
        
        if not df_ml.empty and len(df_ml) > 0:
            ml_value = df_ml['cpu_usage_avg'].mean() * 100
            has_data = True
        
        if not has_data:
            ax.text(0.5, 0.5, 'Aucune donnée disponible', 
                   ha='center', va='center', transform=ax.transAxes, fontsize=14)
        else:
            # Créer un graphique en barres
            schedulers = []
            values = []
            colors = []
            
            if default_value is not None:
                schedulers.append('kube-scheduler\n(par défaut)')
                values.append(default_value)
                colors.append('#3498db')
            
            if ml_value is not None:
                schedulers.append('Scheduler ML')
                values.append(ml_value)
                colors.append('#e67e22')
            
            bars = ax.bar(schedulers, values, color=colors, alpha=0.7, edgecolor='black', linewidth=1.5)
            
            # Ajouter les valeurs sur les barres
            for bar, value in zip(bars, values):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{value:.2f}%',
                       ha='center', va='bottom', fontsize=11, fontweight='bold')
            
            # Ajuster les limites Y
            if values:
                max_val = max(values)
                ax.set_ylim([0, max_val * 1.15])
        
        ax.set_ylabel('Utilisation CPU (%)', fontsize=12)
        ax.set_title('Comparaison de l\'utilisation CPU', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3, axis='y')
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
        
        has_data = False
        default_value = None
        ml_value = None
        
        if not df_default.empty and len(df_default) > 0:
            default_value = df_default['memory_usage_avg'].mean() * 100
            has_data = True
        
        if not df_ml.empty and len(df_ml) > 0:
            ml_value = df_ml['memory_usage_avg'].mean() * 100
            has_data = True
        
        if not has_data:
            ax.text(0.5, 0.5, 'Aucune donnée disponible', 
                   ha='center', va='center', transform=ax.transAxes, fontsize=14)
        else:
            # Créer un graphique en barres
            schedulers = []
            values = []
            colors = []
            
            if default_value is not None:
                schedulers.append('kube-scheduler\n(par défaut)')
                values.append(default_value)
                colors.append('#3498db')
            
            if ml_value is not None:
                schedulers.append('Scheduler ML')
                values.append(ml_value)
                colors.append('#e67e22')
            
            bars = ax.bar(schedulers, values, color=colors, alpha=0.7, edgecolor='black', linewidth=1.5)
            
            # Ajouter les valeurs sur les barres
            for bar, value in zip(bars, values):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{value:.2f}%',
                       ha='center', va='bottom', fontsize=11, fontweight='bold')
            
            # Ajuster les limites Y
            if values:
                max_val = max(values)
                ax.set_ylim([0, max_val * 1.15])
        
        ax.set_ylabel('Utilisation Mémoire (%)', fontsize=12)
        ax.set_title('Comparaison de l\'utilisation mémoire', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3, axis='y')
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
        
        has_data = False
        default_value = None
        ml_value = None
        
        if not df_default.empty and len(df_default) > 0:
            default_value = df_default['network_latency_avg'].mean()
            has_data = True
        
        if not df_ml.empty and len(df_ml) > 0:
            ml_value = df_ml['network_latency_avg'].mean()
            has_data = True
        
        if not has_data:
            ax.text(0.5, 0.5, 'Aucune donnée disponible', 
                   ha='center', va='center', transform=ax.transAxes, fontsize=14)
        else:
            # Créer un graphique en barres
            schedulers = []
            values = []
            colors = []
            
            if default_value is not None:
                schedulers.append('kube-scheduler\n(par défaut)')
                values.append(default_value)
                colors.append('#3498db')
            
            if ml_value is not None:
                schedulers.append('Scheduler ML')
                values.append(ml_value)
                colors.append('#e67e22')
            
            bars = ax.bar(schedulers, values, color=colors, alpha=0.7, edgecolor='black', linewidth=1.5)
            
            # Ajouter les valeurs sur les barres
            for bar, value in zip(bars, values):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{value:.3f} ms',
                       ha='center', va='bottom', fontsize=11, fontweight='bold')
            
            # Ajuster les limites Y
            if values:
                max_val = max(values)
                ax.set_ylim([0, max_val * 1.15])
        
        ax.set_ylabel('Latence réseau (ms)', fontsize=12)
        ax.set_title('Comparaison de la latence réseau', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3, axis='y')
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
        default_cpu_imbalance = None
        ml_cpu_imbalance = None
        
        if not df_default.empty and len(df_default) > 0:
            default_cpu_imbalance = df_default['cpu_imbalance'].mean() * 100
        
        if not df_ml.empty and len(df_ml) > 0:
            ml_cpu_imbalance = df_ml['cpu_imbalance'].mean() * 100
        
        schedulers_cpu = []
        values_cpu = []
        colors_cpu = []
        
        if default_cpu_imbalance is not None:
            schedulers_cpu.append('kube-scheduler\n(par défaut)')
            values_cpu.append(default_cpu_imbalance)
            colors_cpu.append('#3498db')
        
        if ml_cpu_imbalance is not None:
            schedulers_cpu.append('Scheduler ML')
            values_cpu.append(ml_cpu_imbalance)
            colors_cpu.append('#e67e22')
        
        if values_cpu:
            bars1 = ax1.bar(schedulers_cpu, values_cpu, color=colors_cpu, alpha=0.7, edgecolor='black', linewidth=1.5)
            for bar, value in zip(bars1, values_cpu):
                height = bar.get_height()
                ax1.text(bar.get_x() + bar.get_width()/2., height,
                        f'{value:.3f}%',
                        ha='center', va='bottom', fontsize=11, fontweight='bold')
            if values_cpu:
                max_val = max(values_cpu)
                ax1.set_ylim([0, max_val * 1.15])
        else:
            ax1.text(0.5, 0.5, 'Aucune donnée disponible', 
                    ha='center', va='center', transform=ax1.transAxes, fontsize=14)
        
        ax1.set_ylabel('Déséquilibre CPU (%)', fontsize=12)
        ax1.set_title('Comparaison du déséquilibre de charge', fontsize=14, fontweight='bold')
        ax1.grid(True, alpha=0.3, axis='y')
        
        # Memory imbalance
        default_mem_imbalance = None
        ml_mem_imbalance = None
        
        if not df_default.empty and len(df_default) > 0:
            default_mem_imbalance = df_default['memory_imbalance'].mean() * 100
        
        if not df_ml.empty and len(df_ml) > 0:
            ml_mem_imbalance = df_ml['memory_imbalance'].mean() * 100
        
        schedulers_mem = []
        values_mem = []
        colors_mem = []
        
        if default_mem_imbalance is not None:
            schedulers_mem.append('kube-scheduler\n(par défaut)')
            values_mem.append(default_mem_imbalance)
            colors_mem.append('#3498db')
        
        if ml_mem_imbalance is not None:
            schedulers_mem.append('Scheduler ML')
            values_mem.append(ml_mem_imbalance)
            colors_mem.append('#e67e22')
        
        if values_mem:
            bars2 = ax2.bar(schedulers_mem, values_mem, color=colors_mem, alpha=0.7, edgecolor='black', linewidth=1.5)
            for bar, value in zip(bars2, values_mem):
                height = bar.get_height()
                ax2.text(bar.get_x() + bar.get_width()/2., height,
                        f'{value:.4f}%',
                        ha='center', va='bottom', fontsize=11, fontweight='bold')
            if values_mem:
                max_val = max(values_mem)
                ax2.set_ylim([0, max_val * 1.15])
        else:
            ax2.text(0.5, 0.5, 'Aucune donnée disponible', 
                    ha='center', va='center', transform=ax2.transAxes, fontsize=14)
        
        ax2.set_xlabel('Scheduler', fontsize=12)
        ax2.set_ylabel('Déséquilibre Mémoire (%)', fontsize=12)
        ax2.grid(True, alpha=0.3, axis='y')
        
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
            # Eviter division par zéro si la valeur moyenne de référence est nulle
            def percent_change(base, new):
                try:
                    if base == 0 or base is None:
                        return None
                    return ((base - new) / base) * 100.0
                except Exception:
                    return None

            cpu_improvement = percent_change(df_default['cpu_imbalance'].mean(), df_ml['cpu_imbalance'].mean())
            mem_improvement = percent_change(df_default['memory_imbalance'].mean(), df_ml['memory_imbalance'].mean())
            latency_improvement = percent_change(df_default['network_latency_avg'].mean(), df_ml['network_latency_avg'].mean())

            report_lines.append(f"  Réduction du déséquilibre CPU : {cpu_improvement:.2f}%" if cpu_improvement is not None else "  Réduction du déséquilibre CPU : N/A")
            report_lines.append(f"  Réduction du déséquilibre Mémoire : {mem_improvement:.2f}%" if mem_improvement is not None else "  Réduction du déséquilibre Mémoire : N/A")
            report_lines.append(f"  Réduction de la latence : {latency_improvement:.2f}%" if latency_improvement is not None else "  Réduction de la latence : N/A")
        
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
    parser.add_argument(
        '--prefer-node-metrics',
        action='store_true',
        help='Utiliser préférentiellement les métriques fournies par node-exporter (fallback)'
    )
    parser.add_argument(
        '--dump-prometheus-responses',
        action='store_true',
        help='Enregistrer les réponses JSON de Prometheus pour débogage dans le répertoire de sortie'
    )
    
    args = parser.parse_args()
    
    comparator = SchedulerComparator(args.prometheus_url)
    comparator.prefer_node_metrics = bool(args.prefer_node_metrics)
    comparator.dump_prom_responses = bool(args.dump_prometheus_responses)
    comparator.output_dir_for_dumps = args.output
    
    if args.collect:
        # Collecter les métriques
        os.makedirs(args.output, exist_ok=True)
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

