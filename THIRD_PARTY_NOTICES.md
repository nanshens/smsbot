# 第三方组件

本项目通过依赖声明引入第三方软件，分发时应保留各组件随附的许可证和声明。

- [AQ-DBMigration](https://github.com/nanshens/AQ-DBMigration)，固定 1.0.2，GPL-3.0；迁移包装器基于其公开 API 与该版本的钩子行为实现。
- [PDUlib](https://github.com/mgaman/PDUlib)，固定提交 `dbf324a13f79cfcba8d408afee9e1246adb9d762`，上游 `LICENSE.txt` 为 LGPL-2.1；通过 PlatformIO 拉取，保留上游源码与许可证。
- [shadcn/ui](https://github.com/shadcn-ui/ui)，MIT；本地 Button/Dialog 采用其组件组合方式并做样式适配，基于 Radix primitives。
- React、Radix UI、Tailwind CSS、Lucide、Vite、SQLAlchemy、FastAPI 等依赖的版本见 pnpm 锁文件与后端依赖锁文件，许可证以各自分发包为准。

硬件引脚和上电流程参考 [LILYGO 官方工程](https://github.com/Xinyuan-LilyGO/LilyGo-Modem-Series)。
