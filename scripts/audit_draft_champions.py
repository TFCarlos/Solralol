"""Print a non-destructive offline identity/source audit; run as a module."""

from __future__ import annotations

import json
from collections import Counter

from _paths import DATA_DIR
from app.services.draft_analyzer_service import DraftAnalyzerService
from app.services.identidad_campeon import ALIAS_CAMPEONES, cargar_indice_campeones
from app.services.repositorio_campeones import RepositorioCampeones
from backend.draft_diagnostics import audit_draft_catalog


def main() -> None:
    repository = RepositorioCampeones()
    catalog_path = repository.raiz.parent / "champion_catalog.json"
    catalog = json.loads((catalog_path if catalog_path.is_file() else DATA_DIR / "champion_catalog.json").read_text(encoding="utf-8"))
    entries = list(catalog["data"].values())
    analyzer = DraftAnalyzerService()
    rows = audit_draft_catalog(entries, repository, analyzer)
    index = cargar_indice_campeones(repository.raiz.parent / "champion_catalog.json")
    unresolved = sorted(alias for alias, target in ALIAS_CAMPEONES.items()
                        if not index.resolve(alias) or index.resolve(alias) != index.resolve(target))
    print(json.dumps({"catalogVersion": catalog.get("version"), "count": len(rows),
                      "statusCounts": dict(Counter(row["status"] for row in rows)),
                      "ambiguousAliases": {key: sorted(value) for key, value in index.ambiguous.items()},
                      "duplicateLocalRecords": {key: [str(path.name) for path in paths]
                                                for key, paths in repository.duplicate_identities.items()},
                      "unresolvedAliases": unresolved,
                      "sourceGaps": [{"id": row["id"], "missing": [key for key, present in row.get("sources", {}).items() if not present]}
                                     for row in rows if any(not present for present in row.get("sources", {}).values())],
                      "issues": [row for row in rows if row["status"] != "available"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
