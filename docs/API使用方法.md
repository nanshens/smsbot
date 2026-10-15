# SMSBot API 使用方法

## 1. 签发手机号 API Key

1. 先让 ESP32 完成配对注册，平台「电话卡」页面出现对应卡片。
2. 在卡片「设置」填写手机号（号码标签不会改变 SIM 实际发信号码）。
3. 点击卡片的「API Key」→「签发 API Key」，立即复制保存。
4. 调用程序通过环境变量保存 Key，每次请求在请求头中携带它。

每张卡片最多有一个有效的对外 Key，注册时不会自动签发。页面可查看脱敏标识、签发时间和最近成功调用时间，支持重置和删除。完整 Key 只在签发/重置的响应中返回一次，数据库只保存摘要，关闭窗口后不能找回；响应丢失时请重置。

重置或删除成功返回后，旧 Key 的新请求会返回 401；已经开始的请求会先完成。已排队的短信继续执行，若需停止请另行取消。删除 Key 不删除电话卡和短信。重置后重试同一个发信请求仍需沿用原来的幂等 UUID。

Key 绑定稳定的卡片 ID / ICCID，手机号是可编辑标签；更换标签不会把权限转移到另一张卡。API 根据 Key 选卡，不允许通过传入别人的卡片 ID 操作其他卡。

## 2. 认证与地址

示例基础地址：`https://sms.example.com`，替换成你的 HTTPS 域名。

```http
Authorization: Bearer sms_sim_你的完整Key
Content-Type: application/json
```

对外接口前缀为 `/api/v1/sim`。不需要登录 Cookie、TOTP 或 CSRF 请求头。Key 不支持放在 URL 查询参数中，不要把它写入前端公开代码、URL 或日志。一个 Key 可以读取、发送、取消和删除该卡的短信，请仅交给可信调用程序。

三类凭据分别使用：

| 用途 | 接口 | 认证 |
| --- | --- | --- |
| 外部程序操作某张卡 | `/api/v1/sim…` | 页面手动签发的手机号 API Key |
| ESP32 上报、领取和回执 | `/api/device…` | 配对注册返回的设备 Key |
| 管理页面、签发/重置/删除 Key | `/api/sims…` 等 | 登录会话 + TOTP；写请求需要 Origin 和 CSRF |

这些凭据不能互相替代。对外 Key 无权签发 Key、访问其他卡片、修改账号或通知通道。设备 Key 保持原有固件协议，因此无需为本次更新重新烧录。

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

不要传入 `sim_id`：卡片由 Key 确定。成功响应：`{"id":"短信UUID"}`。此时仅表示已保存任务，ESP32 默认每 1 秒领取一次，并不表示已经发出。未绑定有效设备返回 400；设备暂时离线但仍绑定时允许排队。

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
| 400 | 检查设备绑定或 `retry_of` |
| 401 | 缺少/无效/已重置/已删除 Key，或误用了设备 Key |
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

设备协议保持原样：`POST /api/device/register` 使用配对码、稳定 `request_id`、`hardware_id` 和 `iccid` 注册，返回设备 Key。之后设备以该 Key 调用 `/heartbeat`、`/incoming`、`/outgoing/claim?iccid=…`、`/outgoing/{id}/result`。无待发送任务时 claim 返回 204；结果回执需包含领取时的 `attempt_id`、`lease_token`、`iccid` 和 `status`。设备会自行重试和持久化，完整配置见 [烧录流程](../firmware/烧录流程.md)。

登录后可读取 `/api/openapi.json` 查看全部请求字段定义。数据库升级新增 `V3__sim_api_keys.sql`，启动前执行 `python -m app.migrate`；容器启动流程自动执行迁移。旧版本 V1/V2 不需要修改。
