#!/usr/bin/env python3
"""
Serveur d'inférence FastAPI pour le modèle ML/RL du scheduler.
Expose des endpoints pour prédire le meilleur placement de pods.
"""
import os
import logging
from typing import List, Dict, Optional, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from prometheus_client import Counter, Histogram, generate_latest, REGISTRY

from model_loader import ModelLoader
from feature_extractor import FeatureExtractor

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Métriques Prometheus
prediction_requests = Counter(
    'inference_predictions_total',
    'Nombre total de prédictions demandées',
    ['status']
)

prediction_duration = Histogram(
    'inference_prediction_duration_seconds',
    'Durée des prédictions en secondes'
)

# Initialisation FastAPI
app = FastAPI(
    title="Scheduler Inference Server",
    description="Serveur d'inférence ML pour le scheduler Kubernetes 5G",
    version="1.0.0"
)

# Initialisation des composants
model_loader = None
feature_extractor = None


class NodeInfo(BaseModel):
    """Information sur un node Kubernetes"""
    name: str
    cpu_available: float
    memory_available: float
    cpu_capacity: float
    memory_capacity: float
    labels: Dict[str, str] = {}
    taints: List[Dict[str, Any]] = []
    network_latency: Optional[float] = None  # Latence moyenne depuis les pods existants


class PodInfo(BaseModel):
    """Information sur un pod à placer"""
    name: str
    namespace: str
    cpu_request: float
    memory_request: float
    labels: Dict[str, str] = {}
    annotations: Dict[str, str] = {}
    pod_type: Optional[str] = None  # UPF, SMF, CU, DU, etc.


class PredictionRequest(BaseModel):
    """Requête de prédiction pour le placement d'un pod"""
    pod: PodInfo
    candidate_nodes: List[NodeInfo]
    existing_pods: Optional[List[Dict[str, Any]]] = []  # Pods déjà placés pour contexte


class PredictionResponse(BaseModel):
    """Réponse avec les scores de priorité pour chaque node"""
    node_scores: Dict[str, float]  # node_name -> score (plus élevé = meilleur)
    recommended_node: Optional[str] = None  # Node recommandé (optionnel)
    model_version: str
    features_used: Optional[List[str]] = []  # Liste des features utilisées


@app.on_event("startup")
async def startup_event():
    """Initialise les composants au démarrage"""
    global model_loader, feature_extractor
    
    logger.info("Démarrage du serveur d'inférence...")
    
    # Initialiser le chargeur de modèle
    model_path = os.getenv('MODEL_PATH', '/models/scheduler_model.pkl')
    model_loader = ModelLoader(model_path)
    model_loader.load_model()
    
    # Initialiser l'extracteur de features
    k8s_api_url = os.getenv('KUBERNETES_API_URL', 'https://kubernetes.default.svc')
    prometheus_url = os.getenv('PROMETHEUS_URL', 'http://prometheus.monitoring.svc.cluster.local:9090')
    feature_extractor = FeatureExtractor(k8s_api_url, prometheus_url)
    
    logger.info("Serveur d'inférence prêt")


@app.on_event("shutdown")
async def shutdown_event():
    """Nettoyage à l'arrêt"""
    logger.info("Arrêt du serveur d'inférence")


@app.get("/health")
async def health_check():
    """Endpoint de santé"""
    status = {
        "status": "healthy",
        "model_loaded": model_loader is not None and model_loader.is_loaded(),
        "feature_extractor_ready": feature_extractor is not None
    }
    
    if not status["model_loaded"]:
        status["status"] = "degraded"
    
    return status


@app.get("/metrics")
async def metrics():
    """Endpoint Prometheus pour les métriques"""
    return generate_latest(REGISTRY)


