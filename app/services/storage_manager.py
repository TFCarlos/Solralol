"""Central persistent storage paths, safe writes, and verified root migration."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
import weakref
from typing import Any, Iterator

_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: weakref.WeakValueDictionary[str, threading.RLock] = weakref.WeakValueDictionary()
_STORAGE_ROOT_MARKER = ".solralol-storage.json"
_TRANSIENT_REPLACE_RETRIES = 6
_FILE_LOCK_LOCAL = threading.local()


class StorageWriteError(OSError):
    """Safe-to-classify failure while committing persistent user data."""


def bootstrap_config_path() -> Path:
    """Return the small OS-level pointer that locates the active data root."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "Solralol" / "storage.json"


def _path_thread_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(str(path.resolve(strict=False)))
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _THREAD_LOCKS[key] = lock
        return lock


@contextmanager
def _interprocess_lock(path: Path, timeout: float = 8.0) -> Iterator[None]:
    """Lock one resource across processes without leaving Windows sidecars."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        key = os.path.normcase(str(path.resolve(strict=False))).encode("utf-8")
        mutex_name = "Local\\Solralol.Storage." + hashlib.sha256(key).hexdigest()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
        kernel32.ReleaseMutex.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateMutexW(None, False, mutex_name)
        if not handle:
            raise OSError(ctypes.get_last_error(), "No se pudo crear el bloqueo de almacenamiento.")
        acquired = False
        try:
            timeout_ms = max(0, min(int(timeout * 1000), 0xFFFFFFFE))
            result = kernel32.WaitForSingleObject(handle, timeout_ms)
            if result not in (0x00000000, 0x00000080):  # acquired or abandoned owner
                if result == 0xFFFFFFFF:
                    raise OSError(ctypes.get_last_error(), "Error al adquirir el bloqueo de almacenamiento.")
                raise TimeoutError(f"Tiempo agotado al bloquear el archivo {path.name}.")
            acquired = True
            yield
        finally:
            if acquired:
                kernel32.ReleaseMutex(handle)
            kernel32.CloseHandle(handle)
        return

    # POSIX uses flock on a stable sidecar because named kernel mutexes are
    # Windows-specific. These lock files are deliberately retained there.
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Tiempo agotado al bloquear el archivo {path.name}.")
                time.sleep(0.05)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def cleanup_legacy_windows_lock(target: str | Path) -> bool:
    """Remove a released sidecar created by the former Windows lock backend.

    New Windows writes use a named mutex. An exclusive Windows handle with
    delete-on-close excludes both active legacy owners and open waiters. A
    probe/unlock/unlink sequence would have a race between unlocking and
    deleting the path. This helper only targets the exact sidecar for target.
    """
    if os.name != "nt":
        return False
    path = Path(target)
    lock_path = path.with_name(f".{path.name}.lock")
    if lock_path.is_symlink():
        return False
    if not lock_path.is_file():
        return True
    try:
        with _path_thread_lock(path), _interprocess_lock(path, timeout=0.0):
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                            wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
            kernel32.CreateFileW.restype = wintypes.HANDLE
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.CloseHandle.restype = wintypes.BOOL
            # GENERIC_READ | DELETE, no sharing, OPEN_EXISTING,
            # FILE_FLAG_DELETE_ON_CLOSE. Never creates an absent lock file.
            handle = kernel32.CreateFileW(str(lock_path.resolve()), 0x80010000, 0,
                                           None, 3, 0x04000000, None)
            if handle == wintypes.HANDLE(-1).value:
                return ctypes.get_last_error() in (2, 3)  # already absent
            return bool(kernel32.CloseHandle(handle))
    except (OSError, TimeoutError):
        return False


def _retry_replace(source: Path, target: Path) -> None:
    delay = 0.04
    for attempt in range(_TRANSIENT_REPLACE_RETRIES):
        try:
            os.replace(source, target)
            return
        except OSError as error:
            transient = isinstance(error, PermissionError) or getattr(error, "winerror", None) in {5, 32, 33}
            if not transient or attempt == _TRANSIENT_REPLACE_RETRIES - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.5)


@contextmanager
def serialized_file_access(target: str | Path, *, timeout: float = 8.0) -> Iterator[None]:
    """Serialize a read/modify/write transaction across threads and processes.

    Nested use for the same target is reentrant, so callers may hold the
    transaction while invoking one of the atomic-write helpers.
    """
    path = Path(target)
    key = os.path.normcase(str(path.resolve(strict=False)))
    depths = getattr(_FILE_LOCK_LOCAL, "depths", None)
    if depths is None:
        depths = _FILE_LOCK_LOCAL.depths = {}
    if depths.get(key, 0):
        depths[key] += 1
        try:
            yield
        finally:
            depths[key] -= 1
        return
    with _path_thread_lock(path), _interprocess_lock(path, timeout):
        depths[key] = 1
        try:
            yield
        finally:
            depths.pop(key, None)


def cleanup_abandoned_temps(target: Path, *, older_than_seconds: float = 24 * 3600) -> int:
    """Remove only stale temporaries owned by this target's atomic writer."""
    if not target.parent.is_dir():
        return 0
    cutoff = time.time() - older_than_seconds
    removed = 0
    pattern = f".{target.name}.*.tmp"
    for candidate in target.parent.glob(pattern):
        try:
            if candidate.is_file() and candidate.stat().st_mtime < cutoff:
                candidate.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def atomic_write_bytes(target: str | Path, content: bytes, *, timeout: float = 8.0) -> None:
    """Durably write a unique same-directory temporary then replace the target."""
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    with serialized_file_access(path, timeout=timeout):
        _atomic_write_bytes_locked(path, content)


