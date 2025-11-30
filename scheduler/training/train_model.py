#!/usr/bin/env python3
"""
Script d'entraînement du modèle ML pour le scheduler Kubernetes 5G.
Utilise un algorithme de machine learning (Random Forest ou Gradient Boosting) pour prédire
le meilleur placement de pods en fonction des features des nodes et des pods.
"""
import os
import pickle
import logging
import argparse
from typing import Tuple, Optional
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_error

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SchedulerModelTrainer:
    """Entraîneur de modèle ML pour le scheduler"""
    
    def __init__(self, model_type: str = 'random_forest'):
        """
        Args:
            model_type: Type de modèle ('random_forest' ou 'gradient_boosting')
        """
        self.model_type = model_type
        self.model = None
        self.scaler = StandardScaler()
        self.feature_names = [
            'cpu_available_ratio',
            'memory_available_ratio',
            'cpu_load_avg',
            'memory_load_avg',
            'network_latency_normalized',
            'pod_density',
            'pod_cpu_request',
            'pod_memory_request',
            'pod_type_score'
        ]
    
    def prepare_data(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """
        Prépare les données pour l'entraînement.
        
        Args:
            df: DataFrame avec les données brutes
        
        Returns:
            Tuple (X, y) avec les features et les labels
        """
        logger.info("Préparation des données...")
        
        # Sélectionner les features
        feature_cols = [col for col in self.feature_names if col in df.columns]
        
        if not feature_cols:
            raise ValueError("Aucune feature trouvée dans les données")
        
        X = df[feature_cols].values
        
        # Normaliser les features
        X = self.scaler.fit_transform(X)
        
        # Créer les labels : score basé sur la qualité du placement
        # Score plus élevé = meilleur placement
        y = self._create_labels(df)
        
        logger.info(f"Données préparées : {X.shape[0]} échantillons, {X.shape[1]} features")
        
        return X, y
    
    def _create_labels(self, df: pd.DataFrame) -> np.ndarray:
        """
        Crée les labels pour l'entraînement.
        Le label représente la qualité du placement (score de 0 à 1).
        
        Pour un bon placement, on veut :
        - Équilibre de charge optimal (PRIORITÉ ABSOLUE - 60%) : minimise directement l'écart-type futur du cluster
        - CPU bas mais efficace (zone optimale 30-60% pour réduire consommation - 15%)
        - Latence réseau minimale (15%)
        - Mémoire optimisée (moins de charge mémoire - 8%)
        - Ressources disponibles (2%)
        - Surcharge déjà prise en compte dans l'écart-type (0%)
        """
        scores = []
        
        # Calculer la charge moyenne du cluster pour le balance_score
        avg_cpu_load_cluster = df['cpu_load_avg'].mean()
        avg_memory_load_cluster = df['memory_load_avg'].mean()

        for _, row in df.iterrows():
            score = 0.0
            
            cpu_load = row.get('cpu_load_avg', 0.5)
            mem_load = row.get('memory_load_avg', 0.5)
            cpu_ratio = row.get('cpu_available_ratio', 0.5)
            mem_ratio = row.get('memory_available_ratio', 0.5)
            
            # 1. Optimisation CPU (15% - réduit pour donner plus de poids à l'équilibre)
            # Favoriser les nodes avec charge CPU modérée (moins de consommation globale)
            cpu_usage_score = 0.0
            if 0.30 <= cpu_load <= 0.60:
                # Zone optimale : score maximal (CPU bas mais efficace)
                cpu_usage_score = 1.0
            elif cpu_load < 0.30:
                # Très faible utilisation : pénalité modérée
                cpu_usage_score = 0.7 + (cpu_load / 0.30) * 0.3  # 0.7 à 1.0
            else:  # cpu_load > 0.60
                # Utilisation élevée : pénalité forte (consomme trop de CPU)
                cpu_usage_score = max(0.0, 1.0 - (cpu_load - 0.60) * 2.5)  # Décroît rapidement
            
            score += cpu_usage_score * 0.15  # 15% pour l'optimisation CPU (réduit de 20%)
            
            # 2. Latence réseau (15% - réduit pour donner plus de poids à l'équilibre)
            latency = row.get('network_latency_normalized', 0.5)
            # Amplifier l'impact de la latence : très faible latence = score très élevé
            latency_score = (1.0 - latency) ** 1.5  # Fonction exponentielle pour favoriser très faible latence
            score += latency_score * 0.15  # 15% pour la latence (réduit de 20%)
            
            # 3. Optimisation mémoire (8% - réduit pour donner plus de poids à l'équilibre)
            # Moins de charge mémoire = meilleur score
            memory_usage_score = 1.0 - mem_load  # Inverse : moins de charge = meilleur
            score += memory_usage_score * 0.08  # 8% pour la mémoire (réduit de 10%)
            
            # 4. Ressources disponibles (2% - fortement réduit)
            score += (cpu_ratio * 0.01 + mem_ratio * 0.01)  # Total 2% (réduit de 3%)
            
            # 5. Score basé sur l'équilibre de charge (60% - PRIORITÉ ABSOLUE pour minimiser l'écart-type)
            # Note: Le balance_score calculé dans feature_extractor minimise déjà l'écart-type futur
            balance_score = row.get('balance_score', None)
            if balance_score is None:
                # Fallback : calculer approximativement (moins précis que dans feature_extractor)
                # Pour l'entraînement, on utilise la distance à la moyenne comme approximation
                cpu_deviation = abs(cpu_load - avg_cpu_load_cluster)
                mem_deviation = abs(mem_load - avg_memory_load_cluster)
                k_cpu = 25.0  # Facteur augmenté pour CPU (priorité sur l'équilibre CPU)
                k_mem = 25.0  # Facteur pour mémoire
                cpu_balance_score = np.exp(-k_cpu * cpu_deviation) if cpu_deviation > 0 else 1.0
                mem_balance_score = np.exp(-k_mem * mem_deviation) if mem_deviation > 0 else 1.0
                # Poids équilibré (50% CPU, 50% mémoire) pour améliorer les deux équilibres
                balance_score = (cpu_balance_score * 0.5 + mem_balance_score * 0.5)
                balance_score = max(0.0, min(1.0, balance_score))
            
            score += balance_score * 0.60  # 60% pour l'équilibre (augmenté de 45% à 60%)
            
            # 6. Pénalité de surcharge (0% - supprimé, déjà pris en compte dans l'écart-type)
            # Note: La surcharge est déjà prise en compte dans le calcul de l'écart-type
            
            scores.append(max(0.0, min(1.0, score)))
        
        return np.array(scores)
    
    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        test_size: float = 0.2,
        random_state: int = 42
    ) -> dict:
        """
        Entraîne le modèle.
        
        Args:
            X: Features
            y: Labels
            test_size: Proportion des données de test
            random_state: Seed pour la reproductibilité
        
        Returns:
            Dictionnaire avec les métriques d'évaluation
        """
        logger.info(f"Entraînement du modèle {self.model_type}...")
        
        # Séparation train/test
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=random_state
        )
        
        # Créer le modèle
        if self.model_type == 'random_forest':
            self.model = RandomForestRegressor(
                n_estimators=100,
                max_depth=10,
                min_samples_split=5,
                min_samples_leaf=2,
                random_state=random_state,
                n_jobs=-1
            )
        elif self.model_type == 'gradient_boosting':
            self.model = GradientBoostingRegressor(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.1,
                random_state=random_state
            )
        else:
            raise ValueError(f"Type de modèle inconnu : {self.model_type}")
        
        # Entraîner
        self.model.fit(X_train, y_train)
        
        # Évaluer
        train_pred = self.model.predict(X_train)
        test_pred = self.model.predict(X_test)
        
        train_mse = mean_squared_error(y_train, train_pred)
        test_mse = mean_squared_error(y_test, test_pred)
        train_r2 = r2_score(y_train, train_pred)
        test_r2 = r2_score(y_test, test_pred)
        train_mae = mean_absolute_error(y_train, train_pred)
        test_mae = mean_absolute_error(y_test, test_pred)
        
        # Validation croisée
        cv_scores = cross_val_score(self.model, X_train, y_train, cv=5, scoring='r2')
        
        metrics = {
            'train_mse': train_mse,
            'test_mse': test_mse,
            'train_r2': train_r2,
            'test_r2': test_r2,
            'train_mae': train_mae,
            'test_mae': test_mae,
            'cv_r2_mean': cv_scores.mean(),
            'cv_r2_std': cv_scores.std()
        }
        
        logger.info(f"Entraînement terminé")
        logger.info(f"MSE (train/test): {train_mse:.4f} / {test_mse:.4f}")
        logger.info(f"R² (train/test): {train_r2:.4f} / {test_r2:.4f}")
        logger.info(f"MAE (train/test): {train_mae:.4f} / {test_mae:.4f}")
        logger.info(f"R² CV (mean ± std): {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")
        
        # Afficher l'importance des features
        if hasattr(self.model, 'feature_importances_'):
            importances = self.model.feature_importances_
            feature_importance = list(zip(self.feature_names, importances))
            feature_importance.sort(key=lambda x: x[1], reverse=True)
            
            logger.info("\nImportance des features :")
            for feature, importance in feature_importance:
                logger.info(f"  {feature}: {importance:.4f}")
        
        return metrics
    
    def save_model(self, model_path: str, scaler_path: Optional[str] = None):
        """
        Sauvegarde le modèle et le scaler.
        
        Args:
            model_path: Chemin pour sauvegarder le modèle
            scaler_path: Chemin pour sauvegarder le scaler (optionnel)
        """
        if self.model is None:
            raise ValueError("Modèle non entraîné")
        
        # Créer un objet wrapper avec le modèle et le scaler
        model_wrapper = {
            'model': self.model,
            'scaler': self.scaler,
            'feature_names': self.feature_names,
            'model_type': self.model_type,
            'version': '1.0.0'
        }
        
        os.makedirs(os.path.dirname(model_path) if os.path.dirname(model_path) else '.', exist_ok=True)
        
        with open(model_path, 'wb') as f:
            pickle.dump(model_wrapper, f)
        
        logger.info(f"Modèle sauvegardé dans {model_path}")
        
        if scaler_path:
            with open(scaler_path, 'wb') as f:
                pickle.dump(self.scaler, f)
            logger.info(f"Scaler sauvegardé dans {scaler_path}")


