from __future__ import annotations

import json
from time import perf_counter
from typing import Any

import msgpack

try:
    import orjson
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    orjson = None  # type: ignore[assignment]


def pack_msgpack(payload: dict[str, Any]) -> bytes:
    return msgpack.packb(payload, use_bin_type=True)


def unpack_msgpack(payload: bytes) -> dict[str, Any]:
    return msgpack.unpackb(payload, raw=False)


def json_backend_name() -> str:
    return "orjson" if orjson is not None else "json"


def dump_websocket_json_bytes(payload: dict[str, Any]) -> bytes:
    if orjson is not None:
        return orjson.dumps(payload)
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def dump_websocket_json_text(payload: dict[str, Any]) -> str:
    return dump_websocket_json_bytes(payload).decode("utf-8")


def benchmark_snapshot_encodings(
    snapshot: dict[str, Any],
    *,
    iterations: int = 1000,
) -> dict[str, Any]:
    results: dict[str, Any] = {
        "iterations": iterations,
        "json_backend": json_backend_name(),
    }

    started = perf_counter()
    json_blob = b""
    for _ in range(iterations):
        json_blob = dump_websocket_json_bytes(snapshot)
    results["json_encode_seconds"] = round(perf_counter() - started, 6)
    results["json_size_bytes"] = len(json_blob)

    started = perf_counter()
    msgpack_blob = b""
    for _ in range(iterations):
        msgpack_blob = pack_msgpack(snapshot)
    results["msgpack_encode_seconds"] = round(perf_counter() - started, 6)
    results["msgpack_size_bytes"] = len(msgpack_blob)

    started = perf_counter()
    for _ in range(iterations):
        unpack_msgpack(msgpack_blob)
    results["msgpack_decode_seconds"] = round(perf_counter() - started, 6)

    return results
