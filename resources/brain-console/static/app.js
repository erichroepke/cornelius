const state = {
  status: null,
  selectedNode: null,
};

const $ = (id) => document.getElementById(id);
const fmt = (n) => Number.isFinite(Number(n)) ? Number(n).toLocaleString() : "-";

async function getJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value ?? "-";
}

function setPanel(name) {
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === name));
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.panel === name));
  const labels = {
    overview: ["Overview", "Search coverage, graph state, and ingest readiness for the local Brain."],
    search: ["Search", "Find indexed notes by path or content and jump into the graph view."],
    graph: ["Graph", "Inspect a node and its immediate relationships without rendering the whole database."],
    files: ["Files", "Inspect mounted volumes, registered sources, chunk coverage, and sync drift."],
    sources: ["Sources", "Show the consolidation registry and source coverage."],
    health: ["Health", "Check what is indexed, what is missing, and which services are alive."],
  };
  setText("pageTitle", labels[name][0]);
  setText("subtitle", labels[name][1]);
}

function renderStatus(data) {
  state.status = data;
  const files = data.files || {};
  const bdg = data.bdg || {};
  const faiss = data.faiss || {};
  const neo4j = data.neo4j || {};

  setText("markdownCount", fmt(files.total_markdown));
  setText("nodeCount", fmt(bdg.nodes));
  setText("edgeCount", fmt(bdg.edges));
  setText("chunkCount", fmt(faiss.chunk_count));
  setText("brainRoot", data.paths?.brain_root);
  setText("gitHead", data.git?.head);
  setText("lastBootstrap", bdg.last_bootstrap);
  setText("faissUpdated", faiss.updated_at);

  const coverage = files.total_markdown ? Math.max(0, Math.min(100, (bdg.nodes / files.total_markdown) * 100)) : 0;
  $("coverageFill").style.width = `${coverage.toFixed(1)}%`;
  setText("coverageBadge", `${coverage.toFixed(1)}%`);

  const dot = $("daemonDot");
  dot.className = `dot ${neo4j.reachable ? "ok" : "bad"}`;
  setText("daemonText", neo4j.reachable ? "Neo4j connected" : "Neo4j offline");

  setText("neo4jHealth", neo4j.reachable ? `${fmt(neo4j.atoms)} atoms` : (neo4j.error || "offline"));
  setText("faissHealth", faiss.exists ? `${fmt(faiss.chunk_count)} chunks` : "missing");
  setText("bdgHealth", bdg.exists ? `${fmt(bdg.nodes)} nodes / ${fmt(bdg.edges)} edges` : "missing");
  setText("registryHealth", data.registry?.exists ? "present" : "missing");
  setText("missingCount", fmt(files.missing_count));

  renderLayerBars(neo4j.layers || []);
  renderMissing(files.missing_from_graph || []);
}

function renderLayerBars(layers) {
  const root = $("layerBars");
  root.innerHTML = "";
  const max = Math.max(1, ...layers.map((l) => l.count || 0));
  for (const item of layers) {
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML = `
      <span>${item.layer || "none"}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${((item.count || 0) / max) * 100}%"></div></div>
      <strong>${fmt(item.count)}</strong>
    `;
    root.appendChild(row);
  }
}

function renderMissing(items) {
  const root = $("missingList");
  root.innerHTML = "";
  if (!items.length) {
    root.innerHTML = `<div class="result"><h4>Everything discovered is represented in the graph sidecar.</h4></div>`;
    return;
  }
  for (const item of items.slice(0, 80)) {
    const row = document.createElement("div");
    row.className = "result";
    row.innerHTML = `<h4>${escapeHtml(item)}</h4>`;
    root.appendChild(row);
  }
}

function stripFrontmatter(value) {
  return String(value || "").replace(/^---[\s\S]*?---\s*/, "").trim();
}

function resultPreview(item) {
  return stripFrontmatter(item.preview) || stripFrontmatter(item.title) || stripFrontmatter(item.heading) || "No preview available.";
}

function resultCard(item) {
  const card = document.createElement("article");
  card.className = "result";
  const preview = resultPreview(item);
  card.innerHTML = `
    <div class="meta-line">
      <span class="mini">${escapeHtml(item.layer || "unknown")}</span>
      <span class="mini">${escapeHtml(item.source || "search")}</span>
      ${item.degree !== null && item.degree !== undefined ? `<span class="mini">degree ${fmt(item.degree)}</span>` : ""}
    </div>
    <h4>${escapeHtml(item.id)}</h4>
    <p>${escapeHtml(preview)}</p>
  `;
  card.addEventListener("click", () => {
    $("nodeInput").value = item.id;
    setPanel("graph");
    loadNode(item.id);
  });
  return card;
}

