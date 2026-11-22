# NOTICE

## 免责声明

本项目为非官方中文补丁，仅修改本机 Freebuff Desktop 的 `resources/app.asar`（运行时注入），**不访问网络、不上传任何用户数据、不修改服务端账号数据**（「检查更新」动词会向官方更新端点发起一次只读请求，不携带任何本机信息，可用 `--no-net` 跳过）。Freebuff 及相关商标归其权利人所有，本项目与上游无任何关联。

上游更新会覆盖本补丁，重新运行安装器即可恢复；若上游启用 asar 完整性校验，安装器会检测并**拒绝安装**（强行覆盖会导致应用无法启动）。本软件按「现状」提供，不附带任何担保；可随时通过安装器的还原功能恢复官方原版。本包的安装与还原只改动 `resources/app.asar` 及其 `.zhorig` 基线，不存储任何账号信息、不触碰用户数据；卸载 Freebuff Desktop 本体会连同本包产物一并清除。禁止将本项目整体或部分用于转售。

## 致谢与第三方组件

- **[Kfowever/freebuff-zh-patch](https://github.com/Kfowever/freebuff-zh-patch)**（MIT）——本包第二层词库与正则规则来源：
  - `lib/zh-community-lib.js`：其 `library/freebuff-zh-cn.js` 快照（2026-11-20 抓取其仓库 main，对应上游 0.0.204；库文件自声明 PATCH_VERSION 0.10.8，上游安装器发布版本 v0.11.10——两者为其内部版本轨差异），按 MIT 原样分发，许可证原文随附 `licenses/Kfowever-freebuff-zh-patch-LICENSE.txt`
  - `dicts/zh-community.json`：自上述库词条抽取（3,164 条）
  - 本包词典与其存在措辞分歧，以本包自建译文为准（661 条分歧对照留档于维护仓，未随包分发）
- **模式参考（非代码引用）**：[javaht/claude-desktop-zh-cn](https://github.com/javaht/claude-desktop-zh-cn)、[antigravity-cn-community/Antigravity-Chinese-Localization](https://github.com/antigravity-cn-community/Antigravity-Chinese-Localization)
- 本项目自身代码与词典以 MIT 发布（见 `LICENSE`）
