#!/usr/bin/env python3
"""PairIP/AppDetex 一键拆锁：对包含 LicenseActivity/LicenseClient 的 dex 做方法体手术。
用法: python3 kill_pairip.py in.dex out.dex  [dexpatch.py 路径]
已验证: Grok 1.2.50 (classes.dex) / OpenBot 1.4.1 (classes2.dex)
"""
import struct, hashlib, zlib, sys, os
dppath = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(__file__), 'dexpatch.py')
ns = {}
exec(open(dppath).read().split('def main()')[0], ns)
Dex = ns['Dex']
d = Dex(open(sys.argv[1], 'rb').read())

def ret_desc(midx):
    cidx, pidx, nidx = struct.unpack_from('<HHI', d.d, d.method_ids_off + midx * 8)
    si, rt, po = struct.unpack_from('<III', d.d, d.proto_ids_off + pidx * 12)
    return d.type_desc(rt)

# --- 找 method id：super.onStart 必在；退出调用按优先级探测（R8 可能内联掉 finish）---
ids = {}
for i in range(d.method_ids_size):
    cidx, pidx, nidx = struct.unpack_from('<HHI', d.d, d.method_ids_off + i * 8)
    c, n = d.type_desc(cidx), d.string(nidx)
    if n == 'onStart' and c == 'Landroid/app/Activity;': ids['superOnStart'] = i
    if n in ('finish', 'finishAndRemoveTask') and c.endswith('LicenseActivity;'): ids.setdefault('exit', i)
    if n == 'finish' and c == 'Landroid/app/Activity;' and 'exit' not in ids: ids['exit'] = i
assert 'superOnStart' in ids, 'super.onStart not found — wrong dex?'
if 'exit' not in ids:
    print('WARN: no finish/finishAndRemoveTask — onStart 只补 super+return（授权页会多停一帧）')

def set_body(co, ops):
    insn = struct.unpack_from('<I', d.d, co + 12)[0]
    assert len(ops) <= insn, f'body too small: need {len(ops)} have {insn}'
    body = co + 16
    for i, u in enumerate(ops): struct.pack_into('<H', d.d, body + i * 2, u)
    for i in range(len(ops), insn): struct.pack_into('<H', d.d, body + i * 2, 0)

def neuter(cls_desc, names):
    tidx = d.find_type(cls_desc)
    if tidx is None: print('  cls missing:', cls_desc); return 0
    base, cdo = d.class_def(tidx)
    n = 0
    for midx, acc, co in d.iter_methods(cdo):
        c, mname = d.method_at(midx)
        if mname not in names or co == 0: continue
        ret = ret_desc(midx)
        regs, ins = struct.unpack_from('<HH', d.d, co)
        p0 = regs - ins
        if ret == 'V': ops = [0x000e]
        elif ret[0] in 'L[': ops = [(p0 << 8) | 0x12, 0, (p0 << 8) | 0x11]
        elif ret == 'Z': ops = [(p0 << 8) | 0x12, 0, (p0 << 8) | 0x0f]
        elif ret == 'J': ops = [(p0 << 8) | 0x14, 0, (p0 << 8) | 0x00, 0, (p0 << 8) | 0x15]
        else: ops = [(p0 << 8) | 0x12, 0, (p0 << 8) | 0x0f]
        set_body(co, ops); n += 1
    print(f'  neutered {n} in {cls_desc}'); return n

tidx = d.find_type('Lcom/pairip/licensecheck/LicenseActivity;')
base, cdo = d.class_def(tidx)
for midx, acc, co in d.iter_methods(cdo):
    c, n = d.method_at(midx)
    if n == 'onStart':
        regs, ins = struct.unpack_from('<HH', d.d, co)
        p0 = regs - ins
        ops = [0x106f, ids['superOnStart'], p0]
        if 'exit' in ids: ops += [0x106e, ids['exit'], p0]
        ops.append(0x000e)
        set_body(co, ops)
        print('onStart neutered (super%s; return), p0=v%d' % ('+exit' if 'exit' in ids else '', p0))
neuter('Lcom/pairip/licensecheck/LicenseActivity;',
       ['closeApp','exitApp','closeAllTasks','showErrorDialog','showPaywallAndCloseApp','logAndShowErrorDialog',
        'lambda$showErrorDialog$0','lambda$showErrorDialog$1','lambda$showPaywallAndCloseApp$0'])
neuter('Lcom/pairip/licensecheck/LicenseClient;',
       ['initializeLicenseCheck','checkLicense','checkLicenseInternal','scheduleRepeatedLicenseCheck',
        'scheduleAppShutdown','startErrorDialogActivity','startPaywallActivity','handleError',
        'bindToLicensingService','initiateFreshLicensingServiceConnection','stopTrial','handleTrialEnd',
        'lambda$initializeLicenseCheck$0','lambda$initializeLicenseCheck$1','lambda$handleError$0',
        'lambda$scheduleRepeatedLicenseCheck$0','retryOrThrow','unbindFromLicensingService',
        'createCloseAppIntentOrExitIfAppInBackground'])
sig = hashlib.sha1(bytes(d.d[32:])).digest(); d.d[12:32] = sig
struct.pack_into('<I', d.d, 8, zlib.adler32(bytes(d.d[12:])) & 0xffffffff)
open(sys.argv[2], 'wb').write(d.d)
print('wrote', sys.argv[2], len(d.d))
