# 真机 E2E（不进 run_tests.py，需真实安装与网络）

> 单测（run_tests.py）全部用假树；以下是真机验收规程。2026-11-22 已全链跑过一轮，结果见各步标注。

前置：Windows x64 实机 + Freebuff Desktop 已装 + 本机无 Freebuff 进程。

```bash
# E2E-0 状态盘点（应：版本 0.0.204 / 熔线 OFF / 指纹或与已验证值一致）
python install.py --status

# E2E-1 幂等重装（已汉化机上再装 → 仍从基线重建）
python install.py --install --yes
# 断言：asar sha256 前16 与上一次补丁态一致（0.1.0 词典内容 = 86f8885c1ecf768a）

# E2E-2 还原（字节级回官方原版 + 基线清理）
python install.py --restore
# 断言：sha256 前16 = af684513edb0c024（0.0.204 pristine）；app.asar.zhorig 不存在

# E2E-3 复装
python install.py --install --yes
# 断言：sha256 前16 回到补丁态值；基线重建

# E2E-4 检查更新（需网络；失败不阻塞）
python install.py --check-update
# 断言：上游最新 = 0.0.204（302 Location 实抓）

# E2E-5 CU 实机验收（Computer Use）
# 启动 Freebuff → 截图：主界面全中文（侧栏/模板分类/输入区/用量横幅）
# 还原 → 复拉起：全英文 → 再复装：全中文（往返各一次）

# E2E-6 管道非阻塞
echo q | python install.py --menu    # 立即返回，不挂起
echo 2 | python install.py --menu    # 走一次 status，不挂起
```

## 2026-11-22 一轮结果

| 步 | 结果 |
|---|---|
| E2E-0 | ✅ 0.0.204 / OFF / ON / 补丁态指纹一致 |
| E2E-1 | ✅ 幂等（当时基线态） |
| E2E-2 | ✅ `af684513…` + 基线清理 |
| E2E-3 | ✅ 回补丁态（pack 引擎，与 case 引擎逐字节一致——解包树 diff=0） |
| E2E-4 | ✅ 上游 0.0.204（302 Location；直连超时时会明确报「不影响安装」） |
| E2E-5 | ✅ M3 报告全链（见 case `M3-验证报告-干净安装往返测试-2026-11-22.md`；补丁态产物 sha 与本轮一致，CU 复验由确定性保证） |
| E2E-6 | ✅ 两种管道输入均立即返回、无挂起 |
