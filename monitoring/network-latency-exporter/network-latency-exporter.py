#!/usr/bin/env python3
"""
Exporter Prometheus pour mesurer la latence réseau entre pods.
Mesure le RTT (Round Trip Time) entre ce pod et d'autres pods dans le cluster.
"""
import os
import time
import socket
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from prometheus_client import Counter, Gauge, generate_latest, REGISTRY
import json

# Métriques Prometheus
pod_network_rtt_ms = Gauge(
    'pod_network_rtt_ms',
    'Latence réseau (RTT) en millisecondes entre pods',
    ['source_pod', 'source_node', 'target_pod', 'target_node', 'target_ip']
)

pod_network_packet_loss = Gauge(
    'pod_network_packet_loss',
    'Perte de paquets entre pods (0-100)',
    ['source_pod', 'source_node', 'target_pod', 'target_node', 'target_ip']
)

network_measurements_total = Counter(
    'network_measurements_total',
    'Nombre total de mesures de latence effectuées',
    ['source_pod', 'status']
)

class MetricsHandler(BaseHTTPRequestHandler):
    """Handler HTTP pour exposer les métriques Prometheus"""
    def do_GET(self):
        if self.path == '/metrics':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4')
            self.end_headers()
            metrics = generate_latest(REGISTRY)
            if isinstance(metrics, str):
                self.wfile.write(metrics.encode())
            else:
                self.wfile.write(metrics)
        elif self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'healthy'}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Réduire le logging verbeux
        pass

def get_pod_info():
    """Récupère les informations du pod actuel depuis les variables d'environnement Kubernetes"""
    pod_name = os.getenv('POD_NAME', 'unknown')
    node_name = os.getenv('NODE_NAME', 'unknown')
    pod_namespace = os.getenv('POD_NAMESPACE', 'default')
    return pod_name, node_name, pod_namespace

def measure_latency(target_ip, target_port=80, timeout=2):
    """
    Mesure la latence réseau vers une IP cible en utilisant TCP connect
    Retourne le RTT en millisecondes ou None si échec
    """
    try:
        start = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((target_ip, target_port))
        sock.close()
        end = time.time()
        
        if result == 0:
            rtt_ms = (end - start) * 1000
            return rtt_ms
        else:
            return None
    except Exception as e:
        print(f"Erreur lors de la mesure vers {target_ip}: {e}")
        return None

