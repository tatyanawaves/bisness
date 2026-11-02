"""
Клиент языковой модели (Groq, OpenAI-совместимый API).
Ответы запрашиваются в JSON, чтобы их можно было проверить перед использованием.
"""

import json
import re
import time

import requests

from . import config

MAX_ATTEMPTS = 3
# Дольше не ждём: при дневном лимите Groq просит ждать часами, запрос лучше завершить сразу
MAX_WAIT_SECONDS = 30
DEFAULT_WAIT_SECONDS = 15


class LLMError(Exception):
    """Модель не настроена, недоступна или вернула непригодный ответ."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def is_configured() -> bool:
    return bool(config.GROQ_API_KEY)


def model_name() -> str:
    return config.LLM_MODEL


def parse_json(text: str) -> dict:
    """Достаёт JSON-объект из ответа модели, в том числе обёрнутый в ```json."""
    cleaned = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("В ответе модели нет JSON") from None
        try:
            data = json.loads(cleaned[start: end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError("Модель вернула некорректный JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("Модель вернула не объект JSON")
    return data


def _retry_after(resp: requests.Response) -> float:
    try:
        return float(resp.headers.get("retry-after", DEFAULT_WAIT_SECONDS))
    except ValueError:
        return DEFAULT_WAIT_SECONDS


def chat_json(system: str, user: str, max_tokens: int = 1500, temperature: float = 0.2) -> dict:
    """
    Запрашивает у модели JSON-объект.

    При лимите запросов ждёт и повторяет, при некорректном JSON повторяет сразу.
    Если получить ответ не удалось, поднимает LLMError.
    """
    if not is_configured():
        raise LLMError("not_configured", "Не задан GROQ_API_KEY")

    payload = {
        "model": config.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if config.LLM_MODEL.startswith("openai/gpt-oss"):
        # Рассуждения съедают лимит токенов в минуту, для этих задач хватает минимума
        payload["reasoning_effort"] = "low"
        payload["include_reasoning"] = False

    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    problem = "Модель не вернула ответ"
    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = requests.post(
                f"{config.LLM_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=90,
            )
        except requests.RequestException as exc:
            problem = f"Модель недоступна: {type(exc).__name__}"
            continue

        if resp.status_code == 429:
            wait = _retry_after(resp)
            if wait > MAX_WAIT_SECONDS or attempt == MAX_ATTEMPTS - 1:
                raise LLMError("rate_limited", "Исчерпан лимит бесплатного тарифа модели")
            time.sleep(wait)
            continue

        if resp.status_code in (401, 403):
            raise LLMError("bad_key", "Модель отклонила ключ. Проверьте GROQ_API_KEY")

        if resp.status_code == 400 and "json_validate_failed" in resp.text:
            problem = "Модель вернула некорректный JSON"
            continue

        if resp.status_code >= 400:
            raise LLMError("http_error", f"Модель вернула ошибку {resp.status_code}")

        try:
            choice = resp.json()["choices"][0]
            if choice.get("finish_reason") == "length":
                problem = "Ответ модели оборвался на лимите токенов"
                continue
            return parse_json(choice["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            problem = str(exc) or "Модель вернула непригодный ответ"

    raise LLMError("bad_response", problem)
