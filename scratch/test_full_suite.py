"""Suite única: ejecuta todas las pruebas del proyecto relacionadas con el draft.

Ejecutar con: .venv\\Scripts\\python.exe scratch/test_full_suite.py
Devuelve código 0 solo si todas las pruebas pasan.
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["PYTHONIOENCODING"] = "utf-8"

TESTS = [
    "test_fase1.py",
    os.path.join("scratch", "test_draft_winrate_fix.py"),
    os.path.join("scratch", "test_draft_analyzer.py"),
    os.path.join("scratch", "test_draft_redesign.py"),
    os.path.join("scratch", "test_lcu_itemset_flow.py"),
]

failed: list[str] = []
for test in TESTS:
    print(f"\n===== {test} =====", flush=True)
    result = subprocess.run(
        [sys.executable, test],
        cwd=ROOT,
        timeout=300,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    if result.returncode != 0:
        failed.append(test)

print()
if failed:
    print(f"SUITES FALLIDAS: {failed}")
    sys.exit(1)
print("SUITE COMPLETA: TODAS LAS PRUEBAS PASARON")