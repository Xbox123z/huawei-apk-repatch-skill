#!/usr/bin/env python3
"""XAPK / split-APK 套装重建器：对每个 split 就地打 AXML minSdk 补丁，保留 META-INF/services，
按 Android 对齐要求重建 zip（供后续 v1+v2 重签）。

用法:
  python3 rebuild_splits.py <in.xapk|in-dir> <out-dir> [--from N --to M] [--abi arm64-v8a]

要点（都是踩过的坑）:
  * 每个 split 的 AndroidManifest.xml 都有自己的 minSdk，**全部都要改**，漏一个 commit 时报
    INSTALL_FAILED_OLDER_SDK
  * 只删签名三件套 (.RSA/.DSA/.EC/.SF/.MF) 和 stamp-cert-sha256；
    **META-INF/services/* 必须保留**，删了会 "Module with the Main dispatcher is missing"
  * 对齐：lib/**/*.so -> 4096；resources.arsc -> 4；其余 STORE 条目 -> 8
    （RN/Hermes 的 assets/index.android.bundle 靠 mmap，mod8!=0 会 "Compiling JS failed: Buffer misaligned."）
  * 本脚本只产出「未签名」包，必须再跑 add_v1.py + sign_v2.js；
    注意 add_v1.py 会重写整个 zip，其对齐规则必须与本脚本一致，否则前面的对齐白做
"""
import json
import os
import struct
import sys
import zipfile
import zlib

SIG_SUFFIX = ('.RSA', '.DSA', '.EC', '.SF', '.MF')


# ---------- AXML ----------
def axml_strings(a):
    off = 8
    sp_size, = struct.unpack_from('<I', a, off + 4)
    str_count, = struct.unpack_from('<I', a, off + 8)
    flags, = struct.unpack_from('<I', a, off + 16)
    str_off, = struct.unpack_from('<I', a, off + 20)
    utf8 = (flags & 0x100) != 0
    offs = struct.unpack_from('<%dI' % str_count, a, off + 28)
    ss = []
    for i in range(str_count):
        p = off + str_off + offs[i]
        if utf8:
            n = a[p]
            p2 = p + 1
            if n & 0x80:
                p2 += 1
            blen = a[p2]
            p2 += 1
            if blen & 0x80:
                blen = ((blen & 0x7F) << 8) | a[p2]
                p2 += 1
            ss.append(a[p2:p2 + blen].decode('utf-8', 'replace'))
        else:
            n, = struct.unpack_from('<H', a, p)
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from('<H', a, p + 2)[0]
                p += 4
            else:
                p += 2
            ss.append(a[p:p + n * 2].decode('utf-16-le', 'replace'))
    return off + sp_size, ss


def patch_axml_minsdk(axml, from_ver, to_ver):
    """把 uses-sdk/minSdkVersion 的整数值从 from_ver 改成 to_ver。返回 (新字节, 改动数)。"""
    after, strs = axml_strings(axml)
    p = after
    found = []
    while p + 8 <= len(axml):
        c_type, c_hdr, c_size = struct.unpack_from('<HHI', axml, p)
        if c_type == 0x0102:  # START_ELEMENT
            ni, = struct.unpack_from('<I', axml, p + 20)
            if strs[ni] == 'uses-sdk':
                ac, = struct.unpack_from('<H', axml, p + 28)
                for i in range(ac):
                    ap = p + 36 + i * 20
                    an, = struct.unpack_from('<I', axml, ap + 4)
                    dt, dv = struct.unpack_from('<BI', axml, ap + 15)
                    # 0x10 = TYPE_INT_DEC；必须按属性名匹配，同值可能出现在 maxSdkVersion 上
                    if strs[an] == 'minSdkVersion' and dt == 0x10 and dv == from_ver:
                        found.append(ap + 16)
        if c_size == 0:
            break
        p += c_size
    if not found:
        return axml, 0
    out = bytearray(axml)
    for o in found:
        struct.pack_into('<I', out, o, to_ver)
    return bytes(out), len(found)


# ---------- zip ----------
def read_local(zpath):
    """按 local header 原始字节读出条目（保留原 compress_type，不走 zipfile 解压再压）。"""
    raw = open(zpath, 'rb').read()
    out = []
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            lh = info.header_offset
            nlh, elh = struct.unpack_from('<HH', raw, lh + 26)
            doff = lh + 30 + nlh + elh
            out.append(dict(name=info.filename, method=info.compress_type,
                            data=raw[doff:doff + info.compress_size], crc=info.CRC,
                            usize=info.file_size, date=info.date_time,
                            extattr=info.external_attr))
    return out


