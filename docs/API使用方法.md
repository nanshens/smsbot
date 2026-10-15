# SMSBot API 使用方法

## 1. 签发手机号 API Key

1. 在「电话卡」点击「添加手机号」，填写名称和号码。
2. 平台立即为这个手机号签发唯一的 API Key，复制保存；此时不需要连接 ESP32。
3. 外部程序立刻可以使用 Key 查询此卡、查看短信、创建待发送任务。设备未接入时，任务保留在队列中。
4. 任何时候把这个 Key 填入固件的 `PHONE_API_KEY`，设备即可激活并上报，不需要配对码。

**Key 永久有效，不设 30 分钟或其他自动到期时间，不会因首次使用而被消耗。** 每个手机号最多一个有效 Key，平台不保存可恢复的明文。页面可以签发、重置、删除，完整 Key 仅签发时显示；丢失请重置。

重置后旧 Key 失效，删除后该 Key 失效；外部程序与使用这个 Key 的 ESP32 都需要新 Key。删除后可重新签发，已有 Key 可直接重置。重置/删除成功返回前已开始的请求可能完成，排队任务仍保留。升级固件中的 Key 时只上传程序，不要格式化短信队列。

Key 绑定稳定的卡片 ID。手机号在平台内唯一；初次设备接入会补全并绑定 ICCID，后续不能用此 Key 接入另一张 ICCID 的卡。运营商不一定提供本机号码，因此平台无法证明手填手机号与实体 SIM 一致，请自行核对。

已有电话卡直接进入「API Key」管理，无需重复添加。此前生成的短期配对码不是此 Key，不要填到新固件中。

## 2. 认证与地址

示例基础地址：`https://sms.example.com`，替换成你的 HTTPS 域名。

```http
Authorization: Bearer sms_sim_你的完整Key
Content-Type: application/json
```

对外接口前缀为 `/api/v1/sim`。不需要登录 Cookie、TOTP 或 CSRF 请求头。Key 不支持放在 URL 查询参数中，不要把它写入前端公开代码、URL 或日志。一个 Key 可以读取、发送、取消和删除该卡的短信，请仅交给可信调用程序。

手机号 API Key 同时用于 `/api/v1/sim…` 和 `/api/device…`；后者需先激活设备。Key 不能登录管理页面、签发其他 Key、修改账号或访问其他手机号。管理接口仍使用登录会话 + TOTP，写请求需要 Origin 和 CSRF。

旧版设备凭据暂保留兼容，旧配对接口不用于新流程。旧卡使用新固件激活后，其旧设备凭据会失效，后续统一使用手机号 Key。

## 3. 对外接口一览

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/v1/sim` | 当前卡片信息和状态 |
| GET | `/api/v1/sim/messages/incoming` | 收件列表 |
| GET | `/api/v1/sim/messages/incoming/{id}` | 单条收件 |
| DELETE | `/api/v1/sim/messages/incoming/{id}` | 删除收件，取消未执行的转发 |
| GET | `/api/v1/sim/messages/outgoing` | 发件列表 |
| GET | `/api/v1/sim/messages/outgoing/{id}` | 查询发信状态 |
| POST | `/api/v1/sim/messages/outgoing` | 创建待发送短信 |
| POST | `/api/v1/sim/messages/outgoing/{id}/cancel` | 取消尚未领取的短信 |
| DELETE | `/api/v1/sim/messages/outgoing/{id}` | 删除已结束的发信记录 |

成功返回 HTTP 200 和 JSON。删除、取消返回 `{"ok":true}`。不存在、已删除或属于其他卡的短信返回 404。

### 查询电话卡

以下命令使用 Bash 变量；Windows 可用后面的 Python 示例。

```sh
export SMSBOT_URL='https://sms.example.com'
export SMSBOT_API_KEY='sms_sim_替换成真实Key'
curl "$SMSBOT_URL/api/v1/sim" -H "Authorization: Bearer $SMSBOT_API_KEY"
```

返回字段：`id`、`name`、`phone_number`、`iccid`、`operator_name`、`sim_status`、`network_status`、`signal_dbm`、`status_sampled_at`、`last_seen_at`、`online`。无法读取的字段可能为 null；信号单位 dBm。`online` 表示设备启用且近 90 秒收到心跳，不代表运营商保证可收发。

### 收件与发件列表

```sh
curl "$SMSBOT_URL/api/v1/sim/messages/incoming?page=1&size=20" \
  -H "Authorization: Bearer $SMSBOT_API_KEY"
