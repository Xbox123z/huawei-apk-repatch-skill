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

---

# 第三案例：OpenBot 返工（Hermes 对齐雷，2026-10-27 下午）

**用户反馈：「点击图标直接卡着不动」——我上一轮判定"成功"是错的。**

## 我的验证失误（最重要的一课）
上一轮我只验了三件事：`pidof` 有值、无 crash、`LicenseActivity` 出现 0 次 → 就宣布成功。
实际 OpenBot 的窗口一直是 `mHasSurface=false / isVisible=false`：**进程活着，画面从没画出来过**。
而且中途我还用错过 grep（`'Window.*openbot'` 匹配不到 `Window{...run.openbot.mobile/...MainActivity}` 跨行结构），
把真阳性误读成"无窗口"，来回绕了几次。
→ SKILL §6 新增「验收标准」小节：必须查 mHasSurface/isVisible + 截图肉眼确认。

## 真实根因：Hermes mmap 对齐
```
HermesVM: Compiling JS failed: Buffer misaligned., sourceURL: index.android.bundle
→ com.facebook.react.common.JavascriptException: [runtime not ready]
```
RN 的 JS bundle 由 Hermes **mmap 直接读取**，要求 zip 内数据偏移 **8 字节对齐**。
排查过程（三次才定位）：
1. 先怀疑我改坏了 bundle → 比对 sha1：原版与我的包**字节完全一致**，排除
2. 改 rebuild 让 STORE 条目 8 对齐 → 仍报错 → 发现 **`add_v1.py` 会重写整个 zip**，它的对齐规则只管 .so/arsc，把 bundle 又挤歪了（偏移 mod8=1）
3. 修 add_v1.py（method==0 一律 ≥8 对齐）→ 通过

**更妙的是**：APKPure 原版包的 bundle 偏移 mod8=**4**，本身就是歪的。
原版为什么能用？因为它被 PairIP 授权锁先杀掉了，**根本走不到 JS 加载那一步**。
我把锁拆了，反而第一次触发了这个潜伏的对齐 bug——**两层防护互相掩盖，拆一层才炸另一层**。

## 修复链（正确顺序，对齐必须在最后一步之后仍然成立）
```
rebuild(STORE≥8) → add_v1(STORE≥8，重写 zip 会毁对齐！) → sign_v2(只追加块，不动数据)
```
验证：`bundle 偏移 mod8=0` → 无 misalign → `mHasSurface=true` → 截图见登录页 → 交付。

## 附带发现
- OpenBot 含穿山甲/Pangle 广告 SDK（classes3/4.dex），与授权锁是独立的两条干扰线
- 广告 SDK 的 `500013` 类错误在 UI 层，不影响启动，本案例未处理

## 三次案例的成本曲线
| 案例 | 步数 | 主要耗时 |
|---|---|---|
| Grok 1.2.50 | 100+ | 签名库 bug 排查 + dex 编码三轮试错 |
| OpenBot 首攻 | ~20 | 顺利（skill 生效） |
| OpenBot 返工 | ~25 | 验证方法错误导致绕路（已固化为 §6 验收标准） |

---

# 第四案例：ChatGPT 1.2026.286（"侦察先行"省掉一半工序，2026-10-27）

目标：`com.openai.chatgpt`（APKPure XAPK 109.6MB，4-split）。设备同上。
**结果：从下载到出登录页 15 分钟，零试错**——侦察做够就能砍掉不该做的工序。

## 侦察结论直接决定工作量（关键价值）
| 检查项 | ChatGPT 结果 | 因此省掉 |
|---|---|---|
| minSdk | **32** > 设备 31 | 改包这条跑不掉 |
| PairIP / AppDetex / ILicensingService | **完全没有** | ❌ 不用 dex 手术（省掉最硬核、最易错的一步） |
| Play Integrity | 有引用但不阻塞启动 | 不用拆（GMS 26.41 + GSF 7.0 已装，运行期能过） |
| 是否 RN/Hermes | **原生 Kotlin**（无 index.android.bundle） | 无 Hermes 对齐雷（STORE≥8 照跑，无害） |
| targetSdk | **37**（远超设备 31） | 实测可装：**targetSdk 高于设备 SDK 不拦，只有 minSdk 拦** |

