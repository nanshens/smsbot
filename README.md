# SMSBot

自托管短信工作台：LILYGO T-SIM7670G-S3 收发短信，Python 后端保存至 PostgreSQL，自动转发到邮件、Bark 和 PushDeer。React 管理端支持手机与桌面。

## 功能

- 用户名/密码 + 强制 TOTP，首次绑定、恢复码、修改密码、重置验证器、会话撤销与登录限流。
- 先添加手机号并签发永久 API Key，设备随时接入、Key 摘要存储、手动重置/删除、按 ICCID 管理电话卡与状态心跳。
- 每个手机号最多一个永久 API Key，设备和外部程序共用；页面手动签发、重置、删除，仅能操作对应卡片。
- 收信持久化、事件去重、分页/搜索/筛选、单条及批量删除、按卡绑定转发通道。
- SMTP（QQ 邮箱/Gmail/自定义）、Bark、PushDeer；加密凭据、测试通知与持久化重试队列。
- 发信排队、默认 1 秒轮询、原子领取、幂等回执、超时结果未知、人工重发、取消和删除。
- 固件 Wi-Fi + HTTPS、PDU 收发、UCS2 分段、接收分片重组、LittleFS 队列、NVS 身份与重启恢复。
- AQ-DBMigration SQL 迁移，互斥锁和 SQL/历史记录统一事务。

当前固件使用 **Wi-Fi 联网**，蜂窝数据联网尚未实现。QQ 指 QQ 邮箱，不包含 QQ 聊天机器人。

外部程序接入见 [API 使用方法](docs/API使用方法.md)。在「电话卡」→「API Key」签发后即可调用；新固件与外部程序使用同一个手机号 Key，无配对有效期。本次升级新增 `V4__preprovisioned_phones.sql`，本地和 Docker 都在 FastAPI 启动时自动执行迁移，无需手动执行。

## 目录

```text
backend/app/                     Python API、内置定时任务、迁移与管理员命令
backend/resource/db_migration/   V1__init.sql、V2__runtime_guards.sql
backend/tests/                   PostgreSQL 集成测试
frontend/                        React / TypeScript / Vite / pnpm
firmware/                        PlatformIO 固件、配置模板、烧录流程
deploy/                          Nginx 与 Supervisor 配置
Dockerfile                       前后端单容器镜像
.env.example                     环境变量示例
```

## 本地启动

需要 Python 3.11+（开发验证为 3.13）、Node.js 22.12+、pnpm 10.12.4、PostgreSQL。提前创建数据库，账户需要创建业务表和 `migration` schema 的权限。

在项目根目录创建并激活虚拟环境，安装后端：

```sh
python -m venv .venv
# Windows PowerShell
.venv/Scripts/Activate.ps1
# Linux / macOS 使用 source .venv/bin/activate
python -m pip install -r backend/requirements.lock
python -m pip install --no-deps -e backend
```

Linux 安装 psycopg2 时需要编译器、C 标准库头文件与 PostgreSQL 开发库（Debian 的 `build-essential libpq-dev`）。Dockerfile 已包含构建环境。

复制 `.env.example` 为 `.env`，填写数据库地址、账号、密码。本机数据库地址例如 `postgresql+psycopg://127.0.0.1:5432/smsbot`。生成两项独立密钥：

```sh
python -m app.cli generate-secrets
```

将输出填入 `.env` 的 `APP_SECRET` 和 `CREDENTIAL_ENCRYPTION_KEY`。开发默认 `APP_ORIGIN=http://localhost:5173`，浏览器也使用该地址。

开发时开启两个终端：一个后端、一个前端。后端内置 APScheduler，启动时自动运行转发和维护任务。