def _atomic_write_bytes_locked(path: Path, content: bytes) -> None:
    cleanup_abandoned_temps(path)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _retry_replace(temporary, path)
        if os.name != "nt":
            try:
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def atomic_write_text(target: str | Path, content: str, *, encoding: str = "utf-8") -> None:
    atomic_write_bytes(target, content.encode(encoding))


def atomic_write_json(target: str | Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    atomic_write_text(target, payload + "\n")


def atomic_update_json(target: str | Path, updater: Any, *, default: Any,
                       should_write: Any = None, timeout: float = 8.0) -> Any:
    """Read, mutate and atomically commit JSON while holding the cross-process lock."""
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    with serialized_file_access(path, timeout=timeout):
        try:
            with path.open("r", encoding="utf-8") as stream:
                current = json.load(stream)
        except FileNotFoundError:
            current = default
        except json.JSONDecodeError:
            current = default
        value = updater(current)
        if should_write is None or should_write(value, current):
            payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
            _atomic_write_bytes_locked(path, (payload + "\n").encode("utf-8"))
        return value


@dataclass(frozen=True)
class MigrationPlan:
    source: Path
    destination: Path
    extra_recordings: tuple[Path, ...]
    total_bytes: int
    file_count: int
    available_bytes: int
    existing_destination_bytes: int = 0
    extra_electron_data: Path | None = None


class StorageManager:
    """Resolve all user-managed paths from one persistent application root."""

    def __init__(self, root: str | Path | None = None) -> None:
        self._root_override = Path(root).expanduser() if root is not None else None
        self._stats_lock = threading.Lock()
        self._stats_cache: tuple[float, dict[str, Any]] | None = None

    @staticmethod
    def _migration_journal_path() -> Path:
        return bootstrap_config_path().with_name("migration.json")

    @classmethod
    def migration_journal(cls) -> dict[str, Any] | None:
        try:
            value = json.loads(cls._migration_journal_path().read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError):
            return None

    @classmethod
    def startup_migration_state(cls) -> dict[str, Any] | None:
        journal = cls.migration_journal()
        if not journal:
            return None
        state = journal.get("state")
        if state in {"preparing", "assistant_ready", "waiting_for_shutdown", "closing", "validating", "copying", "verifying", "committing", "reinitializing"}:
            pointer_root = ""
            try:
                pointer = json.loads(bootstrap_config_path().read_text(encoding="utf-8"))
                pointer_root = str(Path(pointer.get("data_root", "")).resolve(strict=False))
            except (OSError, ValueError, TypeError):
                pass
            destination = str(Path(str(journal.get("destination", ""))).resolve(strict=False))
            if state == "committing" and pointer_root == destination and source_has_marker(Path(destination)):
                journal.update({"state": "complete", "phase": "complete",
                                "message": "Migración completada y verificada"})
            elif state == "complete" and pointer_root == destination:
                journal.update({"state": "complete", "phase": "complete",
                                "message": "Migración completada y verificada"})
            else:
                journal.update({"state": "recovery_required", "phase": "recovery_required",
                                "message": "Se interrumpió una migración. La ubicación anterior sigue activa; puedes revisar el destino y volver a intentarlo."})
            atomic_write_json(cls._migration_journal_path(), journal)
        return journal

    @classmethod
    def _save_migration_journal(cls, state: dict[str, Any]) -> None:
        atomic_write_json(cls._migration_journal_path(), state)

    @property
    def root(self) -> Path:
        if self._root_override is not None:
            return self._root_override.resolve(strict=False)
        configured = os.environ.get("SOLRALOL_DATA_DIR")
        if configured:
            return Path(configured).expanduser().resolve(strict=False)
        try:
            raw = json.loads(bootstrap_config_path().read_text(encoding="utf-8"))
            configured = raw.get("data_root") if isinstance(raw, dict) else None
            if isinstance(configured, str) and configured.strip():
                return Path(configured).expanduser().resolve(strict=False)
        except (OSError, ValueError, TypeError):
            pass
        return (Path.home() / ".solralol").resolve(strict=False)

    @property
    def default_root(self) -> Path:
        return (Path.home() / ".solralol").resolve(strict=False)

    @property
    def config_dir(self) -> Path:
        return self.root

    @property
    def settings_path(self) -> Path:
        return self.root / "settings.json"

    @property
    def profiles_dir(self) -> Path:
        return self.root / "profiles"

    @property
    def matches_dir(self) -> Path:
        return self.root / "matches"

    @property
    def match_history_cache_path(self) -> Path:
        return self.root / "match_history_cache.json"

    @property
    def recordings_dir(self) -> Path:
        return self.root / "recordings" / "videos"

    @property
    def recording_thumbnails_dir(self) -> Path:
        return self.root / "recording-thumbnails"

    @property
    def analysis_dir(self) -> Path:
        return self.root / "analysis"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def ddragon_dir(self) -> Path:
        return self.root / "ddragon"

    @property
    def meta_dir(self) -> Path:
        return self.root / "meta"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def match_logs_dir(self) -> Path:
        return self.root / "match_logs"

    @property
    def live_sessions_path(self) -> Path:
        return self.root / "live_match_sessions.json"

    def validate_directory(self, candidate: str | Path) -> Path:
        raw = str(candidate).strip()
        if not raw or len(raw) > 1024:
            raise ValueError("Selecciona una ruta de almacenamiento válida.")
        path = Path(raw).expanduser().resolve(strict=False)
        if path == Path(path.anchor):
            raise ValueError("No se puede usar la raíz de una unidad como carpeta de datos.")
        if path.is_relative_to(Path(tempfile.gettempdir()).resolve(strict=False)):
            raise ValueError("El directorio temporal no es una ubicación segura para tus datos.")
        install_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])).resolve(strict=False)
        if path == install_root or path.is_relative_to(install_root):
            raise ValueError("El directorio de datos debe estar fuera de la carpeta de instalación.")
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ValueError("No se puede crear o acceder a la carpeta seleccionada. Comprueba la unidad y sus permisos.") from error
        if not path.is_dir():
            raise ValueError("La ubicación seleccionada no es una carpeta.")
        marker = path / _STORAGE_ROOT_MARKER
        try:
            has_content = any(path.iterdir())
        except OSError as error:
            raise ValueError("Solralol no puede leer la carpeta seleccionada. Comprueba la unidad y sus permisos.") from error
        if has_content and not marker.is_file() and path not in {self.root, self.default_root}:
            raise ValueError("La carpeta de destino ya contiene archivos ajenos a Solralol.")
        probe = path / f".solralol-write-check-{uuid.uuid4().hex}.tmp"
        try:
            with probe.open("xb") as stream:
                stream.write(b"ok")
                stream.flush()
                os.fsync(stream.fileno())
            probe.unlink()
        except OSError as error:
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                pass
            raise ValueError("Solralol no puede leer y escribir en la carpeta seleccionada.") from error
        return path

    @staticmethod
    def _directory_measure(directory: Path) -> tuple[int, int]:
        total = count = 0
        if not directory.exists():
            return total, count
        for current, dirs, files in os.walk(directory, followlinks=False):
            dirs[:] = [name for name in dirs if not (Path(current) / name).is_symlink()]
            for name in files:
                path = Path(current) / name
                try:
                    if path.is_file() and not path.is_symlink():
                        total += path.stat().st_size
                        count += 1
                except OSError:
                    raise ValueError(f"No se pudo medir el archivo {path.name}.")
        return total, count

    @classmethod
    def _directory_measure_excluding(cls, directory: Path, ignored_names: set[str]) -> tuple[int, int]:
        total, count = cls._directory_measure(directory)
        if not directory.exists():
            return total, count
        for current, _dirs, files in os.walk(directory, followlinks=False):
            for name in files:
                path = Path(current) / name
                if name in ignored_names and path.is_file() and not path.is_symlink():
                    try:
                        total -= path.stat().st_size
                        count -= 1
                    except OSError:
                        continue
        return total, count

    def migration_plan(self, candidate: str | Path, recording_output_dir: str | Path | None = None) -> MigrationPlan:
        source = self.root
        if not source.is_dir():
            raise ValueError("No se puede acceder a la ubicación actual. Conecta la unidad o restaura su acceso antes de mover los datos.")
        requested = Path(candidate).expanduser().resolve(strict=False)
        if requested == source or requested.is_relative_to(source) or source.is_relative_to(requested):
            raise ValueError("La ubicación de destino no puede contener ni estar dentro del origen.")
        destination = self.validate_directory(candidate)
        sources: list[Path] = [source]
        extra_recordings: list[Path] = []
        candidates = [Path(recording_output_dir).expanduser().resolve(strict=False)] if recording_output_dir else []
        legacy_default = Path.home() / "Videos" / "Solralol"
        if legacy_default.is_dir():
            candidates.append(legacy_default.resolve(strict=False))
        for candidate_path in candidates:
            is_canonical_recordings = candidate_path == self.recordings_dir.resolve(strict=False)
            if (candidate_path.exists() and not is_canonical_recordings
                    and candidate_path not in extra_recordings):
                extra_recordings.append(candidate_path)
        legacy_electron_raw = os.environ.get("SOLRALOL_LEGACY_ELECTRON_DATA", "").strip()
        extra_electron_data = Path(legacy_electron_raw).expanduser().resolve(strict=False) if legacy_electron_raw else None
        if (not extra_electron_data or not extra_electron_data.is_dir()
                or extra_electron_data.is_relative_to(source) or (source / "electron").exists()):
            extra_electron_data = None
        total = count = 0
        for directory in sources + extra_recordings:
            size, files = self._directory_measure(directory)
            total += size
            count += files
        if extra_electron_data:
            size, files = self._directory_measure_excluding(extra_electron_data, {"storage.json"})
            total += size
            count += files
        existing_destination_bytes = 0
        if destination == self.default_root and destination.exists():
            existing_destination_bytes, existing_count = self._directory_measure(destination)
            total += existing_destination_bytes
            count += existing_count
        usage = shutil.disk_usage(destination.parent if destination.exists() else destination.parent)
        if usage.free < total:
            raise ValueError("No hay espacio suficiente en la unidad de destino para copiar los datos.")
        return MigrationPlan(source, destination, tuple(extra_recordings), total, count, usage.free,
                             existing_destination_bytes, extra_electron_data)

    def migrate(self, candidate: str | Path, recording_output_dir: str | Path | None = None,
                progress: Any = None, migration_id: str | None = None) -> dict[str, Any]:
        migration_id = migration_id or str(uuid.uuid4())
        journal_path = self._migration_journal_path()
        with serialized_file_access(journal_path, timeout=1.0):
            existing = self.migration_journal() or {}
            if existing.get("state") in {"preparing", "validating", "copying", "verifying", "committing", "reinitializing"} and existing.get("migrationId") != migration_id:
                raise RuntimeError("Ya hay otra migración activa en este equipo.")
            return self._migrate_transaction(candidate, recording_output_dir, progress, migration_id)

    def _migrate_transaction(self, candidate: str | Path, recording_output_dir: str | Path | None = None,
                             progress: Any = None, migration_id: str | None = None) -> dict[str, Any]:
        """Copy to a durable staging directory, verify it, then commit the root."""
        migration_id = migration_id or str(uuid.uuid4())
        plan = self.migration_plan(candidate, recording_output_dir)
        destination = plan.destination
        stage = destination.parent / f".{destination.name}.solralol-stage-{migration_id}"
        backup_existing = destination.parent / f".{destination.name}.previous-{migration_id}"
        copied_bytes = copied_files = verified_bytes = verified_files = 0
        last_emit = 0.0
        last_progress_phase = ""
        last_journal_write = 0.0
        last_journal_phase = ""
        state: dict[str, Any] = {
            "migrationId": migration_id, "state": "preparing", "phase": "preparing",
            "source": str(plan.source), "destination": str(destination),
            "currentBytes": 0, "verifiedBytes": 0, "totalBytes": plan.total_bytes,
            "processedFiles": 0, "fileCount": plan.file_count, "currentFile": "",
            "lastProgressAt": time.time(), "message": "Preparando archivos", "stage": str(stage),
        }

        def publish(phase: str, message: str, *, file_name: str = "", force: bool = False) -> None:
            nonlocal last_emit, last_progress_phase, last_journal_write, last_journal_phase
            now = time.monotonic()
            state.update({
                "state": phase, "phase": phase,
                "currentBytes": min(copied_bytes, plan.total_bytes),
                "verifiedBytes": min(verified_bytes, plan.total_bytes),
                "processedFiles": copied_files if phase == "copying" else (state.get("processedFiles", 0) if phase == "validating" else verified_files),
                "fileCount": plan.file_count, "totalBytes": plan.total_bytes,
                "currentFile": file_name[:240], "lastProgressAt": time.time(), "message": message,
            })
            if phase != last_journal_phase or now - last_journal_write >= 1.0 or phase in {"complete", "failed"}:
                self._save_migration_journal(state)
                last_journal_write = now
                last_journal_phase = phase
            if progress and (phase != last_progress_phase or now - last_emit >= 0.25):
                progress(dict(state))
                last_emit = now
                last_progress_phase = phase

        def copy_stream(src: str, dst: str) -> str:
            nonlocal copied_bytes, copied_files
            source_path, target_path = Path(src), Path(dst)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with source_path.open("rb") as source_stream, target_path.open("wb") as target_stream:
                while True:
                    chunk = source_stream.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    target_stream.write(chunk)
                    copied_bytes += len(chunk)
                    publish("copying", "Copiando datos", file_name=source_path.name)
                target_stream.flush()
                os.fsync(target_stream.fileno())
            shutil.copystat(source_path, target_path, follow_symlinks=False)
            copied_files += 1
            publish("copying", "Copiando datos", file_name=source_path.name, force=True)
            return str(target_path)

        def verify_tree(source: Path, target: Path, ignored_names: set[str] | None = None) -> None:
            nonlocal verified_bytes, verified_files
            ignored = ignored_names or set()
            for current, dirs, files in os.walk(source, followlinks=False):
                dirs[:] = [name for name in dirs if not (Path(current) / name).is_symlink()]
                relative = Path(current).relative_to(source)
                for name in files:
                    if name in ignored:
                        continue
                    src = Path(current) / name
                    if src.is_symlink():
                        continue
                    dst = target / relative / name
                    if not dst.is_file() or src.stat().st_size != dst.stat().st_size:
                        raise OSError(f"La verificación de migración no coincide: {name}")
                    digest_source = hashlib.sha256()
                    digest_target = hashlib.sha256()
                    with src.open("rb") as source_stream, dst.open("rb") as target_stream:
                        while True:
                            source_chunk = source_stream.read(8 * 1024 * 1024)
                            target_chunk = target_stream.read(8 * 1024 * 1024)
                            if source_chunk != target_chunk:
                                raise OSError(f"La verificación de contenido no coincide: {name}")
                            if not source_chunk:
                                break
                            digest_source.update(source_chunk)
                            digest_target.update(target_chunk)
                            verified_bytes += len(source_chunk)
                            publish("verifying", "Verificando archivos", file_name=name)
                    if digest_source.digest() != digest_target.digest():
                        raise OSError(f"La verificación de contenido no coincide: {name}")
                    verified_files += 1
                    publish("verifying", "Verificando archivos", file_name=name, force=True)

        try:
            publish("validating", "Validando destino", force=True)
            if stage.exists():
                raise ValueError("Ya existe una carpeta temporal de esta migración. Se conserva para recuperación y no se sobrescribirá.")
            stage.mkdir(parents=False, exist_ok=False)
            def manifest_progress(files_seen: int, bytes_seen: int, file_name: str) -> None:
                state["processedFiles"] = files_seen
                state["currentBytes"] = min(bytes_seen, plan.total_bytes)
                publish("validating", "Preparando archivos", file_name=file_name)

            manifest = self._build_migration_manifest(plan, migration_id, manifest_progress)
            manifest_path = stage / f".solralol-migration-{migration_id}.manifest.json"
            atomic_write_json(manifest_path, manifest)
            state["manifest"] = manifest_path.name
            self._save_migration_journal(state)
            publish("copying", "Copiando datos", force=True)
            if plan.existing_destination_bytes and destination.exists():
                shutil.copytree(destination, stage, dirs_exist_ok=True, copy_function=copy_stream)
                publish("verifying", "Verificando archivos existentes", force=True)
                verify_tree(destination, stage)
                publish("copying", "Copiando datos", force=True)
            if plan.source.exists():
                shutil.copytree(plan.source, stage, dirs_exist_ok=True, copy_function=copy_stream)
            if plan.extra_electron_data:
                electron_target = stage / "electron"
                electron_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(plan.extra_electron_data, electron_target, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("storage.json"), copy_function=copy_stream)
            if plan.extra_recordings:
                recording_target = stage / "recordings" / "videos"
                recording_target.parent.mkdir(parents=True, exist_ok=True)
                for source_recordings in plan.extra_recordings:
                    for item in source_recordings.iterdir():
                        target = recording_target / item.name
                        if target.exists():
                            if item.is_dir() and target.is_dir():
                                self._verify_copy(item, target)
                                continue
                            if item.is_file() and target.is_file() and item.stat().st_size == target.stat().st_size and _file_sha256(item) == _file_sha256(target):
                                continue
                            raise ValueError(f"Hay un archivo con el mismo nombre en Grabaciones: {item.name}")
                        if item.is_dir():
                            shutil.copytree(item, target, copy_function=copy_stream)
                        else:
                            copy_stream(str(item), str(target))

            publish("verifying", "Verificando archivos", force=True)
            verify_tree(plan.source, stage)
            if plan.extra_electron_data:
                verify_tree(plan.extra_electron_data, stage / "electron", ignored_names={"storage.json"})
            if plan.extra_recordings:
                for source_recordings in plan.extra_recordings:
                    verify_tree(source_recordings, stage / "recordings" / "videos")
            self._validate_staged_databases(stage)
            manifest_path.unlink(missing_ok=True)
            manifest_path.with_name(f".{manifest_path.name}.lock").unlink(missing_ok=True)
            self._update_migrated_recording_setting(stage, destination)
            atomic_write_json(stage / _STORAGE_ROOT_MARKER, {"schema": 1, "created_at": time.time()})

            publish("committing", "Aplicando nueva ubicación", force=True)
            if destination.exists():
                if any(destination.iterdir()) and not plan.existing_destination_bytes and not source_has_marker(destination):
                    raise ValueError("La carpeta de destino dejó de estar vac?a durante la migración.")
                os.replace(destination, backup_existing)
            try:
                os.replace(stage, destination)
                if not destination.is_dir() or not source_has_marker(destination):
                    raise OSError("El destino no está disponible tras aplicar la migración.")
                settings_path = destination / "settings.json"
                if settings_path.is_file():
                    json.loads(settings_path.read_text(encoding="utf-8"))
                self._write_bootstrap_root(destination)
            except Exception:
                if destination.exists() and source_has_marker(destination):
                    rollback_stage = destination.parent / f".{destination.name}.rollback-{migration_id}"
                    os.replace(destination, rollback_stage)
                if backup_existing.exists() and not destination.exists():
                    os.replace(backup_existing, destination)
                raise

            result = {"root": str(destination), "migratedBytes": plan.total_bytes,
                      "fileCount": plan.file_count, "restartRequired": True,
                      "previousDestinationBackup": str(backup_existing) if backup_existing.exists() else None}
            state.update({"state": "complete", "phase": "complete", "result": result,
                          "currentBytes": plan.total_bytes, "verifiedBytes": plan.total_bytes,
                          "processedFiles": plan.file_count, "lastProgressAt": time.time(),
                          "message": "Migración completada y verificada"})
            self._save_migration_journal(state)
            if progress:
                progress(dict(state))
            return result
        except Exception as error:
            pointer_root = ""
            try:
                pointer = json.loads(bootstrap_config_path().read_text(encoding="utf-8"))
                pointer_root = str(Path(pointer.get("data_root", "")).resolve(strict=False))
            except (OSError, ValueError, TypeError):
                pass
            if pointer_root and pointer_root == str(destination.resolve(strict=False)) and source_has_marker(destination):
                state.update({"state": "complete", "phase": "complete",
                              "message": "Migración aplicada; se completará la recuperación al reiniciar.",
                              "result": {"root": str(destination), "migratedBytes": plan.total_bytes,
                                         "fileCount": plan.file_count, "restartRequired": True},
                              "lastProgressAt": time.time()})
                try:
                    self._save_migration_journal(state)
                except OSError:
                    pass
                if progress:
                    progress(dict(state))
                return state["result"]
            state.update({"state": "failed", "message": "No se pudo completar la migración. La ubicación original sigue activa.",
                          "errorType": type(error).__name__, "error": str(error)[:500],
                          "lastProgressAt": time.time()})
            try:
                self._save_migration_journal(state)
            except OSError:
                pass
            # Preserve staged data for diagnosis or a later safe recovery.
            if progress:
                progress(dict(state))
            raise

    @staticmethod
    def _build_migration_manifest(plan: MigrationPlan, migration_id: str, progress: Any = None) -> dict[str, Any]:
        sources: list[tuple[str, Path, set[str]]] = []
        if plan.existing_destination_bytes:
            sources.append(("existing_destination", plan.destination, set()))
        sources.append(("storage_root", plan.source, set()))
        if plan.extra_electron_data:
            sources.append(("electron_user_data", plan.extra_electron_data, {"storage.json"}))
        sources.extend(("recordings", directory, set()) for directory in plan.extra_recordings)
        entries: list[dict[str, Any]] = []
        last_emit = 0.0
        bytes_seen = 0
        for label, source_root, ignored in sources:
            for current, dirs, files in os.walk(source_root, followlinks=False):
                dirs[:] = [name for name in dirs if not (Path(current) / name).is_symlink()]
                for name in files:
                    if name in ignored:
                        continue
                    source = Path(current) / name
                    if source.is_symlink():
                        continue
                    try:
                        stat = source.stat()
                        entries.append({"source": label,
                                        "relativePath": str(source.relative_to(source_root)),
                                        "bytes": stat.st_size, "modifiedNs": stat.st_mtime_ns})
                        bytes_seen += stat.st_size
                        if progress and (len(entries) % 128 == 0 or time.monotonic() - last_emit >= 0.25):
                            progress(len(entries), bytes_seen, name)
                            last_emit = time.monotonic()
                    except OSError as error:
                        raise OSError(f"No se pudo preparar el manifiesto de {name}") from error
        if progress:
            progress(len(entries), bytes_seen, "")
        return {"schema": 1, "migrationId": migration_id, "files": entries,
                "totalFiles": len(entries), "totalBytes": sum(entry["bytes"] for entry in entries)}

    @staticmethod
    def _validate_staged_databases(stage: Path) -> None:
        for current, _dirs, files in os.walk(stage, followlinks=False):
            for name in files:
                if Path(name).suffix.casefold() not in {".sqlite", ".sqlite3", ".db"}:
                    continue
                database = Path(current) / name
                connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True, timeout=2)
                try:
                    result = connection.execute("PRAGMA quick_check").fetchone()
                    if not result or result[0] != "ok":
                        raise OSError(f"La base de datos no superó la verificación: {name}")
                finally:
                    connection.close()

    @staticmethod
    def _verify_copy(source: Path, destination: Path, *, ignored_names: set[str] | None = None) -> None:
        ignored = ignored_names or set()
        if not source.exists():
            return
        for current, dirs, files in os.walk(source, followlinks=False):
            dirs[:] = [name for name in dirs if not (Path(current) / name).is_symlink()]
            relative = Path(current).relative_to(source)
            for name in files:
                if name in ignored:
                    continue
                src = Path(current) / name
                if src.is_symlink():
                    continue
                dst = destination / relative / name
                if not dst.is_file() or src.stat().st_size != dst.stat().st_size:
                    raise OSError(f"La verificación de migración no coincide: {name}")
                if _file_sha256(src) != _file_sha256(dst):
                    raise OSError(f"La verificación de contenido no coincide: {name}")

    @staticmethod
    def _update_migrated_recording_setting(stage: Path, destination: Path) -> None:
        settings_path = stage / "settings.json"
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(settings, dict):
            settings["recording_output_dir"] = str(destination / "recordings" / "videos")
            atomic_write_json(settings_path, settings)

    @staticmethod
    def _write_bootstrap_root(root: Path) -> None:
        atomic_write_json(bootstrap_config_path(), {"schema": 1, "data_root": str(root.resolve(strict=False))})

    def storage_stats(self, recording_output_dir: str | Path | None = None) -> dict[str, Any]:
        with self._stats_lock:
            if self._stats_cache and time.monotonic() - self._stats_cache[0] < 30:
                return dict(self._stats_cache[1])
        root = self.root
        categories = {
            "recordings": self.recordings_dir,
            "matches": self.matches_dir,
            "analysis": self.analysis_dir,
            "cache": self.cache_dir,
        }
        per_category: dict[str, int] = {}
        known: set[Path] = set()
        for category, directory in categories.items():
            try:
                per_category[category] = self._directory_measure(directory)[0]
                known.add(directory.resolve(strict=False))
            except OSError:
                per_category[category] = 0
        known.add((root / "recordings").resolve(strict=False))
        # Existing Solralol data predates the directory taxonomy; include the
        # established profile and flat analysis/cache locations in their groups.
        for category, extra in {
            "matches": (self.profiles_dir, self.root / "match_history_cache.json", self.root / "match_logs"),
            "analysis": (self.root / "battlescore", self.root / "saved_analyses"),
            "cache": (self.ddragon_dir, self.meta_dir, self.root / "recording-thumbnails"),
        }.items():
            for directory in extra:
                try:
                    per_category[category] += self._directory_measure(directory)[0] if directory.is_dir() else (directory.stat().st_size if directory.is_file() else 0)
                    known.add(directory.resolve(strict=False))
                except OSError:
                    pass
        if recording_output_dir:
            external_recordings = Path(recording_output_dir).expanduser().resolve(strict=False)
            if not external_recordings.is_relative_to(root):
                try:
                    per_category["recordings"] += self._directory_measure(external_recordings)[0]
                    known.add(external_recordings)
                except OSError:
                    pass
        try:
            root_children = tuple(root.iterdir())
            data_available = root.is_dir()
        except OSError:
            root_children = ()
            data_available = False
        # A read failure is surfaced as unavailable instead of choosing a second root.
        per_category["other"] = 0
        total = sum(per_category.values())
        if data_available:
            others = 0
            for child in root_children:
                if child.is_dir() and child.resolve(strict=False) in known:
                    continue
                try:
                    others += self._directory_measure(child)[0] if child.is_dir() else child.stat().st_size
                except OSError:
                    continue
            per_category["other"] = others
            total = sum(per_category.values())
        volume_path = root if data_available else root.parent
        while not volume_path.exists() and volume_path != volume_path.parent:
            volume_path = volume_path.parent
        try:
            free = shutil.disk_usage(volume_path).free
        except OSError:
            free = 0
        result = {"root": str(root), "totalBytes": total, "freeBytes": free,
                  "categories": per_category, "available": data_available}
        with self._stats_lock:
            self._stats_cache = (time.monotonic(), result)
        return dict(result)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_has_marker(path: Path) -> bool:
    return (path / _STORAGE_ROOT_MARKER).is_file()


def get_storage_manager() -> StorageManager:
    return StorageManager()
