import ipaddress
import json
import smtplib
import socket
import ssl
from email.message import EmailMessage
from urllib.parse import urlsplit
import httpx
from pydantic import BaseModel, ConfigDict, Field
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


def validate_channel(kind, config, credentials):
    schema = SMTPConfig if kind == 'smtp' else PushConfig
    parsed = schema.model_validate(config).model_dump()
    if kind == 'smtp':
        for field in ('sender', 'recipient'):
            if '@' not in parsed[field] or any(c in parsed[field] for c in '\r\n'):
                raise ValueError('邮箱格式不正确')
        host = parsed['host']
    else:
        url = urlsplit(parsed['server'])
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('推送服务需要不含凭据和查询参数的 HTTPS 地址')
        host = url.hostname
    if not host or '/' in host or any(c.isspace() for c in host):
        raise ValueError('服务地址无效')
    required = 'password' if kind == 'smtp' else 'key'
    if not credentials or set(credentials) != {required} or not isinstance(credentials[required], str) or not 1 <= len(credentials[required]) <= 1024:
        raise ValueError(f'请提供 {required}')
    return parsed


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
        base = config['server'].rstrip('/')
        public_host(urlsplit(base).hostname)
        with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
            if kind == 'bark':
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