def main():
    parser = argparse.ArgumentParser(description='Entraînement du modèle ML pour le scheduler')
    parser.add_argument(
        '--data',
        default='training_data.csv',
        help='Fichier CSV avec les données d\'entraînement'
    )
    parser.add_argument(
        '--output',
        default='scheduler_model.pkl',
        help='Fichier de sortie pour le modèle'
    )
    parser.add_argument(
        '--model-type',
        choices=['random_forest', 'gradient_boosting'],
        default='random_forest',
        help='Type de modèle à entraîner'
    )
    parser.add_argument(
        '--test-size',
        type=float,
        default=0.2,
        help='Proportion des données de test'
    )
    
    args = parser.parse_args()
    
    # Charger les données
    logger.info(f"Chargement des données depuis {args.data}...")
    if not os.path.exists(args.data):
        logger.error(f"Fichier de données non trouvé : {args.data}")
        logger.info("Exécutez d'abord data_collector.py pour générer les données")
        return
    
    df = pd.read_csv(args.data)
    logger.info(f"Données chargées : {len(df)} enregistrements")
    
    # Entraîner le modèle
    trainer = SchedulerModelTrainer(model_type=args.model_type)
    X, y = trainer.prepare_data(df)
    metrics = trainer.train(X, y, test_size=args.test_size)
    
    # Sauvegarder le modèle
    trainer.save_model(args.output)
    
    logger.info("\n" + "="*50)
    logger.info("Entraînement terminé avec succès !")
    logger.info("="*50)
    logger.info(f"\nMétriques finales :")
    logger.info(f"  R² sur test : {metrics['test_r2']:.4f}")
    logger.info(f"  MAE sur test : {metrics['test_mae']:.4f}")
    logger.info(f"\nModèle sauvegardé dans : {args.output}")


if __name__ == '__main__':
    main()


