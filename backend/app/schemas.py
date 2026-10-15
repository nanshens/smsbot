from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Login(Input):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)
    code: str = Field(default='', max_length=100)


class Factor(Input):
    code: str = Field(min_length=6, max_length=100)


class SecurityChange(Factor):
    password: str = Field(min_length=1, max_length=200)
    new_password: str | None = Field(default=None, min_length=8, max_length=200)


class SimEdit(Input):
    name: str = Field(min_length=1, max_length=100)
    phone_number: str | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=2000)


class Bindings(Input):
    channel_ids: list[UUID] = Field(max_length=20)


class Outgoing(Input):
    sim_id: UUID
    recipient: str = Field(pattern=r'^\+?[0-9]{3,20}$')
    body: str = Field(min_length=1, max_length=1000)
    idempotency_key: UUID
    retry_of: UUID | None = None

    @field_validator('body')
    @classmethod
    def supported_text(cls, value):
        # SIM UCS2 cannot represent supplementary-plane emoji. Reject explicitly.
        if any(ord(c) > 0xFFFF or 0xD800 <= ord(c) <= 0xDFFF or ord(c) == 0 for c in value):
            raise ValueError('短信暂不支持 emoji 等非 BMP 字符或空字符')
        if len(value) > 670:
            raise ValueError('短信最多 670 个字符（最多 10 个 UCS2 分片）')
        return value


class Channel(Input):
    name: str = Field(min_length=1, max_length=100)
    type: Literal['smtp', 'bark', 'pushdeer']
    enabled: bool = True
    config: dict
    credentials: dict | None = None


class Registration(Input):
    request_id: UUID
    pairing_code: str = Field(min_length=10, max_length=128)
    hardware_id: str = Field(min_length=6, max_length=128)
    iccid: str = Field(pattern=r'^[0-9]{10,32}$')
    name: str = Field(default='LILYGO', min_length=1, max_length=100)
    firmware_version: str = Field(default='', max_length=100)
    modem_version: str = Field(default='', max_length=150)


class Activation(Input):
    hardware_id: str = Field(min_length=6, max_length=128)
    iccid: str = Field(pattern=r'^[0-9]{10,32}$')
    firmware_version: str = Field(default='', max_length=100)
    modem_version: str = Field(default='', max_length=150)


class PhoneCreate(Input):
    name: str = Field(min_length=1, max_length=100)
    phone_number: str = Field(pattern=r'^\+?[0-9]{3,20}$')


class Heartbeat(Input):
    iccid: str = Field(max_length=32)
    operator_name: str = Field(default='', max_length=100)
    sim_status: str = Field(default='unknown', max_length=40)
    network_status: str = Field(default='unknown', max_length=40)
    signal_dbm: int | None = Field(default=None, ge=-150, le=-20)
    queue_depth: int = Field(default=0, ge=0, le=10000)
    last_error: str | None = Field(default=None, max_length=500)


class Incoming(Input):
    iccid: str = Field(max_length=32)
    event_id: str = Field(min_length=1, max_length=128)
    sender: str = Field(max_length=100)
    body: str = Field(max_length=16000)
    modem_received_at: datetime | None = None


class Result(Input):
    iccid: str = Field(max_length=32)
    attempt_id: UUID
    lease_token: str = Field(min_length=20, max_length=128)
    status: Literal['sent', 'failed', 'unknown', 'not_sent']
    error_code: str | None = Field(default=None, max_length=100)
    error_message: str | None = Field(default=None, max_length=500)
    modem_reference: str | None = Field(default=None, max_length=100)
    segment_results: list[dict] = Field(default_factory=list, max_length=10)