async function runSearch() {
  const query = $("searchInput").value.trim();
  const root = $("searchResults");
  if (!query) return;
  setText("searchSummary", `Searching for “${query}”...`);
  root.innerHTML = `<div class="notice"><strong>Searching Brain...</strong><span>Checking graph paths and note content.</span></div>`;
  try {
    const data = await getJson(`/api/search?q=${encodeURIComponent(query)}&limit=25`);
    root.innerHTML = "";
    const results = data.results || [];
    setText("searchSummary", `${fmt(results.length)} results for “${query}”. Click a result to inspect its graph neighborhood.`);
    if (!results.length) {
      root.innerHTML = `<div class="notice"><strong>No results</strong><span>Try a broader term or a filename fragment.</span></div>`;
      return;
    }
    results.forEach((item) => root.appendChild(resultCard(item)));
  } catch (err) {
    setText("searchSummary", "Search failed.");
    root.innerHTML = `<div class="notice danger"><strong>Search failed</strong><span>${escapeHtml(err.message)}</span></div>`;
  }
}

async function loadNode(idOverride) {
  const id = idOverride || $("nodeInput").value.trim();
  if (!id) return;
  state.selectedNode = id;
  setText("selectedLayer", "loading");
  $("nodePreview").textContent = "Loading...";
  try {
    const [node, graph] = await Promise.all([
      getJson(`/api/node?id=${encodeURIComponent(id)}`),
      getJson(`/api/graph?id=${encodeURIComponent(id)}&limit=42`),
    ]);
    setText("selectedLayer", node.props?.layer || "unknown");
    $("nodePreview").textContent = node.content ?? `${id}\n\nNo preview available.`;
    renderGraph(graph);
  } catch (err) {
    $("nodePreview").textContent = err.message;
  }
}

function renderGraph(data) {
  const svg = $("graphSvg");
  const center = data.center || { id: state.selectedNode, layer: "center" };
  const neighbors = data.neighbors || [];
  const width = 760;
  const height = 520;
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(190, 86 + neighbors.length * 3);
  const nodes = [{ ...center, x: cx, y: cy, center: true }];
  neighbors.forEach((n, i) => {
    const angle = (Math.PI * 2 * i) / Math.max(1, neighbors.length);
    nodes.push({ ...n, x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius });
  });

  const edges = neighbors.map((n, i) => {
    const target = nodes[i + 1];
    return `<line x1="${cx}" y1="${cy}" x2="${target.x}" y2="${target.y}" stroke="#c8d3e3" stroke-width="1.3" />`;
  }).join("");

  const circles = nodes.map((n) => {
    const color = n.center ? "#2f6fed" : layerColor(n.layer);
    const label = basename(n.id);
    return `
      <g class="graph-node" tabindex="0" data-id="${escapeAttr(encodeURIComponent(n.id))}">
        <circle cx="${n.x}" cy="${n.y}" r="${n.center ? 18 : 11}" fill="${color}" />
        <text x="${n.x}" y="${n.y + (n.center ? 35 : 26)}" text-anchor="middle" fill="#172033" font-size="${n.center ? 12 : 10}" font-weight="${n.center ? 800 : 650}">${escapeSvg(label.slice(0, 34))}</text>
      </g>
    `;
  }).join("");

  svg.innerHTML = `<rect width="760" height="520" fill="#fbfcff" />${edges}${circles}`;
  svg.querySelectorAll(".graph-node").forEach((el) => {
    el.addEventListener("click", () => {
      const id = decodeURIComponent(el.getAttribute("data-id") || "");
      $("nodeInput").value = id;
      loadNode(id);
    });
  });
}

function layerColor(layer) {
  return {
    signal: "#8b5cf6",
    impression: "#f59e0b",
    insight: "#12a594",
    framework: "#ef4444",
    lens: "#06b6d4",
    synthesis: "#2f6fed",
    index: "#64748b",
  }[layer] || "#64748b";
}

