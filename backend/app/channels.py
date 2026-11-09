import ipaddress
import json
import re
import smtplib
import socket
import ssl
from email.message import EmailMessage
from urllib.parse import urlsplit
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .config import settings


class DeliveryError(Exception):
    """Safe error text; never contains provider responses or credentials."""


class SMTPConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=465, ge=1, le=65535)
    tls: str = Field(default='ssl', pattern='^(ssl|starttls)$')
    username: str = Field(min_length=1, max_length=254)
    sender: str = Field(min_length=3, max_length=254)
    recipient: str = Field(min_length=3, max_length=254)


class PushConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    server: str = Field(min_length=8, max_length=500)


class Rules(BaseModel):
    keywords: list[str] = Field(default_factory=list, max_length=30)
    content_mode: str = Field(default='full', pattern='^(full|extract)$')
    patterns: list[str] = Field(default_factory=list, max_length=10)

    @field_validator('keywords', 'patterns')
    @classmethod
    def check_items(cls, values):
        if any(not isinstance(value, str) or not value.strip() or len(value) > 256 for value in values):
            raise ValueError('规则不能为空或过长')
        return values


class QuickerConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    toUser: str = Field(min_length=1, max_length=254)
    toDevice: str = Field(default='', max_length=100)
    operation: str = Field(default='PASTE', min_length=1, max_length=50)
    action: str = Field(default='', max_length=200)
    wait: bool = True
    maxWaitMs: int = Field(default=3000, ge=1, le=30000)


def matches_keywords(config, body):
    words = config.get('keywords') or []
    return not words or any(word.casefold() in body.casefold() for word in words)


def delivery_content(config, body, legacy_content):
    mode = config.get('content_mode')
    if mode is None:
        return legacy_content
    if mode == 'full':
        return body
    for pattern in config.get('patterns', []):
        match = re.search(pattern, body[:16000])
        if match:
            value = match.group(1) if match.lastindex else match.group(0)
            if value:
                return value
    return None


def validate_channel(kind, config, credentials):
    if kind not in ('smtp', 'bark', 'pushdeer', 'quicker'):
        raise ValueError('通道类型无效')
    raw = dict(config)
    rules = Rules.model_validate({key: raw.pop(key) for key in ('keywords', 'content_mode', 'patterns') if key in raw}).model_dump()
    if rules['content_mode'] == 'extract' and not rules['patterns']:
        raise ValueError('截取模式需要正则表达式')
    for pattern in rules['patterns']:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError('正则表达式无效') from exc
    schema = SMTPConfig if kind == 'smtp' else QuickerConfig if kind == 'quicker' else PushConfig
    parsed = schema.model_validate(raw).model_dump()
    if kind == 'smtp':
        for field in ('sender', 'recipient'):
            if '@' not in parsed[field] or any(c in parsed[field] for c in '\r\n'):
                raise ValueError('邮箱格式不正确')
        host = parsed['host']
    elif kind != 'quicker':
        url = urlsplit(parsed['server'])
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('推送服务需要不含凭据和查询参数的 HTTPS 地址')
        host = url.hostname
    else:
        host = 'push.getquicker.cn'
    if not host or '/' in host or any(c.isspace() for c in host):
        raise ValueError('服务地址无效')
    required = 'password' if kind == 'smtp' else 'code' if kind == 'quicker' else 'key'
    if not credentials or set(credentials) != {required} or not isinstance(credentials[required], str) or not 1 <= len(credentials[required]) <= 1024:
        raise ValueError(f'请提供 {required}')
    return {**parsed, **rules}


def public_host(host):
    if settings().allow_private_notifications:
        return
    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise DeliveryError('通知地址指向非公网网络；自建内网服务需启用部署配置')
    except socket.gaierror as exc:
        raise DeliveryError('通知服务域名解析失败') from exc


def deliver(kind, config, credentials, title, content):
    try:
        config = validate_channel(kind, config, credentials)
        if kind == 'smtp':
            public_host(config['host'])
            message = EmailMessage()
            message['From'] = config['sender']
            message['To'] = config['recipient']
            message['Subject'] = title.replace('\r', ' ').replace('\n', ' ')[:150]
            message.set_content(content)
            context = ssl.create_default_context()
            if config['tls'] == 'ssl':
                client = smtplib.SMTP_SSL(config['host'], config['port'], timeout=20, context=context)
            else:
                client = smtplib.SMTP(config['host'], config['port'], timeout=20)
            with client:
                if config['tls'] == 'starttls':
                    client.starttls(context=context)
                client.login(config['username'], credentials['password'])
                if client.send_message(message):
                    raise DeliveryError('收件人被邮件服务拒绝')
            return
        base = 'https://push.getquicker.cn/to/quicker' if kind == 'quicker' else config['server'].rstrip('/')
        public_host(urlsplit(base).hostname)
        with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
            if kind == 'quicker':
                payload = {key: config[key] for key in ('toUser', 'operation', 'wait', 'maxWaitMs')}
                payload.update({'code': credentials['code'], 'data': content})
                for key in ('toDevice', 'action'):
                    if config[key]:
                        payload[key] = config[key]
                response = client.post(base, json=payload)
                response.raise_for_status()
                result = response.json()
                if result.get('isSuccess') is not True or result.get('successCount', 0) < 1:
                    raise DeliveryError('Quicker 返回投递失败')
            elif kind == 'bark':
                response = client.post(base + '/push', json={'device_key': credentials['key'], 'title': title, 'body': content, 'group': 'SMSBot'})
                response.raise_for_status()
                if response.json().get('code') != 200:
                    raise DeliveryError('Bark 返回投递失败')
            else:
                response = client.post(base + '/message/push', data={'pushkey': credentials['key'], 'text': title, 'desp': content, 'type': 'text'})
                response.raise_for_status()
                data = response.json()
                if data.get('code') != 0:
                    raise DeliveryError('PushDeer 返回投递失败')
                results = data.get('content', {}).get('result', [])
                if not results:
                    raise DeliveryError('PushDeer 没有返回有效投递结果')
                for item in results:
                    detail = json.loads(item) if isinstance(item, str) else item
                    if not isinstance(detail, dict) or detail.get('success', 0) < 1:
                        raise DeliveryError('PushDeer 设备投递失败')
    except DeliveryError:
        raise
    except Exception as exc:
        # Provider exceptions often include URLs / tokens; do not persist them.
        raise DeliveryError('通知发送失败 (' + type(exc).__name__ + ')') from None
