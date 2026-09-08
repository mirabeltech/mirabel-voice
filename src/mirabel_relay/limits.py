"""Request budgets and an optional shared per-person rate limit. No payload logging."""
from __future__ import annotations
import hashlib
import json
import time
from email.parser import BytesParser
from email.policy import default


class Rejected(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class Limits:
    MAX_BODY = 4_100_000  # Leaves room for Lambda's base64/event overhead.
    AUDIO_MODELS = {'gpt-4o-transcribe', 'gpt-4o-mini-transcribe', 'whisper-1'}
    CLEANUP_MODELS = {'claude-haiku-4-5', 'claude-haiku-4-5-20251001'}

    def __init__(self, limiter=None):
        self.limiter = limiter

    def validate(self, request, person):
        if len(request.body) > self.MAX_BODY:
            raise Rejected(413, 'Recording is too large. Use a shorter recording.')
        if request.method != 'POST':
            return
        if request.path == '/v1/messages':
            if len(request.body) > 256_000:
                raise Rejected(413, 'Text is too large for cleanup.')
            try:
                body = json.loads(request.body)
            except (ValueError, UnicodeError):
                raise Rejected(400, 'Invalid cleanup request.')
            if not isinstance(body, dict) or not isinstance(body.get('model'), str) or body.get('model') not in self.CLEANUP_MODELS:
                raise Rejected(400, 'This cleanup model is not approved.')
            tokens = body.get('max_tokens')
            if type(tokens) is not int or not 1 <= tokens <= 8000:
                raise Rejected(400, 'Cleanup output must be limited to 8000 tokens.')
            if body.get('stream') or set(body) - {'model', 'max_tokens', 'messages', 'system', 'temperature', 'stop_sequences', 'stream'}:
                raise Rejected(400, 'Unsupported cleanup option.')
            # Only text content: remote images/documents/tools create extra cost paths.
            messages = body.get('messages')
            if not isinstance(messages, list) or not messages:
                raise Rejected(400, 'Cleanup needs text messages.')
            for message in messages:
                if not isinstance(message, dict) or message.get('role') not in {'user', 'assistant'} or not isinstance(message.get('content'), str):
                    raise Rejected(400, 'Cleanup accepts plain text only.')
            system = body.get('system', '')
            if not isinstance(system, str):
                raise Rejected(400, 'Cleanup instructions must be plain text.')
        elif request.path == '/v1/audio/transcriptions':
            headers = {k.lower(): v for k, v in request.headers.items()}
            content_type = headers.get('content-type', '')
            if '\r' in content_type or '\n' in content_type:
                raise Rejected(400, 'Invalid audio content type.')
            message = BytesParser(policy=default).parsebytes(b'Content-Type: ' + content_type.encode('ascii', errors='replace') + b'\r\nMIME-Version: 1.0\r\n\r\n' + request.body)
            if not message.is_multipart():
                raise Rejected(400, 'Audio needs a multipart upload.')
            fields = {}
            for part in message.iter_parts():
                name = part.get_param('name', header='content-disposition')
                if name in fields or name not in {'file', 'model', 'language', 'prompt', 'response_format', 'temperature'}:
                    raise Rejected(400, 'Unsupported or duplicate audio field.')
                fields[name] = part.get_payload(decode=True) or b''
            if fields.get('model', b'').decode('utf-8', errors='replace') not in self.AUDIO_MODELS:
                raise Rejected(400, 'This transcription model is not approved.')
            if not fields.get('file'):
                raise Rejected(400, 'No audio was supplied.')
        else:
            return
        if self.limiter:
            try:
                allowed = self.limiter.allow(person)
            except Exception:
                raise Rejected(503, 'Usage limits could not be checked. Try again shortly.')
            if not allowed:
                raise Rejected(429, 'Too many requests. Wait a minute and retry.')


class DynamoRateLimit:
    """Atomic counters shared by every Lambda worker; table TTL attribute is expires."""
    def __init__(self, client, table, per_minute, clock=time.time):
        if type(per_minute) is not int or not 1 <= per_minute <= 1000:
            raise ValueError('Requests per minute must be between 1 and 1000')
        self.client, self.table, self.limit, self.clock = client, table, per_minute, clock

    def allow(self, person):
        minute = int(self.clock() // 60)
        key = hashlib.sha256(person.encode()).hexdigest() + ':' + str(minute)
        try:
            self.client.update_item(
                TableName=self.table, Key={'pk': {'S': key}},
                UpdateExpression='SET expires = :expires ADD #count :one',
                ConditionExpression='attribute_not_exists(#count) OR #count < :limit',
                ExpressionAttributeNames={'#count': 'count'},
                ExpressionAttributeValues={':one': {'N': '1'}, ':limit': {'N': str(self.limit)}, ':expires': {'N': str((minute + 2) * 60)}},
            )
            return True
        except Exception as error:
            if getattr(error, 'response', {}).get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
                return False
            raise
