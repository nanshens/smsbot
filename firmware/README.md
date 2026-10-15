# SMSBot firmware

目标板：LILYGO T-SIM7670G-S3 普通版。Wi-Fi + HTTPS 联网，SIM7670G 通过 PDU 模式收发短信。

从 [烧录流程](烧录流程.md) 开始。复制 `include/config.example.h` 为 `include/config.local.h`，配置后运行 `pio run`。

`src/main.cpp` 管理模组、持久化队列和平台通信；`src/sms_codec.cpp` 负责 UCS2 分段、发送 PDU 和接收时间解析。

已通过编译，未实机验证。首次安装需初始化 LittleFS，正常升级不可覆盖队列文件系统。
