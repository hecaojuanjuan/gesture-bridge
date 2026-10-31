# 官方 H5 SDK 来源

`xjiang-sdk/` 原样提取自 2026-10-31 在灵机平台 PID 11785「标准面板 → 公版 AI 智能灯 → 下载源码」获得的 `aiBaseLight.zip`，路径 `private-cloud-h5/node_modules/xjiang-sdk/`。其 package.json 声明版本 1.0.0、MIT 许可。保留源代码和包元数据；未携带示例设备身份、token 或 .env。

平台模板引用的 xjiang-ui 1.1.0 在 npm 无可安装版本。SDK 中仅用到它的 loading 关闭句柄；Vite 将该引用映射到本面板的 `src/sdk-ui.js`，连接状态由页面自身显示。设备通信仍使用官方 SDK。生产包不启用 SDK 的 debug 模式。
