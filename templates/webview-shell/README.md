# WebView Shell 模板

把任意网页包成原生 App（离线壳）。改 3 处即可：

1. **AndroidManifest.xml**：`package="com.wrap.app"`、`android:label="显示名"`、
   activity 的 `android:name`（三处的包名/类名要一致）
2. **目录**：`smali/com/wrap/app/` 换成你的包路径；`MainActivity.smali` 里
   所有 `Lcom/wrap/app/MainActivity;` 同步替换
3. **URL**：MainActivity.smali 顶部 `.field START_URL` 改成目标网址；
   `DESKTOP_UA` 可选（桌面 UA 能拿到完整网页版，如 maps.apple.com）

构建（需先跑 setup_toolchain.sh）：
```bash
scripts/build-toolchain/build_apk.sh templates/webview-shell myapp.apk
adb shell pm install -r -t /data/local/tmp/myapp.apk
```

⚠️ smali 寄存器计数是最大坑：`.registers N` 里 N = 本地寄存器数 + 参数数
（含 this）。onCreate(Bundle) 用了 v0-v2 + p0/p1 → 必须 `.registers 5`；
数错会运行期 VerifyError（tried to get class from non-reference register /
'this' argument not instance of Activity）。

⚠️ 境外站点（maps.apple.com 等）装好后，App 默认可能不走代理 → 内容空白。
去代理 App 勾选它，或全局代理。验收看 mHasSurface=true 且截图有内容。
