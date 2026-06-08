"""Session orientation for Niklas."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .store import NiklasStore, utcnow


ORIENTATION_VERSION = "niklas-orient-v1"
DEFAULT_LIMIT = 5


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _path_hints(cwd: str | None) -> list[str]:
    if not cwd:
        return []
    path = Path(cwd).expanduser()
    hints: list[str] = []
    for part in path.parts:
        clean = part.strip()
        if not clean:
            continue
        lower = clean.lower()
        if lower in {"", "/", "users", "desktop", "documents", "projects", "03-runtime", "01-brain"}:
            continue
        if lower.startswith("."):
            continue
        hints.append(clean)
    return hints[-6:]


def _surface_from_inputs(cwd: str | None, browser_url: str | None, surface: str | None) -> str:
    explicit = _clean(surface)
    if explicit:
        return explicit
    if browser_url:
        return "browser"
    if cwd:
        return "repo-or-local-files"
    return "chat"


def _build_query(
    *,
    current_request: str | None,
    current_goal: str | None,
    project_hint: str | None,
    cwd: str | None,
    browser_url: str | None,
    chat_summary: str | None,
    surface: str | None,
) -> str:
    pieces: list[str] = []
    for value in (project_hint, current_goal, current_request, chat_summary, browser_url, surface):
        cleaned = _clean(value)
        if cleaned:
            pieces.append(cleaned)
    pieces.extend(_path_hints(cwd))
    return " ".join(pieces).strip()


def _candidate_reason(node: dict[str, Any], query: str, cwd: str | None, project_hint: str | None) -> list[str]:
    reasons: list[str] = []
    node_project = str(node.get("project") or "")
    node_title = str(node.get("title") or "")
    node_path = str(node.get("path") or "")
    if project_hint and project_hint.lower() in " ".join([node_project, node_title, node_path]).lower():
        reasons.append("matches project hint")
    if cwd:
        cwd_lower = cwd.lower()
        if node_project and node_project.lower() in cwd_lower:
            reasons.append("project appears in current path")
        if node_title and node_title.lower() in cwd_lower:
            reasons.append("title appears in current path")
    if query and int(node.get("score") or 0) > 0:
        reasons.append("matches current request or chat signal")
    if not reasons:
        reasons.append("nearest available Niklas match")
    return reasons


def _confidence(score: int, has_project_hint: bool, has_goal: bool, has_candidates: bool) -> str:
    if not has_candidates:
        return "none"
    if has_project_hint and has_goal and score >= 8:
        return "high"
    if has_project_hint or score >= 8:
        return "medium"
    return "low"


def _questions(
    *,
    confidence: str,
    current_goal: str | None,
    project_hint: str | None,
    current_request: str | None,
    surface: str,
) -> list[dict[str, str]]:
    questions: list[dict[str, str]] = []
    if not project_hint:
        questions.append(
            {
                "id": "project",
                "question": "Are we working inside an existing Niklas project, starting a new project, or doing a scratch task?",
                "why": "Niklas needs the project boundary before it can choose the right context pack.",
            }
        )
    if not current_goal:
        questions.append(
            {
                "id": "goal",
                "question": "What is the current goal for this session, in one sentence?",
                "why": "The goal is the strongest routing signal for matching source-backed context.",
            }
        )
    if not current_request:
        questions.append(
            {
                "id": "task",
                "question": "What are you trying to do right now: plan, debug, implement, review, ingest, or install something?",
                "why": "Niklas should distinguish orientation from execution before pulling deeper archive context.",
            }
        )
    if surface == "chat":
        questions.append(
            {
                "id": "surface",
                "question": "Which surface should I treat as primary: repo/files, Linear, browser, local notes, CLI, or MCP?",
                "why": "The active surface decides whether Niklas should return docs, commands, code paths, or graph nodes first.",
            }
        )
    if confidence in {"none", "low"}:
        questions.append(
            {
                "id": "done",
                "question": "What would count as done for this session?",
                "why": "A clear stop condition prevents Niklas from routing into broad archive search too early.",
            }
        )
    return questions[:5]


def _trim_candidate(node: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    return {
        "id": node.get("id"),
        "type": node.get("type"),
        "title": node.get("title"),
        "project": node.get("project"),
        "path": node.get("path"),
        "score": node.get("score", 0),
        "reasons": reasons,
        "summary": node.get("summary"),
        "content_preview": node.get("content_preview"),
        "tags": node.get("tags"),
    }


def build_orientation(
    *,
    current_request: str | None = None,
    current_goal: str | None = None,
    project_hint: str | None = None,
    cwd: str | Path | None = None,
    browser_url: str | None = None,
    chat_summary: str | None = None,
    surface: str | None = None,
    limit: int = DEFAULT_LIMIT,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return the first-use Niklas positioning packet for a chat/session."""
    cwd_text = str(cwd) if cwd is not None else None
    clean_request = _clean(current_request)
    clean_goal = _clean(current_goal)
    clean_project = _clean(project_hint)
    clean_browser_url = _clean(browser_url)
    clean_chat_summary = _clean(chat_summary)
    detected_surface = _surface_from_inputs(cwd_text, clean_browser_url, surface)
    query = _build_query(
        current_request=clean_request,
        current_goal=clean_goal,
        project_hint=clean_project,
        cwd=cwd_text,
        browser_url=clean_browser_url,
        chat_summary=clean_chat_summary,
        surface=detected_surface,
    )

    store = NiklasStore(db_path)
    status = store.status()
    nodes: list[dict[str, Any]] = []
    if query:
        nodes = store.search_nodes(query, project_scope=clean_project, limit=max(1, min(int(limit), 20)))

    candidates: list[dict[str, Any]] = []
    for node in nodes:
        candidates.append(
            _trim_candidate(
                node,
                _candidate_reason(node, query, cwd_text, clean_project),
            )
        )

    top = candidates[0] if candidates else None
    top_score = int(top.get("score") or 0) if top else 0
    confidence = _confidence(
        top_score,
        has_project_hint=bool(clean_project),
        has_goal=bool(clean_goal),
        has_candidates=bool(candidates),
    )
    state = "positioned" if confidence in {"medium", "high"} else "needs_questions"
    recommended_context_query = " ".join(
        part for part in [clean_project, clean_goal, clean_request, top.get("title") if top else None] if part
    ).strip()
    if not recommended_context_query:
        recommended_context_query = query

    questions = _questions(
        confidence=confidence,
        current_goal=clean_goal,
        project_hint=clean_project,
        current_request=clean_request,
        surface=detected_surface,
    )

    return {
        "orientation_version": ORIENTATION_VERSION,
        "generated_at": utcnow(),
        "status": {
            "db_exists": status.get("db_exists", False),
            "schema_present": status.get("schema_present", False),
            "node_count": status.get("node_count", 0),
            "relationship_count": status.get("relationship_count", 0),
        },
        "inputs": {
            "current_request": clean_request,
            "current_goal": clean_goal,
            "project_hint": clean_project,
            "cwd": cwd_text,
            "browser_url": clean_browser_url,
            "chat_summary": clean_chat_summary,
            "surface": surface,
        },
        "detected": {
            "surface": detected_surface,
            "path_hints": _path_hints(cwd_text),
            "query": query,
        },
        "position": {
            "state": state,
            "confidence": confidence,
            "project_scope": clean_project or (top.get("project") if top else None),
            "starting_node_id": top.get("id") if top else None,
            "starting_title": top.get("title") if top else None,
            "recommended_next_tool": (
                "niklas_context_pack"
                if state == "positioned" and recommended_context_query
                else "ask_user"
            ),
            "recommended_context_query": recommended_context_query,
            "instruction": (
                "Ask the orientation questions before deeper retrieval."
                if state == "needs_questions"
                else "Use the starting node and recommended context query before execution."
            ),
        },
        "questions": questions,
        "candidates": candidates,
    }


def render_orientation_markdown(orientation: dict[str, Any]) -> str:
    """Render an orientation packet for terminal use."""
    position = orientation.get("position", {})
    lines = [
        "# Niklas Orientation",
        "",
        f"- State: {position.get('state')}",
        f"- Confidence: {position.get('confidence')}",
        f"- Project scope: {position.get('project_scope') or 'unknown'}",
        f"- Starting node: {position.get('starting_title') or position.get('starting_node_id') or 'unknown'}",
        f"- Next tool: {position.get('recommended_next_tool')}",
        f"- Context query: {position.get('recommended_context_query') or 'none'}",
        "",
        "## Questions",
    ]
    questions = orientation.get("questions") or []
    if questions:
        for item in questions:
            lines.append(f"- {item.get('question')}")
    else:
        lines.append("- No blocking orientation questions.")
    lines.extend(["", "## Candidates"])
    candidates = orientation.get("candidates") or []
    if candidates:
        for candidate in candidates:
            title = candidate.get("title") or candidate.get("id")
            project = candidate.get("project") or "unknown"
            score = candidate.get("score", 0)
            lines.append(f"- {title} ({project}, score {score})")
    else:
        lines.append("- No candidates yet.")
    return "\n".join(lines) + "\n"
