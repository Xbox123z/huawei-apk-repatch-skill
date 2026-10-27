# 案例复盘：Grok 1.2.50 装上 Android 12 华为（2026-10-26）

设备：Huawei CLS-AL00，EMUI 12（HarmonyOS 4.3 外壳），Android 12/API 31，arm64-v8a，无 GMS，无 root。
目标：安装 Grok_1.2.50-release.00.xapk（minSdk 32，含 PairIP 授权，4 个 split）。
可用通道：设备 shell（Termux 系）+ 无障碍 UI 自动化；电脑 ADB 一度可用后 adbd 僵尸化；Shizuku 反复掉线。

## 时间线（含所有弯路，弯路也是经验）
1. **侦察**：解 xapk → manifest.json 声称 minSdk 32；解析 AXML 确认 base/3 个 split 全部 minSdk=32。设备 SDK 31 → 直接装必死。
2. **通道探测**：`pm install-create` 报 INTERACT_ACROSS_USERS（uid 非 shell）→ 当时无特权通道。
3. **决策**：与用户确认「修补强装」路线（改 minSdk + 重签 + 绕授权）。
4. **弯路 A：签名库投毒**：npm `apk_sign_ts` 的 v2 实现把摘要算法 ID(0x101) 写进 digests 记录（应为签名 ID 0x103），v3 的 min/maxSdk 位置也不合规。当时未细查 → 埋雷。
5. **弯路 B：单包合并**：把 config.mdpi/arm64 并进 base → 装上后 `Resources$NotFoundException #0x7f0801b8`（split 资源表 ID 不互通）。
6. **弯路 C：误删 META-INF/services**：重建时清 META-INF 连带删了 kotlinx-coroutines 的 ServiceLoader 描述符 → `Module with the Main dispatcher is missing`。修复：只删签名三件套。
7. **v1 补签**：华为文件管理器只读 v1 → 「未包含任何证书」。补 JAR 签名（CRLF/72 字节折行/detached PKCS#7）。
8. **用户两次点到无签名诱饵文件**（我从 xapk 解出的原始 base 躺在 Download 字母序第一位）→ 教训：**中间产物必须隔离改名**。
9. **真凶现身**：`pm install`（此时已借无障碍重启 adbd + 本机 adb 自连打通）报
   `INSTALL_PARSE_FAILED_NO_CERTIFICATES: ... Signature algorithms don't match between digests and signatures records`
   → 拉 AOSP android-12 V2Verifier12.java 对质（line 313）→ 修正 digests algo=0x103 → **Success**。
10. **装上即闪退**：logcat 显示 `LicenseActivity` 出现 → 进程死。确认 PairIP（AppDetex）授权 SDK。
11. **版本考古**：apkeep 列历史版本；1.0.99 minSdk 28 但后端 mouseion.dev 已挂 Cloudflare Access（302）→ 死路；1.2.50 用 accounts.x.ai（活）→ 决定拆锁 1.2.50。
12. **dex 手术 v1**：onStart 改 super+finish+return。编码错三次：
    - 把 35c 数量位写进 word2 → `invalid arg count (0)`
    - 3rc 忘 `(count<<8)|vstart` → `invalid reg index 16+258 (>3)`
    - 清 tries_size 但没删 try_item 字节 → 整 dex 结构错位 → `ClassNotFoundException: GrokApplication`
    最终版：只改指令区（保留 super 三单元、入口 finish、其余原样成死代码），元数据全保留 → 通过。
13. **connect 第三方账号「成功但回来没连上」**：`pm get-app-links` 显示 `grok.com: none`（重签名破坏 assetlinks 验证）→ `pm set-app-links --package ai.x.grok 2 all` → 修复。
14. **仍偶发闪退**：dropbox 挖出 LicenseClient 的 `scheduleRepeatedLicenseCheck`/`scheduleAppShutdown` 周期自杀定时器 → 18 个方法全量 neuter → 稳定。
15. 善后：deviceidle 白名单、appops 放宽、成品归档。

