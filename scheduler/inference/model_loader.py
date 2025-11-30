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
        self.scaler = None
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
                loaded_data = pickle.load(f)
            
            # Vérifier si c'est un wrapper (dict) ou un modèle direct
            if isinstance(loaded_data, dict):
                # Modèle wrapper avec scaler
                self.model = loaded_data.get('model')
                self.scaler = loaded_data.get('scaler')
                self.model_version = loaded_data.get('version', '1.0.0')
                logger.info(f"Modèle wrapper chargé depuis {self.model_path} (version {self.model_version})")
            else:
                # Modèle direct (ancien format)
                self.model = loaded_data
                logger.info(f"Modèle direct chargé depuis {self.model_path}")
                # Essayer d'obtenir la version
                if hasattr(self.model, 'version'):
                    self.model_version = self.model.version
                elif hasattr(self.model, '__version__'):
                    self.model_version = self.model.__version__
            
            self.is_model_loaded = True
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
        
        # Normaliser les features si un scaler est disponible
        if self.scaler is not None:
            try:
                features_array = self.scaler.transform(features_array)
            except Exception as e:
                logger.warning(f"Erreur lors de la normalisation: {e}")
        
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
        Prédiction stub basée sur une heuristique améliorée.
        
        Features attendues (dans l'ordre):
        - cpu_available_ratio
        - memory_available_ratio
        - network_latency_normalized
        - cpu_load_avg
        - memory_load_avg
        - pod_density
        - balance_score (NOUVEAU)
        - overload_penalty (NOUVEAU)
        - label_compatibility
        - pod_type_score
        - same_type_pods_count
        """
        if len(features.shape) == 1:
            features = features.reshape(1, -1)
        
        scores = []
        for node_features in features:
            score = 0.0
            
            if len(node_features) < 2:
                scores.append(0.5)  # Score neutre
                continue
            
            cpu_ratio = node_features[0]
            memory_ratio = node_features[1]
            
            # 1. Optimisation CPU (15% - réduit pour donner plus de poids à l'équilibre)
            if len(node_features) >= 4:
                cpu_load = node_features[3]
                cpu_usage_score = 0.0
                if 0.30 <= cpu_load <= 0.60:
                    cpu_usage_score = 1.0  # Zone optimale (CPU bas mais efficace)
                elif cpu_load < 0.30:
                    cpu_usage_score = 0.7 + (cpu_load / 0.30) * 0.3  # 0.7 à 1.0
                else:  # > 0.60
                    cpu_usage_score = max(0.0, 1.0 - (cpu_load - 0.60) * 2.5)  # Sur-utilisation
                score += cpu_usage_score * 0.15  # 15% (réduit de 20%)
            else:
                # Fallback : utiliser cpu_ratio
                score += cpu_ratio * 0.15
            
            # 2. Latence réseau (15% - réduit pour donner plus de poids à l'équilibre)
            if len(node_features) >= 3:
                latency = node_features[2]
                # Amplifier l'impact : très faible latence = score très élevé
                latency_score = (1.0 - latency) ** 1.5  # Fonction exponentielle
                score += latency_score * 0.15  # 15% (réduit de 20%)
            else:
                score += (1.0 - 0.5) * 0.15  # Fallback neutre
            
            # 3. Optimisation mémoire (8% - réduit pour donner plus de poids à l'équilibre)
            if len(node_features) >= 5:
                mem_load = node_features[4]
                memory_usage_score = 1.0 - mem_load  # Inverse : moins de charge = meilleur
                score += memory_usage_score * 0.08  # 8% (réduit de 10%)
            else:
                score += memory_ratio * 0.08  # Fallback
            
            # 4. Ressources disponibles (2% - fortement réduit)
            score += cpu_ratio * 0.01
            score += memory_ratio * 0.01  # Total 2% (réduit de 3%)
            
            # 5. Équilibre de charge (60% - PRIORITÉ ABSOLUE pour minimiser l'écart-type)
            if len(node_features) >= 7:
                balance_score = node_features[6]
                # Le balance_score vient déjà du feature_extractor et minimise l'écart-type futur
                score += balance_score * 0.60  # 60% (augmenté de 45% à 60%)
            else:
                # Fallback : calculer depuis la charge avec fonction exponentielle inversée
                if len(node_features) >= 5:
                    import math
                    cpu_load = node_features[3] if len(node_features) >= 4 else 0.5
                    mem_load = node_features[4] if len(node_features) >= 5 else 0.5
                    # Utiliser fonction exponentielle inversée pour pénaliser fortement les écarts
                    # Plus proche de 0.5 = meilleur équilibre
                    cpu_deviation = abs(cpu_load - 0.5)
                    mem_deviation = abs(mem_load - 0.5)
                    k_cpu = 25.0  # Facteur augmenté pour CPU (priorité sur l'équilibre CPU)
                    k_mem = 25.0  # Facteur pour mémoire
                    cpu_balance = math.exp(-k_cpu * cpu_deviation) if cpu_deviation > 0 else 1.0
                    mem_balance = math.exp(-k_mem * mem_deviation) if mem_deviation > 0 else 1.0
                    # Poids équilibré (50% CPU, 50% mémoire) pour améliorer les deux équilibres
                    balance_score = (cpu_balance * 0.5 + mem_balance * 0.5)
                    balance_score = max(0.0, min(1.0, balance_score))
                    score += balance_score * 0.60
            
            # 6. Pénalité de surcharge (0% - supprimé, déjà pris en compte dans l'écart-type)
            # Note: La surcharge est déjà prise en compte dans le calcul de l'écart-type
            
            scores.append(max(0.0, min(1.0, score)))  # Clamp entre 0 et 1
        
        return np.array(scores)

