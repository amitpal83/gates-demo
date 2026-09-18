"""Shared tracing + cost/token logging, applied identically to every agent: Langfuse in production, a local JSON-lines log as the fallback."""
import functools
import json
import logging
import os
import time

from . import config

if config.USE_LIVE_LANGFUSE:
    from langfuse import get_client, observe

_LOG_PATH = os.path.join(os.path.dirname(__file__), "observability.log")
logger = logging.getLogger(__name__)

# Rough per-1k-token pricing used only by the fallback cost estimate.
_PRICE_PER_1K_INPUT_USD = 0.0015
_PRICE_PER_1K_OUTPUT_USD = 0.002


def trace(name: str):
    """Decorator: wraps a function call with a trace span -- @observe(name=name) in production, an equivalent local record as the fallback."""
    def decorator(fn):
        if config.USE_LIVE_LANGFUSE:
            return observe(name=name)(fn)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.time()
            result = fn(*args, **kwargs)
            record = {
                "trace": name,
                "duration_ms": round((time.time() - start) * 1000, 1),
                "backend": "local-log-fallback",
            }
            _append(record)
            return result
        return wrapper
    return decorator


def log_usage(
    agent_path: str,
    input_tokens: int,
    output_tokens: int,
    model: str,
    price_per_1k_input: float | None = None,
    price_per_1k_output: float | None = None,
) -> dict:
    """Records tokens + estimated cost -- the 'Tokens & Cost' observability sub-item in the HLD."""
    input_price = price_per_1k_input if price_per_1k_input is not None else _PRICE_PER_1K_INPUT_USD
    output_price = price_per_1k_output if price_per_1k_output is not None else _PRICE_PER_1K_OUTPUT_USD
    cost = round(
        (input_tokens / 1000) * input_price
        + (output_tokens / 1000) * output_price,
        6,
    )
    record = {
        "agent_path": agent_path,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": cost,
    }
    if config.USE_LIVE_LANGFUSE:
        get_client().update_current_span(metadata={"usage": record})
    else:
        _append({"usage": record})
    return record


def _append(record: dict):
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record) + "\n")
    except OSError as error:
        logger.warning("Unable to write local observability log: %s", error)
