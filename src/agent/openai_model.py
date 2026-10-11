"""OpenAI-compatible chat client for the agent loop."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from agent.agent import Model, ModelResponse, ModelUsage, ToolCall

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
_DEFAULT_MODEL = "gpt-5"
_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIModel(Model):
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ):
        if api_key is None:
            api_key = api_key_from_env()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self.api_key = api_key
        self.model = model.strip() if model and model.strip() else _env_text("OPENAI_MODEL", _DEFAULT_MODEL)
        self.base_url = (
            base_url.strip() if base_url and base_url.strip() else _env_text("OPENAI_BASE_URL", _DEFAULT_BASE_URL)
        ).rstrip("/")

    def generate(self, messages: list[dict], tools: list[dict]) -> ModelResponse:
        payload: dict = {"model": self.model, "messages": _to_api_messages(messages)}
        if tools:
            payload["tools"] = _to_api_tools(tools)
        body = _post_json(f"{self.base_url}/chat/completions", self.api_key, payload)
        return _response_from_body(body)


def api_key_from_env() -> str | None:
    """Return ``OPENAI_API_KEY`` from the environment or the project ``.env``."""
    _load_dotenv()
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    return key or None


def _env_text(name: str, default: str) -> str:
    """A non-empty value from the environment or ``.env``. Otherwise `default`."""
    _load_dotenv()
    value = os.environ.get(name, "").strip()
    return value or default


def save_api_key(api_key: str, path: Path | None = None) -> None:
    """Store the key in ``.env`` and in this process. Other lines in the file stay."""
    key = api_key.strip()
    if not key:
        raise ValueError("OPENAI_API_KEY is empty")
    env_path = path or _ENV_PATH
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.is_file() else []
    replaced = False
    updated: list[str] = []
    for line in lines:
        name, separator, _value = line.partition("=")
        if separator and name.strip() == "OPENAI_API_KEY" and not line.lstrip().startswith("#"):
            updated.append(f"OPENAI_API_KEY={key}")
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        updated.append(f"OPENAI_API_KEY={key}")
    env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    os.environ["OPENAI_API_KEY"] = key


def _load_dotenv() -> None:
    if not _ENV_PATH.is_file():
        return
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip())


def _to_api_messages(messages: list[dict]) -> list[dict]:
    api_messages: list[dict] = []
    for message in messages:
        role = message["role"]
        if role in {"system", "user"}:
            api_messages.append({"role": role, "content": message["content"]})
        elif role == "assistant" and message.get("tool_calls"):
            api_messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": json.dumps(call["arguments"]),
                            },
                        }
                        for call in message["tool_calls"]
                    ],
                }
            )
        elif role == "assistant":
            api_messages.append({"role": "assistant", "content": message.get("content") or ""})
        elif role == "tool":
            api_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": message["tool_call_id"],
                    "content": message["content"],
                }
            )
        else:
            raise ValueError(f"unknown message role: {role}")
    return api_messages


def _to_api_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            },
        }
        for tool in tools
    ]


def _response_from_body(body: dict) -> ModelResponse:
    message = body["choices"][0]["message"]
    usage = _usage_from_body(body.get("usage"))
    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        return ModelResponse(
            tool_calls=[
                ToolCall(
                    call["function"]["name"],
                    json.loads(call["function"].get("arguments") or "{}"),
                    call.get("id") or "",
                )
                for call in tool_calls
            ],
            usage=usage,
        )
    return ModelResponse(answer=message.get("content") or "", usage=usage)


def _usage_from_body(usage: dict | None) -> ModelUsage | None:
    if not usage:
        return None
    details = usage.get("prompt_tokens_details") or {}
    return ModelUsage(
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        cached_tokens=int(details.get("cached_tokens") or 0),
    )


def _post_json(url: str, api_key: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI request failed ({exc.code}): {detail}") from exc
