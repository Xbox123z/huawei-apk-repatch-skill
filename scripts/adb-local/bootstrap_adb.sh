#!/data/data/com.dsharnessmobile.shell/files/usr/bin/bash
# 在 Android 本机跑一个 adb 客户端，通过 127.0.0.1:5555 连回本机 adbd。
# 前置：开发者选项里「USB 调试」开启（adbd 会在 5555 监听，即使没插线）。
# 用途：不依赖电脑/Shizuku，用 pm install 会话静默安装，绕开华为文件管理器与纯净模式。
set -e
ADB_DIR="${ADB_DIR:-$HOME/adbget/merged2/data/data/com.termux/files/usr}"
export LD_LIBRARY_PATH="$ADB_DIR/lib"
ADB="$ADB_DIR/bin/adb"
[ -x "$ADB" ] || { echo "adb 未就绪：先按 SKILL.md 第 0 节用 apt 下载 android-tools + 依赖 deb 并解包到 $ADB_DIR"; exit 1; }
"$ADB" -P 5037 start-server 2>/dev/null || nohup "$ADB" -P 5037 server nodaemon >/tmp/adb-server.log 2>&1 &
sleep 2
"$ADB" -P 5037 connect 127.0.0.1:5555
"$ADB" -P 5037 devices -l
echo "用： adb -P 5037 -s 127.0.0.1:5555 shell 'pm install -r -t /data/local/tmp/x.apk'"
