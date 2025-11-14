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
        node_features = []
        node_names = []
        
        for node in request.candidate_nodes:
            features = feature_extractor.extract_node_features(
                node, request.pod, request.existing_pods
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
    1. Plus de ressources disponibles
    2. Moins de latence réseau (si disponible)
    3. Meilleur équilibre de charge
    """
    node_scores = {}
    
    for node in request.candidate_nodes:
        score = 0.0
        
        # Score basé sur les ressources disponibles (normalisé)
        cpu_ratio = node.cpu_available / node.cpu_capacity if node.cpu_capacity > 0 else 0
        memory_ratio = node.memory_available / node.memory_capacity if node.memory_capacity > 0 else 0
        
        # Poids : 40% CPU, 40% mémoire, 20% latence
        score += cpu_ratio * 0.4
        score += memory_ratio * 0.4
        
        # Bonus pour faible latence (si disponible)
        if node.network_latency is not None:
            # Normaliser la latence (assume max 100ms, inverse pour avoir plus = mieux)
            latency_score = max(0, 1 - (node.network_latency / 100.0))
            score += latency_score * 0.2
        
        node_scores[node.name] = score
    
    recommended_node = max(node_scores.items(), key=lambda x: x[1])[0] if node_scores else None
    
    return PredictionResponse(
        node_scores=node_scores,
        recommended_node=recommended_node,
        model_version="default-heuristic-v1",
        features_used=["cpu_available_ratio", "memory_available_ratio", "network_latency"]
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

