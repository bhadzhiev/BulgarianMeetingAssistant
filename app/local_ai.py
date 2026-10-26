"""Shared OpenAI-compatible text inference for every local AI feature."""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit
from urllib.request import urlopen

DEFAULT_BASE_URL = 'http://localhost:1235/v1'
DEFAULT_MODEL = 'qwen3.5-9b'


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


def complete_json(settings, messages, schema, name, timeout=600):
    from meeting_assistant import post_json, extract_json
    base_url = validate_base_url(settings.get('local_ai_base_url', DEFAULT_BASE_URL))
    model = settings.get('local_ai_model', DEFAULT_MODEL)
    mode = settings.get('local_ai_format', 'json_schema')
    if mode not in {'json_schema', 'json_object', 'text'}:
        raise ValueError('Invalid local AI response format')
    # Include the schema in the prompt even when the server cannot constrain output.
    messages = [dict(m) for m in messages]
    messages.append({'role': 'user', 'content': 'Return only one JSON object matching this schema: ' + json.dumps(schema, ensure_ascii=False)})
    max_tokens = settings.get('local_ai_max_tokens', 4096)
    if type(max_tokens) is not int or not 128 <= max_tokens <= 32768:
        raise ValueError('Local AI output limit must be between 128 and 32768 tokens')
    reasoning = settings.get('local_ai_reasoning', 'default')
    if reasoning not in {'default', 'server', 'none', 'low', 'medium', 'high'}:
        raise ValueError('Invalid local AI reasoning effort')
    # Qwen3.5 can consume the entire budget on thinking without returning JSON.
    # Apply this task policy before requesting, not after a slow, empty response.
    # Email extraction keeps its separately approved target settings unchanged.
    if (reasoning == 'default' and name in {'meeting_minutes', 'transcript_correction', 'meeting_title'}
            and isinstance(model, str) and re.search(r'(?:^|/)qwen3\.5(?:-|$)', model, re.I)):
        reasoning = 'none'
    payload = dict(model=model, messages=messages, temperature=0, stream=False, max_tokens=max_tokens)
    if reasoning not in {'default', 'server'}:
        payload['reasoning_effort'] = reasoning
    if mode == 'json_schema':
        payload['response_format'] = {'type': 'json_schema', 'json_schema': {'name': name, 'strict': True, 'schema': schema}}
    elif mode == 'json_object':
        payload['response_format'] = {'type': 'json_object'}
    try:
        response = post_json(base_url + '/chat/completions', payload, timeout=timeout)
    except Exception as exc:
        raise ValueError('Local AI request failed. Check the API URL, model and response format in Settings. No cloud fallback was used.') from exc
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
