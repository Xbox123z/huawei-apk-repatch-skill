# CASE-08：腾讯游戏「区域限制」逆向 + 免费代理不可行性实证

> 实战来源：Huawei CLS-AL00（HarmonyOS 4.3 / Android 12 / 无 root），PUBG Mobile 国际版
> `com.tencent.ig` 注册被拒（"所在国家不可注册"），目标是找到能让注册通过的美国出口。

## 一、先说结论（省时间）

1. **区域判定由客户端字段决定，不是纯 IP**：`libINTLCompliance.so` 把
   `country`（来自 locale）、`lang_type`、`time_limit_time_zone` 上报给
   `minorcer/get_region_config`，服务端据此下发区域配置（含开放哪些登录渠道）。
   → 改设备字段（locale/timezone）比折腾代理更接近根因。
2. **免费公共代理不可用于游戏登录**：实测美国上游成功率 3/10、单次成功耗时 8–10 秒；
   连续多次请求全成功概率 <1%。数据见下文。
3. **免费 V2Ray 节点池里的"美国节点"基本都是死的**：300,249 条池子抽样复测
   （干净端口、逐节点新建实例）存活 0；此前看到的 `104.28.x` 出口是**本机直连出口**
   （僵尸 mihomo 用 DIRECT 配置占着测试端口），不是节点出口。

## 二、可复用的静态分析方法

```bash
# 1) 合规库关键串（不用 IDA，strings+正则足够定位问题域）
python3 - <<'PY'
import re
d=open('libINTLCompliance.so','rb').read()
for m in re.finditer(rb'[\x20-\x7e]{5,}', d):
    s=m.group(0).decode('latin1')
    if any(k in s.lower() for k in ('region','country','time_zone','lang_type')):
        print(s[:120])
PY
```
命中样例：
```
minorcer/get_region_config
minorcer/change_region
%s?appid=%s&sandbox=%s&zoneid=%s&pf=%s&openid=%s&productid=%s&country=%s&currency_type=%s&app_metadata=%s
getDeviceLanguage
country_code_ / time_limit_time_zone_ / &lang_type=
Change region and clear cache.
```

## 三、设备字段怎么改（无 root）

| 目标 | 命令 | 备注 |
|---|---|---|
| 时区 | `adb shell "service call alarm 3 s16 America/Los_Angeles"` | **`setprop persist.sys.timezone` 会被 SELinux 拒**，走 AlarmManager binder 调用才成 |
| 防回弹 | `settings put global auto_time_zone 0` | 否则联网后自动同步回本地时区 |
| 语言 | `settings put system system_locales en-US` | `persist.sys.locale` 改不动（SELinux），但 App 读的是 system_locales |
| 校验 | `date` / `getprop persist.sys.timezone` | 必须读回确认 |

⚠️ 三项都要有**回滚脚本**（本项目：`鹿/restore_region.sh`），且改完立刻校验。

## 四、免费代理实测数据（决定"不值得再试"）

| 指标 | 数据 |
|---|---|
| 免费 V2Ray 池 | 300,249 条 → 抽样复测存活 **0** |
| 公共 SOCKS5 候选 | 12,965 测完存活 **26（0.2%）**，全非 CF |
| 美国住宅代理 | 10 次测 **3 次成功**，成功耗时 8–10s |
| 同批代理 15 分钟后 | **全部失效**（免费代理寿命以分钟计） |
| 连续 5 次请求全成功概率 | ≈ 0.3⁵ ≈ **0.24%** |

结论：游戏 OAuth 需要连续多次请求，免费代理的稳定性差 2–3 个数量级。

## 五、代理池保活架构（可复用）

```
~/httpwrap/
  poolkeeper.py   # 每 2 分钟：复核池内节点、淘汰死的、从 2.2 万候选补新
  pool_us.txt     # 出口国别=US 的节点（用 cloudflare trace loc= 校验，不能只看入口 ASN）
  pool.txt        # 通用池
  pool.js         # 读取池、失败降权（markBad/markGood）
  proxy2.js       # HTTP CONNECT 代理 → 上游 SOCKS5（socks5h 远程 DNS），顺序尝试、先通者胜
```
关键经验：
- **判断出口国别必须用 `https://www.cloudflare.com/cdn-cgi/trace` 的 `loc=`**，
  只看入口 IP 的 ASN 会把"入口在美国、出口在别国"的网关误判成美国。
- **等待时间要放松**：美国上游首包 8–10 秒，超时设 3.5s 会全判死；设 9s 才测得出来。
- **不要用并发抢答**：会优先选到快但错的节点；顺序尝试 + 池文件排序（US 优先）更可控。

## 六、踩过的坑（血泪）

1. `pkill -f <关键词>` / 按整个 cmdline 匹配会**杀掉自己的 shell**（脚本里含关键词）。→ 只按 `argv[0]` 精确匹配，并排除自身 PID。
2. 僵尸进程会**污染所有测量**：按 `NAME` 过滤 `ps` 不可靠（`./mihomo` 显示为 `mihomo` 也可能漏），
   要用 `/proc/<pid>/cmdline` 精确匹配。发现"所有节点出口都一样"时，**先怀疑端口被旧实例占用**。
3. `am start -d 'v2rayng://install-config?url=…'` 需要 **percent-encode 三次**（am 解一层 + Uri 解一层 + App 内 URLDecoder 解一层）。
4. v2rayNG **不支持 `socks://` 分享链接**（dex 里出现只是网络库常量），手动 `Add [SOCKS]` 能填但连上后全黑洞；改用 `Add [HTTP]` 指向本机 HTTP CONNECT 代理可行。
5. 腾讯 Mars xlog 是 **压缩+加密**（magic 0x08/0x09），无 RSA 私钥不可解；UE4 明文日志权限 `-rw-------`，shell 读不到。

## 七、最后一条判断

如果目标平台要求"干净住宅 IP"，**免费方案不存在**（这是实测数据，不是没找到）。
可选：付费住宅代理（按 GB）、借用干净网络、或改玩国服。
