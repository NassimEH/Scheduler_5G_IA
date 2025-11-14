#!/usr/bin/env python3
"""
Module pour charger et utiliser le modèle ML/RL.
Pour l'instant, implémente un stub qui sera remplacé par le vrai modèle.
"""
import os
import logging
import pickle
from typing import List, Optional
import numpy as np

logger = logging.getLogger(__name__)


class ModelLoader:
    """Chargeur de modèle ML/RL pour le scheduler"""
    
    def __init__(self, model_path: str):
        """
        Args:
            model_path: Chemin vers le fichier de modèle
        """
        self.model_path = model_path
        self.model = None
        self.model_version = "stub-v1.0"
        self.is_model_loaded = False
    
    def load_model(self):
        """Charge le modèle depuis le fichier"""
        if not os.path.exists(self.model_path):
            logger.warning(
                f"Modèle non trouvé à {self.model_path}. "
                "Utilisation du modèle stub par défaut."
            )
            self.model = StubModel()
            self.is_model_loaded = True
            return
        
        try:
            with open(self.model_path, 'rb') as f:
                self.model = pickle.load(f)
            self.is_model_loaded = True
            logger.info(f"Modèle chargé depuis {self.model_path}")
            
            # Essayer d'obtenir la version du modèle si disponible
            if hasattr(self.model, 'version'):
                self.model_version = self.model.version
            elif hasattr(self.model, '__version__'):
                self.model_version = self.model.__version__
        except Exception as e:
            logger.error(f"Erreur lors du chargement du modèle: {e}")
            logger.info("Utilisation du modèle stub par défaut")
            self.model = StubModel()
            self.is_model_loaded = True
    
    def is_loaded(self) -> bool:
        """Vérifie si le modèle est chargé"""
        return self.is_model_loaded and self.model is not None
    
    def predict(self, features: List[List[float]]) -> List[float]:
        """
        Prédit les scores pour chaque node candidat.
        
        Args:
            features: Liste de listes de features, une par node candidat
        
        Returns:
            Liste de scores (un par node)
        """
        if not self.is_loaded():
            raise RuntimeError("Modèle non chargé")
        
        # Convertir en numpy array si nécessaire
        if isinstance(features, list):
            features_array = np.array(features)
        else:
            features_array = features
        
        # Prédire avec le modèle
        if hasattr(self.model, 'predict'):
            scores = self.model.predict(features_array)
        elif hasattr(self.model, 'predict_proba'):
            # Pour les modèles de classification, utiliser predict_proba
            proba = self.model.predict_proba(features_array)
            scores = proba[:, 1] if proba.shape[1] > 1 else proba[:, 0]
        else:
            # Fallback : utiliser le modèle stub
            logger.warning("Modèle sans méthode predict, utilisation du stub")
            stub = StubModel()
            scores = stub.predict(features_array)
        
        # Convertir en liste de floats
        if isinstance(scores, np.ndarray):
            return scores.tolist()
        return list(scores)
    
    def get_version(self) -> str:
        """Retourne la version du modèle"""
        return self.model_version


class StubModel:
    """
    Modèle stub pour le développement et les tests.
    Implémente une heuristique simple basée sur les features.
    """
    
    def __init__(self):
        self.version = "stub-v1.0"
    
    def predict(self, features: np.ndarray) -> np.ndarray:
        """
        Prédiction stub basée sur une heuristique simple.
        
        Features attendues (dans l'ordre):
        - cpu_available_ratio
        - memory_available_ratio
        - network_latency_normalized
        - cpu_load_avg
        - memory_load_avg
        - pod_density
        - etc.
        """
        if len(features.shape) == 1:
            features = features.reshape(1, -1)
        
        scores = []
        for node_features in features:
            score = 0.0
            
            # Si on a au moins 2 features (CPU et mémoire)
            if len(node_features) >= 2:
                cpu_ratio = node_features[0]
                memory_ratio = node_features[1]
                
                # Score basé sur les ressources disponibles
                score += cpu_ratio * 0.5
                score += memory_ratio * 0.5
                
                # Bonus pour faible latence si disponible (feature index 2)
                if len(node_features) >= 3 and node_features[2] is not None:
                    latency_score = 1.0 - node_features[2]  # Inverse de la latence normalisée
                    score += latency_score * 0.2
                    score /= 1.2  # Normaliser
            
            scores.append(max(0.0, min(1.0, score)))  # Clamp entre 0 et 1
        
        return np.array(scores)

