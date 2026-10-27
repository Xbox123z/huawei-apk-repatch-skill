<div align="center">

# 🔓 Huawei APK Repatch Skill

### 把「装不上」的 APK 硬塞进任何 Android 设备 —— 无 root、无电脑、无 Shizuku

**一行命令做不到的事，用二进制手术做到。**

<br/>

![status](https://img.shields.io/badge/verified%20on-device-orange?style=flat-square)
![platform](https://img.shields.io/badge/Android-EMUI%2012%20%2F%20API%2031-blue?style=flat-square)
![deps](https://img.shields.io/badge/deps-python3%20%C2%B7%20node%20%C2%B7%20openssl-green?style=flat-square)
![license](https://img.shields.io/badge/license-MIT-lightgrey?style=flat-square)

</div>

---

## ⚡ 这个 skill 解决什么

你手上有一个 APK/XAPK，它说：

> ❌ 「此应用与您的设备不兼容」
> ❌ 「该安装包未包含任何证书」
> ❌ 「已开启纯净模式，禁止安装」
> ❌ 装上了，**秒闪退**
> ❌ 装上了能跑，**用几分钟自己死**
> ❌ 登录第三方账号，提示成功，回去一看**啥也没有**

**这些全是同一件事**：Android 的版本门禁 + 签名校验 + 防盗版运行时 + App Links 验证。
本 skill 把它们**逐层拆开**，全部是已验证的实操，不是理论。

---

## 🏆 实战战绩

| | |
|---|---|
| **目标** | Grok 1.2.50（要求 Android 12L / minSdk 32 / 含 PairIP 防盗版 / 4-split 分发） |
| **设备** | Huawei CLS-AL00 · EMUI 12 · **Android 12 (API 31)** · 无 GMS · 无 root |
| **可用工具** | 一个设备上的 shell + 无障碍 UI 自动化（电脑 ADB 中途死掉，Shizuku 反复掉线） |
| **结果** | ✅ 完整安装 · ✅ 稳定运行 · ✅ OAuth 连接器正常 |
| **复跑验证** | 2026-10-27 · OpenBot 1.4.1（run.openbot.mobile，同款 PairIP）· **约 20 步 / 15 分钟搞定**（Grok 当年 100+ 步）|
| **代价** | 6 轮试错，约 1 亿 token，**全部踩坑已写进本文档** |

---

## 🧨 核心黑科技

### 1. 设备自己 ADB 自己
没有电脑？Shizuku 挂了？
USB 调试一开，`adbd` 就在 `127.0.0.1:5555` 监听 —— **在手机上跑 adb 客户端连回手机自己**。
瞬间拿到完整 `pm install` 会话能力，**华为文件管理器、纯净模式、"未包含任何证书"，全部绕开**。

```bash
adb -P 5037 connect 127.0.0.1:5555     # 是的，连 localhost
adb shell pm install -r -t /data/local/tmp/app.apk   # Success
```

### 2. 手写 APK 签名器（不需要 Java / apksigner）
纯 Python + Node 实现 **v1 (JAR)** 与 **v2 (APK Signature Scheme v2)** 双签名。
过程中发现某 npm 签名库**结构性写错字段**，导致华为报"无证书"——
拉下 **AOSP `V2Verifier12.java` 源码逐行对质**才定位：

> `digests` 记录里必须填**签名算法 ID**（`0x103`），不是摘要算法 ID（`0x101`）。
> 两者不相等 → `Signature algorithms don't match between digests and signatures records`

这条坑，网上搜不到。**本 skill 里有。**

### 3. 手搓 DEX 字节码，拆除防盗版运行时
Grok 内置 **PairIP / AppDetex**：启动弹授权页，查不到 Google Play 授权就**自杀**。
不是崩溃、不是被系统杀 —— 是它自己调 `scheduleAppShutdown`。

本 skill 用**自研最小 DEX 编辑器**直接改 Dalvik 字节码：

```smali
# LicenseActivity.onStart()  →  super.onStart(); finish(); return-void
# LicenseClient 的 18 个方法  →  全部 neuter 成空实现
```

附带**三个致命编码坑**的完整解释（35c 数量位在哪、3rc 的 count 怎么放、为什么绝不能清 `tries_size`）。

### 4. 修复重签名打断的 OAuth 回跳
重签名 = 签名指纹变了 = **App Links 域名验证失败** = 浏览器授权成功但回调送不回 App。

```bash
pm set-app-links --package <pkg> 2 all    # 一行修复
```

---

## 📦 内容

```
huawei-apk-repatch-skill/
├── README.md              ← 你在这里
├── SKILL.md               ★ 主文档：完整流程 + 决策树 + 排障速查表
├── CASE-STUDY.md          ★ 全程复盘：15 步时间线，含每一条弯路
└── scripts/               全部为实战跑通的原件，非演示代码
    ├── build_single_apk.py        AXML 二进制 minSdk 补丁 + zipalign 重建
    ├── add_v1.py                  v1 JAR 签名（CRLF · 72 字节折行 · detached PKCS#7）
    ├── sign_v2.js                 v2 签名（AOSP 对齐，digests algo 已修正）
    ├── dexpatch.py                最小 DEX 编辑器（类/方法定位 · 方法体替换 · header 重算）
    ├── verify_apk.py              独立 v1+v2 校验器（拒绝自证，实测 4/4 通过）
    └── adb-local/bootstrap_adb.sh 本机 adb 自连引导脚本
```

**投喂方式**：把 `SKILL.md` 直接丢给任何有 shell 的 AI agent，它就能复现整套操作。

---

## 🗺️ 流程总览

```
侦察          AXML 解析真实 minSdk（别信 manifest.json）· 检测授权 SDK · 判定 split 结构
  ↓
改包          二进制就地补丁 minSdk · 保留 META-INF/services · 4096/4 字节对齐
  ↓
签名          v1（华为只读它）+ v2（Android 只认它）· 独立校验器复核
  ↓
安装          本机 adb 自连 → pm install-create/write/commit 会话 → 绕开一切 UI 拦截
  ↓
拆锁          DEX 手术：授权页 Activity + 后台自杀定时器，一起拆
  ↓
善后          App Links 强制批准 · deviceidle 白名单 · appops 放宽
```

---

## 🩺 排障速查

| 症状 | 真因 | 处方 |
|---|---|---|
| 未包含任何证书（文件管理器） | 缺 v1 签名 | `add_v1.py` |
| 未包含任何证书（`pm install`） | v2 `digests`/`signatures` 算法 ID 不一致 | `0x103`，见 SKILL §4 |
| `INSTALL_FAILED_OLDER_SDK` | 某个 split 的 minSdk 漏改 | 全部 split 都要改 |
| `Resources$NotFoundException` | 单包合并破坏 split 资源表 | 改走 split 套装安装 |
| `Main dispatcher is missing` | 误删 `META-INF/services/` | 只删签名三件套 |
| `VerifyError: invalid arg count (0)` | 35c 数量位写错位置 | `word0=(count<<12)\|op` |
| `VerifyError: invalid reg index` | 3rc 漏了 count | `word2=(count<<8)\|vstart` |
| `ClassNotFoundException`（整包） | 清了 `tries_size` 没删 try_item | 别动元数据 |
| 用几分钟自己死 | 授权 SDK 的周期复检定时器 | 全量 neuter |
| OAuth 提示成功但没连上 | App Links 验证失败 | `pm set-app-links ... 2 all` |
| ADB 显示 offline / 零端点 | `adbd` 僵尸态 | 远程开关一次 USB 调试 |

---

## ⚠️ 边界与声明

- 本 skill 产出的是**自签名修改版**：无法接收官方 OTA 更新；每次重装需重跑 `set-app-links`
- 拆除授权校验仅适用于**你有权使用的应用**（已购 / 试用 / 你的设备不满足官方安装条件）
- 请勿用于商业分发或侵犯第三方权益，后果自负
- 部分应用有额外完整性校验（证书链 / Play Integrity / 服务端指纹），本流程不保证通用

---

<div align="center">

**觉得有用？点个 Star —— 这些坑值得少踩一次。**

<sub>Verified on Huawei CLS-AL00 · Android 12 · 2026</sub>

</div>
