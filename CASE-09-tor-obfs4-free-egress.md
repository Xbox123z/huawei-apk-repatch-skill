# CASE-09：无 VPN、零成本获得境外出口（Tor 0.4.9 + obfs4 桥 + 链式代理）

> 场景：Huawei CLS-AL00（HarmonyOS 4.3 / Android 12 / 无 root），
> 国内网络环境，**没有任何 VPN / 付费代理可用**，但需要一个稳定的美国 IPv4 出口。
> 结果：**做到了**，出口 `104.129.15.230 (US)`，连续 3/3 成功，且带自愈。

## 一、为什么直接跑 Tor 失败

1. **Tor Browser 自带内核太旧**
   `org.torproject.torbrowser` 14.5.7 的 `lib/arm64-v8a/libTor.so` 是 **0.4.8.17**，
   连上目录服务器后报：
   ```
   At least one protocol listed as required in the consensus is not supported by this
   version of Tor. The missing protocols are: Desc=3 Microdesc=3
   ```
   → 0.4.8 已被 Tor 网络淘汰。
2. **直连引导卡 10%**
   ```
   Bootstrapped 10% (conn_done)
   9 connections died in state handshaking (TLS) with SSL state error in HANDSHAKE
   ```
   为 TLS 被干扰，需要 obfs4 这类抗封锁传输。

## 二、关键三步

### 1) 拿到新版 Tor 内核（GitHub release 会断，走 Maven）
```bash
curl -sSL -o tor.aar \
  https://repo1.maven.org/maven2/info/guardianproject/tor-android/0.4.9.14/tor-android-0.4.9.14.aar
python3 -c "import zipfile,os;z=zipfile.ZipFile('tor.aar');open('libtor.so','wb').write(z.read('jni/arm64-v8a/libtor.so'));os.chmod('libtor.so',0o755)"
./libtor.so --version     # Tor version 0.4.9.14
```
- GitHub release 资产下载在本环境反复截断（3–18MB 断），**Maven 稳定**。
- Android 上要放在**可执行目录**（app 私有 home），`/storage/emulated/0` 是 noexec。

### 2) 拿 obfs4 桥（GitHub 镜像 + jsdelivr）
```bash
# 仓库：Delta-Kronecker/Tor-Bridges-Collector（每日更新，含 *_tested.txt）
curl -sSL -o obfs4_tested.txt \
  https://fastly.jsdelivr.net/gh/Delta-Kronecker/Tor-Bridges-Collector@main/bridge/obfs4_tested.txt
# 496 条已测桥；其它文件：obfs4.txt / webtunnel.txt / snowflake.txt / vanilla_tested.txt
```
传输插件用 **Tor Browser APK 里的 `libLyrebird.so`**（obfs4 + webtunnel，本身可直接执行）。

### 3) torrc（14 条桥 + Lyrebird）
```
SocksPort 9075
DataDirectory <dir>/dataW
Log notice file <dir>/torW.log
UseBridges 1
ClientTransportPlugin obfs4 exec <dir>/libLyrebird.so
Bridge obfs4 100.8.170.63:50164 FBA3... cert=... iat-mode=0
...（再 13 条）
```
启动后：
```
Bootstrapped 75% (enough_dirinfo) → 90% (ap_handshake_done) → 100% (done)
```
SOCKS 在 `127.0.0.1:9075`，出口 `109.70.100.14`（IsTor=true），pubg/discord 均 200。

### 4) 链式代理：Tor 前置 → 目标节点
mihomo（Clash.Meta，Android arm64 PIE 版）配置：
```yaml
proxies:
  - {name: tor, type: socks5, server: 127.0.0.1, port: 9075, udp: false}
  - name: us-east
    type: vless
    server: 104.21.65.253      # 域名被 fake-ip 劫持时改用 DoH 解析出的真实 IP
    port: 2086
    uuid: xxxx
    network: ws
    ws-opts: {path: /, headers: {Host: colocrossingusa.886121.cyou}}
    dialer-proxy: tor          # ★ 关键：让该节点经由 Tor 出网
rules: [MATCH,us-east]
```
实测出口：`104.129.15.230 / loc=US / IPv4`，`pubgmobile` 9/10。

## 三、稳定性（重要经验）

| 现象 | 原因 | 对策 |
|---|---|---|
| 连发 20 次后 SOCKS 全 000，日志 `Failed to find node for hop #1` | Tor 被请求洪水打垮/Circuit 被丢弃 | **请求间隔 ≥2s**，不要并发压测 |
| 引导成功但建不了电路 | 桥过期 | **轮换桥**：从 496 条里随机抽 14 条重开 |
| 链路指向旧 Tor 实例 | Tor 重启后 mihomo 仍缓存旧连接 | Tor 恢复后**重启 mihomo** |

自愈守护（watchdog）逻辑：
```
每 60s：
  检查 Tor SOCKS 能否访问目标站点
    不通 → 随机抽 14 条桥生成新 torrc → 重启 Tor → 等 90s
  检查链路出口是否 loc=US
    不是 → 重启 mihomo
```

## 四、给 v2rayNG 用

`ws` 明文节点会被 v2rayNG（Xray 26.2.6+）直接拒绝：
> 当前节点使用未加密连接…此类节点无法使用 26.2.6+ 版本的 Xray 核心连接。

解法：**不要让 v2rayNG 直连该节点**，而是让它连本机 HTTP 代理：
```
v2rayNG → + → Add [HTTP] → 127.0.0.1 : 11096
```
（mihomo 的 mixed-port；本机到本机是环回，不触发明文检测。）

## 五、踩坑清单
1. `pkill -f <关键词>` 会杀掉自己的 shell（脚本正文含关键词）→ 只按 `argv[0]` 精确匹配。
2. 僵尸 `mihomo`（argv[0]=`./mihomo`）占端口会让所有测量变成"直连结果"→ 用 `/proc/<pid>/cmdline` 核对。
3. Cloudflare fake-IP 环境下 DNS 返回 `198.18.x.x`，导致 mihomo 解析失败 → 用 DoH（`cloudflare-dns.com/dns-query`）解析真实 IP 后写死。
4. `am start -d 'v2rayng://install-config?url=…'` 需要 **percent-encode 三次**。
5. Android bionic 上 IG5 不可用（需 ARM64 glibc rootfs）；静态分析用 `strings` + 正则就够定位问题域。