```

通用查询参数：

| 参数 | 说明 |
| --- | --- |
| `page` | 从 1 开始，默认 1 |
| `size` | 每页 1–100，默认 20 |
| `q` | 搜索正文或收发号码，最多 200 字符 |
| `start` / `end` | 起止时间，ISO 8601；建议 UTC，例如 `2026-10-14T00:00:00Z` |
| `status` | 发件按发信状态筛选；收件按任一转发任务状态筛选 |

响应结构：`{"items":[...],"total":42,"page":1,"size":20}`，按最新时间在前排列，不包含已删除记录。收件字段含 `id`、`sender`、`body`、`modem_received_at`、`received_at`、`forwarding`；发件字段含 `id`、`recipient`、`body`、`status`、`created_at`、`completed_at`、`last_error`、`attempts`。列表还包含当前卡片 ID 和名称。详情返回短信本身记录，不包含列表附加的 `forwarding` / `attempts`。

### 创建发信任务

```sh
curl -X POST "$SMSBOT_URL/api/v1/sim/messages/outgoing" \
  -H "Authorization: Bearer $SMSBOT_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"recipient":"+8613800000000","body":"测试短信","idempotency_key":"a5397fda-dbb1-4bcc-9430-28e867702003"}'
```

| 请求字段 | 必填 | 说明 |
| --- | --- | --- |
| `recipient` | 是 | 3–20 位数字，可带开头的 `+` |
| `body` | 是 | 1–670 个 BMP 字符，不支持 emoji、代理字符或空字符 |
| `idempotency_key` | 是 | 本次业务请求的 UUID；重试同一请求必须保持不变 |
| `retry_of` | 否 | 同一卡片失败或结果未知记录的 ID，用于显式创建一次新的发送 |

不要传入 `sim_id`：卡片由 Key 确定。成功响应：`{"id":"短信UUID"}`。此时仅表示已保存任务，ESP32 默认每 1 秒领取一次，并不表示已经发出。设备未接入或离线时也允许排队，只有接入正确 SIM 的设备才能实际发送。

同一卡片、同一个幂等 UUID、同一内容重复提交只返回原 ID；修改内容则返回 409。重置、删除后重新签发 Key，甚至删除短信记录后，原幂等标识依然保留，避免重试重复发送。新短信必须使用新 UUID。短信以 UCS2 发送：单片 70 字符，长短信每片 67 字符，最多 10 片，可能产生多条计费。

### 查询、取消与删除

```sh
# 将 ID 换成创建接口返回的 UUID
curl "$SMSBOT_URL/api/v1/sim/messages/outgoing/ID" -H "Authorization: Bearer $SMSBOT_API_KEY"
curl -X POST "$SMSBOT_URL/api/v1/sim/messages/outgoing/ID/cancel" -H "Authorization: Bearer $SMSBOT_API_KEY"
curl -X DELETE "$SMSBOT_URL/api/v1/sim/messages/outgoing/ID" -H "Authorization: Bearer $SMSBOT_API_KEY"
```

发信状态：

| 状态 | 含义 |
| --- | --- |
| `pending` | 等待设备领取，可取消 |
| `leased` | 设备已领取，不可取消/删除 |
| `sent` | 模组确认提交，可删除；不是收件人送达证明 |
| `failed` | 失败，可删除，或由调用方明确创建新请求 |
| `unknown` | 结果无法确定，不自动重发、不可删除；人工重发可能重复计费 |
| `cancelled` | 已取消，可删除 |

收件删除会清空正文和号码，并取消未执行转发，但保留最小去重标识；已送达通知无法撤回。正在转发时可能返回 409，请稍后重试。发信仅 `sent` / `failed` / `cancelled` 可删除，`pending` 需先取消。

## 4. Python 调用示例

仅使用标准库。设置 `SMSBOT_URL` 和 `SMSBOT_API_KEY` 环境变量。

```python
import json
import os
import uuid
from urllib.request import Request, urlopen

BASE = os.environ['SMSBOT_URL'].rstrip('/')
KEY = os.environ['SMSBOT_API_KEY']

