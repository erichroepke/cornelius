"""Async Anthropic Messages API client pool for the edge-inference agents.

20 parallel workers consume from the SQLite queue, call the API, parse responses,
write proposals back. Uses httpx (already in venv) — no anthropic SDK dependency.

API key resolution order:
1. ANTHROPIC_API_KEY env var
2. ~/.claude/MEMORY/SECRETS/api_keys.env (Erich's secret store)
3. error
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError as e:
    raise ImportError("enrichment.agent_pool requires httpx (already installed in Cornelius venv)") from e


ANTHROPIC_API_BASE = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-6"  # cost-efficient + quality for structured-output JSON
DEFAULT_MAX_TOKENS = 1024
ANTHROPIC_VERSION = "2023-06-01"


# ---------------------------------------------------------------------------
# API key resolution
# ---------------------------------------------------------------------------

def resolve_api_key() -> str:
    """Find Anthropic API key, prioritising env var then Erich's secret store."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    # Erich's memory note: shell ANTHROPIC_API_KEY may be Claude Code OAuth, NOT a real key.
    # Real keys live in ~/.claude/MEMORY/SECRETS/api_keys.env. Prefer that if present.
    secrets_file = Path.home() / ".claude" / "MEMORY" / "SECRETS" / "api_keys.env"
    if secrets_file.exists():
        for line in secrets_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY=") and "=" in line:
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                if v and not v.startswith("sk-ant-oat"):  # skip OAuth tokens
                    return v
    if key and not key.startswith("sk-ant-oat"):
        return key
    raise RuntimeError(
        "No usable ANTHROPIC_API_KEY found. Set the env var to a real API key "
        "(sk-ant-api03-...), or add it to ~/.claude/MEMORY/SECRETS/api_keys.env"
    )


# ---------------------------------------------------------------------------
# Single-call wrapper
# ---------------------------------------------------------------------------

class AnthropicClient:
    """Thin async wrapper around the Messages API.

    Connection pool reused across calls. Retry on transient 5xx + rate-limit.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or resolve_api_key()
        self.model = model
        self.max_tokens = max_tokens
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=20),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def messages(self, system: str, user: str, *, retries: int = 3) -> dict:
        """Call POST /v1/messages, return the parsed JSON response."""
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        attempt = 0
        last_exc: Optional[Exception] = None
        while attempt < retries:
            attempt += 1
            try:
                resp = await self._client.post(ANTHROPIC_API_BASE, headers=headers, json=body)
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    # Backoff: 1s, 2s, 4s
                    await asyncio.sleep(2 ** (attempt - 1))
                    continue
                resp.raise_for_status()
                return resp.json()
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                last_exc = e
                await asyncio.sleep(2 ** (attempt - 1))
        raise RuntimeError(f"Anthropic API failed after {retries} retries: {last_exc}")

    @staticmethod
    def extract_text(response_json: dict) -> str:
        """Concatenate all text blocks from a Messages API response."""
        blocks = response_json.get("content", [])
        parts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        return "".join(parts).strip()


# ---------------------------------------------------------------------------
# Worker pool
# ---------------------------------------------------------------------------

class Worker:
    """Single worker consuming batches from a Queue and writing proposals back."""

    def __init__(self, worker_id: str, client: AnthropicClient, queue, system_prompt: str, agent_version: str) -> None:
        self.worker_id = worker_id
        self.client = client
        self.queue = queue
        self.system_prompt = system_prompt
        self.agent_version = agent_version

    async def run_once(self, prompt_builder, response_parser) -> bool:
        """Process one batch. Returns False if queue is empty."""
        batch = self.queue.claim_batch(self.worker_id)
        if not batch:
            return False

        import json as _json
        candidates = _json.loads(batch["candidates"])
        anchor = {"id": batch["anchor_id"]}  # extended by caller via prompt_builder if needed

        prompt = prompt_builder(anchor, candidates)

        try:
            resp = await self.client.messages(self.system_prompt, prompt)
            text = self.client.extract_text(resp)
            proposals = response_parser(text)
            for p in proposals:
                self.queue.propose(
                    batch_id=batch["id"],
                    from_id=batch["anchor_id"],
                    to_id=p["candidate_id"],
                    edge_type=p["edge_type"],
                    direction=p["direction"],
                    confidence=p["confidence"],
                    rationale=p["rationale"],
                    agent_version=self.agent_version,
                )
            self.queue.mark_batch_done(batch["id"])
        except Exception as e:
            self.queue.mark_batch_failed(batch["id"], str(e)[:500])
            return True  # don't stop the pool on a single failure
        return True


async def run_pool(
    n_workers: int,
    client: AnthropicClient,
    queue,
    prompt_builder,
    response_parser,
    system_prompt: str,
    agent_version: str,
    max_batches: Optional[int] = None,
) -> dict:
    """Run N workers in parallel until the queue is empty (or max_batches hit)."""
    workers = [
        Worker(f"w{i}", client, queue, system_prompt, agent_version)
        for i in range(n_workers)
    ]
    processed = 0
    start = time.time()
    done = False

    async def loop(w: Worker) -> None:
        nonlocal processed, done
        while not done:
            ok = await w.run_once(prompt_builder, response_parser)
            if not ok:
                done = True
                break
            processed += 1
            if max_batches is not None and processed >= max_batches:
                done = True
                break

    await asyncio.gather(*(loop(w) for w in workers))
    elapsed = time.time() - start
    return {"processed": processed, "elapsed_s": round(elapsed, 1)}