## 新脚本 rebuild_splits.py（补上 skill 的真实缺口）
之前排障表写着「改走 split 套装安装」却**没给脚本**，导致每次现写重建循环——
OpenBot 那次就是现写时删掉了 META-INF/services。现已固化：
```bash
python3 scripts/rebuild_splits.py app.xapk out/ --from 32 --to 31
```
实现要点（注释里都有）：按 local header 原始字节读条目（保留原 compress_type，不解压再压）；
AXML 用「元素名 + 属性名」双条件匹配（同值 32 也会出现在 maxSdkVersion 上）；
输出 `services kept=N` 让保留情况可见；自动报告改动数为 0 时提示核对真实 minSdk。

## 脚本泛化（换任务可直接跑）
add_v1.py / sign_v2.js 改为环境变量喂路径：`SIGN_KEY` / `SIGN_CERT` / `FORGE_PATH`，
不再硬编码 grok_build 绝对路径。

## 本轮运维坑（4 个，均已入 §0/§7）
1. **apkeep 下载截断**：首下 2MB（实际 109MB）且不是 zip。必须「下载 → testzip → 体积阈值」循环重试
2. **adb server 中途崩**：客户端被 SELinux 拒 `execl` 无法自动 fork server。
   恢复：`nohup env LD_LIBRARY_PATH=... adb -P 5037 server nodaemon &` 然后 `connect 127.0.0.1:5555`
3. **`pkill -f "adb.*5037"` 把自己杀了**：该 shell 自己的命令行含此串 → 整条命令 SIGTERM。
   改用 `pkill -x adb`（精确进程名），**永远别用 -f 杀自己链路上的进程**
4. **VPN 分应用排除名单又坑新 App**（与 Grok 同根因）：v2rayNG 排除段 `10445-99999` 覆盖所有普通 App uid
   → 新装 App 默认**不走代理** → 境外域名直连失败。
   → **每次装新 App 后必做**：去 v2rayNG 勾选该 App 或改全局代理（已列为标准善后步骤）

## 验收（§6 标准一次通过）
`mHasSurface=true` + `isVisible=true` + crash 计数 0 + 截图见 "Welcome to ChatGPT" 登录页。
⚠️ **但这只是"能启动能渲染"，不等于"能用"——登录卡在服务端设备认证，见第五案例。改包成功 ≠ 任务成功。**

## 四案例成本曲线
| 案例 | 步数 | 说明 |
|---|---|---|
| Grok 1.2.50 | 100+ | 从零探路，签名库 bug + dex 编码三轮试错 |
| OpenBot 首攻 | ~20 | skill 生效 |
| OpenBot 返工 | ~25 | 新坑（Hermes 对齐）+ 验证方法错误 |
| ChatGPT 改包 | ~15 | 侦察砍掉一半工序，能装能渲染——但登录失败（下案例） |

---

# 第五案例：ChatGPT 登录死锁（服务端完整性 = 本 skill 的能力边界，2026-10-27）

**这是全系列最重要的一条：有些锁根本不该拆、也拆不了。识别它比拆它更值钱。**

## 症状
改包版（1.2026.286）能装能渲染登录页，但点登录 → 跳 `auth.openai.com` →
服务器返回中文页「身份验证错误」，诊断码 `preauth_cookie_device_check_failed`。

