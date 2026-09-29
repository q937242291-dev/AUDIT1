"""Built-in JSON chat-completions HTTP transport; no import-time network activity.

The configured endpoint must accept model/messages/response_format and return
choices[0].message.content containing a JSON object. Credentials are read only
when invoked. This module does not select a model, retry, or start experiments.
"""
from __future__ import annotations

import json
import math
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .contracts import ProtocolError, require


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProtocolError('Provider redirects are disabled to protect credentials')


class CompatibleHTTPProvider:
    """Callable provider for PipelineAdapter, requiring no user-written callback."""

    def __init__(self, config: dict | None = None):
        config = {} if config is None else dict(config)
        allowed = {'transport', 'endpoint_env', 'api_key_env', 'timeout_seconds',
                   'max_response_bytes', 'max_tokens', 'send_reasoning_effort'}
        require(not set(config) - allowed, 'Unknown HTTP provider configuration field')
        require(config.get('transport', 'compatible_http') == 'compatible_http', 'Unknown provider transport')
        self.endpoint_env = config.get('endpoint_env', 'AUDIT_HTTP_ENDPOINT')
        self.api_key_env = config.get('api_key_env', 'AUDIT_API_KEY')
        for name in (self.endpoint_env, self.api_key_env):
            require(isinstance(name, str) and name.isidentifier(), 'Use an environment variable name, not a credential')
        self.timeout = config.get('timeout_seconds', 60)
        require(type(self.timeout) in (int, float) and math.isfinite(self.timeout) and self.timeout > 0,
                'Provider timeout must be finite and positive')
        self.max_bytes = config.get('max_response_bytes', 2_000_000)
        require(type(self.max_bytes) is int and 0 < self.max_bytes <= 20_000_000, 'Invalid response size limit')
        self.max_tokens = config.get('max_tokens')
        require(self.max_tokens is None or type(self.max_tokens) is int and self.max_tokens > 0, 'Invalid max_tokens')
        self.send_reasoning = config.get('send_reasoning_effort', True)
        require(type(self.send_reasoning) is bool, 'send_reasoning_effort must be boolean')

    def __call__(self, request: dict) -> dict:
        require(self.send_reasoning or request.get('reasoning_effort') is None,
                'Declared reasoning_effort cannot be disabled by provider configuration')
        endpoint = os.environ.get(self.endpoint_env, '').strip()
        require(endpoint, f'Set {self.endpoint_env} to the complete JSON chat-completions endpoint')
        url = urlsplit(endpoint)
        local = url.hostname in {'localhost', '127.0.0.1', '::1'}
        require(url.scheme == 'https' or url.scheme == 'http' and local,
                'Provider endpoint requires HTTPS (HTTP is permitted only on loopback)')
        require(bool(url.hostname) and url.username is None and url.password is None and not url.fragment,
                'Provider endpoint must not contain credentials or a fragment')
        key = os.environ.get(self.api_key_env, '')
        require(bool(key) or local, f'Set {self.api_key_env} for the remote provider')
        require(isinstance(request.get('model'), str) and request['model'].strip(), 'Explicit model ID is required')
        body = {'model': request['model'], 'messages': [
            {'role': 'system', 'content': request['system']},
            {'role': 'user', 'content': request['prompt']}], 'response_format': {'type': 'json_object'}}
        if self.max_tokens is not None:
            body['max_tokens'] = self.max_tokens
        if self.send_reasoning and request.get('reasoning_effort') is not None:
            body['reasoning_effort'] = request['reasoning_effort']
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if key:
            headers['Authorization'] = 'Bearer ' + key
        req = Request(endpoint, data=json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8'),
                      headers=headers, method='POST')
        try:
            with build_opener(_NoRedirect()).open(req, timeout=self.timeout) as response:
                require(200 <= response.status < 300, 'Provider returned a non-success status')
                raw = response.read(self.max_bytes + 1)
        except HTTPError as exc:
            raise ProtocolError(f'Provider HTTP status {exc.code}; no automatic retry') from None
        except (URLError, TimeoutError, OSError):
            raise ProtocolError('Provider connection failed; no automatic retry') from None
        require(len(raw) <= self.max_bytes, 'Provider response exceeded configured size limit')
        try:
            envelope = json.loads(raw.decode('utf-8'))
            choice = envelope['choices'][0]
            require(choice.get('finish_reason') in (None, 'stop'), 'Provider response did not finish normally')
            parsed = json.loads(choice['message']['content'])
            require(isinstance(parsed, dict), 'Provider content must be a JSON object')
            usage = envelope.get('usage', {})
            require(isinstance(usage, dict), 'Provider usage must be an object')
        except (KeyError, IndexError, TypeError, UnicodeError, ValueError) as exc:
            if isinstance(exc, ProtocolError):
                raise
            raise ProtocolError('Malformed JSON chat-completions response') from None
        return {'parsed': parsed, 'usage': usage}
