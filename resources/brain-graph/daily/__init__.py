"""
Brain Daily Ingest — Cornelius automation package.

Sweeps "anywhere on disk" for new files, classifies and routes them into
the Brain vault layers, invokes Cornelius skills for insight extraction,
re-runs BDG bootstrap + Neo4j load, and writes a daily digest.

Entry point:
    python -m daily.cli run [--dry-run] [--max-cost-cents N]
    python -m daily.cli rollback YYYY-MM-DD

Version history:
    0.1.0  2026-05-13  Initial scaffold
"""

__version__ = "0.1.0"
__author__ = "Cornelius / Zeus"