def dosdate(dt):
    y, mo, da, h, mi, s = (dt if len(dt) == 6 else (*dt, 0))[:6]
    return ((h << 11) | (mi << 5) | (s // 2)), (((max(y, 1980) - 1980) << 9) | (mo << 5) | da)


def align_for(name, method):
    nb = name.encode()
    if method == 0 and nb.endswith(b'.so'):
        return 4096
    if nb == b'resources.arsc':
        return 4
    if method == 0:
        return 8          # 所有 STORE 条目（Hermes mmap 要求）
    return 1


def write_aligned(entries, dst):
    f = open(dst, 'wb')
    cd = bytearray()
    off = 0
    for name, method, data, usize, dt, extattr, crc in entries:
        nb = name.encode()
        t, d = dosdate(dt)
        pad = (-(off + 30 + len(nb))) % align_for(name, method)
        extra = b'\x00' * pad
        lh = struct.pack('<IHHHHHIIIHH', 0x04034b50, 20, 0, method, t, d,
                         crc, len(data), usize, len(nb), len(extra))
        f.write(lh + nb + extra + data)
        lo = off
        off += len(lh) + len(nb) + len(extra) + len(data)
        cdh = struct.pack('<IHHHHHHIIIHHHHHII', 0x02014b50, 0, 20, 0, method, t, d,
                          crc, len(data), usize, len(nb), len(extra), 0, 0, 0, extattr, lo)
        cd += cdh + nb + extra
    f.write(bytes(cd))
    f.write(struct.pack('<IHHHHIIH', 0x06054b50, 0, 0, len(entries), len(entries), len(cd), off, 0))
    f.close()
    assert zipfile.ZipFile(dst).testzip() is None


def rebuild_one(src, dst, from_ver, to_ver, dex_replace=None):
    entries = read_local(src)
    man = next((e for e in entries if e['name'] == 'AndroidManifest.xml'), None)
    arsc = next((e for e in entries if e['name'] == 'resources.arsc'), None)
    dexes = [e for e in entries if e['name'].endswith('.dex')]
    special = set(id(e) for e in ([man] if man else []) + ([arsc] if arsc else []) + dexes)

    out = []
    nch = 0
    if man:
        axml = zlib.decompressobj(-15).decompress(man['data'])
        patched, nch = patch_axml_minsdk(axml, from_ver, to_ver)
        co = zlib.compressobj(9, zlib.DEFLATED, -15)
        mdata = co.compress(patched) + co.flush()
        out.append((man['name'], 8, mdata, len(axml), man['date'], man['extattr'],
                    zlib.crc32(patched) & 0xffffffff))
    if arsc:
        out.append((arsc['name'], 0, arsc['data'], arsc['usize'], arsc['date'], arsc['extattr'], arsc['crc']))
    for e in dexes:
        if dex_replace and e['name'] in dex_replace:
            nd = dex_replace[e['name']]
            out.append((e['name'], e['method'], nd, len(nd), e['date'], e['extattr'],
                        zlib.crc32(nd) & 0xffffffff))
        else:
            out.append((e['name'], e['method'], e['data'], e['usize'], e['date'], e['extattr'], e['crc']))
    for e in entries:
        if id(e) in special or e['name'] == 'stamp-cert-sha256':
            continue
        if e['name'].startswith('META-INF/') and e['name'].endswith(SIG_SUFFIX):
            continue
        out.append((e['name'], e['method'], e['data'], e['usize'], e['date'], e['extattr'], e['crc']))

    write_aligned(out, dst)
    kept = sum(1 for n, *_ in out if n.startswith('META-INF/services'))
    print('  %-22s -> %-26s %9d B  minSdk x%d  services kept=%d' %
          (os.path.basename(src), os.path.basename(dst), os.path.getsize(dst), nch, kept))
    return nch


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(2)
    src, outdir = sys.argv[1], sys.argv[2]
    args = sys.argv[3:]
    def opt(name, default=None):
        for i, a in enumerate(args):
            if a == name and i + 1 < len(args):
                return args[i + 1]
        return default
    from_ver = int(opt('--from', 32))
    to_ver = int(opt('--to', 31))
    os.makedirs(outdir, exist_ok=True)

    total = 0
    if src.endswith('.xapk') or zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            manifest = json.loads(z.read('manifest.json'))
            tmp = os.path.join(outdir, '_extract')
            os.makedirs(tmp, exist_ok=True)
            plan = []
            for s in manifest['split_apks']:
                p = os.path.join(tmp, os.path.basename(s['file']))
                with open(p, 'wb') as w:
                    w.write(z.read(s['file']))
                outname = ('base.apk' if s['id'] == 'base'
                           else 'cfg-' + s['id'].replace('config.', '') + '.apk')
                plan.append((p, os.path.join(outdir, outname)))
            for p, o in plan:
                total += rebuild_one(p, o, from_ver, to_ver)
        print('OK: %d splits rebuilt (minSdk %d -> %d). 下一步: add_v1.py + sign_v2.js 逐个重签'
              % (len(plan), from_ver, to_ver))
    else:
        plan = []
        for fn in sorted(os.listdir(src)):
            if not fn.endswith('.apk'):
                continue
            outname = ('base.apk' if 'base' in fn.lower() else
                       'cfg-' + fn.replace('.apk', '') + '.apk')
            plan.append((os.path.join(src, fn), os.path.join(outdir, outname)))
        for p, o in plan:
            total += rebuild_one(p, o, from_ver, to_ver)
        print('OK: %d apks rebuilt (minSdk %d -> %d)' % (len(plan), from_ver, to_ver))

    if total == 0:
        print('⚠️ 没有任何 split 被改动：确认 --from 是否等于包的真实 minSdk（用 AXML 解析，别信 manifest.json）')


if __name__ == '__main__':
    main()