def ping_measure(target_ip, count=3):
    """
    Utilise ping pour mesurer la latence et la perte de paquets
    Retourne (rtt_ms moyen, perte_pourcentage) ou (None, None) si échec
    """
    try:
        # Utilise ping avec 3 paquets, timeout de 1 seconde
        result = subprocess.run(
            ['ping', '-c', str(count), '-W', '1', target_ip],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            # Parse la sortie de ping pour extraire le RTT moyen
            output = result.stdout
            # Format typique: "rtt min/avg/max/mdev = 0.123/0.456/0.789/0.123 ms"
            import re
            rtt_match = re.search(r'= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms', output)
            if rtt_match:
                avg_rtt = float(rtt_match.group(2))
                return avg_rtt, 0.0
            
            # Alternative: calculer depuis les lignes individuelles
            lines = output.split('\n')
            rtts = []
            for line in lines:
                if 'time=' in line:
                    time_match = re.search(r'time=([\d.]+) ms', line)
                    if time_match:
                        rtts.append(float(time_match.group(1)))
            
            if rtts:
                avg_rtt = sum(rtts) / len(rtts)
                return avg_rtt, 0.0
        
        # Calculer la perte de paquets
        loss_match = re.search(r'(\d+)% packet loss', result.stdout)
        loss_percent = float(loss_match.group(1)) if loss_match else 100.0
        
        return None, loss_percent
        
    except Exception as e:
        print(f"Erreur ping vers {target_ip}: {e}")
        return None, None

def discover_pods(namespace='workloads'):
    """
    Découvre les pods dans le namespace spécifié en utilisant l'API Kubernetes
    Retourne une liste de dicts avec pod_name, node_name, pod_ip
    """
    try:
        # Utilise kubectl pour lister les pods (nécessite un service account avec permissions)
        result = subprocess.run(
            ['kubectl', 'get', 'pods', '-n', namespace, '-o', 'json'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            pods = []
            for item in data.get('items', []):
                pod_name = item['metadata']['name']
                node_name = item['spec'].get('nodeName', 'unknown')
                pod_ip = item['status'].get('podIP', '')
                if pod_ip:
                    pods.append({
                        'name': pod_name,
                        'node': node_name,
                        'ip': pod_ip
                    })
            return pods
    except Exception as e:
        print(f"Erreur lors de la découverte des pods: {e}")
    
    # Fallback: utiliser les variables d'environnement ou une liste statique
    return []

def update_metrics():
    """Met à jour les métriques en mesurant la latence vers les autres pods"""
    source_pod, source_node, namespace = get_pod_info()
    
    # Découvrir les pods cibles
    target_pods = discover_pods(namespace)
    
    if not target_pods:
        # Si pas de découverte, utiliser une liste statique depuis env vars
        target_ips = os.getenv('TARGET_PODS', '').split(',')
        for target_ip in target_ips:
            if target_ip.strip():
                rtt = measure_latency(target_ip.strip())
                if rtt is not None:
                    pod_network_rtt_ms.labels(
                        source_pod=source_pod,
                        source_node=source_node,
                        target_pod='unknown',
                        target_node='unknown',
                        target_ip=target_ip.strip()
                    ).set(rtt)
                    network_measurements_total.labels(
                        source_pod=source_pod,
                        status='success'
                    ).inc()
                else:
                    network_measurements_total.labels(
                        source_pod=source_pod,
                        status='failed'
                    ).inc()
        return
    
    # Mesurer la latence vers chaque pod découvert
    for target in target_pods:
        target_ip = target['ip']
        target_pod = target['name']
        target_node = target['node']
        
        # Mesure TCP connect latency
        rtt = measure_latency(target_ip)
        
        # Mesure ping (si disponible)
        ping_rtt, packet_loss = ping_measure(target_ip)
        
        if rtt is not None:
            pod_network_rtt_ms.labels(
                source_pod=source_pod,
                source_node=source_node,
                target_pod=target_pod,
                target_node=target_node,
                target_ip=target_ip
            ).set(rtt)
            network_measurements_total.labels(
                source_pod=source_pod,
                status='success'
            ).inc()
        else:
            network_measurements_total.labels(
                source_pod=source_pod,
                status='failed'
            ).inc()
        
        if ping_rtt is not None:
            # Utiliser ping RTT si disponible (plus précis)
            pod_network_rtt_ms.labels(
                source_pod=source_pod,
                source_node=source_node,
                target_pod=target_pod,
                target_node=target_node,
                target_ip=target_ip
            ).set(ping_rtt)
        
        if packet_loss is not None:
            pod_network_packet_loss.labels(
                source_pod=source_pod,
                source_node=source_node,
                target_pod=target_pod,
                target_node=target_node,
                target_ip=target_ip
            ).set(packet_loss)

def run_metrics_updater():
    """Thread pour mettre à jour les métriques périodiquement"""
    while True:
        try:
            update_metrics()
        except Exception as e:
            print(f"Erreur lors de la mise à jour des métriques: {e}")
        time.sleep(10)  # Mise à jour toutes les 10 secondes

if __name__ == '__main__':
    import threading
    
    # Démarrer le thread de mise à jour des métriques
    updater_thread = threading.Thread(target=run_metrics_updater, daemon=True)
    updater_thread.start()
    
    # Démarrer le serveur HTTP
    server = HTTPServer(('0.0.0.0', 8080), MetricsHandler)
    print("Network Latency Exporter démarré sur le port 8080")
    print("Métriques disponibles sur /metrics")
    server.serve_forever()

