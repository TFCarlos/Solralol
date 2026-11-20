#!/usr/bin/env python3
"""Solralol graphical development control center.

Run this file from any working directory: ``python path/to/solralol_dev.py``.
The production Python backend stays Qt-free; PySide6 is used only by this tool.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parent

# EDIT THESE SETTINGS ONLY IF AUTOMATIC DETECTION DOES NOT MATCH YOUR REPOSITORY.
FRONTEND_DIRECTORY: str | None = None  # e.g. "frontend" or "."
FRONTEND_NPM_SCRIPT: str | None = None  # e.g. "dev:electron" or "dev"
BACKEND_ARGUMENTS: list[str] | None = None  # e.g. ["-m", "backend.protocol"]
BACKEND_WORKING_DIRECTORY: str = "."
EVENT_PREFIX = "__SOLRALO_TEST_EVENT__:"
STATUS_PREFIX = "__SOLRALOL_STATUS__:"
ANSI_ESCAPE_RE = re.compile(r"\x1B(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1B\\)|[@-_])")
IS_WINDOWS = os.name == "nt"


def identify_frontend() -> tuple[Path, str, dict[str, str]]:
    paths = [ROOT / FRONTEND_DIRECTORY] if FRONTEND_DIRECTORY else [ROOT / "frontend", ROOT]
    for directory in paths:
        manifest = directory / "package.json"
        if not manifest.is_file():
            continue
        try:
            content = json.loads(manifest.read_text(encoding="utf-8"))
            scripts = content.get("scripts", {})
            if not isinstance(scripts, dict):
                continue
            candidates = [FRONTEND_NPM_SCRIPT] if FRONTEND_NPM_SCRIPT else ["dev:electron", "electron:dev", "dev"]
            for name in candidates:
                if name and name in scripts:
                    return directory.resolve(), name, scripts
        except (ValueError, OSError):
            pass
    raise RuntimeError("Frontend not found. Configure FRONTEND_DIRECTORY and FRONTEND_NPM_SCRIPT at the top of the script.")


def identify_backend() -> tuple[list[str], Path]:
    cwd = (ROOT / BACKEND_WORKING_DIRECTORY).resolve()
    if BACKEND_ARGUMENTS is not None:
        return [str(arg) for arg in BACKEND_ARGUMENTS], cwd
    possibilities = [
        ("backend/protocol.py", ["-u", "-m", "backend.protocol"]),
    ]
    for file, args in possibilities:
        if (ROOT / file).is_file():
            return args, cwd
    raise RuntimeError(
        "Could not identify the Python backend entry point. Expected backend/protocol.py. "
        "Set BACKEND_ARGUMENTS only for a deliberate local backend override."
    )


def project_python() -> str:
    candidates = [
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / "venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
        ROOT / "venv" / "bin" / "python",
    ]
    executable = next((p for p in candidates if p.is_file()), None)
    if executable is None:
        raise RuntimeError(
            "Project Python virtual environment was not found. Create it with "
            "'py -3.11 -m venv .venv' and install requirements-dev.txt."
        )
    return str(executable)


def print_event(data: dict[str, Any]) -> None:
    # Bypass captured pytest terminal output while preserving real-time event streaming.
    sys.__stdout__.write(EVENT_PREFIX + json.dumps(data, ensure_ascii=False) + "\n")
    sys.__stdout__.flush()


class PytestLiveReporter:
    def __init__(self) -> None:
        self.reports: dict[str, list[Any]] = {}
        self.collection_failures: list[tuple[str, str]] = []
        self.count = 0
        self.total = 0

    def pytest_collectreport(self, report: Any) -> None:
        if report.failed:
            self.collection_failures.append((str(report.nodeid), summarize_error(report.longreprtext)))

    def pytest_collection_finish(self, session: Any) -> None:
        self.total = len(session.items) + len(self.collection_failures)
        print_event({"kind": "total", "total": self.total})

    def pytest_runtest_logreport(self, report: Any) -> None:
        self.reports.setdefault(report.nodeid, []).append(report)

    def pytest_runtest_logfinish(self, nodeid: str, location: Any) -> None:
        reports = self.reports.pop(nodeid, [])
        failures = [r for r in reports if r.failed]
        skipped = [r for r in reports if r.skipped]
        calls_passed = any(r.when == "call" and r.passed for r in reports)
        if failures:
            report = failures[0]
            status, reason = "failed", str(report.longreprtext or summarize_error(report.longreprtext))
        elif skipped:
            report = skipped[0]
            status, reason = "skipped", str(report.longreprtext or "Skipped")
        elif calls_passed:
            status, reason = "passed", ""
        else:
            status, reason = "error", "Test did not complete a successful call phase"
        self.count += 1
        duration = sum(float(getattr(r, "duration", 0) or 0) for r in reports)
        print_event({"kind": "result", "name": nodeid, "status": status, "error": reason, "duration": duration})

    def pytest_sessionfinish(self, session: Any, exitstatus: Any) -> None:
        for name, error in self.collection_failures:
            self.count += 1
            print_event({"kind": "result", "name": "collection: " + name, "status": "error", "error": error})
        if self.total == 0:
            print_event({"kind": "total", "total": 1})
            print_event({"kind": "result", "name": "pytest discovery", "status": "error", "error": "No pytest tests were discovered"})
        print_event({"kind": "finished", "exit_code": int(session.exitstatus), "completed": self.count})


def summarize_error(longrepr: str) -> str:
    text = str(longrepr).strip()
    if not text:
        return "No error details provided"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    exception_lines = [line[2:].strip() for line in lines if line.startswith("E ") or line.startswith("E\t")]
    if exception_lines:
        error = exception_lines[-1]
        # Pytest sometimes abbreviates `assert 1 == 2, "reason"` to `E assert 1 == 2`.
        # Preserve the more informative source assertion when it includes an explicit message.
        if error.startswith("assert "):
            assertion_sources = [line.lstrip("> ").strip() for line in lines if line.startswith(">") and "assert " in line]
            if assertion_sources and len(assertion_sources[-1]) > len(error):
                error = assertion_sources[-1]
        return error
    return lines[-1] if lines else text


def pytest_worker() -> int:
    try:
        import pytest
    except ImportError:
        print_event({"kind": "total", "total": 1})
        print_event({"kind": "result", "name": "pytest availability", "status": "error", "error": "pytest is not installed in the project Python environment"})
        return 2
    reporter = PytestLiveReporter()
    # The legacy scratch/ trees contain manual/live-client scripts, some of which exit
    # during import. The isolated automated suite lives in tests/.
    os.environ["PYTEST_ADDOPTS"] = ""
    # Keep pytest's terminal plugin active: its assertion formatter relies on it.
    # Capture only its own progress/summary so the manager can display one clean live line per check.
    with contextlib.redirect_stdout(io.StringIO()):
        return int(pytest.main(["-q", "--maxfail=0", str(ROOT / "tests")], plugins=[reporter]))


def main() -> None:
    """Start the standalone Qt development dashboard; Qt is not imported by backend code."""
    try:
        from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Qt, QUrl
        from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
        from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
        from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow,
            QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSplitter, QTabWidget,
            QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
    except ImportError as exc:
        raise RuntimeError("PySide6 is required for this development tool. Install requirements-dev.txt in .venv.") from exc

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Solralol Development Control Center")
    # Keep the control process alive until its own close handler decides to quit.
    # This prevents a transient/hidden top-level window during test completion from
    # ending the event loop and destroying the live test summary.
    app.setQuitOnLastWindowClosed(False)

    class Dashboard(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Solralol · Development Control Center")
            self.resize(1180, 820)
            self.setMinimumSize(900, 660)
            self.front = QProcess(self)
            self.front.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            self.tests = QProcess(self)
            self.tests.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            self.probe = QNetworkAccessManager(self)
            self.backend_state = "STOPPED"
            self.external_frontend = False
            self.ready_frontend = False
            self.vite_ready = False
            self.electron_ready = False
            self.startup_timers: dict[str, Any] = {}
            self.pending_frontend_launch: tuple[Path, str, str, str, str] | None = None
            self.closing_down = False
            self.total = self.completed = 0
            self.counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
            self.test_collection_errors = False
            self.results: list[dict[str, Any]] = []
            self.test_started = 0.0
            self.front_pending = self.tests_pending = self.backend_pending = ""
            self.backend_probe: Any = None
            self.backend_restart_pending = False
            self.front_restart_requested = False
            self.frontend_start_pending = False
            self.shutdown_close_pending = False
            self.kill_timer = QTimer(self)
            self.kill_timer.setSingleShot(True)
            self.kill_timer.timeout.connect(self.force_cancel_tests)
            self._ui()
            self.front.readyReadStandardOutput.connect(self.read_front)
            self.front.started.connect(
                lambda: self.set_status(
                    self.vite_badge, "STARTING", f"supervisor PID {int(self.front.processId())}"
                )
            )
            self.front.finished.connect(self.front_finished)
            self.front.errorOccurred.connect(self.front_error)
            self.tests.readyReadStandardOutput.connect(self.read_tests)
            self.tests.finished.connect(self.tests_finished)
            self.tests.errorOccurred.connect(self.test_error)
            self._log(self.front_log, "SYSTEM", f"Ready · {ROOT}")

        def _ui(self) -> None:
            root = QWidget(); root.setObjectName("root")
            layout = QVBoxLayout(root); layout.setContentsMargins(22, 18, 22, 18); layout.setSpacing(12)
            heading = QHBoxLayout(); titlebox = QVBoxLayout()
            title = QLabel("Development Control Center"); title.setObjectName("title")
            subtitle = QLabel(f"SOLRALOL  /  DEV     {ROOT}"); subtitle.setObjectName("muted")
            titlebox.addWidget(title); titlebox.addWidget(subtitle); heading.addLayout(titlebox); heading.addStretch()
            layout.addLayout(heading)
            panel = QFrame(); panel.setObjectName("panel"); buttons_layout = QVBoxLayout(panel)
            buttons_layout.addWidget(self._label("PROCESS CONTROLS"))
            row = QHBoxLayout(); row.setSpacing(9)
            self.front_button = QPushButton("Start Frontend"); self.backend_button = QPushButton("Start / Restart Backend")
            self.run_button = QPushButton("Run Test Suite"); self.stop_button = QPushButton("Stop Everything")
            self.front_button.setObjectName("primary"); self.backend_button.setObjectName("button")
            self.run_button.setObjectName("button"); self.stop_button.setObjectName("danger")
            for b in (self.front_button, self.backend_button, self.run_button, self.stop_button):
                b.setMinimumHeight(42); row.addWidget(b, 1)
            buttons_layout.addLayout(row)
            self.action_feedback = QLabel("Ready · choose an action")
            self.action_feedback.setObjectName("actionFeedback")
            self.action_feedback.setMinimumHeight(22)
            buttons_layout.addWidget(self.action_feedback)
            layout.addWidget(panel)
            status = QFrame(); status.setObjectName("panel"); sr = QHBoxLayout(status)
            self.vite_badge, self.front_badge, self.backend_badge, self.test_badge = QLabel(), QLabel(), QLabel(), QLabel()
            for name, badge in (("VITE", self.vite_badge), ("ELECTRON / RENDERER", self.front_badge), ("PYTHON BACKEND", self.backend_badge), ("TEST RUNNER", self.test_badge)):
                cell = QFrame(); cell.setObjectName("status")
                cl = QVBoxLayout(cell); n = QLabel(name); n.setObjectName("muted"); badge.setMinimumHeight(28)
                cl.addWidget(n); cl.addWidget(badge); sr.addWidget(cell, 1)
            layout.addWidget(status)
            self.tabs = QTabWidget()
            self.front_log = self._log_panel("Frontend output")
            self.backend_log = self._log_panel("Backend output")
            test_page = QWidget(); tl = QVBoxLayout(test_page)
            action = QHBoxLayout(); self.run_small = QPushButton("Run Tests"); self.cancel = QPushButton("Cancel Tests"); self.clear = QPushButton("Clear Test Output")
            self.run_small.setObjectName("primary"); self.cancel.setObjectName("button"); self.clear.setObjectName("button")
            action.addWidget(self.run_small); action.addWidget(self.cancel); action.addStretch(); action.addWidget(self.clear); tl.addLayout(action)
            pr = QHBoxLayout(); self.progress = QProgressBar(); self.progress.setRange(0, 1); self.progress_label = QLabel("Tests completed: 0 / 0"); self.progress_label.setObjectName("muted")
            pr.addWidget(self.progress, 1); pr.addWidget(self.progress_label); tl.addLayout(pr)
            self.summary = QLabel("No test run yet"); self.summary.setObjectName("muted"); tl.addWidget(self.summary)
            self.table = QTableWidget(0, 3); self.table.setHorizontalHeaderLabels(["Result", "Test", "Duration"])
            self.table.horizontalHeader().setStretchLastSection(True); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.details = QPlainTextEdit(); self.details.setReadOnly(True); self.details.setPlaceholderText("Select a test for its full failure details.")
            self.test_log = QPlainTextEdit(); self.test_log.setReadOnly(True); self.test_log.setMaximumBlockCount(2500); self.test_log.setPlaceholderText("Live test runner output")
            test_page.log_view = self.test_log; self.test_page = test_page
            split = QSplitter(Qt.Orientation.Vertical); split.addWidget(self.table); split.addWidget(self.details); split.addWidget(self.test_log); split.setSizes([260, 120, 120]); tl.addWidget(split, 1)
            self.tabs.addTab(self.front_log, "Frontend"); self.tabs.addTab(self.backend_log, "Backend"); self.tabs.addTab(test_page, "Tests")
            layout.addWidget(self.tabs, 1); self.setCentralWidget(root)
            self.setStyleSheet("""
              QWidget#root{background:#111318;color:#edf0f4;font-family:'Segoe UI';font-size:10pt}
              QFrame#panel,QFrame#status{background:#191d24;border:1px solid #2a303a;border-radius:12px}
              QLabel#title{font-size:20pt;font-weight:700;color:#f5f0e5} QLabel#muted{color:#929aa8}
              QLabel#actionFeedback{color:#929aa8;padding:2px 3px;font-size:9pt}
              QPushButton{border:0;border-radius:8px;padding:10px 13px;font-weight:600}
              QPushButton#primary{background:#c29a54;color:#161513} QPushButton#primary:hover{background:#d4ad69}
              QPushButton#button{background:#282e38;color:#edf0f4;border:1px solid #343c49}
              QPushButton#danger{background:#542e32;color:#ffdddd}
              QTabWidget::pane{background:#191d24;border:1px solid #2a303a;border-radius:9px}
              QTabBar::tab{background:#171a20;color:#a0a7b2;padding:9px 17px;border-top-left-radius:7px;border-top-right-radius:7px}
              QTabBar::tab:selected{background:#252b34;color:#f1f3f6}
              QPlainTextEdit,QTableWidget{background:#111419;color:#d7dce4;border:1px solid #2b313b;border-radius:7px;selection-background-color:#665333}
              QHeaderView::section{background:#20252d;color:#aab2bf;padding:7px;border:0}
              QProgressBar{background:#252a33;border:0;border-radius:5px;height:9px} QProgressBar::chunk{background:#c29a54;border-radius:5px}
            """)
            self.front_button.clicked.connect(self.start_frontend); self.backend_button.clicked.connect(self.restart_backend)
            self.run_button.clicked.connect(self.run_tests); self.run_small.clicked.connect(self.run_tests)
            self.stop_button.clicked.connect(self.stop_everything); self.cancel.clicked.connect(self.cancel_tests); self.clear.clicked.connect(self.clear_tests)
            self.table.itemSelectionChanged.connect(self.show_detail); self.cancel.setEnabled(False)
            for key in ("STOPPED",): self.set_status(self.vite_badge, key); self.set_status(self.front_badge, key); self.set_status(self.backend_badge, key); self.set_status(self.test_badge, key)

        @staticmethod
        def _label(text: str) -> Any:
            label = QLabel(text); label.setStyleSheet("color:#caa96c;font-size:9pt;font-weight:700;letter-spacing:1px"); return label

        def _log_panel(self, title: str) -> Any:
            w = QWidget(); vl = QVBoxLayout(w); h = QHBoxLayout(); label = QLabel(title); label.setObjectName("muted")
            clear = QPushButton("Clear log"); clear.setObjectName("button"); view = QPlainTextEdit(); view.setReadOnly(True); view.setMaximumBlockCount(2500); view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            h.addWidget(label); h.addStretch(); h.addWidget(clear); vl.addLayout(h); vl.addWidget(view, 1); clear.clicked.connect(view.clear); w.log_view = view
            return w

        @staticmethod
        def _log(panel: Any, source: str, text: str) -> None:
            view = panel.log_view; bar = view.verticalScrollBar(); follow = bar.value() >= bar.maximum() - 2
            for line in str(text).replace("\x00", "").splitlines() or [""]:
                view.appendPlainText(f"[{time.strftime('%H:%M:%S')}] [{source}] {line}")
                if source == "ERROR" or re.search(r"\b(error|failed|exception|traceback)\b", line, re.I):
                    cursor = view.textCursor(); cursor.movePosition(QTextCursor.MoveOperation.End)
                    cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                    fmt = QTextCharFormat(); fmt.setForeground(QColor("#ef8585")); cursor.mergeCharFormat(fmt)
                    view.setTextCursor(cursor)
            if follow: bar.setValue(bar.maximum())

        def read_complete_lines(self, key: str, chunk: bytes, final: bool = False) -> list[str]:
            pending = getattr(self, key) + chunk.decode("utf-8", errors="replace")
            pieces = pending.split("\n")
            setattr(self, key, "" if final else pieces.pop())
            if final and pieces[-1:] == [""]:
                pieces.pop()
            return [ANSI_ESCAPE_RE.sub("", line.rstrip("\r")) for line in pieces]

        @staticmethod
        def set_status(label: Any, state: str, detail: str = "") -> None:
            colors = {"STOPPED":"#858b96", "STARTING":"#d6a64b", "RUNNING":"#49bf87", "RESTARTING":"#d6a64b", "STOPPING":"#d6a64b", "ERROR":"#ef6868"}
            color = colors.get(state, colors["ERROR"]); label.setText(f"●  {state}  {('· ' + detail) if detail else ''}")
            label.setStyleSheet(f"color:{color};background:{color}20;border:1px solid {color}55;border-radius:8px;padding:5px 8px;font-weight:700")

        def set_action_feedback(self, message: str, tone: str = "info") -> None:
            colors = {"info": "#aab2bf", "busy": "#d6a64b", "success": "#49bf87", "warning": "#e0b35b", "error": "#ef6868"}
            markers = {"info": "•", "busy": "◌", "success": "✓", "warning": "!", "error": "×"}
            color = colors.get(tone, colors["info"])
            self.action_feedback.setText(f"{markers.get(tone, '•')}  {message}")
            self.action_feedback.setStyleSheet(f"color:{color};padding:2px 3px;font-size:9pt;font-weight:600")

        def start_frontend(self) -> None:
            self.set_action_feedback("Checking frontend status…", "busy")
            if self.frontend_start_pending:
                self.set_action_feedback("Frontend ownership check or startup is already in progress.", "busy")
                return
            if self.front.state() != QProcess.ProcessState.NotRunning:
                # Drain any queued shutdown messages before trusting the cached
                # READY flag; the user may click immediately after closing Electron.
                self.read_front()
                current_state = self.front_badge.text()
                if self.ready_frontend and "RUNNING" in current_state:
                    self._log(self.front_log, "SYSTEM", "Frontend is already active."); self.set_action_feedback("Frontend is already running.", "success"); return
                vite_failed = "ERROR" in self.vite_badge.text()
                if ("STARTING" in current_state or "RESTARTING" in current_state) and not vite_failed:
                    self._log(self.front_log, "SYSTEM", "Frontend startup is already in progress."); self.set_action_feedback("Frontend startup is already in progress.", "busy"); return
                if self.external_frontend:
                    self._log(self.front_log, "SYSTEM", "An externally managed frontend is active; this manager will not terminate it."); self.set_action_feedback("Frontend is owned by another session.", "warning"); return
                # Electron may have closed while npm/Vite is still completing its
                # shutdown. Ask the owned supervisor to finish cleanly before a
                # new stack is launched; the timer below is only a last-resort reap.
                self.front_restart_requested = True
                self.front_button.setEnabled(False)
                self.set_status(self.front_badge, "RESTARTING", "cleaning up previous session")
                self._log(self.front_log, "SYSTEM", "The previous desktop window is closed but its development supervisor is still alive. Stopping that owned process tree before relaunching.")
                self.set_action_feedback("Cleaning up the previous session before reopening…", "busy")
                self.front.write(b'{"type":"stop"}\n')
                QTimer.singleShot(55000, self.force_restart_frontend_cleanup)
                return
            self.front_button.setEnabled(False)
            self.frontend_start_pending = True
            try:
                directory, name, scripts = identify_frontend(); python = project_python()
                identify_backend()
                if "electron" not in scripts[name].lower(): directory, name = ROOT, "dev"
                root_pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
                if "dev" not in root_pkg.get("scripts", {}): raise RuntimeError("Root package.json has no dev command to start Electron + Vite.")
                required = [ROOT / "scripts" / "dev.cjs", ROOT / "frontend" / "electron" / "main" / "index.cjs",
                            ROOT / "frontend" / "vite.config.ts", ROOT / "frontend" / "node_modules" / "vite" / "bin" / "vite.js",
                            ROOT / "frontend" / "node_modules" / "electron"]
                missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
                if missing: raise RuntimeError("Frontend development files or dependencies are missing: " + ", ".join(missing) + ". Install frontend dependencies with 'npm --prefix frontend ci'.")
                npm = shutil.which("npm.cmd" if IS_WINDOWS else "npm")
                node = shutil.which("node.exe" if IS_WINDOWS else "node")
                if not npm or not node: raise RuntimeError("Node.js/npm not found. Install Node.js and add it to PATH.")
                # Windows cannot launch .cmd files directly. Passing a quoted npm.cmd
                # command through cmd.exe is also fragile when paths contain spaces.
                # Invoke npm's JS CLI with node so QProcess receives a structured argv.
                if IS_WINDOWS:
                    npm_cli = str(Path(npm).resolve().parent / "node_modules" / "npm" / "bin" / "npm-cli.js")
                    if not Path(npm_cli).is_file():
                        raise RuntimeError(f"Could not locate npm's JavaScript CLI beside {npm}. Reinstall Node.js or repair PATH.")
                    launch_executable, launch_prefix = node, npm_cli
                else:
                    launch_executable, launch_prefix = npm, ""
                self._frontend_launch = (directory, name, launch_executable, launch_prefix, python)
                req = QNetworkRequest(QUrl("http://127.0.0.1:5173/")); req.setTransferTimeout(1200)
                reply = self.probe.get(req); reply.finished.connect(lambda: self.front_probe_done(reply))
                self.set_status(self.front_badge, "STARTING", "checking Vite")
                self.set_action_feedback("Checking Vite and backend ownership…", "busy")
            except (RuntimeError, OSError, ValueError) as exc:
                self.frontend_start_pending = False
                self.set_status(self.front_badge, "ERROR", "configuration"); self._log(self.front_log, "ERROR", str(exc)); self.set_action_feedback(f"Frontend could not start: {exc}", "error"); self.front_button.setEnabled(True); QMessageBox.critical(self, "Frontend configuration", str(exc))

        def find_external_backends(self, callback: Any) -> None:
            """Check for the exact project venv + protocol entry point without blocking Qt."""
            if not IS_WINDOWS:
                callback([]); return
            try: python = str(Path(project_python()).resolve()).replace("'", "''")
            except RuntimeError: callback([]); return
            query = ("$exe='" + python + "'; Get-CimInstance Win32_Process | "
                     "Where-Object { $_.Name -match '^pythonw?\\.exe$' -and $_.ExecutablePath -ieq $exe "
                     "-and $_.CommandLine -match '(^|\\s)-m\\s+backend\\.protocol(\\s|$)' } | "
                     "Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress")
            probe = QProcess(self); probe.setProgram("powershell.exe")
            probe.setArguments(["-NoProfile", "-NonInteractive", "-Command", query]); probe.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            self.backend_probe = probe
            timer = QTimer(probe); timer.setSingleShot(True); timer.timeout.connect(probe.kill); timer.start(7000)
            complete = False
            def finished(code: int, _status: Any = None) -> None:
                nonlocal complete
                if complete: return
                complete = True
                timer.stop(); raw = bytes(probe.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
                probe.deleteLater(); self.backend_probe = None
                if code != 0:
                    callback(None); return
                try:
                    entries = json.loads(raw) if raw else []
                    matches = entries if isinstance(entries, list) else [entries]
                    pids = sorted({int(item["ProcessId"]) for item in matches if item.get("ProcessId")})
                except (ValueError, TypeError, KeyError):
                    pids = []
                callback(pids)
            probe.finished.connect(finished); probe.errorOccurred.connect(lambda _error: finished(-1)); probe.start()

        def front_probe_done(self, reply: Any) -> None:
            # A refused connection (the normal case when Vite is not running yet)
            # closes the reply device. Reading it unconditionally emits a Qt warning.
            if reply.error() == QNetworkReply.NetworkError.NoError and reply.isOpen():
                body = bytes(reply.readAll()).decode("utf-8", errors="replace")
            else:
                body = ""
            code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            reply.deleteLater()
            if code == 200 and "/@vite/client" in body:
                self.frontend_start_pending = False
                self.external_frontend = True; self.ready_frontend = False
                self.set_status(self.vite_badge, "RUNNING", "external Vite · HTTP ready")
                self.set_status(self.front_badge, "ERROR", "Electron readiness unavailable from external session")
                self._log(self.front_log, "SYSTEM", "Vite at 127.0.0.1:5173 is already active; no duplicate frontend launched.")
                self.set_action_feedback("Vite is already active; no duplicate frontend was started.", "success")
                if hasattr(self, "backend") and self.backend.state() != QProcess.ProcessState.NotRunning:
                    self.set_status(self.backend_badge, "STOPPING", "avoiding duplicate backend")
                    self._log(self.backend_log, "BACKEND", "Stopping the standalone backend because the external Electron stack owns its backend.")
                    self.backend.closeWriteChannel(); QTimer.singleShot(8000, self.force_stop_standalone_backend)
                else: self.front_button.setEnabled(True)
                return
            directory, name, executable, prefix, python = self._frontend_launch
            if not re.fullmatch(r"[A-Za-z0-9:_-]+", name):
                self.frontend_start_pending = False
                self.set_status(self.front_badge, "ERROR", "invalid npm script")
                self._log(self.front_log, "ERROR", "The detected npm script name contains unsupported characters; refusing to launch it.")
                return
            if hasattr(self, "backend") and self.backend.state() != QProcess.ProcessState.NotRunning:
                self.pending_frontend_launch = (directory, name, executable, prefix, python)
                self.set_status(self.backend_badge, "STOPPING", "avoiding duplicate backend")
                self._log(self.backend_log, "BACKEND", "Stopping the standalone backend before Electron starts its managed instance.")
                self.backend.closeWriteChannel()
                QTimer.singleShot(8000, self.force_stop_standalone_backend)
                return
            self.find_external_backends(lambda pids: self._launch_frontend_if_clear(pids, directory, name, executable, prefix, python))

        def _launch_frontend_if_clear(self, pids: list[int] | None, directory: Path, name: str, executable: str, prefix: str, python: str) -> None:
            if self.closing_down: self.frontend_start_pending = False; return
            if pids is None:
                self.frontend_start_pending = False
                self.set_status(self.front_badge, "ERROR", "process check failed"); self.front_button.setEnabled(True)
                self._log(self.front_log, "ERROR", "Could not safely check for an existing project backend. Confirm PowerShell/WMI is available and try again."); self.set_action_feedback("Could not verify backend ownership; frontend was not started.", "error"); return
            if pids:
                self.frontend_start_pending = False
                self.set_status(self.backend_badge, "ERROR", f"external process PID {pids[0]}")
                self.set_status(self.front_badge, "ERROR", "backend already active")
                self._log(self.backend_log, "ERROR", f"A matching backend process exists (PID {pids[0]}), but its health cannot be verified through its private stdio protocol. It is owned by another launcher; stop that session before starting Electron here to avoid a duplicate backend.")
                self.set_action_feedback("A backend from another session is active; stop it before launching this frontend.", "warning")
                self.front_button.setEnabled(True)
                return
            self._start_frontend_process(directory, name, executable, prefix, python)

        def _start_frontend_process(self, directory: Path, name: str, executable: str, prefix: str, python: str) -> None:
            env = QProcessEnvironment.systemEnvironment(); env.insert("NODE_ENV", "development"); env.insert("SOLRALOL_DEV_CONTROL_CENTER", "1"); env.insert("SOLRALOL_MANUAL_BACKEND", "1"); env.insert("SOLRALOL_PYTHON", python); env.insert("PYTHONUNBUFFERED", "1")
            env.insert("SOLRALOL_BACKEND_SHUTDOWN_TIMEOUT_MS", "45000"); env.insert("SOLRALOL_STACK_SHUTDOWN_TIMEOUT_MS", "55000")
            self.front.setProcessEnvironment(env); self.front.setWorkingDirectory(str(directory))
            arguments = ([prefix] if prefix else []) + ["run", name]
            self.vite_ready = self.electron_ready = self.ready_frontend = False
            self.managed_backend_pid = None
            self.front.start(executable, arguments)
            self.frontend_start_pending = False
            self.front_button.setEnabled(True)
            self._log(self.front_log, "SYSTEM", f"Starting npm run {name} from {directory}; no production build.")
            self.set_status(self.vite_badge, "STARTING", "waiting for HTTP readiness")
            self.set_status(self.front_badge, "STARTING", "waiting for Electron and renderer")
            self.set_status(self.backend_badge, "STARTING", "waiting for backend health response")
            self.arm_startup_deadline("vite", 45, self.vite_badge, "Vite HTTP readiness")
            self.arm_startup_deadline("electron", 60, self.front_badge, "Electron main and renderer readiness")
            self.arm_startup_deadline("backend", 60, self.backend_badge, "Python app.bootstrap health response")
            self.set_action_feedback("Starting Vite, Electron, and the managed Python backend…", "busy")

        def arm_startup_deadline(self, component: str, seconds: int, badge: Any, step: str) -> None:
            previous = self.startup_timers.pop(component, None)
            if previous: previous.stop(); previous.deleteLater()
            timer = QTimer(self); timer.setSingleShot(True)
            timer.timeout.connect(lambda: self.startup_deadline(component, badge, step))
            self.startup_timers[component] = timer; timer.start(seconds * 1000)

        def startup_deadline(self, component: str, badge: Any, step: str) -> None:
            active = self.front.state() != QProcess.ProcessState.NotRunning if component != "backend" else (
                self.front.state() != QProcess.ProcessState.NotRunning
                or (hasattr(self, "backend") and self.backend.state() != QProcess.ProcessState.NotRunning)
            )
            if not active: return
            state = badge.text()
            if "STARTING" not in state and "RESTARTING" not in state: return
            if component == "backend" and self.front.state() != QProcess.ProcessState.NotRunning:
                pid_detail = (f"managed Python PID {self.managed_backend_pid}"
                              if self.managed_backend_pid else f"Python PID unavailable; supervisor PID {int(self.front.processId())}")
            else:
                pid_detail = f"process PID {int(self.front.processId()) if self.front.state() != QProcess.ProcessState.NotRunning else int(self.backend.processId())}"
            detail = f"deadline exceeded; pending: {step}; {pid_detail}"
            self.set_status(badge, "ERROR", detail)
            if component == "backend":
                self.backend_restart_pending = False; self.backend_button.setEnabled(True)
            elif component == "electron": self.front_button.setEnabled(True)
            self._log(self.front_log if component != "backend" else self.backend_log, "ERROR", detail)
            self.set_action_feedback(f"Startup stalled at {step}; process remains alive for diagnosis.", "error")

        def handle_status_event(self, event: dict[str, Any]) -> None:
            component, state = event.get("component"), str(event.get("state", "")).upper()
            detail = str(event.get("detail") or "")
            pid = event.get("pid")
            if pid: detail = f"PID {pid} · {detail}" if detail else f"PID {pid}"
            if component == "vite":
                badge = self.vite_badge
                if state == "RUNNING":
                    self.vite_ready = True; self._cancel_startup_deadline("vite")
                elif state == "ERROR": self.vite_ready = False
            elif component == "electron":
                badge = self.front_badge
                if state in ("STARTING", "RESTARTING"):
                    self.electron_ready = self.ready_frontend = False
                    self.arm_startup_deadline("electron", 60, badge, "Electron main and renderer readiness")
                if state == "RUNNING":
                    self.electron_ready = self.ready_frontend = True; self._cancel_startup_deadline("electron")
                    self.front_button.setEnabled(True)
                    self.set_action_feedback("Electron main and renderer are ready.", "success")
                elif state in ("STOPPED", "ERROR"):
                    self.electron_ready = self.ready_frontend = False
                if state == "ERROR": self.front_button.setEnabled(True)
            elif component == "backend":
                badge = self.backend_badge
                if pid: self.managed_backend_pid = pid
                elif state == "STOPPED": self.managed_backend_pid = None
                if state in ("STARTING", "RESTARTING"):
                    self.backend_restart_pending = True; self.backend_button.setEnabled(False)
                    self.arm_startup_deadline("backend", 60, badge, "Python app.bootstrap health response")
                if state == "RUNNING":
                    self._cancel_startup_deadline("backend")
                    self.backend_restart_pending = False; self.backend_button.setEnabled(True)
                    self.set_action_feedback("Python backend passed its health check.", "success")
                elif state == "ERROR":
                    self._cancel_startup_deadline("backend")
                    self.backend_restart_pending = False; self.backend_button.setEnabled(True)
                    self.set_action_feedback("Python backend failed; see backend output.", "error")
                elif state == "RESTARTING": self.backend_restart_pending = True
                self._log(self.backend_log, "BACKEND STATUS", f"{state} {detail}".strip())
            else: return
            if state not in {"STOPPED", "STARTING", "RUNNING", "STOPPING", "RESTARTING", "ERROR"}: return
            display = "STARTING" if state == "RESTARTING" else state
            self.set_status(badge, display, detail)

        def _cancel_startup_deadline(self, component: str) -> None:
            timer = self.startup_timers.pop(component, None)
            if timer: timer.stop(); timer.deleteLater()

        def read_front(self) -> None:
            for line in self.read_complete_lines("front_pending", bytes(self.front.readAllStandardOutput())):
                if not line.strip(): continue
                if line.startswith(STATUS_PREFIX):
                    try: self.handle_status_event(json.loads(line[len(STATUS_PREFIX):]))
                    except (ValueError, TypeError): self._log(self.front_log, "ERROR", "Malformed structured lifecycle event")
                    continue
                low = line.lower()
                if "[solralol-backend]" in low or "backend process" in low or "backend ready" in low or "backend " in low and ("restart" in low or "exited" in low):
                    self._log(self.backend_log, "BACKEND", line)
                else: self._log(self.front_log, "ELECTRON" if any(x in low for x in ("electron", "renderer", "window")) else "VITE", line)

        def front_finished(self, code: int, exit_status: Any) -> None:
            self.read_front()
            for line in self.read_complete_lines("front_pending", b"", final=True):
                self._log(self.front_log, "ELECTRON", line)
            if not self.closing_down:
                clean_exit = code == 0 and exit_status == QProcess.ExitStatus.NormalExit
                final_state = "STOPPED" if clean_exit else "ERROR"
                if not any(state in self.front_badge.text() for state in ("STOPPED", "ERROR")):
                    self.set_status(self.front_badge, final_state, f"supervisor exit {code}")
                if not any(state in self.vite_badge.text() for state in ("STOPPED", "ERROR")):
                    self.set_status(self.vite_badge, final_state, f"supervisor exit {code}")
                # This QProcess owns the complete npm → Vite → Electron stack. Once
                # its supervisor exits, its managed backend is no longer running.
                backend_process_stopped = (
                    not hasattr(self, "backend")
                    or self.backend.state() == QProcess.ProcessState.NotRunning
                )
                if not self.external_frontend and backend_process_stopped:
                    self.set_status(self.backend_badge, "STOPPED" if clean_exit else "ERROR", "stack exited")
                self.set_action_feedback("Development stack stopped." if clean_exit else f"Development stack exited unexpectedly (code {code}).", "info" if clean_exit else "error")
            self.ready_frontend = self.external_frontend = False
            self.frontend_start_pending = False
            self.vite_ready = self.electron_ready = False
            for component in tuple(self.startup_timers): self._cancel_startup_deadline(component)
            self.front_button.setEnabled(True)
            if self.front_restart_requested and not self.closing_down:
                self.front_restart_requested = False
                QTimer.singleShot(0, self.start_frontend)

        def force_restart_frontend_cleanup(self) -> None:
            if not self.front_restart_requested or self.front.state() == QProcess.ProcessState.NotRunning:
                return
            self._log(self.front_log, "ERROR", "The previous development supervisor did not exit cleanly; force-stopping its owned process tree before relaunch.")
            pid = int(self.front.processId())
            if IS_WINDOWS and pid:
                self.kill_process_tree(pid)
            else:
                self.front.kill()

        def front_error(self, error: Any) -> None:
            if error == QProcess.ProcessError.FailedToStart:
                self.frontend_start_pending = False
                self.set_status(self.front_badge, "ERROR", self.front.errorString()); self.set_status(self.vite_badge, "ERROR", self.front.errorString()); self._log(self.front_log, "ERROR", self.front.errorString()); self.set_action_feedback("Frontend process failed to launch.", "error")

        def restart_backend(self) -> None:
            if self.backend_restart_pending:
                self._log(self.backend_log, "SYSTEM", "A backend restart is already in progress."); self.set_action_feedback("Backend restart is already in progress.", "busy"); return
            self.set_action_feedback("Checking backend status…", "busy")
            if self.front.state() != QProcess.ProcessState.NotRunning:
                if self.external_frontend:
                    self._log(self.backend_log, "ERROR", "Frontend is externally owned; stop it and relaunch from this control center to manage its backend."); self.set_status(self.backend_badge, "ERROR", "external owner"); self.set_action_feedback("Backend belongs to an external frontend session.", "warning"); return
                if not self.ready_frontend:
                    self._log(self.backend_log, "SYSTEM", "Wait for Electron and its backend startup to become ready before requesting a restart."); self.set_action_feedback("Wait until Electron and the backend finish starting.", "warning"); return
                backend_text = self.backend_badge.text()
                if "STARTING" in backend_text or "RESTARTING" in backend_text:
                    self.set_action_feedback("Backend startup or restart is already in progress.", "busy"); return
                self.backend_restart_pending = True; self.backend_button.setEnabled(False)
                self.set_status(self.backend_badge, "RESTARTING", "requesting shutdown")
                self._log(self.backend_log, "BACKEND", "Existing process detected (owned by Electron). Requesting graceful shutdown…")
                self.set_action_feedback("Restarting the Electron-managed Python backend…", "busy")
                self.front.write((json.dumps({"type":"restart-backend"}) + "\n").encode()); return
            # Standalone backend is allowed only when Electron is not running.
            try: python = project_python(); args, cwd = identify_backend()
            except (RuntimeError, OSError) as exc:
                self.set_status(self.backend_badge, "ERROR", "configuration"); self._log(self.backend_log, "ERROR", str(exc)); self.set_action_feedback(f"Backend could not start: {exc}", "error"); QMessageBox.critical(self, "Backend configuration", str(exc)); return
            if not hasattr(self, "backend"):
                self.backend = QProcess(self); self.backend.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
                self.backend.readyReadStandardOutput.connect(self.read_backend); self.backend.finished.connect(self.backend_finished)
                self.backend.started.connect(self.backend_health_check)
                self.backend.errorOccurred.connect(self.backend_error)
            if self.backend.state() != QProcess.ProcessState.NotRunning:
                self.backend_restart_pending = True; self.backend_button.setEnabled(False)
                self.set_status(self.backend_badge, "RESTARTING", "graceful shutdown"); self._log(self.backend_log, "BACKEND", "Requesting graceful shutdown of previous instance…")
                self.backend.closeWriteChannel(); QTimer.singleShot(8000, self.force_stop_standalone_backend); return
            self.find_external_backends(lambda pids: self._start_standalone_if_clear(pids, python, args, cwd))

        def _start_standalone_if_clear(self, pids: list[int] | None, python: str, args: list[str], cwd: Path) -> None:
            if self.closing_down: return
            if pids is None:
                self.set_status(self.backend_badge, "ERROR", "process check failed")
                self._log(self.backend_log, "ERROR", "Could not safely check for an existing project backend. No backend was started."); self.set_action_feedback("Could not verify backend ownership; nothing was launched.", "error"); return
            if pids:
                self.set_status(self.backend_badge, "ERROR", f"PID {pids[0]} · external health unverified")
                self._log(self.backend_log, "BACKEND", f"Matching Solralol backend already running (PID {pids[0]}). It belongs to another launcher; restart that session there to avoid duplicate or unsafe termination.")
                self.set_action_feedback(f"Backend is already running in another session (PID {pids[0]}).", "warning")
                return
            env = QProcessEnvironment.systemEnvironment(); env.insert("PYTHONUNBUFFERED", "1"); env.insert("PYTHONPATH", str(ROOT))
            self.backend.setProcessEnvironment(env); self.backend.setWorkingDirectory(str(cwd)); self.backend.start(python, args)
            self.backend_restart_pending = True; self.backend_button.setEnabled(False)
            self.set_status(self.backend_badge, "STARTING", "starting Python"); self._log(self.backend_log, "BACKEND", f"Starting Python backend: {python} {' '.join(args)}")
            self.arm_startup_deadline("backend", 60, self.backend_badge, "standalone Python app.bootstrap health response")
            self.set_action_feedback("Python backend launched; waiting for its health check…", "busy")
        def backend_health_check(self) -> None:
            self.backend.write(b'{"protocol":1,"id":"dev-health","method":"app.bootstrap","params":{}}\n')

        def backend_error(self, error: Any) -> None:
            if error == QProcess.ProcessError.FailedToStart:
                self._cancel_startup_deadline("backend")
                self.backend_restart_pending = False; self.backend_button.setEnabled(True)
                self.set_status(self.backend_badge, "ERROR", "could not launch")
                self._log(self.backend_log, "ERROR", self.backend.errorString())
                self.set_action_feedback("Backend process failed to launch.", "error")

        def read_backend(self) -> None:
            for line in self.read_complete_lines("backend_pending", bytes(self.backend.readAllStandardOutput())):
                try: msg = json.loads(line)
                except ValueError: self._log(self.backend_log, "BACKEND", line); continue
                if msg.get("id") == "dev-health":
                    self._cancel_startup_deadline("backend")
                    self.backend_restart_pending = False; self.backend_button.setEnabled(True)
                    if msg.get("ok") is True:
                        self.set_status(self.backend_badge, "RUNNING", f"PID {int(self.backend.processId())}"); self._log(self.backend_log, "BACKEND", f"Backend ready (PID {int(self.backend.processId())})."); self.set_action_feedback("Python backend passed its health check.", "success")
                    else:
                        self.set_status(self.backend_badge, "ERROR", "health check failed"); self._log(self.backend_log, "ERROR", str(msg.get("error", "Backend health request failed"))); self.set_action_feedback("Backend health check failed; see backend output.", "error")

        def backend_finished(self, code: int, exit_status: Any) -> None:
            if self.pending_frontend_launch:
                args=self.pending_frontend_launch; self.pending_frontend_launch=None
                self.backend_restart_pending = False
                self._log(self.backend_log,"BACKEND","Standalone backend stopped; starting Electron-owned backend.")
                self._start_frontend_process(*args)
            elif not self.closing_down and "RESTARTING" in self.backend_badge.text(): QTimer.singleShot(150, self._restart_standalone_after_stop)
            elif not self.closing_down:
                clean_exit = code == 0 and exit_status == QProcess.ExitStatus.NormalExit
                self.set_status(self.backend_badge, "STOPPED" if clean_exit else "ERROR", f"exit {code}")
                self.set_action_feedback("Backend stopped." if clean_exit else f"Backend exited unexpectedly with code {code}.", "info" if clean_exit else "error")
            if self.front.state() == QProcess.ProcessState.NotRunning: self.front_button.setEnabled(True)

        def _restart_standalone_after_stop(self) -> None:
            self.backend_restart_pending = False; self.backend_button.setEnabled(True); self.restart_backend()

        def run_tests(self) -> None:
            if self.tests.state() != QProcess.ProcessState.NotRunning:
                self.set_action_feedback("The test suite is already running.", "busy")
                return
            self.set_action_feedback("Preparing pytest discovery in tests/…", "busy")
            try: python = project_python()
            except RuntimeError as exc:
                self.set_action_feedback(f"Tests could not start: {exc}", "error")
                QMessageBox.critical(self, "Python environment", str(exc)); return
            self.total = self.completed = 0; self.counts = {"passed":0,"failed":0,"skipped":0,"error":0}; self.test_collection_errors = False; self.results = []; self.table.setRowCount(0); self.details.clear()
            self.test_started = time.monotonic(); self.progress.setRange(0, 0); self.progress_label.setText("Discovering tests…"); self.summary.setText("Test discovery running")
            env = QProcessEnvironment.systemEnvironment(); env.insert("PYTHONUNBUFFERED", "1"); env.insert("CI", "1"); env.insert("PYTEST_ADDOPTS", "")
            self.tests.setProcessEnvironment(env); self.tests.setWorkingDirectory(str(ROOT)); self.tests.start(python, [str(Path(__file__).resolve()), "--pytest-worker"])
            self.set_status(self.test_badge, "RUNNING", "discovering tests"); self.cancel.setEnabled(True); self.run_button.setEnabled(False); self.run_small.setEnabled(False)
            self.set_action_feedback("Pytest is discovering tests; the dashboard will stay open when they finish.", "busy")
            self.tabs.setCurrentIndex(2)
            self._log(self.test_page, "TESTS", "Starting pytest discovery in tests/. The total is collected from pytest, not hardcoded.")
            self._log(self.test_page, "TESTS", "Frontend package has no test script. scratch/ and app/scratch/ contain manual/rehearsal scripts and are excluded from automatic pytest runs.")

        def read_tests(self) -> None:
            for line in self.read_complete_lines("tests_pending", bytes(self.tests.readAllStandardOutput())):
                if line.startswith(EVENT_PREFIX):
                    try: self.test_event(json.loads(line[len(EVENT_PREFIX):]))
                    except (ValueError, TypeError): self._log(self.test_page, "TESTS", "Malformed test event: " + line)
                elif line.strip(): self._log(self.test_page, "PYTEST", line)

        def test_event(self, event: dict[str, Any]) -> None:
            if event.get("kind") == "total":
                self.total = int(event.get("total", 0)); self.progress.setRange(0, max(1, self.total)); self._progress_label(); return
            if event.get("kind") == "result":
                status = event.get("status", "error"); status = status if status in self.counts else "error"
                self.completed += 1; self.counts[status] += 1
                item = {"name":str(event.get("name","unknown")),"status":status,"error":str(event.get("error","")),"duration":float(event.get("duration",0) or 0)}; self.results.append(item)
                if status == "error" and item["name"].startswith("collection:"): self.test_collection_errors = True
                r=self.table.rowCount(); self.table.insertRow(r); label={"passed":"PASS","failed":"FAIL","skipped":"SKIP","error":"ERROR"}[status]
                self.table.setItem(r,0,QTableWidgetItem(label)); self.table.setItem(r,1,QTableWidgetItem(item["name"])); self.table.setItem(r,2,QTableWidgetItem(f"{item['duration']:.2f}s"))
                self.table.item(r,0).setForeground(QColor({"passed":"#49bf87","failed":"#ef6868","skipped":"#d6a64b","error":"#ef6868"}[status]))
                self.progress.setValue(self.completed); self._progress_label(); self.summary.setText(f"{self.counts['passed']} passed · {self.counts['failed']} failed · {self.counts['skipped']} skipped · {self.counts['error']} errors")
                self._log(self.test_page,"TEST",f"{self.completed}/{self.total or '?'} {label} {item['name']}"); return
            if event.get("kind") == "finished": self.finish_tests(int(event.get("exit_code",1)))

        def _progress_label(self) -> None: self.progress_label.setText(f"Tests completed: {self.completed} / {self.total}")

        def finish_tests(self, code: int) -> None:
            elapsed=time.monotonic()-self.test_started; incomplete=self.completed != self.total or code not in (0,1) or self.test_collection_errors
            state="ERROR" if incomplete or self.counts["failed"] or self.counts["error"] else "STOPPED"
            self.set_status(self.test_badge, state, f"{elapsed:.1f}s")
            note="Collection errors prevented complete test discovery · " if self.test_collection_errors else ""
            self.summary.setText(f"{'INCOMPLETE · ' if incomplete else 'TEST EXECUTION COMPLETED · '}{note}{self.counts['passed']} passed · {self.counts['failed']} failed · {self.counts['skipped']} skipped · {self.counts['error']} errors · {self.completed}/{self.total} · {elapsed:.1f}s")
            self.cancel.setEnabled(False); self.run_button.setEnabled(True); self.run_small.setEnabled(True); self._log(self.test_page,"TESTS",self.summary.text())
            if incomplete or self.counts["failed"] or self.counts["error"]:
                self.set_action_feedback(f"Tests finished with issues: {self.counts['failed']} failed, {self.counts['error']} errors.", "error")
            elif self.counts["skipped"]:
                self.set_action_feedback(f"Tests finished: {self.counts['passed']} passed, {self.counts['skipped']} skipped.", "warning")
            else:
                self.set_action_feedback(f"All {self.completed} discovered tests passed in {elapsed:.1f}s.", "success")

        def tests_finished(self, code: int, _status: Any) -> None:
            self.read_tests()
            for line in self.read_complete_lines("tests_pending", b"", final=True):
                self._log(self.test_page, "PYTEST", line)
            if self.cancel.isEnabled(): self.finish_tests(code)
            if not self.closing_down and not self.isVisible():
                self.show()

        def test_error(self, error: Any) -> None:
            if error == QProcess.ProcessError.FailedToStart:
                self.summary.setText("Test runner failed to start: " + self.tests.errorString()); self.cancel.setEnabled(False); self.run_button.setEnabled(True); self.run_small.setEnabled(True); self.set_status(self.test_badge, "ERROR", "could not launch"); self.set_action_feedback("Test runner failed to launch.", "error")

        def cancel_tests(self) -> None:
            if self.tests.state() == QProcess.ProcessState.NotRunning:
                self.set_action_feedback("There is no test run to cancel.", "info")
                return
            self.tests.terminate(); self.set_status(self.test_badge, "STOPPING", "cancelling tests"); self.set_action_feedback("Cancelling the test runner and its owned children…", "busy"); self.kill_timer.start(1800)

        def force_cancel_tests(self) -> None:
            if self.tests.state() != QProcess.ProcessState.NotRunning:
                if IS_WINDOWS: self.kill_process_tree(int(self.tests.processId()))
                else: self.tests.kill()

        def kill_process_tree(self, pid: int) -> None:
            killer = QProcess(self)
            killer.finished.connect(lambda *_: killer.deleteLater())
            killer.start("taskkill.exe", ["/PID", str(pid), "/T", "/F"])

        def force_stop_standalone_backend(self) -> None:
            if self.backend.state() == QProcess.ProcessState.NotRunning: return
            self._log(self.backend_log, "BACKEND", "Graceful shutdown timed out; forcing termination of the owned backend process tree.")
            if IS_WINDOWS: self.kill_process_tree(int(self.backend.processId()))
            else: self.backend.kill()

        def clear_tests(self) -> None:
            self.table.setRowCount(0); self.details.clear(); self.test_log.clear(); self.summary.setText("Test output cleared"); self.progress.setRange(0,1); self.progress.setValue(0); self.progress_label.setText("Tests completed: 0 / 0")
            self.set_action_feedback("Test output cleared.", "info")

        def show_detail(self) -> None:
            rows=self.table.selectionModel().selectedRows()
            if rows:
                x=self.results[rows[0].row()]; self.details.setPlainText(f"{x['status'].upper()} · {x['name']}\nDuration: {x['duration']:.3f}s\n\n{x['error'] or 'No failure details.'}")

        def stop_everything(self) -> None:
            if self.closing_down:
                self.set_action_feedback("Shutdown is already in progress…", "busy")
                return
            self.closing_down=True; self.pending_frontend_launch=None; self.stop_button.setEnabled(False)
            self.set_action_feedback("Stopping managed frontend, backend, and test processes…", "busy")
            managed_active = (
                self.front.state() != QProcess.ProcessState.NotRunning
                or self.tests.state() != QProcess.ProcessState.NotRunning
                or bool(self.backend_probe and self.backend_probe.state() != QProcess.ProcessState.NotRunning)
                or (hasattr(self, "backend") and self.backend.state() != QProcess.ProcessState.NotRunning)
            )
            if not managed_active:
                self._log(self.front_log, "SYSTEM", "Stop Everything requested; no managed processes were running.")
            if self.backend_probe and self.backend_probe.state() != QProcess.ProcessState.NotRunning: self.backend_probe.kill()
            if self.tests.state() != QProcess.ProcessState.NotRunning: self.cancel_tests()
            if self.external_frontend: self._log(self.front_log,"SYSTEM","External frontend is not owned by this manager and was left untouched.")
            elif self.front.state() != QProcess.ProcessState.NotRunning:
                self.set_status(self.front_badge,"STOPPING","graceful shutdown"); self.front.write(b'{"type":"stop"}\n'); QTimer.singleShot(55000,self.force_stop_frontend)
            if hasattr(self,"backend") and self.backend.state() != QProcess.ProcessState.NotRunning:
                self.backend.closeWriteChannel(); QTimer.singleShot(8000,self.force_stop_standalone_backend)
            self.check_stop()

        def force_stop_frontend(self) -> None:
            if self.front.state() != QProcess.ProcessState.NotRunning:
                pid=int(self.front.processId())
                if IS_WINDOWS: self.kill_process_tree(pid)
                else: self.front.kill()
            self.check_stop()

        def check_stop(self) -> None:
            front=self.front.state()==QProcess.ProcessState.NotRunning or self.external_frontend
            backend=not hasattr(self,"backend") or self.backend.state()==QProcess.ProcessState.NotRunning
            probe=not self.backend_probe or self.backend_probe.state()==QProcess.ProcessState.NotRunning
            if front and backend and probe and self.tests.state()==QProcess.ProcessState.NotRunning:
                if not self.shutdown_close_pending:
                    self.shutdown_close_pending = True
                    self.set_action_feedback("Shutdown complete. Closing the control center…", "success")
                    self._log(self.front_log, "SYSTEM", "All managed processes have stopped; closing the control center.")
                    QTimer.singleShot(900, self.close)
            else: QTimer.singleShot(250,self.check_stop)

        def closeEvent(self,event:Any)->None:
            active=self.front.state()!=QProcess.ProcessState.NotRunning or self.tests.state()!=QProcess.ProcessState.NotRunning or bool(self.backend_probe and self.backend_probe.state()!=QProcess.ProcessState.NotRunning) or (hasattr(self,"backend") and self.backend.state()!=QProcess.ProcessState.NotRunning)
            if active:
                event.ignore()
                if not self.closing_down: self.stop_everything()
            else:
                event.accept()
                QTimer.singleShot(0, app.quit)

    window=Dashboard(); window.show(); sys.exit(app.exec())


if __name__ == "__main__":
    if "--pytest-worker" in sys.argv:
        sys.exit(pytest_worker())
    try:
        main()
    except RuntimeError as exc:
        sys.stderr.write(f"[ERROR] {exc}\n")
        sys.exit(2)