## 根因：Google Play Integrity 设备令牌（服务端验 + 硬件签）
登录前 App 必须向 OpenAI 服务器出示一张由 **Google Play 服务**签发的设备完整性令牌，
证明"认证过的真机 + 官方签名"。三前提本设备缺两个半：
1. **机型不在 Google 认证库**（华为 CLS-AL00 受制裁，`ro.product.cert` 空）→ 发不出令牌，密钥烧在 TrustZone，无法伪造
2. **应用非官方签名**（我们重签了）→ "应用完整性"维度必挂
3. **检查在服务端** → 客户端怎么 patch 都没用

## 走过的退路（全部堵死，但都是必要排查）
- **降级官方旧版 1.2024.262**（minSdk 23 免改包、官方签名 v3 完整、无 DeviceCheck 代码）→
  能装能跑，但**服务端已废弃旧版**：「此 ChatGPT 版本已过时」
- 再查旧版 dex：`preauth`/`PlayIntegrity` **同样存在** → 设备认证一直都在，不是新版才加，降级无用
- "已过时"文案在本地 config.zh.apk 的 arsc 里（客户端渲染），但触发它的是服务端版本判定，改文案无用

## 关键判据（写进 SKILL §1 第 0 关）
| 锁类型 | 标志 | 能否拆 |
|---|---|---|
| PairIP / AppDetex / LVL | 客户端 LicenseActivity，logcat 有 `Could not bind licensing service` | ✅ 第 5 步 dex 手术 |
| **Play Integrity / DeviceCheck / attestation** | 登录页由**服务器**返回，要求设备令牌 | ❌ 硬件+服务端双锁，本 skill 全套无效 |

Grok 能成功正是因为它只有前者、没有后者；ChatGPT 两者都有。**动手前先扫 dex 有没有
`PlayIntegrity`/`preauth`/`attestation`——有就先假设可能是服务端锁，别急着改包。**

## 交付给用户的正确结论
- 原生 ChatGPT 在这台华为上**无法登录**（不是没努力，是物理/架构上做不到）
- 可用替代：① GBox 里的 GPT（已绕过）② 网页版 chatgpt.com（官方确认不做设备认证）③ 换 Google 认证机型
- **诚实说"做不到"比假装能修更有价值**——省掉用户和下一个 AI 的一整场空战

## 五案例总成本曲线
| 案例 | 结果 | 步数 | 核心教训 |
|---|---|---|---|
| Grok 1.2.50 | ✅ 成功 | 100+ | 客户端 PairIP 可拆 |
| OpenBot 首攻 | ✅ 成功 | ~20 | 侦察先行 |
| OpenBot 返工 | ✅ 成功 | ~25 | 渲染才是验收标准 |
| ChatGPT 改包 | ⚠️ 能装不能登录 | ~15 | 改包成功≠任务成功 |
| ChatGPT 登录 | ❌ 能力边界 | — | **服务端完整性锁拆不了，要会识别会放弃** |

---

# 第六案例：从零造 App（本机 APK 构建工具链 + WebView 壳，2026-10-27）

**背景**：ChatGPT 撞服务端锁后，用户提出——"用浏览器网页做一个能几乎 100% 复现功能的仿制 App"，
目标是把 **Apple 地图（maps.apple.com）** 装进这台华为。这是本 skill 能力的升维：从"改别人的包"到"自己造包"。

## 可行性侦察（先证明网页是真应用）
```
curl maps.apple.com（Mac Safari UA）→ 200，加载 /static/maps-app-web-client/mapkit.core.js
curl maps.apple.com（Android 移动 UA）→ 200，14 处 mapkit，不跳 App Store
```
→ maps.apple.com 是**真正的 Apple 地图 Web 应用**（MapKit JS 引擎），WebView 壳方案成立。
（对照：Grok/ChatGPT 网页版也是同理，网页壳能拿到 ≈ 原生体验。）

