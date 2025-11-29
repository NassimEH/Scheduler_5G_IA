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
    1. Optimisation CPU (zone optimale 40-70%)
    2. Plus de ressources disponibles
    3. Moins de latence réseau
    4. Meilleur équilibre de charge
    """
    node_scores = {}
    
    # Pour l'heuristique, calculer la charge moyenne du cluster
    all_cpu_loads = [feature_extractor._get_node_cpu_load(node.name) for node in request.candidate_nodes]
    all_memory_loads = [feature_extractor._get_node_memory_load(node.name) for node in request.candidate_nodes]
    
    avg_cpu_load_cluster = sum(all_cpu_loads) / len(all_cpu_loads) if all_cpu_loads else 0.5
    avg_memory_load_cluster = sum(all_memory_loads) / len(all_memory_loads) if all_memory_loads else 0.5

    for node in request.candidate_nodes:
        score = 0.0
        
        cpu_ratio = node.cpu_available / node.cpu_capacity if node.cpu_capacity > 0 else 0
        memory_ratio = node.memory_available / node.memory_capacity if node.memory_capacity > 0 else 0
        
        # 1. Optimisation CPU (30% - PRIORITÉ)
        node_cpu_load = feature_extractor._get_node_cpu_load(node.name)
        cpu_usage_score = 0.0
        if 0.4 <= node_cpu_load <= 0.7:
            cpu_usage_score = 1.0  # Zone optimale
        elif node_cpu_load < 0.4:
            cpu_usage_score = node_cpu_load / 0.4  # Sous-utilisation
        else:  # > 0.7
            cpu_usage_score = max(0.0, 1.0 - (node_cpu_load - 0.7) * 3.33)  # Sur-utilisation
        
        score += cpu_usage_score * 0.30
        
        # 2. Ressources disponibles (20%)
        score += cpu_ratio * 0.10
        score += memory_ratio * 0.10
        
        # 3. Latence (15%)
        if node.network_latency is not None:
            latency_score = max(0, 1 - (node.network_latency / 100.0))
            score += latency_score * 0.15
        
        # 4. Équilibre de charge (25%)
        node_memory_load = feature_extractor._get_node_memory_load(node.name)
        cpu_balance_penalty = abs(node_cpu_load - avg_cpu_load_cluster)
        mem_balance_penalty = abs(node_memory_load - avg_memory_load_cluster)
        balance_score = 1.0 - ((cpu_balance_penalty + mem_balance_penalty) / 2.0)
        score += balance_score * 0.25
        
        # 5. Pénalité de surcharge (10%)
        overload_penalty = 0.0
        if node_cpu_load > 0.7 or node_memory_load > 0.7:
            overload_penalty = 1.0
        score += (1.0 - overload_penalty) * 0.10
        
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

