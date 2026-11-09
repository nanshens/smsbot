# 短信转发规则与 Quicker

在“转发设置”中添加或编辑通道，再到电话卡设置中绑定通道。关键词按逗号、中文逗号或换行分隔；任意一个关键词出现在短信正文中就创建转发任务，不区分英文字母大小写。留空表示所有短信。短信始终保存到收件箱，即使不满足关键词。

“完整短信正文”把原始短信正文作为通知内容；“正则截取”按从上到下的顺序尝试，每行一条，以第一条匹配成功的表达式为准。有捕获组时转发第一组，否则转发完整匹配；全部不匹配就取消本次转发。示例：`验证码[：:]\s*(\d{4,8})`。测试通知直接发送固定测试文字，不经过关键词和正则筛选。已经排队的任务会在发送时使用当前通道的正文设置；编辑通道不会补发此前被关键词过滤的短信。

Quicker 通道使用固定地址 `https://push.getquicker.cn/to/quicker`，发送 JSON。页面中填写 `toUser`、`toDevice`、`operation`、`action`、`wait`、`maxWaitMs`。`code` 作为加密凭据填写；编辑时留空会保持原值。`data` 不需要填写，由平台填入完整或截取后的短信正文。通道在电话卡设置中绑定后才接收该卡的新短信。

## 已部署 Docker 的更新

以下示例使用 README 中的容器名 `smsbot`、端口 `3434:8080` 和 `3444:8000`。先核对线上实际参数，特别是网络和挂载；如果不同，请在新 `docker run` 命令里照原样保留。保持 `.env`、PostgreSQL、域名证书和反向代理配置不变，尤其不要更换 `DATABASE_URL`、`DATABASE_USER`、`DATABASE_PASSWORD`、`CREDENTIAL_ENCRYPTION_KEY`，也不要重置手机号 API Key 或解绑设备。设备固件中的 `PLATFORM_URL` 和 `ROOT_CA` 无需改动。

```sh
docker inspect smsbot --format '{{.Config.Image}} {{.HostConfig.NetworkMode}} {{json .HostConfig.PortBindings}} {{json .HostConfig.Binds}}'
docker build -t smsbot:quicker .
docker stop -t 30 smsbot
docker rename smsbot smsbot-before-quicker
docker run -d --name smsbot --env-file .env --restart unless-stopped -p 3434:8080 -p 3444:8000 smsbot:quicker
docker logs --tail 100 smsbot
docker inspect -f '{{.State.Health.Status}}' smsbot
```

如果旧容器使用自定义 Docker 网络、额外 `-e` 或 `-v` 参数，新命令也必须带上相同参数。新容器启动时自动执行 V5 数据库迁移；无需手工运行迁移命令。只运行一个应用容器，避免两个转发调度器同时工作。健康状态为 `healthy` 后，访问原域名的 `/api/health`，应返回 `{"status":"ok"}`。接着在网页电话卡界面确认设备在线；固件每隔约 30 秒发送心跳，失败时持续重试，最长退避约 60 秒。尚未得到平台确认的短信保留在设备本地队列，连接恢复后继续上传。

如果健康状态正常但设备仍离线，检查原域名、HTTPS 证书和代理到 `3434` 的端口是否仍正确；查看设备串口输出的 `wifi`、`ntp`、`http`、`activated`。`http=401` 说明 API Key 被更换或删除，`http=409` 说明设备与 SIM 绑定不匹配；连接超时或 TLS 错误则优先检查域名、证书与代理。不要为了排查重置 API Key 或清除设备存储，否则会让原本可恢复的连接失效。

确认运行正常后，可以保留已停止的 `smsbot-before-quicker` 作为回退容器。需要回退时：

```sh
docker stop smsbot
docker rm smsbot
docker rename smsbot-before-quicker smsbot
docker start smsbot
```

V5 仅增加通道类型的允许值，不删除旧数据。更新前仍建议备份 PostgreSQL 数据库；不要删除数据库容器或数据卷。
