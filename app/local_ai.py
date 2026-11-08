"""Shared OpenAI-compatible text inference for every local AI feature.

Prompt practices applied across the codebase (small local models such as Qwen
benefit from them the most):
- One task per prompt with an explicit output contract and a JSON schema.
- The critical contract is repeated AFTER the data (lost-in-the-middle guard):
  complete_json appends the schema reminder as the final user message. Long value
  lists (such as every timestamp of a part) are shown as a short description there;
  the server still enforces them through response_format.
- A one-shot example anchors the format where the format is subtle (meeting
  notes items, meeting titles).
- Prompts say what TO do and give a reason, not only what to avoid; the model
  may always answer null / found=false / [] instead of guessing.
- Qwen3.5 thinking can exhaust the output budget before any JSON appears, so
  JSON tasks default to reasoning 'none' below unless the user chose otherwise.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit
from urllib.request import urlopen

DEFAULT_BASE_URL = 'http://localhost:1235/v1'
DEFAULT_MODEL = 'qwen3.5-9b'
DEFAULT_CONTEXT = 16384


class KeyStore:
    """The key of the configured API in the shared Atlanta Keychain item. A local server needs none."""
    def __new__(cls):
        from .credentials import CredentialStore
        return CredentialStore('default', 'local_ai')


def is_remote(base_url):
    """True when the configured API is outside this Mac and its local network, so text leaves them."""
    import ipaddress
    host = (urlsplit(base_url or '').hostname or '').casefold()
    if host == 'localhost' or host.endswith('.local'):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (address.is_loopback or address.is_private or address.is_link_local)


class OutputTruncatedError(ValueError):
    """The endpoint exhausted its output budget; callers may split the input."""

    def __init__(self, message, can_split=True):
        super().__init__(message)
        self.can_split = can_split


def validate_base_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError('Enter an HTTP API base URL, for example http://localhost:1235/v1')
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        raise ValueError('Invalid local AI API URL') from None
    if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('Use an HTTP(S) API base URL without credentials, query or fragment')
    if url.path.rstrip('/').endswith(('/chat/completions', '/models')):
        raise ValueError('Enter the API base URL ending in /v1, not a specific API operation')
    return value.rstrip('/')


def migrate_settings(settings):
    settings = dict(settings)
    for field in ('summarizer', 'title_provider'):
        if settings.get(field) == 'ollama':
            settings[field] = 'local'
    return settings


def list_models(base_url):
    base_url = validate_base_url(base_url)
    try:
        with urlopen(base_url + '/models', timeout=15) as response:
            payload = json.load(response)
    except Exception as exc:
        raise ValueError('Cannot read models from the configured AI endpoint. Check its URL and that the server is running.') from exc
    if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
        raise ValueError('The AI endpoint did not return an OpenAI-compatible model list')
    models = list(dict.fromkeys(item['id'] for item in payload['data']
        if isinstance(item, dict) and isinstance(item.get('id'), str) and item['id'].strip()))
    return models


# A value list longer than this is described, not listed, in the prompt text.
SCHEMA_ENUM_LIMIT = 24


def schema_hint(schema):
    """The schema for the prompt text. A long enum repeats every timestamp of a part in each of
    about ten fields; that doubled a notes prompt and filled the local context."""
    if isinstance(schema, list):
        return [schema_hint(value) for value in schema]
    if not isinstance(schema, dict):
        return schema
    hint = {key: schema_hint(value) for key, value in schema.items() if key != 'enum'}
    values = schema.get('enum')
    if isinstance(values, list):
        if len(values) > SCHEMA_ENUM_LIMIT:
            hint['description'] = 'One value that appears in the input' + (' or null' if None in values else '') + '.'
        else:
            hint['enum'] = values
    return hint


def server_reason(exc):
    """The HTTP status and the short error message of the AI server, so a person sees why it refused."""
    import urllib.error
    if not isinstance(exc, urllib.error.HTTPError):
        return ''
    try:
        body = exc.read(4000).decode('utf-8', 'replace')
        data = json.loads(body)
        error = data.get('error') if isinstance(data, dict) else None
        message = error.get('message') if isinstance(error, dict) else error if isinstance(error, str) else data.get('message') if isinstance(data, dict) else None
    except (OSError, ValueError, AttributeError):
        message = None
    message = ' '.join(str(message).split())[:300] if message else ''
    message = re.sub(r'sk-[A-Za-z0-9_-]{8,}', 'sk-…', message)
    return f' The server answered HTTP {exc.code}' + (f': {message}' if message else '.')


def complete_json(settings, messages, schema, name, timeout=600, api_key=''):
    from meeting_assistant import post_json, extract_json
    base_url = validate_base_url(settings.get('local_ai_base_url', DEFAULT_BASE_URL))
    model = settings.get('local_ai_model', DEFAULT_MODEL)
    mode = settings.get('local_ai_format', 'json_schema')
    if mode not in {'json_schema', 'json_object', 'text'}:
        raise ValueError('Invalid API response format')
    # Include the schema in the prompt even when the server cannot constrain output.
    from .prompts import apply
    messages = apply(settings,messages,name)
    messages.append({'role': 'user', 'content': 'Return only one JSON object matching this schema: ' + json.dumps(schema_hint(schema), ensure_ascii=False)})
    max_tokens = settings.get('local_ai_max_tokens', 4096)
    if type(max_tokens) is not int or not 128 <= max_tokens <= 32768:
        raise ValueError('API output limit must be between 128 and 32768 tokens')
    reasoning = settings.get('local_ai_reasoning', 'default')
    if reasoning not in {'default', 'server', 'none', 'low', 'medium', 'high'}:
        raise ValueError('Invalid API reasoning effort')
    # Qwen3.5 can consume the entire budget on thinking without returning JSON.
    # Apply this task policy before requesting, not after a slow, empty response.
    # Email extraction keeps its separately approved target settings unchanged.
    # A cloud API (Kimi K3) also spent a 16,384-token budget on thinking and returned no notes.
    # Topic matching is a short classification; on a cloud API, thinking only makes a speaker rename slow.
    if reasoning == 'default' and (
            name in {'meeting_minutes', 'meeting_consolidation', 'transcript_correction', 'meeting_title', 'team_review'}
            and (is_remote(base_url) or isinstance(model, str) and re.search(r'(?:^|/)qwen3\.5(?:-|$)', model, re.I))
            or name == 'topic_matches' and is_remote(base_url)):
        reasoning = 'none'
    payload = dict(model=model, messages=messages, stream=False, max_tokens=max_tokens)
    # Some cloud models accept only their own temperature (Kimi K3: only 1). "server" leaves it to them.
    if settings.get('local_ai_temperature', 'zero') == 'zero':
        payload['temperature'] = 0
    if reasoning not in {'default', 'server'}:
        payload['reasoning_effort'] = reasoning
    if mode == 'json_schema':
        payload['response_format'] = {'type': 'json_schema', 'json_schema': {'name': name, 'strict': True, 'schema': schema}}
    elif mode == 'json_object':
        payload['response_format'] = {'type': 'json_object'}
    try:
        response = post_json(base_url + '/chat/completions', payload, timeout=timeout,
            **({'headers': {'Authorization': 'Bearer ' + api_key}} if api_key else {}))
    except Exception as exc:
        raise ValueError('Configured API request failed. Check the API URL, model and response format in Settings. No cloud fallback was used.' + server_reason(exc)) from exc
    try:
        choice = response['choices'][0]
        if choice.get('finish_reason') == 'length':
            content = choice.get('message', {}).get('content')
            # Splitting cannot help a model that spends the budget before it
            # starts its answer (for example, on reasoning alone).
            can_split = isinstance(content, str) and bool(content.strip())
            detail = ('The answer exceeded the output limit.' if can_split else
                      'The server returned no answer text before reaching the limit; reasoning may have used the budget.')
            effort = 'server default' if reasoning in {'default', 'server'} else reasoning
            raise OutputTruncatedError(f'The model output was truncated. {detail} '
                f'Output limit: {max_tokens} tokens; reasoning: {effort}. '
                'Choose Reasoning effort Off, increase the output limit, or choose another model in Settings. '
                'The recording and previous results were kept.', can_split=can_split)
        content = choice['message']['content']
        if not isinstance(content, str) or not content.strip():
            raise ValueError('The model returned no text')
        result = extract_json(content)
        if not isinstance(result, dict):
            raise ValueError('The model must return a JSON object')
        return result
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError('The AI endpoint returned an invalid chat completion') from exc
