from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from niklas.ingest import ingest_path
from niklas.retrieval import build_context_pack
from niklas.store import NiklasStore


def test_fts5_indexing_and_search_query(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    # Write a note containing search terms
    note = project / "workflow.md"
    note.write_text(
        "---\ntitle: Proxy Editing Process\ntags: [proxy, video, premiere]\n---\n"
        "# Proxy Editing Process\n\n"
        "This describes how we optimize video editing by using proxy files. "
        "Create lightweight ProRes proxy clips before review.\n",
        encoding="utf-8",
    )

    db_path = tmp_path / "niklas.sqlite"
    ingest_path(project, project_scope="Studio", db_path=db_path)

    store = NiklasStore(db_path)

    # 1. Verify index is populated
    fts_rows = sqlite3_fts_rows(db_path)
    assert len(fts_rows) >= 2  # The source node and the note node

    # 2. Search using terms that match
    results = store.search_nodes("proxy editing process", project_scope="Studio")
    assert len(results) >= 1
    assert any(r["title"] == "Proxy Editing Process" for r in results)

    # 3. Search using tag term
    results_tag = store.search_nodes("premiere", project_scope="Studio")
    assert len(results_tag) == 1
    assert "premiere" in results_tag[0]["tags"]

    # 4. Search using body term
    results_body = store.search_nodes("lightweight", project_scope="Studio")
    assert len(results_body) == 1
    assert "lightweight" in results_body[0]["content_preview"]


def sqlite3_fts_rows(db_path: Path) -> list:
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT * FROM nodes_fts").fetchall()
    finally:
        conn.close()