## 本机搭工具链（无电脑、无 root、无 apt install 权限）
Termux 源里其实**全套都有**（apktool/aapt2/d8/openjdk-17），但 dpkg 无 root 装不进 →
`apt-get download *.deb` + **python 解 ar 归档 + data.tar(.zst|.xz)** 合并到自建 `tchain/` 目录。
踩坑链（每一环都卡过，全部固化进 setup_toolchain.sh）：
1. java 缺 `libandroid-shmem.so` → 下；又缺 `libandroid-spawn.so` → 下；又缺 `libz.so.1` → 下 zlib… **迭代 8 轮**补齐
2. aapt2 缺 `libfmt`/`libpng16`/`libexpat.so.1` → 前两个 apt 有，**libexpat 没有对应包名** → `cp /system/lib64/libexpat.so $TLIB/libexpat.so.1` 借系统的
3. java 默认临时目录 `/tmp` 不可写 → `-Djava.io.tmpdir=$HOME/tmp`
4. apktool 缺 Android framework 资源表 → adb pull `/system/framework/framework-res.apk` → `apktool if` 注册
5. **`LD_LIBRARY_PATH` 污染管道命令**（本 skill §0 老坑重现）：给 aapt2 设的 env 会让 `head`/`grep` 找不到 libandroid-support → 所有验证用命令替换 `out=$(...)` 隔离

## 造壳的两个致命 bug（手写 smali）
1. **`apktool.yml` 缺 `usesFramework.ids:[1]`** → aapt2 link 报 "attribute android:name not found"（android: 命名空间没加载）。真实解码产物有这个字段，手写工程必须照抄
2. **`.registers` 计数错** → 编译期无警告，**运行期 VerifyError**：
   - onCreate：用了 v0-v2 + p0/p1，我写 `.registers 4`（应为 5）→ v2 覆盖 p0(this) → "'this' argument java.lang.String not instance of Activity"
   - onBackPressed：`.registers 2`（应为 3）→ "tried to get class from non-reference register v1(type=Boolean)"
   规则：`.registers N`，N = 本地寄存器数 + 参数数（含 this）。修正后进程存活、零崩溃

## 反编译真实 App 重编的死路（避坑）
试过"改造真实发布的 WebGPT"（它本就是 chatgpt.com 的 WebView 壳）——但 apktool **重编**卡在
Material 组件的 `$` 前缀合成资源名（`$mtrl_checkbox_button_...` invalid entry name）。
→ **造壳用干净手写工程（templates/webview-shell/），别去重编混淆大 App**

## 交付
- `com.apple.maps`（6.3KB 极简 WebView 壳，桌面 Safari UA 加载 maps.apple.com）：安装成功、进程稳定、零崩溃
- 模板 `templates/webview-shell/` 已回归验证可独立构建（改包名/label/URL 三处即可包任意网页）
- 两个待用户侧动作（非技术障碍）：① 设备亮屏解锁后点图标（熄屏下 screencap 全黑、无 surface 属正常）
  ② maps uid 落在 v2rayNG 排除段 → 地图瓦片要走代理（勾选该 App 或全局代理），否则空白
- 顺带：ChatGPT 需求用**开源 WebGPT**（org.webgpt.app，已装）满足——它就是 chatgpt.com 的 WebView 壳，无 integrity 锁

## 六案例总成本曲线（更新）
| 案例 | 结果 | 核心教训 |
|---|---|---|
| Grok 1.2.50 | ✅ | 客户端 PairIP 可拆 |
| OpenBot 首攻+返工 | ✅ | 侦察先行 / 渲染才是验收 |
| ChatGPT 改包+登录 | ⚠️ | 服务端锁拆不了，会识别会放弃 |
| **Apple 地图造壳** | ✅ | **改不动就自己造；本机可搭完整 APK 工具链** |

**能力闭环**：本 skill 现在覆盖「改包重签 → dex 拆锁 → 识别服务端锁 → 放弃改包转自造 WebView 壳」全谱系。
遇到服务端完整性锁的 App，正解不是硬啃，是 `templates/webview-shell` + 目标网页 URL。