def call(path, method='GET', body=None):
    request = Request(BASE + '/api/v1/sim' + path, method=method,
                      data=None if body is None else json.dumps(body).encode(),
                      headers={'Authorization': 'Bearer ' + KEY,
                               'Content-Type': 'application/json'})
    with urlopen(request, timeout=20) as response:
        return json.load(response)

print(call(''))
print(call('/messages/incoming?size=10'))
# 将业务 UUID 和请求正文持久化，再发送；超时重试时复用这份 payload。
payload = {'recipient': '+8613800000000', 'body': '测试短信',
           'idempotency_key': str(uuid.uuid4())}
message = call('/messages/outgoing', 'POST', payload)
print(call('/messages/outgoing/' + message['id']))
```

示例会创建真实发信任务，请先替换接收号码。网络超时不能说明服务端未保存，重试时复用持久化的 UUID，不要每次重新生成。

## 5. 常见错误

错误通常是 `{"detail":"说明"}`；参数错误另含 `fields`。

| HTTP | 处理方式 |
| --- | --- |
| 400 | 检查 `retry_of` |
| 401 | 缺少/无效/已重置/已删除 Key；外部接口不接受旧版设备 Key |
| 403 | 管理页面写请求的 Origin/CSRF 校验失败 |
| 404 | 记录不存在、已删除或不属于该 Key 对应卡片 |
| 409 | 幂等内容冲突、状态不允许操作或转发正在执行 |
| 422 | 检查字段、UUID、号码、长度与字符范围 |
| 429 | 管理或设备认证限流；稍后重试 |
| 500 | 服务端异常；发信重试务必保留幂等 UUID |

## 6. 管理与设备接口补充

管理页面调用以下接口，需已完成 TOTP 的登录 Cookie；POST/DELETE 还需 `Origin` 与登录返回的 `X-CSRF-Token`：

| 方法 | 路径 | 返回 |
| --- | --- | --- |
| GET | `/api/sims/{sim_id}/api-key` | `active` 与脱敏 `key` 元数据 |
| POST | `/api/sims/{sim_id}/api-key` | 首次签发，返回 `sim_id`、`api_key`；已存在则 409 |
| POST | `/api/sims/{sim_id}/api-key/reset` | 替换现有 Key，返回新明文；未签发则 409 |
| DELETE | `/api/sims/{sim_id}/api-key` | 删除 Key，返回 `ok`；重复删除仍成功 |

### 设备激活（永久 Key）

`POST /api/device/activate` 使用同一个 `Authorization: Bearer <手机号API Key>`，请求：

```json
{"hardware_id":"ESP32-MAC-ADDRESS","iccid":"8986001234567890123","firmware_version":"0.2.0","modem_version":"SIM7670G"}
```

`hardware_id` 为 6–128 字符，`iccid` 为 10–32 位数字，两个版本字段可省略。成功返回 `device_id`、`sim_id`、`poll_interval_ms`、`heartbeat_interval_ms`，不会签发第二个 Key。同一设备和 ICCID 重复激活安全，不受时间限制。不同 ICCID、已被其他手机号使用的卡、未解绑的另一台设备返回 409。

激活后以同一 Key 调用 `POST /api/device/heartbeat`、`/incoming`、`/outgoing/claim?iccid=…`、`/outgoing/{id}/result`。无待发任务时 claim 返回 204；结果回执需领取时的 `attempt_id`、`lease_token`、`iccid` 和 `status`。这些动作由固件完成，见 [烧录流程](../firmware/烧录流程.md)。

添加手机号的管理接口为 `POST /api/sims`，请求 `{"name":"我的卡","phone_number":"+8613800000000"}`，返回 `sim_id`、`name`、`phone_number` 和仅本次可见的 `api_key`。重复号码返回 409；已有号码的 Key 管理接口见上表。

登录后可读取 `/api/openapi.json` 查看全部请求字段定义。本次数据库升级新增 `V4__preprovisioned_phones.sql`（此前 V3 已引入 Key 表），启动前执行 `python -m app.migrate`；容器启动流程自动执行迁移。旧版本 V1/V2/V3 不需要修改。若历史数据中存在重复手机号，需要先修正重复号码再迁移；号码唯一性比较忽略非数字字符，不会自动合并或删除历史短信。
