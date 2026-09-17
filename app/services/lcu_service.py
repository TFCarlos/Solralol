from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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
        self.session.headers.update({
            "Authorization": f"Basic {auth_b64}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
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
            output = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
            port_match = re.search(r'--app-port=(\d+)', output)
            auth_match = re.search(r'--remoting-auth-token=([\w-]+)', output)
            if port_match and auth_match:
                return ["LeagueClient", "0", port_match.group(1), auth_match.group(1), "https"]
        except Exception:
            pass

        return None

    def is_connected(self) -> bool:
        if not self.port or not self.auth_token:
            if not self.refresh_connection():
                return False
        try:
            resp = self.session.get(f"https://127.0.0.1:{self.port}/lol-summoner/v1/current-summoner", timeout=1.5)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def is_champ_select_active(self) -> bool:
        if not self.is_connected():
            return False
        try:
            resp = self.session.get(f"https://127.0.0.1:{self.port}/lol-champ-select/v1/session", timeout=1.5)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def get_champ_select_session(self) -> dict[str, Any] | None:
        if not self.is_connected():
            return None
        try:
            resp = self.session.get(f"https://127.0.0.1:{self.port}/lol-champ-select/v1/session", timeout=2)
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException:
            pass
        return None

    def import_rune_page(
        self,
        name: str,
        primary_tree: str,
        secondary_tree: str,
        keystone_name: str,
        slots: list[str],
        secondary_slots: list[str],
        shards: list[str],
    ) -> tuple[bool, str]:
        """Aplica la página de runas directamente en el cliente mediante LCU API."""
        if not self.is_connected():
            return False, "Cliente de League of Legends no está conectado."

        primary_style_id = self.RUNE_STYLE_IDS.get(primary_tree.casefold(), 8000)
        sub_style_id = self.RUNE_STYLE_IDS.get(secondary_tree.casefold(), 8400)

        perk_ids: list[int] = []

        # Keystone
        ks_id = self.RUNE_NAME_TO_ID.get(keystone_name.casefold())
        if ks_id:
            perk_ids.append(ks_id)

        # Primary slots
        for slot in slots:
            pid = self.RUNE_NAME_TO_ID.get(slot.casefold())
            if pid and pid not in perk_ids:
                perk_ids.append(pid)

        # Secondary slots
        for sslot in secondary_slots:
            pid = self.RUNE_NAME_TO_ID.get(sslot.casefold())
            if pid and pid not in perk_ids:
                perk_ids.append(pid)

        # Stat shards
        for shard in shards:
            pid = self.RUNE_NAME_TO_ID.get(shard.casefold())
            if pid:
                perk_ids.append(pid)

        if len(perk_ids) < 6:
            return False, f"Solo se pudieron identificar {len(perk_ids)} runas válidas para el cliente."

        payload = {
            "name": f"Solralol - {name}"[:30],
            "primaryStyleId": primary_style_id,
            "subStyleId": sub_style_id,
            "selectedPerkIds": perk_ids,
            "current": True,
        }

        try:
            # Obtener páginas existentes
            resp_pages = self.session.get(f"https://127.0.0.1:{self.port}/lol-perks/v1/pages", timeout=3)
            if resp_pages.status_code == 200:
                pages = resp_pages.json()
                current_page = next((p for p in pages if p.get("current") or p.get("isEditable")), None)
                if current_page and current_page.get("id"):
                    page_id = current_page["id"]
                    # Eliminar página actual si no se puede sobrescribir o actualizar directamente
                    del_resp = self.session.delete(f"https://127.0.0.1:{self.port}/lol-perks/v1/pages/{page_id}", timeout=3)

            post_resp = self.session.post(f"https://127.0.0.1:{self.port}/lol-perks/v1/pages", json=payload, timeout=3)
            if post_resp.status_code in (200, 201):
                return True, "¡Página de runas importada correctamente al cliente!"
            
            # Intentar PUT a currentpage como alternativa
            put_resp = self.session.put(f"https://127.0.0.1:{self.port}/lol-perks/v1/currentpage", json=payload, timeout=3)
            if put_resp.status_code in (200, 201, 204):
                return True, "¡Página de runas importada a la página activa del cliente!"

            return False, f"El cliente respondió con código {post_resp.status_code}."
        except requests.RequestException as exc:
            return False, f"Error de comunicación con LCU: {exc}"

    def import_item_set(self, champion_id: int, champion_name: str, role: str,
                        item_ids: list[str], boots_id: str | None = None) -> tuple[bool, str]:
        """Guarda un conjunto propio sin eliminar los conjuntos del usuario."""
        if champion_id <= 0 or len(item_ids) != 6 or len(set(item_ids)) != 6:
            return False, "Se necesitan un campeón válido y seis objetos distintos."
        ids = item_ids + ([boots_id] if boots_id else [])
        if not all(str(i).isdigit() and int(i) > 0 for i in ids):
            return False, "La build contiene IDs de objetos inválidos."
        if not self.is_connected():
            return False, "Cliente de League of Legends no está conectado."
        try:
            summoner = self.session.get(
                f"https://127.0.0.1:{self.port}/lol-summoner/v1/current-summoner", timeout=3)
            if summoner.status_code != 200:
                return False, "No se pudo identificar al invocador local."
            summoner_id = summoner.json().get("summonerId")
            if not summoner_id:
                return False, "El cliente no publicó el ID del invocador."
            url = f"https://127.0.0.1:{self.port}/lol-item-sets/v1/item-sets/{summoner_id}/sets"
            existing = self.session.get(url, timeout=3)
            if existing.status_code != 200:
                return False, "No se pudieron leer los conjuntos existentes; no se ha sobrescrito nada."
            payload = existing.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("itemSets"), list):
                return False, "Formato de conjuntos inesperado; no se ha sobrescrito nada."
            uid = f"solralol-draft-{champion_id}-{role.casefold()}"
            blocks = [{"type": "Objetos principales (6; última compra alternativa)",
                       "items": [{"id": str(i), "count": 1} for i in item_ids]}]
            if boots_id:
                blocks.append({"type": "Botas recomendadas contra este equipo",
                               "items": [{"id": str(boots_id), "count": 1}]})
            item_set = {
                "uid": uid, "title": f"Solralol - {champion_name} ({role})",
                "type": "custom", "map": "SR", "mode": "CLASSIC",
                "associatedMaps": [11], "associatedChampions": [champion_id],
                "preferredItemSlots": [], "sortrank": 0, "startedFrom": "blank",
                "blocks": blocks,
            }
            payload["itemSets"] = [s for s in payload["itemSets"] if s.get("uid") != uid] + [item_set]
            response = self.session.put(url, json=payload, timeout=3)
            if response.status_code in (200, 201, 204):
                return True, "Build guardada en los conjuntos de objetos del cliente."
            return False, f"El cliente rechazó la build ({response.status_code})."
        except (requests.RequestException, ValueError, TypeError) as exc:
            return False, f"Error al importar la build: {exc}"

    def import_summoner_spells(self, spell1_name: str, spell2_name: str) -> tuple[bool, str]:
        """Aplica los hechizos de invocador en el cliente mediante LCU API."""
        if not self.is_connected():
            return False, "Cliente de League of Legends no está conectado."

        sp1_id = self.SPELL_NAME_TO_ID.get(spell1_name.casefold())
        sp2_id = self.SPELL_NAME_TO_ID.get(spell2_name.casefold())

        if not sp1_id or not sp2_id:
            return False, f"No se reconocieron los hechizos: {spell1_name}, {spell2_name}."

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