async function loadSources() {
  const root = $("sourcesTable");
  root.innerHTML = `<div class="result"><h4>Loading registry...</h4></div>`;
  try {
    const data = await getJson("/api/sources");
    const sources = Array.isArray(data.sources) ? data.sources : [];
    setText("sourceCount", `${fmt(sources.length)} records`);
    if (!sources.length) {
      root.innerHTML = `<div class="result"><h4>No registry records found</h4><p>${escapeHtml(data.error || "")}</p></div>`;
      return;
    }
    root.innerHTML = `<div class="table-row header"><span>Name</span><span>Path</span><span>Role</span><span>Status</span></div>`;
    sources.slice(0, 80).forEach((s) => {
      const row = document.createElement("div");
      row.className = "table-row";
      row.innerHTML = `
        <span>${escapeHtml(s.name || s.id || s.source || "source")}</span>
        <span>${escapeHtml(s.path || s.location || s.url || "")}</span>
        <span>${escapeHtml(s.role || s.type || "")}</span>
        <span>${escapeHtml(s.status || s.ingest_status || "")}</span>
      `;
      root.appendChild(row);
    });
  } catch (err) {
    root.innerHTML = `<div class="result"><h4>Registry failed</h4><p>${escapeHtml(err.message)}</p></div>`;
  }
}

async function loadFiles() {
  setText("volumeCount", "loading");
  setText("registeredSourceCount", "loading");
  $("volumeList").innerHTML = `<div class="notice"><strong>Scanning mounted volumes...</strong><span>Shallow scan only; no recursive RAID walk.</span></div>`;
  $("registeredSources").innerHTML = `<div class="notice"><strong>Loading registry...</strong><span>Checking source paths against the current machine.</span></div>`;
  try {
    const data = await getJson("/api/files");
    renderFiles(data);
  } catch (err) {
    $("volumeList").innerHTML = `<div class="notice danger"><strong>Files overview failed</strong><span>${escapeHtml(err.message)}</span></div>`;
  }
}

function renderFiles(data) {
  const index = data.file_index || {};
  const volumes = data.volumes || [];
  const sources = data.sources || [];

  setText("filesIndexedCount", `${fmt(index.chunked_files)} / ${fmt(index.markdown_files)}`);
  setText("filesMissingChunks", fmt(index.missing_chunk_count));
  setText("filesLayerDrift", fmt(index.layer_mismatch_count));
  setText("filesGitDrift", fmt(index.git?.total || 0));
  setText("volumeCount", `${fmt(volumes.length)} mounted`);
  setText("registeredSourceCount", `${fmt(sources.length)} records`);
  setText("folderBucketCount", `${fmt((index.folders || []).length)} buckets`);
  setText("notSearchableCount", fmt(index.missing_chunk_count));
  setText("outOfSyncCount", fmt((index.git?.total || 0) + (index.graph_without_file_count || 0) + (index.chunk_without_file_count || 0) + (index.layer_mismatch_count || 0)));

  renderVolumes(volumes);
  renderRegisteredSources(sources);
  renderFolderCoverage(index.folders || []);
  renderCompactList("notSearchableList", index.missing_chunks || [], "All markdown files have semantic chunks.");
  const driftItems = [
    ...(index.graph_without_file || []).map((id) => `graph without file: ${id}`),
    ...(index.chunk_without_file || []).map((id) => `chunk without file: ${id}`),
    ...(index.layer_mismatches || []).map((item) => `layer mismatch: ${item.id} (${item.actual} should be ${item.expected})`),
    ...((index.git?.items || []).map((line) => `git: ${line}`)),
  ];
  renderCompactList("outOfSyncList", driftItems, "No graph, chunk, layer, or git drift detected.");
}

function renderVolumes(volumes) {
  const root = $("volumeList");
  root.innerHTML = "";
  if (!volumes.length) {
    root.innerHTML = `<div class="result"><h4>No mounted volumes found</h4></div>`;
    return;
  }
  for (const volume of volumes) {
    const item = document.createElement("article");
    item.className = "source-card";
    const entries = (volume.entries || []).slice(0, 10).map((entry) => `
      <li><span>${escapeHtml(entry.kind === "directory" ? "dir" : "file")}</span>${escapeHtml(entry.name)}${entry.dir_count !== undefined ? `<small>${fmt(entry.dir_count)} dirs / ${fmt(entry.file_count)} files</small>` : ""}</li>
    `).join("");
    item.innerHTML = `
      <div class="source-card-head">
        <h4>${escapeHtml(basename(volume.path))}</h4>
        <span class="badge ${volume.accessible ? "" : "muted"}">${volume.accessible ? "accessible" : "blocked"}</span>
      </div>
      <p>${escapeHtml(volume.path)}</p>
      <div class="mini-row"><span>${fmt(volume.dir_count)} dirs</span><span>${fmt(volume.file_count)} files</span>${volume.truncated ? "<span>truncated</span>" : ""}</div>
      <ul class="entry-list">${entries}</ul>
    `;
    root.appendChild(item);
  }
}

