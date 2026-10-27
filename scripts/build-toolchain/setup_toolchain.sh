#!/data/data/com.dsharnessmobile.shell/files/usr/bin/bash
# 在 Android 本机（Termux 系 shell）从零搭 APK 构建工具链：java + apktool + aapt2 + framework。
# 无 root、无电脑。产物：$TC/bin/{java,apktool,aapt2} 与 $TC/apktool-framework/1.apk
# 关键：dpkg 无 root 装不了，改 apt-get download + python 解 ar/data.tar(.zst|.xz) 合并到 tchain/
set -e
H="${HOME:-/data/data/com.dsharnessmobile.shell/files/home}"
TC="$H/tchain"; WORK="$H/grok_build"
mkdir -p "$TC" "$WORK" "$H/tmp"; cd "$WORK"
export PATH=/data/data/com.dsharnessmobile.shell/files/usr/bin:$PATH
PKGS="openjdk-17 apktool aapt2 zlib libandroid-shmem libandroid-spawn libandroid-glob libandroid-support libc++ libffi libiconv ncurses pcre2 libfmt libpng"
for p in $PKGS; do apt-get download "$p" >/dev/null 2>&1 || echo "no pkg $p"; done
python3 - <<'PY'
import tarfile, io, lzma, glob, os
root=os.environ.get('TC','')+'/'; root=os.path.expanduser('~')+'/tchain'
import glob as g
for deb in g.glob(os.path.join(os.path.expanduser('~'),'grok_build','*.deb')):
    data=open(deb,'rb').read(); off=8
    while off<len(data):
        nm=data[off:off+16].decode().strip().rstrip('/')
        size=int(data[off+48:off+58].decode().strip()); body=data[off+60:off+60+size]
        if nm.startswith('data.tar'):
            try:
                if nm.endswith('.zst'):
                    import zstandard; body=zstandard.ZstdDecompressor().stream_reader(io.BytesIO(body)).read()
                elif nm.endswith('.xz'): body=lzma.decompress(body)
                tarfile.open(fileobj=io.BytesIO(body)).extractall(root, filter='data')
            except Exception as e: print('skip',os.path.basename(deb),str(e)[:40])
        off+=60+size+(size%2)
print('extracted all debs ->', root)
PY
TLIB="$TC/data/data/com.termux/files/usr/lib"; TBIN="$TC/data/data/com.termux/files/usr/bin"
ALIB="$H/adbget/merged2/data/data/com.termux/files/usr/lib"
# libexpat.so.1 从系统借（aapt2 需要，Termux 包名不叫 expat）
[ -f "$TLIB/libexpat.so.1" ] || cp /system/lib64/libexpat.so "$TLIB/libexpat.so.1" 2>/dev/null || true
# java
export LD_LIBRARY_PATH="$TLIB:$ALIB"
"$TLIB/jvm/java-17-openjdk/bin/java" -version 2>&1 | head -1
# framework：从设备拉 framework-res.apk 注册进 apktool
ADB="$H/adbget/merged2/data/data/com.termux/files/usr/bin/adb"
if [ -x "$ADB" ]; then
  LD_LIBRARY_PATH="$ALIB" "$ADB" -s 127.0.0.1:5555 pull /system/framework/framework-res.apk "$WORK/framework-res.apk" 2>/dev/null || true
fi
if [ -f "$WORK/framework-res.apk" ]; then
  "$TLIB/jvm/java-17-openjdk/bin/java" -jar "$TLIB/../share/java/apktool.jar" if "$WORK/framework-res.apk" -p "$WORK/apktool-framework" >/dev/null 2>&1 || true
fi
echo "工具链就绪。用法见 build_apk.sh"
