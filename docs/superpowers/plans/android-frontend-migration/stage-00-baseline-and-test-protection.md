# 阶段 0：基线与两个测试保护

> 此文件由 scripts/split_migration_plans.py 自动生成；修改原计划或脚本映射后重新生成。

执行前阅读 [总览与共享约束](README.md)。原文中的章节号及 P/T/IT 缩写以总览为准。
原始完整计划：[2026-10-10-android-frontend-migration.md](<../2026-10-10-android-frontend-migration.md>)。

[下一阶段](stage-01-backend-connection.md)

**文件：** 现有 MainActivity、ModelManager、OcrManager、OcrScreen；新增 Android docs/migration/baseline.md、native-assets.sha256；T/NativeAssetManifestTest.kt。
**接口：** 保留 ModelManager.initialize/chat/stopGeneration/resetConversation、OcrManager.recognizeUri 和 JNI 包名。

- [ ] 记录配置、AAR/JNI/模型 SHA-256；构建现有 APK，在 arm64 设备离线运行两个测试，记录设备和实际结果。
- [ ] 基线列出流式对话、停止、清空、性能指标、拍照、相册、重新识别、复制、置信度、耗时及错误提示。
- [ ] 若 Android 根目录仍无 Git，初始化当前目录源码版本控制，显式提交源码、配置、wrapper；第三方源码和大模型资产保留原位置并用清单记录，不递归暂存整个工程。
- [ ] 添加资产清单检查；保留 Vulkan 到 CPU 的回退。按需初始化及资源关闭由阶段 2 完成。
- [ ] 验收后提交 `chore: record Android migration baseline and native assets`。

**通过条件：** 两个原入口离线工作，已保存真实设备基线；addition_isCorrect/useAppContext 不能代替该验收。

---

## 阶段参考

### 应参考的前端文件

| 文件 | 用途 |
|---|---|
| [APK: app/src/main/java/com/liaic/radiolabrepository/MainActivity.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/MainActivity.kt>) | 现有 APK 基础与测试入口 |
| [APK: app/src/main/java/com/liaic/radiolabrepository/ModelManager.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/ModelManager.kt>) | 现有 APK 基础与测试入口 |
| [APK: app/src/main/java/com/liaic/radiolabrepository/OcrManager.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/OcrManager.kt>) | 现有 APK 基础与测试入口 |
| [APK: app/src/main/java/com/liaic/radiolabrepository/ui/OcrScreen.kt](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/src/main/java/com/liaic/radiolabrepository/ui/OcrScreen.kt>) | 现有 APK 基础与测试入口 |
| [APK: app/build.gradle.kts](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/app/build.gradle.kts>) | 现有 SDK、ABI 与原生库打包 |
| [APK: gradle/libs.versions.toml](<C:/Users/liaic/AndroidStudioProjects/RadioLabRepository/gradle/libs.versions.toml>) | 既有构建依赖 |

### 应参考的后端接口

| 方法与路径 | 状态与用途 | 实现参考 |
|---|---|---|
| `GET /api/libraries/status` | 现有接口；旧服务器连接探针、元件库可用状态 | [app/api/library_api_routes.py](<../../../../app/api/library_api_routes.py>) |

新增 client OCR 字段、部署模式和项目 token 以 [共享后端契约](../client-ocr-backend/README.md) 为准；现有路径不代表新字段已经支持。

两个现有端侧测试入口本身不依赖业务后端；只读接口仅用于连接和基线对照。
