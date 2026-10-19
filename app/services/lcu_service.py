from __future__ import annotations

import base64
import itertools
import logging
import re
import subprocess
import threading
import unicodedata
from pathlib import Path
from typing import Any

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_LOGGER = logging.getLogger(__name__)


class LCUService:
    """Cliente para la League Client Update API (LCU) local."""

    STANDARD_LOCKFILE_PATHS = [
        Path(r"C:\Riot Games\League of Legends\lockfile"),
        Path(r"D:\Riot Games\League of Legends\lockfile"),
        Path(r"E:\Riot Games\League of Legends\lockfile"),
        Path(r"F:\Riot Games\League of Legends\lockfile"),
    ]

    RUNE_NAME_TO_ID = {
        # Keystone & Precision
        "press the attack": 8005,
        "presión enfocada": 8005,
        "lethal tempo": 8008,
        "compás mortal": 8008,
        "fleet footwork": 8021,
        "pies flexibles": 8021,
        "conqueror": 8010,
        "conquistador": 8010,
        "overheal": 9101,
        "supercuración": 9101,
        "triumph": 9111,
        "triunfo": 9111,
        "presence of mind": 8009,
        "claridad mental": 8009,
        "legend: alacrity": 9104,
        "leyenda: presteza": 9104,
        "legend: haste": 9105,
        "leyenda: celeridad": 9105,
        "legend: bloodline": 9103,
        "leyenda: linaje": 9103,
        "coup de grace": 8014,
        "golpe de gracia": 8014,
        "cut down": 8017,
        "derribo": 8017,
        "last stand": 8299,
        "último esfuerzo": 8299,
        # Domination
        "electrocute": 8112,
        "electrocutar": 8112,
        "dark harvest": 8128,
        "cosecha oscura": 8128,
        "hail of blades": 9923,
        "lluvia de cuchillas": 9923,
        "cheap shot": 8126,
        "golpe bajo": 8126,
        "taste of blood": 8139,
        "sabor a sangre": 8139,
        "sudden impact": 8143,
        "impacto repentino": 8143,
        "zombie ward": 8136,
        "guardián zombi": 8136,
        "ghost poro": 8120,
        "poro fantasmal": 8120,
        "eyeball collection": 8138,
        "colección de globos oculares": 8138,
        "treasure hunter": 8135,
        "cazador de tesoros": 8135,
        "relentless hunter": 8105,
        "cazador voraz": 8105,
        "ultimate hunter": 8106,
        "cazador definitivo": 8106,
        # Sorcery
        "summon aery": 8214,
        "invocar a aery": 8214,
        "arcane comet": 8229,
        "cometa arcano": 8229,
        "phase rush": 8230,
        "irrupción de fase": 8230,
        "nullifying orb": 8224,
        "orbe nulo": 8224,
        "manaflow band": 8226,
        "banda de mana": 8226,
        "nimbus cloak": 8275,
        "capa del nimbo": 8275,
        "transcendence": 8210,
        "trascendencia": 8210,
        "celerity": 8234,
        "celeridad": 8234,
        "absolute focus": 8233,
        "concentración absoluta": 8233,
        "scorch": 8237,
        "quemadura": 8237,
        "waterwalking": 8232,
        "caminar sobre el agua": 8232,
        "gathering storm": 8236,
        "tormenta creciente": 8236,
        # Resolve
        "grasp of the undying": 8437,
        "garras del inmortal": 8437,
        "aftershock": 8439,
        "reverberación": 8439,
        "guardian": 8465,
        "guardián": 8465,
        "demolish": 8446,
        "demoler": 8446,
        "font of life": 8463,
        "fuente de vida": 8463,
        "shield bash": 8401,
        "golpe de escudo": 8401,
        "conditioning": 8429,
        "acondicionamiento": 8429,
        "second wind": 8444,
        "segundo aire": 8444,
        "bone plating": 8473,
        "revestimiento de huesos": 8473,
        "overgrowth": 8451,
        "sobrecrecimiento": 8451,
        "revitalize": 8483,
        "revitalizar": 8483,
        "unflinching": 8453,
        "inquebrantable": 8453,
        # Inspiration
        "glacial augment": 8351,
        "aumento glacial": 8351,
        "unsealed spellbook": 8360,
        "libro de hechizos dessellado": 8360,
        "first strike": 8369,
        "primer golpe": 8369,
        "hextech flashtraption": 8306,
        "destello hextech": 8306,
        "magical footwear": 8304,
        "calzado mágico": 8304,
        "triple tonic": 8313,
        "triple tónico": 8313,
        "future's market": 8321,
        "mercado del futuro": 8321,
        "minion dematerializer": 8316,
        "desmaterializador de súbditos": 8316,
        "biscuit delivery": 8345,
        "entrega de galletas": 8345,
        "cosmic insight": 8347,
        "perspicacia cósmica": 8347,
        "approach velocity": 8410,
        "velocidad de aproximación": 8410,
        "time warp tonic": 8352,
        "tónico del tiempo": 8352,
        # Stat Shards
        "adaptive force": 5008,
        "fuerza adaptable": 5008,
        "attack speed": 5005,
        "velocidad de ataque": 5005,
        "ability haste": 5007,
        "velocidad de habilidad": 5007,
        "health scaling": 5001,
        "vida progresiva": 5001,
        "health": 5001,
        "vida": 5001,
        "armor": 5002,
        "armadura": 5002,
        "magic resist": 5003,
        "resistencia mágica": 5003,
        "tenacity and slow resist": 5013,
        "tenacidad y resistencia a ralentización": 5013,
        "movement speed": 5010,
        "velocidad de movimiento": 5010,
    }

    RUNE_STYLE_IDS = {
        "precision": 8000,
        "domination": 8100,
        "sorcery": 8200,
        "resolve": 8400,
        "inspiration": 8300,
    }

    SPELL_NAME_TO_ID = {
        "destello": 4,
        "flash": 4,
        "teleportación": 12,
        "teleport": 12,
        "aplastar": 11,
        "smite": 11,
        "ignición": 14,
        "ignite": 14,
        "curación": 7,
        "heal": 7,
        "barrera": 21,
        "barrier": 21,
        "fantasmal": 6,
        "ghost": 6,
        "extenuación": 3,
        "exhaust": 3,
        "purificar": 1,
        "cleanse": 1,
        "claridad": 13,
    }

    def __init__(self) -> None:
        self.port: int | None = None
        self.auth_token: str | None = None
        self.session = requests.Session()
        self.session.verify = False
        self._rune_import_lock = threading.Lock()

    def refresh_connection(self) -> bool:
        """Intenta localizar el lockfile del cliente de League y configurar la sesión."""
        lock_data = self._find_lockfile()
        if not lock_data:
            self.port = None
            self.auth_token = None
            return False

        _, _, port_str, password, protocol = lock_data
        self.port = int(port_str)
        self.auth_token = password
        auth_bytes = f"riot:{self.auth_token}".encode("utf-8")
        auth_b64 = base64.b64encode(auth_bytes).decode("utf-8")
        self.session.headers.update(
            {
                "Authorization": f"Basic {auth_b64}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        return True

    def _find_lockfile(self) -> list[str] | None:
        # 1. Comprobar rutas estándar de instalación
        for path in self.STANDARD_LOCKFILE_PATHS:
            if path.exists():
                try:
                    content = path.read_text(encoding="utf-8").strip()
                    parts = content.split(":")
                    if len(parts) >= 5:
                        return parts
                except OSError:
                    pass

        # 2. Buscar proceso LeagueClientUx mediante command line (Windows)
        try:
            cmd = "wmic process where name='LeagueClientUx.exe' get commandline"
            output = subprocess.check_output(
                cmd, shell=True, text=True, stderr=subprocess.DEVNULL
            )
            port_match = re.search(r"--app-port=(\d+)", output)
            auth_match = re.search(r"--remoting-auth-token=([\w-]+)", output)
            if port_match and auth_match:
                return [
                    "LeagueClient",
                    "0",
                    port_match.group(1),
                    auth_match.group(1),
                    "https",
                ]
        except Exception:
            pass

        return None

    def is_connected(self) -> bool:
        if not self.port or not self.auth_token:
            if not self.refresh_connection():
                return False
        try:
            resp = self.session.get(
                f"https://127.0.0.1:{self.port}/lol-summoner/v1/current-summoner",
                timeout=1.5,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def is_champ_select_active(self) -> bool:
        if not self.is_connected():
            return False
        try:
            resp = self.session.get(
                f"https://127.0.0.1:{self.port}/lol-champ-select/v1/session",
                timeout=1.5,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def get_champ_select_session(self) -> dict[str, Any] | None:
        if not self.is_connected():
            return None
        try:
            resp = self.session.get(
                f"https://127.0.0.1:{self.port}/lol-champ-select/v1/session", timeout=2
            )
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException:
            pass
        return None

    def import_rune_page(
        self,
        name: str,
        primary_tree: str | int,
        secondary_tree: str | int,
        keystone_name: str | int,
        slots: list[str | int],
        secondary_slots: list[str | int],
        shards: list[str | int],
        *,
        keystone_id: int | None = None,
        slot_ids: list[int] | None = None,
        secondary_slot_ids: list[int] | None = None,
        shard_ids: list[int] | None = None,
    ) -> tuple[bool, str]:
        """Serializa importaciones para evitar que se pisen selecciones simultáneas.

        Parámetros: página recomendada y selecciones opcionales por ID.
        Retorno: resultado confirmado de la importación LCU.
        """
        with self._rune_import_lock:
            return self._import_rune_page_unlocked(
                name,
                primary_tree,
                secondary_tree,
                keystone_name,
                slots,
                secondary_slots,
                shards,
                keystone_id=keystone_id,
                slot_ids=slot_ids,
                secondary_slot_ids=secondary_slot_ids,
                shard_ids=shard_ids,
            )

    def _import_rune_page_unlocked(
        self,
        name: str,
        primary_tree: str | int,
        secondary_tree: str | int,
        keystone_name: str | int,
        slots: list[str | int],
        secondary_slots: list[str | int],
        shards: list[str | int],
        *,
        keystone_id: int | None = None,
        slot_ids: list[int] | None = None,
        secondary_slot_ids: list[int] | None = None,
        shard_ids: list[int] | None = None,
    ) -> tuple[bool, str]:
        """Valida, guarda y comprueba una página completa usando reglas LCU.

        Parámetros: recomendación de runas, incluyendo IDs canónicos opcionales.
        Retorno: éxito confirmado al releer la página o diagnóstico en español.
        """
        if not self.is_connected():
            return False, "Cliente de League of Legends no está conectado."
        try:
            base = f"https://127.0.0.1:{self.port}/lol-perks/v1"
            perks_response = self.session.get(f"{base}/perks", timeout=3)
            styles_response = self.session.get(f"{base}/styles", timeout=3)
            pages_response = self.session.get(f"{base}/pages", timeout=3)
            for endpoint, response in (
                ("perks", perks_response),
                ("styles", styles_response),
                ("pages", pages_response),
            ):
                if response.status_code != 200:
                    _LOGGER.error(
                        "[LCU][Runas] GET %s falló: HTTP %s; detalle=%s",
                        endpoint,
                        response.status_code,
                        response.text[:400],
                    )
                    return (
                        False,
                        f"No se pudieron leer las definiciones de runas ({response.status_code}).",
                    )
            perks = perks_response.json()
            styles = styles_response.json()
            pages = pages_response.json()
            if not all(isinstance(value, list) for value in (perks, styles, pages)):
                return (
                    False,
                    "El cliente devolvió definiciones de runas con formato no válido.",
                )
            perks_by_id = {
                int(item["id"]): item
                for item in perks
                if isinstance(item, dict) and str(item.get("id", "")).isdigit()
            }
            styles_by_id = {
                int(item["id"]): item
                for item in styles
                if isinstance(item, dict) and str(item.get("id", "")).isdigit()
            }
            primary_style_id = self._resolve_rune_style(primary_tree, styles_by_id)
            secondary_style_id = self._resolve_rune_style(secondary_tree, styles_by_id)
            if primary_style_id is None or secondary_style_id is None:
                return (
                    False,
                    "El árbol principal o secundario no existe en este cliente.",
                )

            raw_perks: list[str | int] = [
                keystone_id if keystone_id is not None else keystone_name,
                *(slot_ids if slot_ids else slots),
                *(secondary_slot_ids if secondary_slot_ids else secondary_slots),
                *(shard_ids if shard_ids else shards),
            ]
            perk_ids = [
                self._resolve_rune_id(value, perks_by_id) for value in raw_perks
            ]
            if any(value is None for value in perk_ids):
                missing = [
                    str(value)
                    for value, resolved in zip(raw_perks, perk_ids, strict=True)
                    if resolved is None
                ]
                return (
                    False,
                    f"No se reconocieron estas runas recomendadas: {', '.join(missing)}.",
                )
            ids = [int(value) for value in perk_ids if value is not None]
            ids, order_error = self._order_rune_selection(
                primary_style_id,
                secondary_style_id,
                ids,
                styles_by_id,
            )
            if order_error:
                _LOGGER.warning(
                    "[LCU][Runas] No se pudo ordenar la selección en filas LCU: %s; IDs=%s",
                    order_error,
                    ids,
                )
                return False, order_error
            _LOGGER.debug(
                "[LCU][Runas] Recomendación recibida: primaria=%s secundaria=%s "
                "keystone=%s primarias=%s secundarias=%s fragmentos=%s; "
                "IDs_normalizados=%s",
                primary_tree,
                secondary_tree,
                keystone_name,
                slots,
                secondary_slots,
                shards,
                ids,
            )
            error = self._validate_rune_selection(
                primary_style_id,
                secondary_style_id,
                ids,
                perks_by_id,
                styles_by_id,
            )
            if error:
                _LOGGER.warning(
                    "[LCU][Runas] Validación rechazada: %s; IDs=%s", error, ids
                )
                return False, error

            page_name = self._managed_rune_page_name(name)
            payload = {
                "name": page_name,
                "primaryStyleId": primary_style_id,
                "subStyleId": secondary_style_id,
                "selectedPerkIds": ids,
                "current": True,
            }
            _LOGGER.debug("[LCU][Runas] Payload validado: %s", payload)
            managed = [
                page
                for page in pages
                if isinstance(page, dict)
                and str(page.get("name", "")).casefold().startswith("solralol")
                and page.get("isEditable")
                and page.get("id") is not None
            ]
            existing = self._seleccionar_pagina_runa(managed, pages, name)
            huella_paginas = tuple(
                (str(page.get("id", "")), str(page.get("name", "")))
                for page in pages
                if isinstance(page, dict)
            )
            if (
                existing is None
                and getattr(self, "_rune_capacity_full_fingerprint", None)
                == huella_paginas
            ):
                return (
                    False,
                    "El cliente alcanzó el límite de páginas y no hay una página editable disponible.",
                )
            if existing and existing.get("id") is not None:
                page_id = existing["id"]
                response = self.session.put(
                    f"{base}/pages/{page_id}", json=payload, timeout=3
                )
                accion = "PUT"
            elif existing:
                return (
                    False,
                    "La página existente no incluye un identificador editable.",
                )
            else:
                response = self.session.post(f"{base}/pages", json=payload, timeout=3)
                accion = "POST"
            _LOGGER.info(
                "[LCU][Runas] %s /pages respondió HTTP %s; nombre=%s",
                accion,
                response.status_code,
                page_name,
            )
            if response.status_code not in (200, 201, 204):
                _LOGGER.error(
                    "[LCU][Runas] Escritura fallida: HTTP %s; detalle=%s",
                    response.status_code,
                    response.text[:500],
                )
                cuerpo = {}
                try:
                    cuerpo = response.json()
                except (ValueError, TypeError):
                    pass
                mensaje_lcu = (
                    str(cuerpo.get("message", "")) if isinstance(cuerpo, dict) else ""
                )
                if accion == "PUT" and response.status_code == 404:
                    refresh = self.session.get(f"{base}/pages", timeout=3)
                    actualizadas = refresh.json() if refresh.status_code == 200 else []
                    self._rune_capacity_full_fingerprint = tuple(
                        (str(page.get("id", "")), str(page.get("name", "")))
                        for page in actualizadas
                        if isinstance(page, dict)
                    )
                    administradas_actualizadas = [
                        page
                        for page in actualizadas
                        if isinstance(page, dict)
                        and str(page.get("name", "")).casefold().startswith("solralol")
                        and page.get("isEditable")
                        and page.get("id") is not None
                    ]
                    destino = self._seleccionar_pagina_runa(
                        administradas_actualizadas, actualizadas, name
                    )
                    if destino is None:
                        return (
                            False,
                            "La página elegida ya no existe y no hay otra editable.",
                        )
                    response = self.session.put(
                        f"{base}/pages/{destino['id']}", json=payload, timeout=3
                    )
                    existing = destino
                if (
                    accion == "POST"
                    and response.status_code == 400
                    and "max pages reached" in mensaje_lcu.casefold()
                ):
                    refresh = self.session.get(f"{base}/pages", timeout=3)
                    actualizadas = refresh.json() if refresh.status_code == 200 else []
                    self._rune_capacity_full_fingerprint = tuple(
                        (str(page.get("id", "")), str(page.get("name", "")))
                        for page in actualizadas
                        if isinstance(page, dict)
                    )
                    administradas_actualizadas = [
                        page
                        for page in actualizadas
                        if isinstance(page, dict)
                        and str(page.get("name", "")).casefold().startswith("solralol")
                        and page.get("isEditable")
                        and page.get("id") is not None
                    ]
                    reutilizable = self._seleccionar_pagina_runa(
                        administradas_actualizadas, actualizadas, name
                    )
                    if reutilizable is not None:
                        response = self.session.put(
                            f"{base}/pages/{reutilizable['id']}",
                            json=payload,
                            timeout=3,
                        )
                        accion = "PUT"
                        if response.status_code in (200, 201, 204):
                            _LOGGER.info(
                                "[LCU][Runas] Límite alcanzado; se actualiza la página "
                                "administrada %s (id=%s)",
                                reutilizable.get("name", ""),
                                reutilizable["id"],
                            )
                        else:
                            return (
                                False,
                                "Se alcanzó el límite y la página SOLRALOL editable "
                                "no pudo actualizarse. No se modificaron otras páginas.",
                            )
                    else:
                        mensaje_capacidad = (
                            "El cliente alcanzó el límite de páginas de runas. "
                            "No hay una página editable que Solralol pueda reutilizar."
                        )
                        return False, mensaje_capacidad
                elif response.status_code not in (200, 201, 204):
                    return (
                        False,
                        f"El cliente rechazó la página de runas (HTTP {response.status_code}): {mensaje_lcu or response.text[:180]}",
                    )

            verify_response = self.session.get(f"{base}/pages", timeout=3)
            if verify_response.status_code != 200:
                return (
                    False,
                    "La página se envió, pero no se pudo verificar en el cliente.",
                )
            saved_pages = verify_response.json()
            saved = next(
                (
                    page
                    for page in saved_pages
                    if isinstance(page, dict) and page.get("name") == page_name
                ),
                None,
            )
            if not saved or not self._same_rune_page(saved, payload):
                _LOGGER.error(
                    "[LCU][Runas] Lectura posterior discrepante: solicitado=%s guardado=%s",
                    payload,
                    self._safe_rune_page(saved),
                )
                return (
                    False,
                    "El cliente guardó una configuración distinta; revisa la página de runas.",
                )
            _LOGGER.info(
                "[LCU][Runas] Página confirmada tras lectura: %s",
                self._safe_rune_page(saved),
            )
            accion_confirmada = "actualizada" if accion == "PUT" else "creada"
            return (
                True,
                f"¡Página SOLRALOL {accion_confirmada} y verificada: {page_name}!",
            )
        except requests.RequestException as exc:
            return False, f"Error de comunicación con LCU: {exc}"
        except (KeyError, TypeError, ValueError):
            _LOGGER.exception("[LCU][Runas] Respuesta o definición inválida")
            return False, "El cliente devolvió datos de runas incompletos o no válidos."

    @classmethod
    def _seleccionar_pagina_runa(
        cls,
        paginas_solralol: list[dict[str, Any]],
        paginas: list[dict[str, Any]],
        nombre_recomendacion: str,
    ) -> dict[str, Any] | None:
        """Elige una página Solralol compatible o la última página editable.

        Parámetros: páginas gestionadas, colección LCU ordenada y nombre recomendado.
        Retorno: página editable elegida o None si no hay ninguna.
        """
        ranura = cls._rune_page_slot(nombre_recomendacion)
        if paginas_solralol:
            if ranura is not None:
                coincidente = next(
                    (
                        pagina
                        for pagina in paginas_solralol
                        if cls._rune_page_slot(str(pagina.get("name", ""))) == ranura
                    ),
                    None,
                )
                if coincidente is not None:
                    return coincidente
            return paginas_solralol[0]
        editables = [
            pagina
            for pagina in paginas
            if isinstance(pagina, dict)
            and pagina.get("isEditable")
            and pagina.get("id") is not None
        ]
        return editables[-1] if editables else None

    @staticmethod
    def _rune_page_slot(nombre: str) -> int | None:
        """Obtiene la ranura 1 o 2 de un nombre en inglés o español.

        Parámetros: nombre de campeón o página LCU.
        Retorno: número de ranura o None cuando no está indicado.
        """
        coincidencia = re.search(r"(?:page|página)\s*([12])\b", nombre, re.IGNORECASE)
        return int(coincidencia.group(1)) if coincidencia else None

    @classmethod
    def _managed_rune_page_name(cls, nombre: str) -> str:
        """Normaliza el nombre gestionado y conserva el número de página.

        Parámetros: nombre recomendado, posiblemente con número de página.
        Retorno: nombre con prefijo Solralol y ranura en formato Page N.
        """
        texto = str(nombre or "").strip()
        ranura = cls._rune_page_slot(texto)
        campeon = re.sub(
            r"\s+(?:page|página)\s*[12]\b", "", texto, flags=re.IGNORECASE
        ).strip()
        sufijo = f" - Page {ranura}" if ranura is not None else ""
        prefijo = "Solralol - "
        limite_campeon = max(1, 30 - len(prefijo) - len(sufijo))
        return f"{prefijo}{campeon[:limite_campeon].rstrip()}{sufijo}"

    @staticmethod
    def _normalize_rune_text(value: str) -> str:
        """Normaliza nombres de runas para comparar nombres traducidos.

        Parámetros: nombre o identificador textual recibido.
        Retorno: texto en minúsculas sin marcas diacríticas ni espacios externos.
        """
        normalizado = unicodedata.normalize("NFKD", value.casefold().strip())
        return "".join(
            caracter for caracter in normalizado if not unicodedata.combining(caracter)
        )

    @classmethod
    def _resolve_rune_id(
        cls, value: str | int, perks_by_id: dict[int, dict[str, Any]]
    ) -> int | None:
        """Resuelve una runa contra las definiciones vigentes del cliente.

        Parámetros: ID o nombre recomendado y definiciones LCU por ID.
        Retorno: ID vigente o None si no se reconoce.
        """
        if isinstance(value, int) or str(value).strip().isdigit():
            perk_id = int(value)
            return perk_id if perk_id in perks_by_id else None
        sought = cls._normalize_rune_text(str(value))
        for perk_id, definition in perks_by_id.items():
            if cls._normalize_rune_text(str(definition.get("name", ""))) == sought:
                return perk_id
        alias = cls.RUNE_NAME_TO_ID.get(str(value).casefold().strip())
        return alias if alias in perks_by_id else None

    @staticmethod
    def _resolve_rune_style(
        value: str | int, styles_by_id: dict[int, dict[str, Any]]
    ) -> int | None:
        """Resuelve el árbol recomendado contra estilos activos del cliente.

        Parámetros: ID o nombre del árbol y estilos LCU por ID.
        Retorno: ID del estilo vigente o None si no existe.
        """
        if isinstance(value, int) or str(value).strip().isdigit():
            style_id = int(value)
            return style_id if style_id in styles_by_id else None
        sought = LCUService._normalize_rune_text(str(value))
        for style_id, definition in styles_by_id.items():
            if sought in {
                LCUService._normalize_rune_text(str(definition.get("name", ""))),
                LCUService._normalize_rune_text(str(definition.get("idName", ""))),
            }:
                return style_id
        aliases = {
            "precision": 8000,
            "domination": 8100,
            "sorcery": 8200,
            "inspiration": 8300,
            "resolve": 8400,
            "precision española": 8000,
            "dominacion": 8100,
            "brujeria": 8200,
            "inspiracion": 8300,
            "valor": 8400,
        }
        style_id = aliases.get(sought)
        return style_id if style_id in styles_by_id else None

    @staticmethod
    def _validate_rune_selection(
        primary_style_id: int,
        secondary_style_id: int,
        perk_ids: list[int],
        perks_by_id: dict[int, dict[str, Any]],
        styles_by_id: dict[int, dict[str, Any]],
    ) -> str:
        """Comprueba orden, árboles, filas, shards y unicidad con reglas LCU.

        Parámetros: IDs ordenados, definiciones de perks y estilos vigentes.
        Retorno: motivo de rechazo o cadena vacía si la página es válida.
        """
        if len(perk_ids) != 9:
            return f"La página requiere 9 selecciones y recibió {len(perk_ids)}."
        if len(set(perk_ids[:6])) != 6:
            return (
                "La recomendación contiene runas principales o secundarias duplicadas."
            )
        primary = styles_by_id.get(primary_style_id)
        secondary = styles_by_id.get(secondary_style_id)
        if not primary or not secondary or primary_style_id == secondary_style_id:
            return "Los árboles principal y secundario no son válidos o son iguales."
        if secondary_style_id not in primary.get("allowedSubStyles", []):
            return "El árbol secundario no está permitido por el árbol principal."
        primary_slots = primary.get("slots")
        secondary_slots = secondary.get("slots")
        if not isinstance(primary_slots, list) or len(primary_slots) < 7:
            return "El cliente no proporcionó las filas completas del árbol principal."
        if not isinstance(secondary_slots, list) or len(secondary_slots) < 4:
            return "El cliente no proporcionó las filas completas del árbol secundario."
        if perk_ids[0] not in primary_slots[0].get("perks", []):
            return "La primera selección no es una keystone del árbol principal."
        for indice in range(1, 4):
            if perk_ids[indice] not in primary_slots[indice].get("perks", []):
                return f"La runa principal {indice} no pertenece a su fila correspondiente."
        filas_secundarias: list[int] = []
        for perk_id in perk_ids[4:6]:
            fila = next(
                (
                    indice
                    for indice in range(1, 4)
                    if perk_id in secondary_slots[indice].get("perks", [])
                ),
                None,
            )
            if fila is None:
                return "Una runa secundaria no pertenece a una fila menor del árbol elegido."
            filas_secundarias.append(fila)
        if filas_secundarias[0] == filas_secundarias[1]:
            return "Las dos runas secundarias deben ocupar filas distintas."
        for indice, perk_id in enumerate(perk_ids[6:9], start=4):
            if perk_id not in primary_slots[indice].get("perks", []):
                return f"El fragmento de estadísticas {indice - 3} no corresponde a su fila."
        for indice, perk_id in enumerate(perk_ids):
            definition = perks_by_id.get(perk_id)
            if not definition:
                return f"El ID de runa {perk_id} no existe en esta versión del cliente."
            if indice < 4 and int(definition.get("styleId", -1)) != primary_style_id:
                return f"La runa {perk_id} no pertenece al árbol principal."
            if (
                4 <= indice < 6
                and int(definition.get("styleId", -1)) != secondary_style_id
            ):
                return f"La runa {perk_id} no pertenece al árbol secundario."
        return ""

    @staticmethod
    def _order_rune_selection(
        primary_style_id: int,
        secondary_style_id: int,
        perk_ids: list[int],
        styles_by_id: dict[int, dict[str, Any]],
    ) -> tuple[list[int], str]:
        """Ordena las selecciones según las filas activas expuestas por LCU.

        Parámetros: árboles elegidos, nueve IDs recomendados y estilos del cliente.
        Retorno: IDs en orden LCU y error vacío, o IDs originales con diagnóstico.
        """
        if len(perk_ids) != 9:
            return (
                perk_ids,
                f"La página requiere 9 selecciones y recibió {len(perk_ids)}.",
            )
        primary = styles_by_id.get(primary_style_id, {}).get("slots", [])
        secondary = styles_by_id.get(secondary_style_id, {}).get("slots", [])
        if len(primary) < 7 or len(secondary) < 4:
            return (
                perk_ids,
                "El cliente no proporcionó filas suficientes para ordenar la página.",
            )
        menores_primarias = list(perk_ids[1:4])
        ordenadas_primarias: list[int] = []
        for row_index in range(1, 4):
            elegibles = [
                perk_id
                for perk_id in menores_primarias
                if perk_id in primary[row_index].get("perks", [])
            ]
            if len(elegibles) != 1:
                return perk_ids, (
                    f"La recomendación tiene {len(elegibles)} runas para la fila "
                    f"principal {row_index}."
                )
            seleccionado = elegibles[0]
            ordenadas_primarias.append(seleccionado)
            menores_primarias.remove(seleccionado)
        secundarias: list[tuple[int, int]] = []
        for perk_id in perk_ids[4:6]:
            rows = [
                row_index
                for row_index in range(1, 4)
                if perk_id in secondary[row_index].get("perks", [])
            ]
            if len(rows) != 1:
                return perk_ids, (
                    f"La runa secundaria {perk_id} no pertenece a una fila menor "
                    "única del árbol seleccionado."
                )
            secundarias.append((rows[0], perk_id))
        if secundarias[0][0] == secundarias[1][0]:
            return (
                perk_ids,
                "Las dos runas secundarias deben proceder de filas distintas.",
            )
        secundarias.sort()
        fragmentos: tuple[int, ...] | None = None
        for permutacion in itertools.permutations(perk_ids[6:9]):
            if all(
                perk_id in primary[row_index].get("perks", [])
                for row_index, perk_id in zip(range(4, 7), permutacion, strict=True)
            ):
                fragmentos = permutacion
                break
        if fragmentos is None:
            return (
                perk_ids,
                "Los tres fragmentos no corresponden a sus filas de estadísticas.",
            )
        return (
            [
                perk_ids[0],
                *ordenadas_primarias,
                *(perk_id for _, perk_id in secundarias),
                *fragmentos,
            ],
            "",
        )

    @staticmethod
    def _same_rune_page(saved: dict[str, Any], payload: dict[str, Any]) -> bool:
        """Compara selecciones guardadas con la configuración solicitada.

        Parámetros: página releída y carga útil esperada.
        Retorno: True cuando árboles e IDs coinciden exactamente.
        """
        return (
            saved.get("primaryStyleId") == payload["primaryStyleId"]
            and saved.get("subStyleId") == payload["subStyleId"]
            and saved.get("selectedPerkIds") == payload["selectedPerkIds"]
        )

    @staticmethod
    def _safe_rune_page(page: dict[str, Any] | None) -> dict[str, Any] | None:
        """Limita el diagnóstico a nombre, árboles e IDs, omitiendo datos privados.

        Parámetros: página LCU opcional.
        Retorno: resumen seguro o None si no existe página.
        """
        if page is None:
            return None
        return {
            "name": page.get("name"),
            "primaryStyleId": page.get("primaryStyleId"),
            "subStyleId": page.get("subStyleId"),
            "selectedPerkIds": page.get("selectedPerkIds"),
        }

    ITEM_SET_TITLE_PREFIX = "Solralol - "
    ITEM_SET_UID_PREFIX = "solralol-"
    # Compañeros de jungla (hueco de starter): se compran en lugar del objeto
    # inicial de línea y solo uno termina completando la misión de jungla.
    JUNGLE_STARTER_IDS = ("1101", "1102", "1103")
    JUNGLE_ROLES = frozenset({"jungle", "jungla", "jgl"})

    @staticmethod
    def _item_set_container(
        payload: Any,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
        """Normaliza la lectura de conjuntos: contenedor {itemSets} o lista suelta.

        El cliente devuelve un objeto ``{accountId, itemSets, timestamp}``, pero
        algunas versiones responden con la lista de conjuntos directamente; ambas
        formas se aceptan para no perder los conjuntos del jugador.
        """
        if isinstance(payload, dict) and isinstance(payload.get("itemSets"), list):
            return [s for s in payload["itemSets"] if isinstance(s, dict)], payload
        if isinstance(payload, list):
            return [s for s in payload if isinstance(s, dict)], {}
        return None

    @staticmethod
    def _situational_blocks(
        situational: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Convierte los grupos situacionales del campeón en bloques de la página.

        Cada grupo se traduce a un bloque con el mismo nombre que muestra la
        tarjeta SITUACIONALES del analizador local. Un grupo sin nombre, sin
        objetos o con IDs inválidos se omite en lugar de romper la importación.
        """
        blocks: list[dict[str, Any]] = []
        for group in situational or []:
            if not isinstance(group, dict):
                continue
            label = str(group.get("label") or group.get("key") or "").strip()
            raw_items = group.get("items")
            if not label or not isinstance(raw_items, list):
                continue
            ids: list[str] = []
            for entry in raw_items:
                item_id = (
                    str(entry.get("id", "")) if isinstance(entry, dict) else str(entry)
                )
                if item_id.isdigit() and int(item_id) > 0 and item_id not in ids:
                    ids.append(item_id)
            if ids:
                blocks.append(
                    {"type": label, "items": [{"id": i, "count": 1} for i in ids]}
                )
        return blocks

    def import_item_set(
        self,
        champion_id: int,
        champion_name: str,
        role: str,
        item_ids: list[str],
        boots_id: str | None = None,
        situational: list[dict[str, Any]] | None = None,
    ) -> tuple[bool, str]:
        """Crea la página general «Solralol - <Campeón> Build» sin tocar los conjuntos del usuario.

        La página es general (sin campeón asociado), así que el cliente la ofrece en
        la tienda para cualquier campeón. Cada importación sustituye la página
        anterior de Solralol en lugar de acumular copias.

        ``situational`` son los grupos situacionales del campeón (Corta curas,
        Tanque / Resistencias, Asesino / Daño explosivo, Utilidad y Defensa) tal
        como los expone ``DraftAnalyzerService.get_situational_items``; cada grupo
        se añade como un bloque adicional después de los objetos principales y las
        botas. Los grupos vacíos o con IDs inválidos se omiten.

        Si ``role`` es jungla, el primer bloque (el hueco de starter) reúne los
        tres compañeros de jungla (``JUNGLE_STARTER_IDS``) para que la partida
        empiece eligiendo uno; el resto de líneas no llevan bloque starter.
        """
        name = str(champion_name or "").strip()
        if champion_id <= 0 or not name:
            return False, "Se necesita un campeón válido para crear la página de build."
        ids_principales = [str(item).strip() for item in item_ids]
        if not 1 <= len(ids_principales) <= 6:
            return (
                False,
                "La build necesita entre uno y seis objetos principales válidos.",
            )
        if len(set(ids_principales)) != len(ids_principales):
            return False, "La build contiene objetos principales duplicados."
        starter_ids = (
            list(self.JUNGLE_STARTER_IDS)
            if str(role or "").strip().casefold() in self.JUNGLE_ROLES
            else []
        )
        ids = ids_principales + ([str(boots_id)] if boots_id else []) + starter_ids
        if not all(i.isdigit() and int(i) > 0 for i in ids):
            return False, "La build contiene IDs de objetos inválidos."
        if not self.is_connected():
            return False, "Cliente de League of Legends no está conectado."
        try:
            summoner = self.session.get(
                f"https://127.0.0.1:{self.port}/lol-summoner/v1/current-summoner",
                timeout=3,
            )
            if summoner.status_code != 200:
                return False, "No se pudo identificar al invocador local."
            summoner_id = summoner.json().get("summonerId")
            if not summoner_id:
                return False, "El cliente no publicó el ID del invocador."
            url = f"https://127.0.0.1:{self.port}/lol-item-sets/v1/item-sets/{summoner_id}/sets"
            existing = self.session.get(url, timeout=3)
            if existing.status_code != 200:
                return (
                    False,
                    "No se pudieron leer los conjuntos existentes; no se ha sobrescrito nada.",
                )
            container = self._item_set_container(existing.json())
            if container is None:
                return (
                    False,
                    "Formato de conjuntos inesperado; no se ha sobrescrito nada.",
                )
            current_sets, wrapper = container

            title = f"{self.ITEM_SET_TITLE_PREFIX}{name} Build"
            uid_role = str(role or "").strip().casefold()
            uid = f"{self.ITEM_SET_UID_PREFIX}build-{champion_id}" + (
                f"-{uid_role}" if uid_role else ""
            )
            blocks: list[dict[str, Any]] = []
            if starter_ids:
                # En jungla el hueco de starter lo ocupan los tres compañeros.
                blocks.append(
                    {
                        "type": "Objetos iniciales (starter): elige un compañero de jungla",
                        "items": [{"id": str(i), "count": 1} for i in starter_ids],
                    }
                )
            blocks.append(
                {
                    "type": f"Objetos principales ({len(ids_principales)})",
                    "items": [{"id": i, "count": 1} for i in ids_principales],
                }
            )
            if boots_id:
                blocks.append(
                    {
                        "type": "Botas recomendadas contra este equipo",
                        "items": [{"id": str(boots_id), "count": 1}],
                    }
                )
            situational_blocks = self._situational_blocks(situational)
            blocks.extend(situational_blocks)
            item_set = {
                "uid": uid,
                "title": title,
                "type": "custom",
                "map": "any",
                "mode": "any",
                "associatedMaps": [11, 12],
                "associatedChampions": [],
                "preferredItemSlots": [],
                "sortrank": 0,
                "startedFrom": "blank",
                "blocks": blocks,
            }
            # Página general única: la anterior de Solralol se reemplaza, la del
            # jugador se conserva intacta.
            kept = [
                s
                for s in current_sets
                if not str(s.get("uid", "")).startswith(self.ITEM_SET_UID_PREFIX)
            ]
            payload = dict(wrapper)
            payload["itemSets"] = kept + [item_set]
            payload.setdefault("accountId", 0)
            payload.setdefault("timestamp", 0)
            response = self.session.put(url, json=payload, timeout=3)
            if response.status_code in (200, 201, 204):
                extra = (
                    f" Incluye {len(situational_blocks)} bloques de objetos situacionales."
                    if situational_blocks
                    else ""
                )
                if starter_ids:
                    extra += (
                        " El bloque inicial ocupa el hueco de starter con los "
                        "3 compañeros de jungla."
                    )
                return True, (
                    f"Página general «{title}» creada en el cliente "
                    f"(disponible para cualquier campeón).{extra}"
                )
            return False, f"El cliente rechazó la build ({response.status_code})."
        except (requests.RequestException, ValueError, TypeError) as exc:
            return False, f"Error al importar la build: {exc}"

    def import_summoner_spells(
        self, spell1_name: str, spell2_name: str
    ) -> tuple[bool, str]:
        """Aplica los hechizos de invocador en el cliente mediante LCU API."""
        if not self.is_connected():
            return False, "Cliente de League of Legends no está conectado."

        sp1_id = self.SPELL_NAME_TO_ID.get(spell1_name.casefold())
        sp2_id = self.SPELL_NAME_TO_ID.get(spell2_name.casefold())

        if not sp1_id or not sp2_id:
            return (
                False,
                f"No se reconocieron los hechizos: {spell1_name}, {spell2_name}.",
            )

        try:
            payload = {
                "spell1Id": sp1_id,
                "spell2Id": sp2_id,
            }
            resp = self.session.patch(
                f"https://127.0.0.1:{self.port}/lol-champ-select/v1/session/my-selection",
                json=payload,
                timeout=3,
            )
            if resp.status_code in (200, 204):
                return True, "¡Hechizos de invocador aplicados correctamente!"
            return False, f"Error del cliente al cambiar hechizos ({resp.status_code})."
        except requests.RequestException as exc:
            return False, f"Error de comunicación con LCU: {exc}"
