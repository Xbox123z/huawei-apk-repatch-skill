> ⚠️ **先读 [SAFETY-RULES.md](SAFETY-RULES.md)**：本 skill 的最高优先红线（永不破坏用户网络；任何全局设置必须成对回滚并校验）。

# Skill: 在低版本 Android / 华为 EMUI 上强装高要求 APK（重签名 + dex 拆锁 + 本机 adb 自连）

> 实战来源：在 Huawei CLS-AL00（EMUI 12 / Android 12 / SDK 31，无 GMS、无 root、无电脑 ADB）上
> 成功安装并运行 Grok 1.2.50（要求 minSdk 32、含 PairIP 防盗版、官方仅发 split APK）。
> 全程约 1 亿 token、6 轮试错。本 skill 是完整复盘，按此流程可在新任务上直接复用。

## 适用场景
- APK/XAPK 的 minSdk 高于设备 SDK（INSTALL_FAILED_OLDER_SDK）
- 华为/荣耀：纯净模式、文件管理器报「该安装包未包含任何证书」
- 应用内置授权 SDK（PairIP/AppDetex、Google LVL）导致装上即闪退 / 「Something went wrong」
- 无 root、无电脑、无 Shizuku —— 只有设备上的一个 shell 环境 + 无障碍通道

## 0. 环境准备（本机 adb 自连 = 本流程的生命线）
电脑 ADB / Shizuku 都不可靠时，用**设备自己的 adbd**：USB 调试开启后 adbd 监听 127.0.0.1:5555，
在设备 shell 里跑 adb 客户端连回自己，即获得完整 `pm install` 会话能力（绕开华为一切 UI 拦截）。

```bash
# Termux 系环境（dpkg 无 root 时 apt install 会失败，改用 download + python 解包）
apt-get download android-tools zlib libzstd libc++ abseil-cpp brotli fmt libprotobuf liblz4
# 注意 libzstd 在 zstd 包里、libc++ 包名就叫 libc++；用 python 解 ar+data.tar.xz 合并到 merged2/
LD_LIBRARY_PATH=<lib目录> <bin目录>/adb version          # 应输出 1.0.41
nohup <adb> -P 5037 server nodaemon &                    # 客户端自举 server 会 execl 被拒，必须手动起
<adb> -P 5037 connect 127.0.0.1:5555                     # 连本机 adbd
<adb> -P 5037 shell id                                   # uid=2000(shell) context=u:r:shell:s0 → 成功
```
坑：
- 管道给本机 `grep/tail` 会被 LD_LIBRARY_PATH 污染（它们依赖 libandroid-support）→ 管道命令用绝对路径或不带 env，或 shell 内用设备端 grep
- adbd 僵尸态（开关开着但接口零端点）：用无障碍通道远程「关→开 USB 调试 + 确认弹窗」即重启 adbd，无需重启手机
- `pm install-create -a` 在 Android 12 不存在；`settings put` 可能被 EMUI 拒（SecurityException getCurrentUser）

## 1. 侦察（先跑，别急着动手）
```bash
unzip -l app.xapk                    # base.apk + config.*.apk + manifest.json → split 套装
# 用 python 解析二进制 AXML 拿真实 minSdk/targetSdk（manifest.json 会骗人，以 AXML 为准）
# 检查 base 是否含 lib/（split 模式时 .so 在 config.<abi>.apk，resources.arsc 在 config.<lang>/<dpi>.apk）
```
决策树：
- 🛑 **第 0 关·先判锁在客户端还是服务端（ChatGPT 血案：不判就动手 = 白烧一整个战役）**
  在改任何字节之前，先花 2 分钟确认这个 App 的授权/登录锁是不是**服务端强制**：
  ```bash
  # 扫 dex 找服务端完整性标志（这些出现 = 大概率服务端验，客户端 patch 无效）
  python3 -c "import zipfile,sys; z=zipfile.ZipFile('base.apk'); [print(n, [p for p in [b'PlayIntegrity',b'playintegrity',b'preauth',b'DeviceCheck',b'attestation'] if p in z.read(n)]) for n in z.namelist() if n.endswith('.dex')]"
  ```
  **判据**：登录/报错页由**服务器返回**（如 `auth.xxx.com` 网页弹中文"身份验证错误 / preauth_cookie_device_check_failed"），
  且错误要求一张 **Google Play Integrity / DeviceCheck 令牌** → **这是硬件级+服务端双重锁，本 skill 全套手术都救不了**：
    - 令牌由设备 TrustZone 私钥签发，机型不在 Google 认证库（华为/部分国产受制裁机型）就发不出，无法伪造
    - 重签名本身会让"应用完整性"维度必挂（Grok 能过是因为它只查 PairIP 纯客户端锁，不查 integrity）
    - 降级找旧版也没用：旧版 dex 同样有 preauth（认证一直都在），且服务端往往已把旧版废弃（"此版本已过时"）
  **→ 遇到这种，直接停手，转告用户用网页版（官方确认网页端不做设备认证）或换认证机型。不要改包。**
  对照：PairIP/AppDetex/LVL 是**客户端**锁（本 skill 第 5 步能拆）；Play Integrity/DeviceCheck 是**服务端+硬件**锁（拆不了）。
- minSdk 太高 → 需要改包重签（本 skill 主线）
- 设备 SDK 与包差距 ≤ 几 → 优先找官方旧版本（apkeep -l -a <pkg> -d apk-pure 列版本；旧版可能免改包）
- 授权 SDK（dex 里 grep `Lcom/pairip` / `appdetex` / `LVL`）→ 必须配合第 5 步 dex 拆锁
- ⚠️ **不是所有包都需要改 minSdk/重签**（OpenBot 实证）：先 `dumpsys package <pkg>` 看是否已装、直接启动抓 logcat 定位真实症状，再决定动哪层手术。
  OpenBot（run.openbot.mobile，APKPure）minSdk 24 < 设备 31，安装本来就成功——闪退纯粹是 PairIP，只需第 5 步 + 重签
- 快速判症：`logcat -d | grep LicenseClient` 出现 `Could not bind with the licensing service: com.android.vending.licensing.ILicensingService` → 100% 是 PairIP
- **侦察清单（每项都可能砍掉一整道工序）**：
  1. AXML 真实 minSdk → 决定要不要改包
  2. `targetSdk` 高**不用管**：targetSdk 高于设备 SDK **不拦安装**，只有 minSdk 拦（实测 target 37 装在 API 31 成功）
  3. 扫全部 `classes*.dex` 找 `Lcom/pairip` / `appdetex` / `ILicensingService` → 决定要不要 dex 手术（纯客户端锁可拆）
  4. 有 `assets/index.android.bundle` → RN/Hermes，必须 STORE≥8 对齐；没有 → 原生应用，无此雷
  5. ⚠️ **扫到 `PlayIntegrity` / `preauth` / `attestation` → 高度警惕服务端锁（见第 0 关）**。
     它可能不阻塞"启动/渲染"，但会**阻塞登录**（登录要服务器验设备令牌）。
     **不要因为"能启动"就判断为可解**——ChatGPT 就是能装能渲染登录页、却在点登录后被服务端 `preauth_cookie_device_check_failed` 卡死。
     正确做法：改包前先拿"这个 App 登录是否依赖 Play Integrity"问用户/查官网，或直接告知"能装但可能无法登录"的预期

## 2. 改包（**首选 scripts/rebuild_splits.py，一条命令搞定整个套装**）
```bash
python3 scripts/rebuild_splits.py app.xapk out/ --from 32 --to 31
# 自动：每个 split 各自打 AXML minSdk + 保留 META-INF/services + 按对齐规则重建
# 输出会报 services kept=N 与改动数；改动数 0 说明 --from 不等于真实 minSdk
```
（build_single_apk.py 是单包合并版，仅在不便用 split 套装时用；注意 §2 末的对齐/资源表教训）
- **AXML 就地补丁**：解析 string pool + 遍历 chunk，只改 `uses-sdk/minSdkVersion` 的 int 值（同值 32 可能出现在别处如 maxSdkVersion，必须按元素名+属性名匹配）；重新 deflate，更新 CRC
- **必须保留 `META-INF/services/*`**（ServiceLoader 描述符！删了 → kotlinx-coroutines Main dispatcher missing 崩溃）；只删签名三件套 .RSA/.SF/.MF 和 stamp-cert-sha256
  - ⚠️ **血泪重演警告**（OpenBot 复跑时又踩了一次）：自己临时手写重建循环时，**绝不允许** `if name.startswith('META-INF/'): continue` 这种一刀切。
    正确谓词照抄 add_v1.py：`name=='stamp-cert-sha256' or (name.startswith('META-INF/') and name.endswith(('.RSA','.DSA','.EC','.SF','.MF')))`
    症状：装上了、授权页也不弹了，但 MainActivity.onCreate 抛 `ExceptionInInitializerError: Module with the Main dispatcher is missing`
- **对齐**：resources.arsc → STORE + 4 字节对齐；lib/**/*.so → STORE + 4096 对齐（Android 11+ 要求）；**其余所有 STORE 条目 → ≥8 字节对齐**（React Native/Hermes 的 assets/index.android.bundle 靠 mmap 读取，偏移 mod8≠0 → `Compiling JS failed: Buffer misaligned.` → 界面永远白屏卡住但不崩溃）
  - ⚠️ **对齐必须在整条链上保持一致**：rebuild → add_v1（重写 zip！）→ sign_v2。任何一步用旧对齐规则都会把前面步骤的对齐毁掉。add_v1.py 已修正（method==0 一律 ≥8 对齐）
  - ⚠️ **原版包自己可能就是歪的**（OpenBot 实证：APKPure 原版 bundle 偏移 mod8=4）——原版被授权锁先杀掉所以从没走到 JS 加载，拆锁后这颗雷才炸出来。**拆锁后必须全链路重新验证渲染**
- **split 套装优先于单包合并**：把 config.mdpi 等资源硬并进单包会 `Resources$NotFoundException`（资源表 ID 不互通）。正确做法：每个 split 各自改 manifest、各自重签，用 `pm install-create/write -S <size> <sid> <name> <path> ×N; pm install-commit` 一次提交，框架自己叠加资源表
- 每个 split 的 manifest 都有自己的 minSdk，**全部要改**（漏一个 → commit 时 INSTALL_FAILED_OLDER_SDK）

## 3. v1 (JAR) 签名（add_v1.py）
- MANIFEST.MF / CERT.SF 必须 **CRLF**、**72 字节折行**（续行以空格开头）、行内不切断 UTF-8 多字节
- CERT.RSA = `openssl smime -sign -noattr -signer cert.pem -inkey key.pem -in CERT.SF -outform DER`
  （detached PKCS#7；华为安装器只读 v1，缺 v1 → 「未包含任何证书」）
- 每个 entry 的 CRC 用**解压后内容**计算（deflate 条目别把 CRC 算在压缩字节上）

## 4. v2 签名（sign_v2.js —— 纯 Node 实现，AOSP 逐字段对齐）
关键结构（全部小端、length-prefixed=uint32+bytes、sequence=LP(拼接)）：
```
APK Signing Block: [size u64][pairs][size u64]["APK Sig Block 42"]   # 插在 CD 之前
pair: [size u64 = len(id+value)][id u32=0x7109871a][value]
value = LP( LP(signer) )
signer = LP(signedData) + signatures + LP(pubkeySPKI)
signedData = digests + certs + attrs        # 各为 LP sequence
digests 项: [algo u32] + LP(digest)
```
**血泪坑（npm 库 apk_sign_ts 的 bug，AOSP V2Verifier12.java:313 实锤）**：
digests 项里的 algo 必须填**签名算法 ID**（RSA-SHA256=0x0103），不是摘要算法 ID（0x0101）！
digests 与 signatures 的算法列表必须完全相等，否则 Android 报
`Signature algorithms don't match between digests and signatures records` → 「未包含任何证书」。
- 内容摘要 = 三段分块（1MiB）：A=[0,blockStart) B=CD C=EOCD(cd字段=blockStart)；
  每块 `0xa5+len+data` 做 SHA256，汇总 `0x5a+count+hashes` 再 SHA256
- 签名 = RSA-PKCS1-SHA256 over signedData；EOCD 的 CD offset 要加 block 长度
- **v3 不要手搓**（SignedData 字段布局极易错，Android 12 上坏 v3 会连坐 v2 整体失败）；只做 v1+v2 足够
- 生成密钥：`openssl genrsa 2048` + 自签证书（有效期拉满）
- 验签：verify_apk.py 独立重算（不要复用签名代码自证）；再用设备 `pm install` 实测

## 5. dex 拆锁（LicenseClient/PairIP 类，dexpatch.py 已实现最小 DEX 编辑器）
症状：装上后闪退 / 「Something went wrong. Check that Google Play is enabled...」/
LicenseActivity 一出现进程即死 → 授权 SDK 在作祟。
```python
# 步骤：
# a) 在 classes*.dex 找 'Lcom/pairip/licensecheck/LicenseActivity;' / 'LicenseClient;'
# b) 解析 class_def → class_data → method 列表（direct 段和 virtual 段的 method_idx 基址各自归零！）
# c) 两类拆法（组合使用）：
#    LicenseActivity.onStart → 保留原 super.onStart（35c: word0=(1<<12)|0x6f, word1=methodIdx, word2=C=v2）
#                              + invoke-virtual finish（0x6e）+ return-void
#      35c 格式：寄存器数在 word0 高 4 位！写成 (count<<8) 会报 invalid arg count(0)
#      3rc 格式：word2=(count<<8)|vstart；range 的 kind 编码在 word1 高 4 位
#      别动 tries_size/debug_info_off（清零会让 handler 悬空 → 整个 dex 拒载 → ClassNotFoundException）
#      入口插 return 后原代码变不可达死代码，校验器接受，try/handler 可原样保留
#    LicenseClient 杀手机件全部 neuter 成空方法体（按返回类型选 return-void / const/4+return(-object)）：
#      initializeLicenseCheck, checkLicense, checkLicenseInternal, scheduleRepeatedLicenseCheck,
#      scheduleAppShutdown, startErrorDialogActivity, startPaywallActivity, handleError,
#      createCloseAppIntentOrExitIfAppInBackground, exitApp/closeApp/closeAllTasks（Activity 侧）
#    —— 只拆 Activity 不拆 Client 会「用着用着闪退」：Client 有周期复检定时器
#    ⚠️ 找 finish 的 method_id 别硬编码：R8 可能把 Activity.finish 内联掉，dex 里根本没有该 method 引用
#      （OpenBot 实证：只有 LicenseActivity 自己的 finishAndRemoveTask / ActivityManager$AppTask.finishAndRemoveTask）。
#      正确做法：反汇编同类 exitApp/closeApp 看它实际调什么，或全表扫 name∈{finish,finishAndRemoveTask}
#      且 owner 是该 Activity 自身（继承来的也能调），拿到 id 再写 35c。
#      找不到就退回「super.onStart(); return-void」——不 finish 只是授权页多停一帧，比 patch 失败强。
# d) 修完必须重算 header：sha1(dex[32:]) 写入 [12:32]，adler32(dex[12:]) 写入 [8:12]
# e) 替换进 base.apk 时 classes.dex 用原 compress_type，CRC 用新内容
```
返回类型解析坑：proto 的 return_type_idx 是 **type_idx**，要经 type_ids→string_ids 两级映射；
直接当 string idx 用会读出乱码导致选错 return 指令（校验失败）。

## 6. 安装与善后
```bash
adb shell pm uninstall <pkg>
SID=$(adb shell pm install-create -r -t -i com.android.vending | tr -dc 0-9)   # -i 伪装 Play 安装器
for f in base cfg-*; do adb shell pm install-write -S $(stat -c%s $f.apk) $SID $f.apk /data/local/tmp/...; done
adb shell pm install-commit $SID
# OAuth 回跳断链（connect 第三方账号「已连接但回来没有」）：
# 重签名导致 App Links 域名验证失败（assetlinks 指纹不匹配）→ 强制批准：
adb shell pm set-app-links --package <pkg> 2 all
adb shell pm get-app-links <pkg>            # 确认 Domain verification state: approved
# 每次重装都要重新 set-app-links！
# 华为省电误杀：adb shell dumpsys deviceidle whitelist +<pkg>；cmd appops set <pkg> RUN_IN_BACKGROUND allow
```

### ⚠️ 验收标准（OpenBot 教训：我在这条上栽了两次，别信"进程活着"）
**pidof 有值 + 无 crash 记录 ≠ App 可用。** 必须验证画面真的渲染出来了：
```bash
# 判据（三选二即可确认，全过最稳）：
adb shell "dumpsys window windows" | grep -aA8 "Window.*<pkg>/.*Activity" | grep -aE "mHasSurface|isVisible"
#   → 必须 mHasSurface=true 且 isVisible=true（false = 卡住/白屏，即使进程活着）
adb shell "screencap -p" > /path/shot.png      # 截图肉眼确认 UI 内容
adb shell "logcat -d | grep -aciE 'misalign|JavascriptException|FATAL'"   # 应为 0
```
- 采样时注意：grep 窗口状态要**跨行匹配**（`grep -aA8` 后再过滤 mHasSurface），单行 grep 会假阴性
- 用户报「卡着不动」而日志一切正常时，**第一反应就是查 mHasSurface 而不是查崩溃**
- RN 应用（有 index.android.bundle / Hermes）拆锁后必查：`logcat | grep -i "Compiling JS failed"`

## 7. 排障速查
| 症状 | 真因 | 处置 |
|---|---|---|
| 未包含任何证书（文件管理器） | 缺 v1 或点了无签名诱饵文件 | 补 v1；清理同名旧包 |
| 未包含任何证书（pm install） | v2 digests/signatures 算法 ID 不一致 | 两处都写签名算法 ID（0x103） |
| INSTALL_FAILED_OLDER_SDK（commit 时） | 某个 split 的 minSdk 漏改 | 全部 split 都要改 |
| Resources$NotFoundException | 单包合并破坏了 split 资源表 | 改走 split 套装安装 |
| Main dispatcher is missing | 删了 META-INF/services（即兴重写重建循环时高发） | 用 skill 自带 add_v1.py 谓词，别手搓 |
| licensing service 绑定失败但界面无异常 | 该 App 的锁在 classes2/3.dex 不在 classes.dex | 遍历所有 dex 找 pairip 类 |
| patch onStart 时找不到 Activity.finish 的 method_id | R8 已内联掉 finish | 反汇编 exitApp/closeApp 找真实退出调用（常见 finishAndRemoveTask） |
| VerifyError invalid reg index | 3rc 的 word2 缺 count<<8 | word2=(count<<8)\|vstart |
| VerifyError invalid arg count(0) | 35c 数量位写进 word2 | word0=(count<<12)\|op |
| VerifyError "tried to get class from non-reference register" / "'this' argument not instance of Activity" | 手写 smali 的 `.registers` 数少了（没算参数/this） | `.registers N`，N = 本地寄存器 + 参数个数（含 p0=this）；见 §8 |
| 整包 ClassNotFoundException | 清 tries 但没删 try_item 字节 | 不动元数据，入口 return 即可 |
| 装上后一直卡住/白屏但不崩溃（RN 应用） | Hermes mmap bundle 偏移 mod8≠0 → `Compiling JS failed: Buffer misaligned.` | 全链路 STORE≥8 对齐（§2），改后重装 |
| 用几分钟就闪退 | LicenseClient 周期复检定时器 | 第 5 步全量 neuter |
| OAuth 回跳丢失 | App Links 验证失败 | pm set-app-links 2 all |
| 新装 App 连不上境外服务（curl 却通） | VPN 分应用排除段 `10445-99999` 覆盖普通 App uid → 它**不走代理** | 去代理 App 勾选该 App / 改全局代理（每次装新 App 必查） |
| **能装能渲染登录页，点登录后服务器返回"身份验证错误 / preauth_cookie_device_check_failed"** | **Google Play Integrity 服务端+硬件双锁**：机型无 Google 认证 + 我们重签名 → 令牌发不出 | **本 skill 无法解决**。别改包了，转网页版（不做设备认证）或换认证机型。旧版也救不了（旧版同样有 preauth，且服务端常已废弃旧版） |
| adb 连不上（offline/零端点） | adbd 僵尸 | 无障碍远程开关 USB 调试重启 adbd |
| adb server 突然没了（execl Permission denied） | 客户端无法自动 fork server | `nohup env LD_LIBRARY_PATH=... adb -P 5037 server nodaemon &` 再 connect |
| 执行 pkill 后整条命令被 SIGTERM | `pkill -f` 匹配到自己 shell 的命令行 | 用 `pkill -x adb`（精确进程名），别对链路自身用 -f |
| 下载下来的 xapk 只有几 MB / 不是 zip | 下载截断或反爬页 | 循环「下载→testzip→体积阈值」重试 |
| 华为弹窗找不到关闭 | 纯净模式=多组件策略非单 App | 用 pm 会话安装直接绕开 |

## 8. 从零构建 APK（当"改包"不如"造壳"时）
遇到 §1 第 0 关判定的**服务端锁 App**（ChatGPT 这类），或想要某网页的原生入口，
**与其硬改官方包，不如自己造一个 WebView 壳**（全新包名、官方签名规则不适用、无 integrity 锁）。
本机（无电脑无 root）可搭出完整 APK 构建工具链：
```bash
bash scripts/build-toolchain/setup_toolchain.sh   # java+apktool+aapt2+framework，apt download+python 解包
bash scripts/build-toolchain/build_apk.sh <proj> out.apk   # 编译 apktool 工程 + v1/v2 签名 + 校验
```
- 模板见 `templates/webview-shell/`：改包名/label/URL 三处即可包任意网页（maps.apple.com、任意 SPA）
- 工具链坑（都已固化进脚本）：
  - `apktool.yml` **必须含 `usesFramework.ids:[1]`**，否则 aapt2 link 找不到 android: 命名空间（"attribute android:name not found"）
  - aapt2 缺 `libexpat.so.1`：Termux 无 expat 包，`cp /system/lib64/libexpat.so $TLIB/libexpat.so.1`
  - java 依赖链：libandroid-shmem/spawn/glob/support + libc++/ffi/iconv/ncurses/pcre2/fmt/png/zlib 全要解到同一 lib 目录
  - java 临时目录：`-Djava.io.tmpdir=$HOME/tmp`（默认 /tmp 不可写会 IOException）
  - **smali 寄存器计数**是头号运行期坑：`.registers N` = 本地 + 参数(含 this)；数错 → VerifyError（见 §7 末）
  - 反编译真实 App 再重编常卡在 `$` 前缀合成资源名（`$mtrl_checkbox_...` invalid entry）——所以造壳用**干净手写工程**，别改混淆大 App

## 9. 文件清单
- scripts/rebuild_splits.py — **改包首选**：整个 XAPK/split 套装一条命令重建（AXML minSdk + 保 services + 对齐）
- scripts/kill_pairip.py — **拆锁首选**：PairIP/AppDetex 一键 neuter（自动探测 finish/finishAndRemoveTask，回归验证过）
- scripts/build_single_apk.py — 单包合并版 AXML 补丁 + 对齐重建（仅在必须合成单包时用，注意 §2 教训）
- scripts/add_v1.py — v1 JAR 签名（折行/CRC/STORE≥8 对齐已修正；密钥走 `SIGN_KEY`/`SIGN_CERT` 环境变量）
- scripts/sign_v2.js — v2 签名（Node，需 node-forge，路径走 `FORGE_PATH`；digests algo 已按 AOSP 修正）
- scripts/dexpatch.py — 最小 DEX 编辑器（类/方法定位、方法体替换、header 重算）
- scripts/verify_apk.py — 独立 v1+v2 校验器
- scripts/adb-local/bootstrap_adb.sh — 本机 adb 自连
- scripts/build-toolchain/setup_toolchain.sh — 本机搭 java+apktool+aapt2+framework（§8）
- scripts/build-toolchain/build_apk.sh — 用工具链编译 apktool 工程 + 签名一条龙（§8）
- templates/webview-shell/ — 可复用 WebView 壳工程，改包名/label/URL 包任意网页（已回归验证可独立构建）
- CASE-STUDY.md — 五个案例完整时间线（Grok / OpenBot 首攻 / OpenBot 返工 / ChatGPT 改包 / ChatGPT 登录边界 + 造壳）
- CASE-07-offline-static-site.md — **整站离线化造 App**（jyywiki.cn：850 页 / 230 MB / 断网可读；含 5 个 smali 坑与「不被系统外跳浏览器」的延迟加载修法）

| [CASE-08](CASE-08-game-region-and-free-proxy.md) | 腾讯游戏区域限制逆向、免费代理不可行性实证、代理池保活架构 |