```sh
# 终端一：已激活虚拟环境
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# 终端二：前端
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

后端会先执行数据库迁移，成功后启动定时任务并接收请求；迁移失败会停止启动。首次启动成功后，在另一个已激活虚拟环境的终端创建管理员：

```sh
python -m app.cli create-admin --username admin
```

密码交互输入，至少 8 位。只需创建一次，没有默认账号密码或公开注册。以后更新 SQL 文件后直接重启后端，已执行的版本不会重复应用。

访问 [本地工作台](http://localhost:5173)。首次登录验证码留空，进入 TOTP 扫码绑定流程，保存只展示一次的恢复码。

## 连接设备

在「电话卡」添加手机号，保存永久 API Key，然后按照 [固件烧录流程](firmware/烧录流程.md) 配置 Wi-Fi、平台 HTTPS 地址、CA 和 PHONE_API_KEY。

Vite 开发服务是 HTTP，不能直接给此固件使用。设备需要可达且证书有效的 HTTPS 入口（例如反向代理到 8080）。不能使用设备自身的 `localhost` 指向电脑，也不能关闭证书校验。

## Docker 部署

已编写 Dockerfile，**未执行 Docker 构建或运行测试**。以下命令供部署时使用：

```sh
docker build -t smsbot:local .
docker run -d --name smsbot --env-file .env -p 3434:8080 -p 3444:8000 smsbot:local
docker exec -it smsbot python -m app.cli create-admin --username admin
```

PostgreSQL 使用已有服务或独立容器。数据库地址必须从应用容器可达；同网络数据库容器使用服务名，并给 `docker run` 增加相应 `--network`。也可通过 `-e DATABASE_URL=...` 覆盖文件中的值。

前端端口为 8080，API 为 8000。前端通过 Nginx 同源代理 `/api`。容器等待数据库后启动 Nginx 和 API；API 在开放服务前自动迁移，成功后启动内置定时任务，进程以非 root 用户运行。

### 内置定时任务

FastAPI lifespan 启动 APScheduler，退出时停止调度并等待正在执行的任务结束。每 1 秒领取一条到期转发任务，每 30 秒处理租约超时、过期会话和临时凭据。同步数据库和通知请求在线程池执行，不阻塞 API 事件循环；同一 job 在本进程内不会重入。

更新已有环境时先安装 `backend/requirements.lock` 中的新依赖，并停止旧版独立 worker。现在只需启动 Uvicorn。默认一个 API 进程；若使用多个进程或副本，每个进程都有调度器，转发领取通过 PostgreSQL 行锁和租约协调，维护任务使用数据库互斥锁。

调度周期保存在进程内，短信任务和重试状态保存在 PostgreSQL，重启不会丢失待转发短信。异常任务记录脱敏错误，下一个周期继续运行。通知服务接受发送后若连接中断，重试仍可能产生重复通知，不能保证外部服务恰好一次送达。

生产设置 `APP_ORIGIN=https://你的域名`、`COOKIE_SECURE=true`，外层配置 HTTPS。仅本地 HTTP 8080 测试时设置 `APP_ORIGIN=http://localhost:8080`、`COOKIE_SECURE=false`。真实 `.env` 不进入镜像。

迁移绝对路径固定为 `/app/backend/resource/db_migration`。**不要把已经由 Windows 本地路径迁移过的数据库直接交给容器重跑**；AQ 的历史记录含绝对路径，执行器会拒绝路径不一致。生产库从首次部署起就应由固定容器路径迁移，见 [迁移说明](docs/数据库迁移.md)。

## 使用与边界

1. 卡片以 ICCID 识别，手机号可手动填写；发信号码由 SIM 决定，不由管理标签决定。
2. 在「转发设置」创建通道，再到卡片「设置」绑定。失败转发可在收件详情重试。
3. 发送成功表示模组确认提交，不等于收件人收到。结果未知不会自动重发，人工重发可能重复计费。
4. 删除短信清空正文和号码、取消未执行转发，但保留最小幂等标识，避免设备重试恢复已删除内容。已送达通知不能撤回。
5. 发信使用 UCS2，最多 670 个 BMP 字符（最多 10 片），暂不支持 emoji。收信解析支持 GSM7/UCS2，见固件说明中的缓存与重组限制。

SMTP 要求 SSL/TLS 或 STARTTLS。QQ 邮箱使用授权码；Gmail 使用账号支持的应用密码；本版不包含 Gmail OAuth 授权流程。Bark 配置根地址和设备 Key，PushDeer 配置根地址和 PushKey。

默认禁止通知连接内网地址，自建内网服务需由部署者设置 `ALLOW_PRIVATE_NOTIFICATIONS=true`。只有管理员可以配置通道。

备份 PostgreSQL 和加密主密钥；更改 `APP_SECRET` 会影响会话、设备 Key、配对码等摘要，不能在普通升级时随意重新生成。

## 验证

```sh
python -m pip install -e "backend[test]"
# PowerShell：使用可删除的专用测试库，名称必须以 _test 结尾
$env:SMSBOT_TEST_DATABASE_URL='postgresql+psycopg://127.0.0.1:5432/smsbot_test'
$env:SMSBOT_TEST_DATABASE_USER='测试账户'
$env:SMSBOT_TEST_DATABASE_PASSWORD='测试密码'
python -m pytest backend/tests -q
cd frontend
pnpm build
cd ../firmware
pio run
```

测试会清空指定测试库的 `public` 和 `migration` schema，禁止指向业务库。未配置数据库时集成测试显示 skipped，不代表通过。

详见 [验证记录](docs/验证记录.md)。目前没有实机烧录/收发结果，也没有使用真实账号发送邮件或推送，需要接入硬件与账号后联调。示例固件配置可以编译，占位参数不能连接平台。
