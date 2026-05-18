import json, subprocess
from pathlib import Path

PASS = subprocess.check_output(['bash', '-c', 'grep BRAIN_NEO4J_PASS /Users/erichroepke/Desktop/Cornelius/resources/brain-graph/.env | cut -d= -f2']).decode().strip()

for pass_name, threshold in [('firstpass', 0.85), ('secondpass', 0.85)]:
    dir_path = Path(f'/Users/erichroepke/Desktop/Cornelius/resources/brain-graph/data/team-b-{pass_name}')
    edges = []
    for f in sorted(dir_path.glob('proposals-*.jsonl')):
        for line in f.read_text().splitlines():
            line = line.strip()
            if line:
                e = json.loads(line)
                if e['confidence'] >= threshold:
                    edges.append(e)

    cypher_lines = []
    for e in edges:
        anchor = e['anchor'].replace("'", "\\'")
        target = e['target'].replace("'", "\\'")
        edge_type = e['edge_type']
        rationale = e['rationale'].replace("'", "\\'").replace('\n', ' ')[:200]
        conf = e['confidence']
        direction = e['direction']
        if direction == 'A->B':
            from_id, to_id = anchor, target
        elif direction == 'B->A':
            from_id, to_id = target, anchor
        elif direction == 'bidirectional':
            from_id, to_id = sorted([anchor, target])
        else:
            continue
        stmt = (
            f"MATCH (a:Atom {{id:'{from_id}'}}), (b:Atom {{id:'{to_id}'}}) "
            f"MERGE (a)-[r:{edge_type}]->(b) "
            f"SET r.confidence={conf}, r.source='team-b-{pass_name}-2026-05-15', "
            f"r.rationale='{rationale}', r.bidirectional={'true' if direction == 'bidirectional' else 'false'};"
        )
        cypher_lines.append(stmt)

    print(f"{pass_name}: {len(cypher_lines)} statements")
    if cypher_lines:
        result = subprocess.run(
            ['docker', 'exec', '-i', 'zeus-brain-neo4j',
             'cypher-shell', '-u', 'neo4j', '-p', PASS, '--format', 'plain'],
            input='\n'.join(cypher_lines), capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(f"STDERR: {result.stderr[:500]}")
        else:
            print(f"{pass_name}: OK")
    else:
        print(f"{pass_name}: no edges above threshold")

# Verify
verify = subprocess.run(
    ['docker', 'exec', 'zeus-brain-neo4j',
     'cypher-shell', '-u', 'neo4j', '-p', PASS,
     "MATCH ()-[r]->() WHERE r.source STARTS WITH 'team-b' RETURN r.source AS src, type(r) AS t, count(r) AS n ORDER BY src, t"],
    capture_output=True, text=True, timeout=60,
)
print(verify.stdout)
