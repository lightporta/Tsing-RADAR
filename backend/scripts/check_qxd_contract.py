#!/usr/bin/env python3
"""Probe a deployed Tsing-RADAR 清小搭 OpenAI-compatible endpoint."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

FINISH_REASONS = {
    "stop",
    "length",
    "tool_calls",
    "content_filter",
    "function_call",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def usage(value: Any) -> None:
    require(isinstance(value, dict), "usage must be an object")
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        require(
            isinstance(value.get(key), int) and value[key] >= 0,
            f"usage.{key} must be a non-negative integer",
        )


def request(
    url: str,
    token: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> tuple[int, str, str]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Authorization": f"Bearer {token}", "Accept": "*/*"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return (
                response.status,
                response.headers.get("content-type", ""),
                response.read().decode("utf-8"),
            )
    except urllib.error.HTTPError as exc:
        return (
            exc.code,
            exc.headers.get("content-type", ""),
            exc.read().decode("utf-8", errors="replace"),
        )


def parse_sse(text: str) -> list[Any]:
    events: list[Any] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(":"):
            continue
        require(line.startswith("data:"), f"unexpected SSE line: {line}")
        raw_data = line[5:].strip()
        events.append("[DONE]" if raw_data == "[DONE]" else json.loads(raw_data))
    return events


def validate_stream(text: str) -> None:
    events = parse_sse(text)
    require(len(events) >= 3, "stream needs role, stop, and [DONE] events")
    require(events[-1] == "[DONE]", "stream must end with [DONE]")
    frames = events[:-1]
    roles = []
    stops = []
    for frame in frames:
        choices = frame.get("choices")
        require(isinstance(choices, list) and choices, "SSE frame needs choices")
        choice = choices[0]
        delta = choice.get("delta")
        require(isinstance(delta, dict), "SSE choice.delta must be an object")
        if delta.get("role") is not None:
            roles.append(frame)
        if choice.get("finish_reason") is not None:
            stops.append(frame)
    require(len(roles) == 1 and frames[0] is roles[0], "role frame must occur once and first")
    require(len(stops) == 1 and frames[-1] is stops[0], "stop frame must occur once and last")
    require(stops[0]["choices"][0]["finish_reason"] in FINISH_REASONS, "invalid finish_reason")
    usage(stops[0].get("usage"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="URL ending in /v1")
    parser.add_argument("--token", required=True, help="Bearer credential")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    try:
        invalid_status, _, _ = request(
            f"{base_url}/models",
            f"{args.token}-invalid",
        )
        require(invalid_status == 401, "invalid credential must return 401")

        status, _, raw_models = request(f"{base_url}/models", args.token)
        require(status == 200, f"/models returned HTTP {status}")
        models = json.loads(raw_models)
        require(models.get("object") == "list", "models.object must be 'list'")
        require(isinstance(models.get("data"), list) and models["data"], "models.data is empty")
        model = models["data"][0].get("id")
        require(isinstance(model, str) and model, "model id is missing")

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "max_tokens": 1,
        }
        status, _, raw_nonstream = request(
            f"{base_url}/chat/completions",
            args.token,
            method="POST",
            body={**payload, "stream": False},
        )
        require(status == 200, f"non-streaming completion returned HTTP {status}")
        nonstream = json.loads(raw_nonstream)
        choices = nonstream.get("choices")
        require(isinstance(choices, list) and choices, "non-streaming choices are missing")
        require(
            isinstance(choices[0].get("message", {}).get("content"), str),
            "choices[0].message.content must be a string",
        )
        require(choices[0].get("finish_reason") in FINISH_REASONS, "invalid finish_reason")
        usage(nonstream.get("usage"))

        status, content_type, raw_stream = request(
            f"{base_url}/chat/completions",
            args.token,
            method="POST",
            body={**payload, "stream": True},
        )
        require(status == 200, f"streaming completion returned HTTP {status}")
        require(
            content_type.startswith("text/event-stream"),
            "stream response must use text/event-stream",
        )
        validate_stream(raw_stream)
        print("PASS: auth, models, non-streaming, and streaming contracts")
        return 0
    except (
        ValueError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
