from __future__ import annotations

import json
import re
from typing import Any

import requests

from app.services.match_log_service import MatchLogService


class MatchAIAnalyzerService:
    """
    Servicio para generar análisis post-partida detallados con IA (Gemini API)
    basándose en el fichero de log de la partida.
    """

    FALLBACK_MODELS = [
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-flash-latest",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash",
        "gemini-1.5-flash-latest",
    ]

    def analyze_match(
        self,
        session: dict[str, Any],
        api_key: str,
    ) -> tuple[str, str]:
        """
        Analiza la partida utilizando el log registrado y la API de Gemini.
        Devuelve una tupla (markdown_analysis, model_used).
        """
        api_key = api_key.strip()
        if not api_key:
            raise ValueError(
                "No se ha configurado la Gemini API Key. "
                "Por favor confígurala en Ajustes."
            )

        # Obtener o generar el log de la partida
        log_service = MatchLogService()
        log_data, formatted_log = log_service.get_match_log(session)

        # Construir el prompt para Gemini
        prompt = self._build_analysis_prompt(log_data, formatted_log)

        # Llamar a Gemini API
        markdown_response, model_used = self._call_gemini_api(prompt, api_key)

        return markdown_response, model_used

    def _build_analysis_prompt(
        self,
        log_data: dict[str, Any],
        formatted_log: str,
    ) -> str:
        metadata = log_data.get("metadata", {})
        user_stats = log_data.get("user_stats", {})
        champ = metadata.get("champion_name", "Campeón")

        ITEM_DICTIONARY = {
            # === CONSUMIBLES / TRINKETS / INICIALES ===
            "1054": "Escudo de Doran (Doran's Shield)",
            "1055": "Espada de Doran (Doran's Blade)",
            "1056": "Anillo de Doran (Doran's Ring)",
            "1082": "Sello Oscuro (The Dark Seal)",
            "1083": "Sacrificio (Cull)",
            "1101": "Brote de Brincamontes (Scorchclaw Pup)",
            "1102": "Brote de Alaplata (Gustwalker Seedling)",
            "1103": "Brote de Pisamusgo (Mosstomper Seedling)",
            "2003": "Poción de salud (Health Potion)",
            "2031": "Poción reutilizable (Refillable Potion)",
            "2055": "Guardián de control (Control Ward)",
            "2138": "Elixir de hierro (Elixir of Iron)",
            "2139": "Elixir de sorbería (Elixir of Sorcery)",
            "2140": "Elixir de cólera (Elixir of Wrath)",
            "3340": "Totem de centinela (Stealth Ward)",
            "3363": "Alteración de visión lejana (Farsight Alteration)",
            "3364": "Lente del oráculo (Oracle Lens)",
            "3865": "Atlas mundial (World Atlas)",
            "3876": "Soporte rúnico (Runic Compass)",
            "3877": "Recompensa del mundo (Bounty of Worlds)",

            # === BOTAS ===
            "1001": "Botas (Boots)",
            "2422": "Botas de Mercurio mágicas (Slightly Magical Footwear)",
            "3005": "Botas de dinamismo (Boots of Dynamism)",
            "3006": "Botas de berserker (Berserker's Greaves)",
            "3009": "Botas de rapidez (Boots of Swiftness)",
            "3020": "Botas del hechicero (Sorcerer's Shoes)",
            "3047": "Placas de acero revestidas (Plated Steelcaps)",
            "3111": "Botas de mercurio (Mercury's Treads)",
            "3158": "Botas jónicas de lucidez (Ionian Boots of Lucidity)",

            # === COMPONENTES BÁSICOS / ÉPICOS ===
            "1011": "Cinturón de gigante (Giant's Belt)",
            "1018": "Capa de agilidad (Cloak of Agility)",
            "1026": "Varita explosiva (Blasting Wand)",
            "1027": "Tomo de amplificación (Amplifying Tome)",
            "1028": "Cristal de rubí (Ruby Crystal)",
            "1029": "Armadura de tela (Cloth Armor)",
            "1031": "Capa de cadenas (Chain Vest)",
            "1033": "Manto de anulación de magia (Null-Magic Mantle)",
            "1035": "Cuchillo de brasa (Emberknife)",
            "1036": "Espada larga (Long Sword)",
            "1037": "Picacha (Pickaxe)",
            "1038": "Espadón (B.F. Sword)",
            "1042": "Daga (Dagger)",
            "1043": "Arco curvo (Recurve Bow)",
            "1052": "Tomo de amplificación (Amplifying Tome)",
            "1057": "Armadura de negrura (Negatron Cloak)",
            "1058": "Vara Innecesariamente Grande (Needlessly Large Rod)",
            "1086": "Honda de explorador (Scout's Slingshot)",
            "2015": "Fragmento de Kircheis (Kircheis Shard)",
            "3012": "Cáliz de la bendición (Chalice of Blessing)",
            "3024": "Brillo (Sheen)",
            "3035": "Último Suspiro (Last Whisper)",
            "3051": "Hacha de Hogar (Zeal)",
            "3057": "Brillo (Sheen)",
            "3066": "Armadura de guardián (Winged Moonplate)",
            "3067": "Gema de la luz (Kindlegem)",
            "3070": "Lágrima de la diosa (Tear of the Goddess)",
            "3076": "Chaleco de zarzas (Bramble Vest)",
            "3082": "Prisión del buscador (Seeker's Armguard)",
            "3086": "Fervor (Zeal)",
            "3105": "Medallón de la cordura (Aegis of the Legion)",
            "3113": "Espejo de cristal de Bandle (Bandle Glass Mirror)",
            "3114": "Idolo prohibido (Forbidden Idol)",
            "3123": "Llamado del verdugo (Executioner's Calling)",
            "3133": "Martillo de guerra de Caulfield (Caulfield's Warhammer)",
            "3134": "Daga de la bruma (Serrated Dirk)",
            "3145": "Alternador Hextech (Hextech Alternator)",
            "3191": "Cronómetro (Stopwatch)",
            "3211": "Hábito del espectro (Spectre's Cowl)",
            "3742": "Coraza del muerto (Dead Man's Plate)",
            "3801": "Capa de fuego solar (Bami's Cinder)",
            "3802": "Capítulo perdido (Lost Chapter)",
            "3916": "Códice diabólico (Fiendish Codex)",
            "6660": "Rectriz (Rectrix)",

            # === OBJETOS LEGENDARIOS (FÍSICOS / CRÍTICOS / ASESINOS) ===
            "2626": "Hidra profana (Profane Hydra)",
            "3004": "Manamúne (Manamune)",
            "3026": "Ángel guardián (Guardian Angel)",
            "3031": "Filo Infinito (Infinity Edge)",
            "3032": "Flechas salvajes de Yun Tal (Yun Tal Wildarrows)",
            "3033": "Recordatorio Mortal (Mortal Reminder)",
            "3036": "Recuerdos de Lord Dominik (Lord Dominik's Regards)",
            "3046": "Bailarín Fantasma (Phantom Dancer)",
            "3071": "Cuchilla Negra (Black Cleaver)",
            "3072": "Sanguinaria (Bloodthirster)",
            "3074": "Hidra voraz (Ravenous Hydra)",
            "3078": "Fuerza de la trinidad (Trinity Force)",
            "3085": "Huracán de Runaan (Runaan's Hurricane)",
            "3094": "Cañón de fuego rápido (Rapid Firecannon)",
            "3139": "Cimitarra mercurial (Mercurial Scimitar)",
            "3142": "Filo de la fantasía de Youmuu (Youmuu's Ghostblade)",
            "3153": "Espada del rey arruinado (Blade of the Ruined King)",
            "3156": "Fauces de Malmortius (Maw of Malmortius)",
            "3161": "Lanza de Shojin (Spear of Shojin)",
            "3179": "Espada de la penumbra (Umbral Glaive)",
            "3181": "Rompecascos (Hullbreaker)",
            "3508": "Saqueador de esencias (Essence Reaver)",
            "6333": "Calibrador de Sterak (Sterak's Gage)",
            "6609": "Espada voltaica (Voltaic Cyclosword)",
            "6616": "Oportunidad (Hubris / Opportunity)",
            "6676": "El Recaudador (The Collector)",
            "6692": "Rencor de Serylda (Serylda's Grudge)",
            "6695": "Prebenda de Axioma (Axiom Arc)",
            "6699": "Terminus (Terminus)",
            "6701": "Final del ingenio (Wit's End)",
            "6706": "Hidra titánica (Titanic Hydra)",

            # === OBJETOS LEGENDARIOS (MAGOS / AP) ===
            "3003": "Abrazo del arcángel (Archangel's Staff)",
            "3027": "Vara de las edades (Rod of Ages)",
            "3041": "Mejai (Mejai's Soulstealer)",
            "3089": "Sombrero mortal de Rabadon (Rabadon's Deathcap)",
            "3100": "Perdición del liche (Lich Bane)",
            "3115": "Diente de Nashor (Nashor's Tooth)",
            "3116": "Cetro de cristal de Rylai (Rylai's Crystal Scepter)",
            "3124": "Guantelete de guinsoo (Guinsoo's Rageblade)",
            "3135": "Bastón del vacío (Void Staff)",
            "3151": "Tormento de Liandry (Liandry's Torment)",
            "3152": "Cinturón cohete Hextech (Hextech Rocketbelt)",
            "3157": "Reloj de arena de Zhonya (Zhonya's Hourglass)",
            "3165": "Morellonomicon (Morellonomicon)",
            "3173": "Impulso cósmico (Cosmic Drive)",
            "3175": "Enfoque al horizonte (Horizon Focus)",
            "4628": "Impulso de las sombras (Shadowflame)",
            "4629": "Cielo desgarrado (Sundered Sky)",
            "4633": "Creador de grietas (Riftmaker)",
            "4636": "Viento de tormenta (Stormsurge)",
            "4645": "Llamasombría (Shadowflame)",
            "6653": "Abrazo de la serafina (Seraph's Embrace)",
            "6655": "Compañero de Luden (Luden's Companion)",
            "6657": "Malignidad (Malignance)",
            "6658": "Criptoflora (Cryptbloom)",

            # === OBJETOS LEGENDARIOS (TANQUES / COLOSOS) ===
            "3065": "Rostro espiritual (Spirit Visage)",
            "3068": "Capa de fuego solar (Sunfire Aegis)",
            "3075": "Malla de espinas (Thornmail)",
            "3083": "Armadura de warmog (Warmog's Armor)",
            "3109": "Promesa del caballero (Knight's Vow)",
            "3110": "Corazón de hielo (Frozen Heart)",
            "3143": "Presagio de Randuin (Randuin's Omen)",
            "3193": "Máscara abisal (Abyssal Mask)",
            "4401": "Desespero encallado (Unending Despair)",
            "6662": "Guantelete de fuego escarchado (Iceborn Gauntlet)",
            "6664": "Rastro de la estela (Trailblazer)",
            "6665": "Jak'Sho, el Proteico (Jak'Sho, The Protean)",
            "6667": "Rookern Kaenic (Kaenic Rookern)",
            "6690": "Orgullo de Mwami (Heartsteel)",

            # === OBJETOS LEGENDARIOS (SOPORTES / UTILIDAD) ===
            "3011": "Renovador de piedra lunar (Moonstone Renewer)",
            "3107": "Redención (Redemption)",
            "3119": "Campana de Mikael (Mikael's Blessing)",
            "3122": "Incensario ardiente (Ardent Censer)",
            "3174": "Mandato imperial (Imperial Mandate)",
            "3190": "Solari de Hierro (Locket of the Iron Solari)",
            "3222": "Crisol de Mikael (Mikael's Crucible)",
            "3504": "Incensario ardiente (Ardent Censer)",
            "4005": "Mandato imperial (Imperial Mandate)",
            "6617": "Eco de Helia (Echoes of Helia)",
            "6620": "Tejesueños (Dream Maker)",
            "6621": "Zaz'Zak (Zaz'Zak's Realmspike)",
            "6622": "Trineo de solsticio (Solstice Sleigh)",
            "6623": "Oposición celestial (Celestial Opposition)",
        }

        # Pre-traducir la lista de objetos finales del usuario
        user_items_raw = user_stats.get("items", [])
        if isinstance(user_items_raw, str):
            try:
                user_items_raw = json.loads(user_items_raw.replace("'", '"'))
            except Exception:
                user_items_raw = []

        user_items_translated = [
            ITEM_DICTIONARY.get(str(i), f"Objeto Oculto ({i})")
            for i in user_items_raw
        ]
        user_items_str = (
            ", ".join(user_items_translated)
            if user_items_translated
            else "Ninguno"
        )

        # TRADUCCIÓN DEL LOG MEDIANTE REGEX
        clean_log = re.sub(r"\bObjeto\s+", "", formatted_log)
        pattern = re.compile(
            r"\b(" + "|".join(ITEM_DICTIONARY.keys()) + r")\b"
        )
        clean_log = pattern.sub(
            lambda m: ITEM_DICTIONARY[m.group(0)], clean_log
        )

        return f"""Eres un Analista Profesional y Coach de Alto Nivel de League of Legends (Challenger).
Tu trabajo es realizar una evaluación táctica post-partida profunda, estructurada y constructiva para el jugador que ha jugado con el campeón '{champ}'.
A continuación tienes el REGISTRO OFICIAL Y COMPLETO DE LOG DE LA PARTIDA (Todos los IDs numéricos han sido sustituidos por sus nombres de texto correspondientes):
text {clean_log} 
INSTRUCCIONES OBLIGATORIAS DE FORMATO Y CONTENIDO:
Responde EXCLUSIVAMENTE en español con formato Markdown bien formateado, limpio y visual.
DEBES incluir de forma clara y detallada las siguientes secciones exactas:


📊 Análisis de Partida con IA: {champ}


🎯 Resumen Ejecutivo
Resultado de la partida: {metadata.get('result')} ({metadata.get('duration_formatted')})
KDA Final: {user_stats.get('kills')}/{user_stats.get('deaths')}/{user_stats.get('assists')} | Farmeo: {user_stats.get('cs_total')} CS ({user_stats.get('cs_per_min')} CS/min)
Calificación Global: [Asigna una nota: S+, S, A+, A, B, C, D]
Resumen táctico general: Breve balance general de la partida y papel del jugador (3-4 frases).


⏳ Rendimiento por Fases de la Partida


🟢 Early Game (0-15 min)
Evaluación de la fase de líneas, tradeos, nivel de farmeo inicial, primeras bajas y control de visión temprano.


🟡 Mid Game (15-25 min)
Evaluación de rotaciones, peleas de equipo/escaramuzas, picos de poder de objetos y presión en el mapa.


🔴 Late Game (25+ min)
Evaluación de teamfights decisivas, ejecución de condiciones de victoria y control de Barón/Dragón Anciano (si la partida duró menos de 25 min, analizar cómo se cerró o se perdió la partida).


🌾 Rendimiento del Farmeo (Farm / CS)
Análisis de la eficiencia de CS por minuto ({user_stats.get('cs_per_min')} CS/min).
Comparativa de farmeo con los rivales directos y ritmo de generación de oro a lo largo del tiempo.
Consejos específicos para mejorar el farmeo en distintas etapas.


⚔️ Valoración de la Build vs Equipo Enemigo
Análisis de los objetos comprados ({user_items_str}) frente a la composición de campeones enemigos (daño físico/mágico, curaciones enemigas, tanques, CC).
Aciertos y fallos en la adaptación de la build (¿Faltó penetración de armadura/mágica, cortacuras, resistencia o protección?).


🤺 Cómo Deberías Haber Enfrentado a Cada Rival (Matchups y Counterplay)
Identifica a cada uno de los campeones del equipo enemigo presentes en la partida/log y desglosa lo siguiente para cada rival:
- **[Nombre del Campeón Enemigo]** - Dificultad del enfrentamiento: [Fácil | Normal | Difícil]
  - **Consejos y Trucos:** Forma óptima de enfrentarte a él en fase de líneas/teamfights jugando con {champ} (tradeos, baits, dodgear habilidades clave).
  - **Counterplay a su Build y Kit:** Cómo adaptarte o contrarrestar los objetos específicos que se hizo y sus habilidades (ej. cuándo comprar cortacuras, resistencia mágica, penetración, etc.).


⏱️ Velocidad de Compra y Tempos de Receso (Recalls)
Evaluación del timing de vuelta a base y compra de ítems principales.
Análizar si las vueltas a base se hicieron aprovechando picos de poder (power spikes) o si se perdió tempo/oleadas innecesariamente.


🎯 Impacto de Asesinatos en Objetivos (Kills vs Objetivos / Kills "Vacías")
Análisis de si las bajas (kills) conseguidas se tradujeron en capturas de dragones, heraldos, torres, barones o ventajas en el mapa.
Identificación y evaluación de "Kills Vacías" (asesinatos logrados que no aportaron ningún objetivo ni ventaja táctica real posterior).


💀 Impacto de Muertes en Objetivos Perdidos
Análisis de cómo las muertes del jugador facilitaron al equipo enemigo la pérdida de torres, dragones, barones o presión de líneas.
Identificación de muertes críticas que cambiaron el tempo de la partida.


💡 Consejos Clave para la Siguiente Partida
Proporciona 3 o 4 consejos accionables, claros y prioritarios para mejorar en las próximas partidas.
"""

    def _get_available_models(self, api_key: str) -> list[str]:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            resp = requests.get(
                url, headers={"Accept": "application/json"}, timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                raw_models = data.get("models", [])
                gen_models = []
                for m in raw_models:
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods:
                        name = (
                            str(m.get("name", ""))
                            .replace("models/", "")
                            .strip()
                        )
                        if name:
                            gen_models.append(name)

                if gen_models:
                    priority_keywords = [
                        "flash-lite",
                        "2.5-flash",
                        "flash-latest",
                        "2.0-flash-lite",
                        "2.0-flash",
                        "flash",
                    ]
                    sorted_models = []
                    for kw in priority_keywords:
                        for m in gen_models:
                            if kw in m and m not in sorted_models:
                                sorted_models.append(m)
                    for m in gen_models:
                        if m not in sorted_models:
                            sorted_models.append(m)
                    return sorted_models
        except Exception:
            pass

        return self.FALLBACK_MODELS

    def _call_gemini_api(self, prompt: str, api_key: str) -> tuple[str, str]:
        models = self._get_available_models(api_key)
        last_error = ""

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
            },
        }

        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=35,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = (
                            candidates[0]
                            .get("content", {})
                            .get("parts", [])
                        )
                        if parts:
                            text = parts[0].get("text", "")
                            if text and len(text.strip()) > 50:
                                return text, model
                elif resp.status_code in (400, 404):
                    last_error = (
                        f"HTTP {resp.status_code} ({model}): {resp.text[:150]}"
                    )
                    continue
                else:
                    resp.raise_for_status()
            except requests.RequestException as err:
                last_error = f"Error ({model}): {err}"
                continue

        raise RuntimeError(
            f"Error al llamar a la API de Gemini para el análisis: {last_error or 'Sin respuesta de la API'}"
        )