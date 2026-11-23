"""Client for the configured model gateway's JSON chat-completions interface."""

import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

if __package__:
    from .scene_io import reject_json_constant, unique_object
else:
    from scene_io import reject_json_constant, unique_object

MAX_RESPONSE_BYTES = 1_048_576


class ModelError(RuntimeError):
    """The gateway is unavailable or returned an unusable response."""

    def __init__(self, message: str, *, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def retry_delay(value: str | None) -> float:
    if value is not None:
        try:
            seconds = float(value)
        except ValueError:
            try:
                timestamp = parsedate_to_datetime(value)
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                seconds = (timestamp - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return 0.25
        # Treat a large positive delay as outside the budget instead of capping it.
        if not math.isnan(seconds):
            return max(0.0, seconds)
    return 0.25


class RejectRedirects(HTTPRedirectHandler):
    """Keep the authorization header on the configured gateway."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def parse_json(payload):
    return json.loads(payload, parse_constant=reject_json_constant, object_pairs_hook=unique_object)


@dataclass(frozen=True)
class ModelClient:
    endpoint: str
    model: str
    api_key: str = field(repr=False)
    use_json_schema: bool = False
    timeout: float = 120.0

    @classmethod
    def from_env(cls):
        names = ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY")
        values = {name: os.environ.get(name, "").strip() for name in names}
        missing = [name for name in names if not values[name]]
        if missing:
            raise ModelError(f"Missing model configuration: {', '.join(missing)}.")
        base_url = values["LLM_BASE_URL"].rstrip("/")
        try:
            parsed = urlsplit(base_url)
            if (
                parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.query or parsed.fragment
            ):
                raise ValueError
            _ = parsed.port
        except ValueError:
            raise ModelError("LLM_BASE_URL must be an HTTP(S) gateway base URL.") from None
        try:
            timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", "120"))
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError
        except ValueError:
            raise ModelError("LLM_TIMEOUT_SECONDS must be positive and finite.") from None
        return cls(
            endpoint=f"{base_url}/chat/completions",
            model=values["LLM_MODEL"],
            api_key=values["LLM_API_KEY"],
            use_json_schema=os.environ.get("LLM_USE_JSON_SCHEMA") == "1",
            timeout=timeout,
        )

    def complete(
        self, stage: str, instructions: str, data: dict, schema: dict,
        *, budget: float | None = None,
    ) -> dict:
        """Send one request and decode the assistant's JSON object."""
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": f"{instructions}\nReturn only JSON matching this schema: "
                    + json.dumps(schema, ensure_ascii=False),
                },
                {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
            ],
        }
        if self.use_json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": stage, "strict": True, "schema": schema},
            }
        request = Request(
            self.endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        timeout = self.timeout if budget is None else min(self.timeout, budget)
        if timeout <= 0:
            raise ModelError("Model-call time budget exhausted.")
        deadline = monotonic() + timeout
        raw = bytearray()
        try:
            with build_opener(RejectRedirects()).open(request, timeout=timeout) as response:
                while True:
                    chunk = response.read1(16_384)
                    if monotonic() >= deadline:
                        raise TimeoutError
                    if not chunk:
                        break
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise ModelError("Model gateway response exceeded the size limit.")
            envelope = parse_json(raw)
        except HTTPError as exc:
            delay = retry_delay(exc.headers.get("Retry-After")) if exc.code in (429, 502, 503, 504) else None
            exc.close()
            raise ModelError(f"Model gateway returned HTTP {exc.code}.", retry_after=delay) from None
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise ModelError("Model gateway request timed out.") from None
            raise ModelError("Could not complete the model gateway request.") from None
        except TimeoutError:
            raise ModelError("Model gateway request timed out.") from None
        except (OSError, HTTPException):
            raise ModelError("Could not complete the model gateway request.") from None
        except (ValueError, RecursionError):
            raise ModelError("Model gateway response is not valid JSON.") from None

        try:
            content = envelope["choices"][0]["message"]["content"]
        except (TypeError, KeyError, IndexError):
            raise ModelError("Model gateway response is missing message content.") from None
        if not isinstance(content, str) or not content.strip():
            raise ModelError("Model gateway returned empty message content.")

        lines = content.strip().splitlines()
        fence = chr(96) * 3
        if lines[0].strip().lower() in (fence, f"{fence}json") and lines[-1].strip() == fence:
            lines = lines[1:-1]
        try:
            result = parse_json("\n".join(lines))
        except (ValueError, RecursionError):
            raise ModelError("The model message is not a JSON object.") from None
        if not isinstance(result, dict):
            raise ModelError("The model message is not a JSON object.")
        return result
