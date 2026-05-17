# ZEUS Brain Console

Local read-only dashboard for the git-backed Brain wiki and Neo4j/BDG indexes.

## Run

```bash
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 server.py
```

Open:

```text
http://localhost:8789
```

## Data Sources

- Wiki: `/Users/erichroepke/Desktop/Brain/wiki`
- BDG sidecar: `/Users/erichroepke/Cornelius/resources/brain-graph/data/graph_enrichments.json`
- FAISS metadata: `/Users/erichroepke/Cornelius/resources/local-brain-search/data/brain_metadata.pkl`
- Neo4j: configured from `/Users/erichroepke/Cornelius/resources/brain-graph/.env`

The browser never receives the Neo4j password. The server reads credentials locally and exposes only read-only status/search endpoints.
