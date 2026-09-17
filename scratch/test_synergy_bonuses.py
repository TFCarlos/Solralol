import sys
import os
sys.path.insert(0, os.path.abspath("."))

from app.services.synergy_recommendation_service import SynergyRecommendationService

service = SynergyRecommendationService()

test_profile = {
    "items": ["Cuchilla Negra", "Baile de la Muerte"],
    "power_curve_and_scaling": {
        "power_spike_items": ["Fuerza de Trinidad"]
    },
    "most_played_build": ["Cuchilla Negra", "Fuerza de Trinidad", "Calibrador de Sterak"],
    "full_build": ["Cuchilla Negra", "Fuerza de Trinidad", "Calibrador de Sterak", "Baile de la Muerte", "Firmamento Desgarrado"],
    "situational_items": {
        "anti_tank": ["Malla de espinas", "Verdugo de Krakens"],
        "defensive": ["Reloj de arena de Zhonya"]
    }
}

test_items = {
    "3071": {
        "name": "Cuchilla Negra",
        "tier": "Legendary",
        "gold": {"purchasable": True, "total": 3000},
        "intended_classes": ["Bruiser"]
    },
    "3078": {
        "name": "Fuerza de Trinidad",
        "tier": "Legendary",
        "gold": {"purchasable": True, "total": 3333},
        "intended_classes": ["Bruiser"]
    },
    "3053": {
        "name": "Calibrador de Sterak",
        "tier": "Legendary",
        "gold": {"purchasable": True, "total": 3200},
        "intended_classes": ["Bruiser"]
    },
    "3075": {
        "name": "Malla de Espinas",
        "tier": "Legendary",
        "gold": {"purchasable": True, "total": 2700},
        "intended_classes": ["Tank"]
    }
}

recs = service.rank_items(
    champion_profile=test_profile,
    style_key="Diver",
    items=test_items,
    threats=[]
)

print("--- Synergy Recommendation Output ---")
for rec in recs:
    print(f"Item: {rec.name} | Score: {rec.score} | Reasons: {rec.reasons}")

