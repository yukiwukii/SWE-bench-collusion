"""OpenRouter list prices and key usage (stdlib only, so the host-side summary script can import it too)."""
from __future__ import annotations

import functools
import json
import os
import urllib.request

_API = "https://openrouter.ai/api/v1"


def _get(path: str, key: str | None = None) -> dict:
    req = urllib.request.Request(_API + path, headers={"Authorization": f"Bearer {key}"} if key else {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


@functools.lru_cache(maxsize=None)
def model_pricing(slug: str) -> dict[str, float]:
    """USD per token for an OpenRouter slug (``z-ai/glm-5.3``; an ``openrouter/`` prefix is ignored)."""
    slug = slug.removeprefix("openrouter/")
    for m in _get("/models")["data"]:
        if m["id"] == slug:
            return {k: float(v) for k, v in m["pricing"].items() if isinstance(v, (str, int, float))}
    raise KeyError(f"model not found on OpenRouter: {slug}")


def litellm_registry(model_name: str) -> dict:
    """LiteLLM ``register_model`` entry so mini-swe-agent can price (and cost-cap) an OpenRouter model."""
    p = model_pricing(model_name)
    entry = {"litellm_provider": "openrouter", "mode": "chat",
             "input_cost_per_token": p.get("prompt", 0.0), "output_cost_per_token": p.get("completion", 0.0)}
    if "input_cache_read" in p:
        entry["cache_read_input_token_cost"] = p["input_cache_read"]
    if "input_cache_write" in p:
        entry["cache_creation_input_token_cost"] = p["input_cache_write"]
    return {model_name: entry}


def estimate_cost(pricing: dict[str, float], input_tokens: int, output_tokens: int,
                  cache_read_tokens: int = 0, cache_write_tokens: int = 0) -> float:
    """List-price estimate. ``input_tokens`` includes cached tokens (as harbor reports it)."""
    uncached = max(input_tokens - cache_read_tokens - cache_write_tokens, 0)
    return (uncached * pricing.get("prompt", 0.0)
            + cache_read_tokens * pricing.get("input_cache_read", pricing.get("prompt", 0.0))
            + cache_write_tokens * pricing.get("input_cache_write", pricing.get("prompt", 0.0))
            + output_tokens * pricing.get("completion", 0.0))


def key_status(key: str | None = None) -> dict:
    """Total USD billed to the key so far, and its remaining limit (None = no limit)."""
    d = _get("/key", key or os.environ["OPENROUTER_API_KEY"])["data"]
    return {"usage_usd": d.get("usage"), "limit_usd": d.get("limit"), "limit_remaining_usd": d.get("limit_remaining"),
            "limit_reset": d.get("limit_reset")}