function renderRegisteredSources(sources) {
  const root = $("registeredSources");
  root.innerHTML = "";
  if (!sources.length) {
    root.innerHTML = `<div class="result"><h4>No registered sources found</h4></div>`;
    return;
  }
  for (const source of sources) {
    const item = document.createElement("article");
    item.className = "source-card";
    const status = source.is_current_brain ? "current brain" : source.accessible_now ? "reachable" : source.exists_now ? "blocked" : "missing";
    item.innerHTML = `
      <div class="source-card-head">
        <h4>${escapeHtml(source.id || source.name || "source")}</h4>
        <span class="badge ${source.accessible_now ? "" : "muted"}">${escapeHtml(status)}</span>
      </div>
      <p>${escapeHtml(source.path || "")}</p>
      <div class="mini-row">
        <span>${escapeHtml(source.host || "unknown host")}</span>
        <span>${escapeHtml(source.role || "source")}</span>
        ${source.markdown_count_at_scan !== undefined && source.markdown_count_at_scan !== null ? `<span>${fmt(source.markdown_count_at_scan)} md at scan</span>` : ""}
        ${source.current_markdown_count !== undefined && source.current_markdown_count !== null ? `<span>${fmt(source.current_markdown_count)} md now</span>` : ""}
      </div>
    `;
    root.appendChild(item);
  }
}

function renderFolderCoverage(folders) {
  const root = $("folderCoverageTable");
  root.innerHTML = `<div class="table-row file-header"><span>Bucket</span><span>Files</span><span>Graph</span><span>Chunked</span><span>Chunks</span><span>Issues</span></div>`;
  if (!folders.length) {
    root.innerHTML = `<div class="result"><h4>No folder coverage data</h4></div>`;
    return;
  }
  folders.slice(0, 80).forEach((folder) => {
    const issues = (folder.missing_graph || 0) + (folder.missing_chunks || 0) + (folder.layer_mismatches || 0);
    const row = document.createElement("div");
    row.className = `table-row file-row ${issues ? "warn-row" : ""}`;
    row.innerHTML = `
      <span>${escapeHtml(folder.bucket)}</span>
      <span>${fmt(folder.files)}</span>
      <span>${fmt(folder.graph_nodes)}</span>
      <span>${fmt(folder.chunked_files)}</span>
      <span>${fmt(folder.chunks)}</span>
      <span>${fmt(issues)}</span>
    `;
    root.appendChild(row);
  });
}

function renderCompactList(id, items, emptyText) {
  const root = $(id);
  root.innerHTML = "";
  if (!items.length) {
    root.innerHTML = `<div class="result"><h4>${escapeHtml(emptyText)}</h4></div>`;
    return;
  }
  for (const item of items.slice(0, 80)) {
    const row = document.createElement("div");
    row.className = "result compact-result";
    row.innerHTML = `<h4>${escapeHtml(item)}</h4>`;
    root.appendChild(row);
  }
}

async function refresh() {
  const data = await getJson("/api/status");
  renderStatus(data);
}

function basename(path) {
  return String(path || "").split("/").pop() || path;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[ch]));
}

function escapeSvg(value) {
  return escapeHtml(value);
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#096;");
}

document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    setPanel(btn.dataset.panel);
    if (btn.dataset.panel === "files") loadFiles();
    if (btn.dataset.panel === "sources") loadSources();
  });
});

$("refreshBtn").addEventListener("click", refresh);
$("graphJumpBtn").addEventListener("click", () => {
  setPanel("graph");
  if (!$("nodeInput").value.trim()) {
    $("nodeInput").value = "wiki/Meta/master-brain-architecture-2026-05-17.md";
    loadNode();
  }
});
$("searchBtn").addEventListener("click", runSearch);
$("searchInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter") runSearch();
});
$("loadNodeBtn").addEventListener("click", () => loadNode());
document.querySelectorAll(".quick-searches button").forEach((button) => {
  button.addEventListener("click", () => {
    $("searchInput").value = button.dataset.query;
    runSearch();
  });
});

refresh().catch((err) => {
  $("daemonDot").className = "dot bad";
  setText("daemonText", err.message);
});
