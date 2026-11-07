"""Depodaki paylaşılan protokol şeması, koddan üretilenle birebir aynı olmalı.

Uyumsuzluk varsa şu komutla yeniden üretin::

    uv run ati-engine export-protocol-schema --output ../shared/protocol/engine-local-api.schema.json
"""

from __future__ import annotations

import functools
import json
import operator
from pathlib import Path
from typing import Any

import msgspec

from ati_engine.core.events import PUBLIC_EVENT_TYPES, Event, KillSwitchEngaged, encode_event
from ati_engine.protocol import build_protocol_schema

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "shared" / "protocol" / "engine-local-api.schema.json"
)


def test_committed_schema_matches_code() -> None:
    expected = build_protocol_schema()
    committed = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert committed == expected, "Protokol şeması güncel değil; yeniden üretin."


def test_every_public_event_is_in_schema() -> None:
    defs = build_protocol_schema()["$defs"]
    for event_type in PUBLIC_EVENT_TYPES:
        assert event_type.__name__ in defs


def test_events_roundtrip_as_tagged_union() -> None:
    """İstemciler olayı ``type`` alanına göre çözer; aynı birleşim motor tarafında da çalışır."""
    original = KillSwitchEngaged(reason="r", actor="a")
    raw = encode_event(original)
    assert json.loads(raw)["type"] == "KillSwitchEngaged"
    union: Any = functools.reduce(operator.or_, PUBLIC_EVENT_TYPES)
    decoded = msgspec.json.decode(raw, type=union)
    assert decoded == original
    assert isinstance(decoded, Event)
