"""AI provider abstraction.

The application talks to ``AIProvider`` only. Which provider is used is a
configuration choice (AI_PROVIDER / AI_MODEL / AI_API_KEY / AI_BASE_URL in the
environment), so switching vendors or moving to a local model needs no code
change. Providers call plain HTTPS endpoints through httpx - no vendor SDKs.

    AIProvider
      |-- OpenAIProvider       (OpenAI chat-completions API)
      |-- GeminiProvider       (Google Generative Language API)
      |-- AnthropicProvider    (Anthropic Messages API)
      `-- LocalModelProvider   (any OpenAI-compatible local server, e.g. Ollama)

With AI_PROVIDER=none the platform falls back to its deterministic rule
engine and labels the output as such; it never fakes an AI answer.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class AIUnavailableError(RuntimeError):
    """No provider is configured, or the provider call failed."""


class AIProvider(ABC):
    name: str = "base"

    def __init__(self, model: str, api_key: str | None = None, base_url: str | None = None, timeout: float = 60.0) -> None:
        if not model:
            raise AIUnavailableError("AI_MODEL is not set. Set it to a model name offered by your AI provider.")
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or self.default_base_url).rstrip("/")
        self.timeout = timeout

    default_base_url: str = ""

    @abstractmethod
    def complete(self, system: str, messages: list[dict[str, str]], max_tokens: int = 1200) -> str:
        """Return the assistant's reply. ``messages`` is [{"role": "user"|"assistant", "content": str}]."""

    def _post(self, url: str, headers: dict, payload: dict) -> dict:
        import httpx

        try:
            response = httpx.post(url, headers=headers, json=payload, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise AIUnavailableError(f"The AI provider could not be reached ({type(exc).__name__}).") from exc
        if response.status_code >= 400:
            # the body may echo the request; log-safe message only
            raise AIUnavailableError(f"The AI provider returned an error (HTTP {response.status_code}).")
        return response.json()

    def _require_key(self) -> str:
        if not self.api_key:
            raise AIUnavailableError("AI_API_KEY is not set for the configured AI provider.")
        return self.api_key


class OpenAIProvider(AIProvider):
    name = "openai"
    default_base_url = "https://api.openai.com/v1"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._require_key()}", "Content-Type": "application/json"}

    def complete(self, system, messages, max_tokens=1200):
        payload = {"model": self.model, "messages": [{"role": "system", "content": system}, *messages], "temperature": 0.2}
        data = self._post(f"{self.base_url}/chat/completions", self._headers(), payload)
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, AttributeError, TypeError) as exc:
            raise AIUnavailableError("The AI provider returned an unexpected response.") from exc


class LocalModelProvider(OpenAIProvider):
    """OpenAI-compatible server running on your own machine (Ollama, LM Studio,
    llama.cpp, vLLM). No data leaves the machine and no API key is needed."""
    name = "local"
    default_base_url = "http://localhost:11434/v1"

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


class GeminiProvider(AIProvider):
    name = "gemini"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"

    def complete(self, system, messages, max_tokens=1200):
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in messages]
        payload = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                   "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens}}
        headers = {"x-goog-api-key": self._require_key(), "Content-Type": "application/json"}
        data = self._post(f"{self.base_url}/models/{self.model}:generateContent", headers, payload)
        try:
            return "".join(part.get("text", "") for part in data["candidates"][0]["content"]["parts"]).strip()
        except (KeyError, IndexError, AttributeError, TypeError) as exc:
            raise AIUnavailableError("The AI provider returned an unexpected response.") from exc


class AnthropicProvider(AIProvider):
    name = "anthropic"
    default_base_url = "https://api.anthropic.com/v1"

    def complete(self, system, messages, max_tokens=1200):
        payload = {"model": self.model, "system": system, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2}
        headers = {"x-api-key": self._require_key(), "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
        data = self._post(f"{self.base_url}/messages", headers, payload)
        try:
            return "".join(block.get("text", "") for block in data["content"] if block.get("type") == "text").strip()
        except (KeyError, AttributeError, TypeError) as exc:
            raise AIUnavailableError("The AI provider returned an unexpected response.") from exc


PROVIDERS: dict[str, type[AIProvider]] = {
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "anthropic": AnthropicProvider,
    "local": LocalModelProvider,
}


def build_provider(name: str | None, model: str | None, api_key: str | None = None, base_url: str | None = None) -> AIProvider | None:
    """Create the configured provider, or None when AI is switched off."""
    key = (name or "none").strip().lower()
    if key in ("", "none", "off", "disabled"):
        return None
    if key not in PROVIDERS:
        raise AIUnavailableError(f"Unknown AI_PROVIDER '{name}'. Choose one of: none, {', '.join(PROVIDERS)}.")
    return PROVIDERS[key](model=model or "", api_key=api_key, base_url=base_url)
