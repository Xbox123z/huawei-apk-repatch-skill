#!/data/data/com.dsharnessmobile.shell/files/usr/bin/bash
# 用本机工具链把 apktool 工程目录编成签名 APK。
# 用法: build_apk.sh <project_dir> <out.apk>   （需已 setup_toolchain.sh，且同级有 key.pem/cert.pem）
set -e
H="${HOME:-/data/user/0/com.dsharnessmobile.shell/files/home}"
TC="$H/tchain"; TLIB="$TC/data/data/com.termux/files/usr/lib"; TBIN="$TC/data/data/com.termux/files/usr/bin"
ALIB="$H/adbget/merged2/data/data/com.termux/files/usr/lib"
JAVA="$TLIB/jvm/java-17-openjdk/bin/java"; JAR="$TLIB/../share/java/apktool.jar"
FW="$H/grok_build/apktool-framework"; SK="/storage/emulated/0/鹿/huawei-apk-repatch-skill/scripts"
PROJ="$1"; OUT="$2"
export LD_LIBRARY_PATH="$TLIB:$ALIB" PATH="$TBIN:$PATH" SIGN_KEY="${SIGN_KEY:-$H/grok_build/key.pem}" SIGN_CERT="${SIGN_CERT:-$H/grok_build/cert.pem}" FORGE_PATH="${FORGE_PATH:-$H/apksign/node_modules/node-forge}"
rm -rf "$PROJ/build" "${OUT}.unsigned.apk"
"$JAVA" -Djava.io.tmpdir="$H/tmp" -jar "$JAR" b "$PROJ" -p "$FW" -o "${OUT}.unsigned.apk"
python3 -c "exec(open('$SK/add_v1.py').read().split('if __name__')[0]); resign('${OUT}.unsigned.apk','${OUT}.v1.apk')"
"$JAVA" >/dev/null 2>&1 || true
node "$SK/sign_v2.js" "${OUT}.v1.apk" "$OUT" >/dev/null
python3 "$SK/verify_apk.py" "$OUT"
echo "built+signed: $OUT"
