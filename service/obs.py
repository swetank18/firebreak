"""Structured logging, and the correlation id that ties a run together.

`AGENTS.md`, definition of done: "a structured log line with the scenario
correlation ID". `EXECUTION.md` section 10 asks for the same thing.

The emitting modules use plain `logging.getLogger(__name__)` and nothing from
this file — `decision/` in particular must stay free of platform imports, and a
logging call that reaches for the platform is a dependency like any other. So
the producers stay stdlib-only and the FORMAT is configured here, at the edge,
by whoever is running the thing.

Silent by default: with no handler installed, INFO records go nowhere, which is
what the evaluation scripts want when they run the engine tens of thousands of
times.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message", "asctime", "taskName",
}


class JsonFormatter(logging.Formatter):
    """One line of JSON per record, with every extra field carried through."""

    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k, v in record.__dict__.items():
            if k not in _RESERVED and not k.startswith("_"):
                out[k] = v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def configure(level: int = logging.INFO, stream=None) -> None:
    """Install the JSON handler. Call once, from an entry point, never on import."""
    h = logging.StreamHandler(stream or sys.stderr)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)