@app.post("/predict", response_model=PredictionResponse)
@prediction_duration.time()
async def predict(request: PredictionRequest):
    """
    Prédit le meilleur placement pour un pod donné.
    
    Args:
        request: Requête contenant les informations du pod et des nodes candidats
    
    Returns:
        Réponse avec les scores de priorité pour chaque node
    """
    try:
        prediction_requests.labels(status='success').inc()
        
        if not model_loader or not model_loader.is_loaded():
            logger.warning("Modèle non chargé, utilisation de l'heuristique par défaut")
            return _default_heuristic(request)
        
        if not feature_extractor:
            raise HTTPException(
                status_code=503,
                detail="Feature extractor non initialisé"
            )
        
        # Extraire les features pour chaque node candidat
        # Passer tous les nodes pour calculer l'équilibre global
        node_features = []
        node_names = []
        
        for node in request.candidate_nodes:
            features = feature_extractor.extract_node_features(
                node, request.pod, request.existing_pods, request.candidate_nodes
            )
            node_features.append(features)
            node_names.append(node.name)
        
        # Prédire avec le modèle
        scores = model_loader.predict(node_features)
        
        # Construire la réponse
        node_scores = {name: float(score) for name, score in zip(node_names, scores)}
        recommended_node = max(node_scores.items(), key=lambda x: x[1])[0] if node_scores else None
        
        return PredictionResponse(
            node_scores=node_scores,
            recommended_node=recommended_node,
            model_version=model_loader.get_version(),
            features_used=feature_extractor.get_feature_names()
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de la prédiction: {e}", exc_info=True)
        prediction_requests.labels(status='error').inc()
        
        # Fallback vers heuristique par défaut
        logger.info("Utilisation de l'heuristique par défaut en cas d'erreur")
        return _default_heuristic(request)


def _default_heuristic(request: PredictionRequest) -> PredictionResponse:
    """
    Heuristique par défaut si le modèle n'est pas disponible.
    Priorise les nodes avec :
    1. Équilibre de charge optimal (PRIORITÉ ABSOLUE - 60%) : minimise directement l'écart-type futur du cluster
    2. CPU bas mais efficace (zone optimale 30-60% pour réduire consommation - 15%)
    3. Latence réseau minimale (15%)
    4. Mémoire optimisée (moins de charge mémoire - 8%)
    5. Ressources disponibles (2%)
    6. Moins de surcharge (0%)
    """
    node_scores = {}
    
    # Pour l'heuristique, calculer la charge actuelle du cluster
    all_cpu_loads = [feature_extractor._get_node_cpu_load(node.name) for node in request.candidate_nodes]
    all_memory_loads = [feature_extractor._get_node_memory_load(node.name) for node in request.candidate_nodes]

    for node in request.candidate_nodes:
        score = 0.0
        
        cpu_ratio = node.cpu_available / node.cpu_capacity if node.cpu_capacity > 0 else 0
        memory_ratio = node.memory_available / node.memory_capacity if node.memory_capacity > 0 else 0
        
        # 1. Optimisation CPU (15% - réduit pour donner plus de poids à l'équilibre)
        node_cpu_load = feature_extractor._get_node_cpu_load(node.name)
        cpu_usage_score = 0.0
        if 0.30 <= node_cpu_load <= 0.60:
            cpu_usage_score = 1.0  # Zone optimale (CPU bas mais efficace)
        elif node_cpu_load < 0.30:
            cpu_usage_score = 0.7 + (node_cpu_load / 0.30) * 0.3  # 0.7 à 1.0
        else:  # > 0.60
            cpu_usage_score = max(0.0, 1.0 - (node_cpu_load - 0.60) * 2.5)  # Sur-utilisation
        
        score += cpu_usage_score * 0.15  # 15% (réduit de 20%)
        
        # 2. Latence réseau (15% - réduit pour donner plus de poids à l'équilibre)
        if node.network_latency is not None:
            # Amplifier l'impact : très faible latence = score très élevé
            normalized_latency = min(1.0, node.network_latency / 100.0)
            latency_score = (1.0 - normalized_latency) ** 1.5  # Fonction exponentielle
            score += latency_score * 0.15  # 15% (réduit de 20%)
        
        # 3. Optimisation mémoire (8% - réduit pour donner plus de poids à l'équilibre)
        node_memory_load = feature_extractor._get_node_memory_load(node.name)
        memory_usage_score = 1.0 - node_memory_load  # Inverse : moins de charge = meilleur
        score += memory_usage_score * 0.08  # 8% (réduit de 10%)
        
        # 4. Ressources disponibles (2% - fortement réduit)
        score += cpu_ratio * 0.01
        score += memory_ratio * 0.01  # Total 2% (réduit de 3%)
        
        # 5. Équilibre de charge (60% - PRIORITÉ ABSOLUE pour minimiser l'écart-type)
        # Calculer l'écart-type futur du cluster pour ce node
        pod_cpu_request = request.pod.cpu_request if hasattr(request.pod, 'cpu_request') else 0.0
        pod_mem_request = request.pod.memory_request if hasattr(request.pod, 'memory_request') else 0.0
        
        # Estimer la charge future du node
        future_cpu_load = node_cpu_load
        future_mem_load = node_memory_load
        if node.cpu_capacity > 0:
            cpu_increase = pod_cpu_request / node.cpu_capacity
            future_cpu_load = min(1.0, node_cpu_load + cpu_increase)
        if node.memory_capacity > 0:
            mem_increase = pod_mem_request / node.memory_capacity
            future_mem_load = min(1.0, node_memory_load + mem_increase)
        
        # Construire le vecteur de charges futures pour tous les nodes
        all_cpu_loads_future = []
        all_memory_loads_future = []
        for n in request.candidate_nodes:
            if n.name == node.name:
                all_cpu_loads_future.append(future_cpu_load)
                all_memory_loads_future.append(future_mem_load)
            else:
                n_cpu_load = feature_extractor._get_node_cpu_load(n.name)
                n_mem_load = feature_extractor._get_node_memory_load(n.name)
                all_cpu_loads_future.append(n_cpu_load)
                all_memory_loads_future.append(n_mem_load)
        
        # Calculer l'écart-type futur (ce que nous voulons minimiser)
        import math
        if len(all_cpu_loads_future) > 1:
            # Calculer la moyenne
            avg_cpu_future = sum(all_cpu_loads_future) / len(all_cpu_loads_future)
            avg_mem_future = sum(all_memory_loads_future) / len(all_memory_loads_future)
            # Calculer la variance puis l'écart-type
            cpu_variance = sum((x - avg_cpu_future) ** 2 for x in all_cpu_loads_future) / len(all_cpu_loads_future)
            mem_variance = sum((x - avg_mem_future) ** 2 for x in all_memory_loads_future) / len(all_memory_loads_future)
            cpu_std_future = math.sqrt(cpu_variance)
            mem_std_future = math.sqrt(mem_variance)
        else:
            cpu_std_future = 0.0
            mem_std_future = 0.0
        
        # Score d'équilibre : inverse de l'écart-type (plus l'écart-type est faible, meilleur)
        k_cpu = 25.0  # Facteur augmenté pour CPU (priorité sur l'équilibre CPU)
        k_mem = 25.0  # Facteur pour mémoire
        cpu_balance_score = math.exp(-k_cpu * cpu_std_future) if cpu_std_future >= 0 else 0.0
        mem_balance_score = math.exp(-k_mem * mem_std_future) if mem_std_future >= 0 else 0.0
        # Poids équilibré (50% CPU, 50% mémoire) pour améliorer les deux équilibres
        balance_score = (cpu_balance_score * 0.5 + mem_balance_score * 0.5)
        balance_score = max(0.0, min(1.0, balance_score))
        score += balance_score * 0.60  # 60% (augmenté de 45% à 60% pour priorité absolue)
        
        # 6. Pénalité de surcharge (0% - supprimé pour donner tout le poids à l'équilibre)
        # Note: La surcharge est déjà prise en compte dans le calcul de l'écart-type
        
        node_scores[node.name] = score
    
    recommended_node = max(node_scores.items(), key=lambda x: x[1])[0] if node_scores else None
    
    return PredictionResponse(
        node_scores=node_scores,
        recommended_node=recommended_node,
        model_version="default-heuristic-v3",
        features_used=["cpu_usage_optimization", "cpu_available_ratio", "memory_available_ratio", 
                       "network_latency", "balance_score", "overload_penalty"]
    )


@app.get("/")
async def root():
    """Endpoint racine avec informations"""
    return {
        "service": "Scheduler Inference Server",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "predict": "/predict",
            "metrics": "/metrics"
        }
    }


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    host = os.getenv("HOST", "0.0.0.0")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )

