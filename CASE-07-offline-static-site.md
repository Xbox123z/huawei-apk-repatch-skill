# CASE 07：静态站点整站离线化 → 原生 App（jyywiki.cn）

> 场景：用户要求「把 https://jyywiki.cn/ 做成一个 App 装手机上，要完美！！！全博客的内容都要」。
> 环境：Huawei CLS-AL00 / HarmonyOS 4.3 / Android 12 / 无 root / 无 PC / 全流程在本机完成。
> 结果：230 MB APK，内置 850 个页面 + 2686 个资源文件，**断网可读**，v1+v2 双签，已装机。

## 1. 为什么不能只做「套壳」

`WebView.loadUrl(网址)` 的壳在离线时是白屏/错误页。用户要的是**内容**，
所以必须把整站镜像进 APK 的 `assets/`，再在 `shouldInterceptRequest` 里把
`https://jyywiki.cn/...` **就地**映射到 `assets/site/...`。
这样 URL 仍然是原站地址 ⇒ 页面里的绝对路径、`_next` 静态资源、CDN 引用全部照旧工作，
不需要改写 HTML，也不会破坏 KaTeX / highlight.js。

## 2. 流水线（四个脚本，全部本机跑）

| 阶段 | 脚本 | 要点 |
|---|---|---|
| ① 镜像 | `mirror.py` | BFS 抓 HTML，正则提取 `href/src/srcset/url()`/JS 里的 `/_next/*`；同时镜像 CDN（jsdelivr / cdnjs / fonts） |
| ② 路由数据 | `crawl_data.py` | Next.js 客户端跳转需要 `/_next/data/<buildId>/<route>.json`；从任一带 `__NEXT_DATA__` 的 HTML 里取 buildId，按已抓 HTML 的路径反推 URL 逐个抓（本案例 25/699 命中） |
| ③ 缺口补齐 | `audit_fill.py` | 重新扫描所有已镜像文件的站内引用，凡本地缺失就补抓，循环到收敛（本案例补齐 1243 个文件，剩 14 条是源站自身 404） |
| ④ 打包 | `pack_assets.py` | apktool 先出「无资源」APK，再用 Python `zipfile` 追加 `assets/site/**`（图片/字体/视频用 STORED，文本 DEFLATED），最后走本机 v1+v2 签名链 |

> 为什么不用 Java 打包资源：325 MB 资源交给 apktool/jvm 会吃内存且慢；
> Python 追加 zip 更稳，且完全绕开 termux coreutils（本机 `rm` 因缺 `libandroid-selinux.so` 直接挂）。

## 3. 五个 smali 坑（全部踩过，逐个复现过）

### 坑 1：`WebResourceRequest` 是接口 → 必须 `invoke-interface`

```
java.lang.IncompatibleClassChangeError: Found interface android.webkit.WebResourceRequest, but class was expected
```
```smali
# ✗ invoke-virtual {p2}, Landroid/webkit/WebResourceRequest;->getUrl()...
# ✓
invoke-interface {p2}, Landroid/webkit/WebResourceRequest;->getUrl()Landroid/net/Uri;
```
`getUrl()` / `isForMainFrame()` 都走 interface。

### 坑 2：分支极性写反 → isLocal 永远 false（静默回落到联网）

```smali
invoke-virtual {p0, v0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
move-result v1
if-eqz v1, :next        # ✓ 不等才跳到下一个 host；写 if-nez 就永远跳过 return-true
const/4 v1, 0x1
return v1
:next
```
症状极具迷惑性：App 看起来"能打开"，其实全部走网络 —— 断网才暴露。

### 坑 3：`if-eqz v3, :havepath` 把默认值覆盖成了 `/`

```smali
invoke-virtual {v0}, Landroid/net/Uri;->getPath()Ljava/lang/String;
move-result-object v3
if-nez v3, :havepath    # ✓ null 才跳（跳过默认值）；写 if-eqz 会给每个非空 path 都塞 "/"
const-string v3, "/"
:havepath
```
症状：**所有资源都被映射成 `index.html`**，日志里"命中"很多，页面却是错的。

### 坑 4：MIME 必须按「资源路径」判定，不能按「URL 路径」

```smali
# ✗ invoke-static {v3}, Net->mimeOf(...)   # v3 = URL path：https://jyywiki.cn/ 的 path 是 "/"
# ✓ invoke-static {v4}, Net->mimeOf(...)   # v4 = assets 路径：site/jyywiki.cn/index.html
```
后果极隐蔽：URL `/` 匹配不到任何扩展名 ⇒ `application/octet-stream` ⇒ **华为 WebView 把主文档当下载处理**，
页面不渲染、`onDownloadStart` 触发、还会外跳浏览器。

### 坑 5：`invoke-*` 的 p 寄存器不能超过 v15

```
Invalid register: v18. Must be between v0 and v15, inclusive.
```
`.registers 20` + 2 个参数 ⇒ `p0 = v18`，但 smali 对 `invoke-*` 只接受 v0–v15（4-bit 形式）。
即：**方法寄存器总数 ≤ 16 时才可安心用 p 寄存器**。要么把 `.registers` 压到 16（locals v0–v13 + p0/p1 = v14/v15），
要么改用 `invoke-*/range` 并全程用 v 寄存器。

### 附加坑：延迟加载才是「不被系统跳浏览器」的关键

`am start`（后台启动）后立刻 `loadUrl` 时，HarmonyOS 会把这次 WebView 导航**交给系统浏览器**：
```
ActivityTaskManager: notifyActivityLaunching intent=Intent { act=VIEW dat=https://jyywiki.cn/ flg=0x14002000 cmp=com.microsoft.emmx/... }
HwAppJumpReporter: callerPkg:cn.jyywiki.offline ... targetLabel:Edge
```
现象 = 一开 App 就跳到 Edge，用户会认为「你只是做了个快捷方式」。

修法：**把 `loadUrl` 从 `onCreate` 挪到 `onResume` / `onWindowFocusChanged(true)`，并用 `loaded` 标志只触发一次**：

```smali
.method private startLoad()V
    .registers 3
    iget-boolean v0, p0, Lcn/jyywiki/offline/MainActivity;->loaded:Z
    if-eqz v0, :done
    const/4 v0, 0x1
    iput-boolean v0, p0, Lcn/jyywiki/offline/MainActivity;->loaded:Z
    iget-object v1, p0, Lcn/jyywiki/offline/MainActivity;->wv:Landroid/webkit/WebView;
    if-eqz v1, :done
    const-string v2, "https://jyywiki.cn/"
    invoke-virtual {v1, v2}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V
    :done
    return-void
.end method
```
并在 `onResume` / `onWindowFocusChanged(Z)` 里 `invoke-virtual {p0}, ...->startLoad()V`。

## 4. 站内搜索（850 条，纯静态）

离线包里无法依赖服务端搜索，于是：
- `gen_search.py` 扫全部 HTML 取 `<title>` / 首个 `<h1|h2>`，输出 `_app/index.json`（850 条，90 KB）
- `_app/search.html` 自绘搜索页（原生 JS，无框架），按标题/路径/章节即时过滤 + 章节 chip
- 入口用**原生悬浮按钮**（`gradientdrawable` 画圆 + `TextView("搜")` + `onClickListener`），
  点击 `loadUrl("https://jyywiki.cn/_app/search.html")` ⇒ 仍走拦截、仍在离线包内

## 5. 验收方法（不起前台也能验）

屏幕锁定时 `screencap` 全黑，不能作为验收依据。改用**日志探针**：

| 标记 | 含义 |
|---|---|
| `JYYREQ <url>` | 拦截器被调用 |
| `JYYHIT <asset>` | 命中本地资源 |
| `JYYMISS <path>` | 本地缺失（回落网络） |
| `JYYDONE <url>` | `onPageFinished` 触发（页面真的加载完成） |
| `JYYJS {"t":标题,"n":正文长度,"i":图片数,"a":链接数}` | `evaluateJavascript` 回读 DOM —— **渲染的硬证据** |
| `notifyActivityLaunching ... VIEW dat=https://jyywiki.cn` | 被系统外跳浏览器（必须为 0） |

最终实测：`REQ=14 HIT=12 MISS=1 DONE=2`，`JYYDOWN=0`（不再被当下载），外跳 0。

## 6. 产物

- APK：`JYY-Wiki-1.0.apk`，230,901,540 B，sha256 `9137ea75d580765d9290ce11af91ac048d66684f222bf4c949478a58af718fac`
- 签名：`v1 files=2686 covered=2686 missing=0`；`v2 digest=OK`
- 内容：850 页面 / 2686 文件 / 325 MB 镜像 → 230 MB APK

## 7. 复用清单

1. `mirror.py` 改 `SITE_HOSTS/CDN_HOSTS` 与起始 URL
2. `crawl_data.py` 只在目标是 Next.js 站点时需要
3. `audit_fill.py` 跑两轮基本收敛
4. smali 侧改 3 处：包名、`startLoad()` 里的 URL、`Net.isLocal()` 里的 host 白名单
5. 别忘 `.registers ≤ 16`、MIME 用资源路径、`loadUrl` 延迟到可见后