## 关键证据样本
- AOSP 校验器：`digestsSigAlgorithms` 与 `signaturesSigAlgorithms` 必须 `equals`
- 原始 onStart 首指令 `0x106f 0x3504 0x0002` = invoke-super/range? 否——是 35c：`(count<<12)|op`
- LicenseClient 方法表（dex 解析输出）：checkLicense/scheduleAppShutdown/startErrorDialogActivity/…
- 最终形态：4-split 套装，v1+v2 自签，minSdk 31，授权链全拆，App Links 强制 approved

## 成本结构（为何 1 亿 token）
- 反复的设备端日志抓取与解析（logcat/dropbox 输出巨大）
- dex 编码三轮试错（每轮全量重签+重装+验证）
- 通道探测与恢复（无障碍/Shizuku/adb 各自掉线的处理）
- 建议：复用本 skill 时，先做 §1 侦察 + §5 的授权 SDK 检查，可跳过 60% 弯路

---

# 第二案例：OpenBot 1.4.1（skill 复跑验证，2026-10-27）

**skill 写完后第一次被真正复用——验证了方法论可迁移，同时暴露两个新坑（均已回写 SKILL.md）。**

目标：`run.openbot.mobile`（CMU 开源自动驾驶 App，APKPure 下载，4-split，minSdk **24**，targetSdk 36）。
症状：用户报「闪退」。

## 与 Grok 的关键差异（侦察的价值）
| | Grok 1.2.50 | OpenBot 1.4.1 |
|---|---|---|
| minSdk | 32 > 设备 31 → **必须改包** | 24 < 31 → **不用改，安装本来就成功** |
| 授权 SDK | PairIP | PairIP（同一款） |
| 锁在哪 | classes.dex | **classes2.dex**（多 dex 必须全扫） |
| 退出方式 | Activity.finish | `finishAndRemoveTask` + `System.exit` |
| `Activity.finish` method_id | 存在 | **不存在**（R8 内联掉了） |

## 流程（比 Grok 快一个数量级，约 20 步 vs 100+ 步）
1. 本机 adb 自连恢复（server 起不来 = 后台进程漏传 `LD_LIBRARY_PATH`，`nohup env LD_LIBRARY_PATH=... adb server nodaemon` 修复）
2. 定位包：Download 里 xapk 文件名被浏览器截断（`_2839ae1b.xapk`），**用 AXML 解析 package 名识别**，不靠文件名
3. `pm list packages` 发现已装 → 直接启动抓 logcat → 立刻看到 `LicenseClient: Could not bind with the licensing service` → 确诊 PairIP，跳过改包
4. 扫 5 个 dex 定位 PairIP 在 classes2.dex；dump 方法表确认与 Grok 同构
5. onStart 补丁：`Activity.finish` 找不到 → 反汇编 `exitApp` 发现它调自己的 `finishAndRemoveTask`（本类 method id）→ 用它替代
6. 拆 LicenseClient 20 方法 + LicenseActivity 10 方法 → 重签 4 split → 装

## 新坑 A：META-INF 一刀切（我即兴手搓重建循环又踩了 skill 记录过的坑）
`if name.startswith('META-INF/'): continue` 删光 services → `ExceptionInInitializerError: Module with the Main dispatcher is missing`。
skill 自带的 add_v1.py 谓词本来是对的——**教训：复用 skill 脚本，别即兴重写**。

## 新坑 B：R8 会内联掉 finish
不能假设 `Landroid/app/Activity;->finish` 的 method_id 存在于目标 dex。
反汇编同类退出路径（exitApp/closeApp）看它实际调什么再定 method_id。

## 结果
`LicenseActivity` 出现 **0 次**、`LicenseClient` 日志 **0 行**、进程 30s+ 稳定、无 crash/ANR/SoLoader 失败。

## 推论
PairIP/AppDetex 是通用商业防盗版方案（Grok、OpenBot 都带）。
「装上就闪退 + logcat 有 licensing service 绑定失败」→ 直接套 SKILL §5，命中率高。
