#!/usr/bin/env python3
"""独立校验 (split) APK 的 v1+v2 签名。用法: python3 verify_apk.py a.apk [b.apk ...]"""
import struct, hashlib, zipfile, sys

def lp(b,o):
    n,=struct.unpack_from('<I',b,o); return b[o+4:o+4+n], o+4+n

def check_v2(path):
    raw=open(path,'rb').read(); ONE_MB=1024*1024
    e=raw.rfind(b'PK\x05\x06'); cd=struct.unpack_from('<I',raw,e+16)[0]
    if raw[cd-16:cd]!=b'APK Sig Block 42': return 'v2: NO BLOCK'
    S=struct.unpack_from('<Q',raw,cd-24)[0]; bs=cd-8-S
    if struct.unpack_from('<Q',raw,bs)[0]!=S: return 'v2: BAD BLOCK SIZE'
    p=bs+8; pairs={}
    while p<cd-24:
        psz=struct.unpack_from('<Q',raw,p)[0]; pid=struct.unpack_from('<I',raw,p+8)[0]
        pairs[pid]=raw[p+12:p+8+psz]; p+=8+psz
    if 0x7109871a not in pairs: return 'v2: no pair'
    v2=pairs[0x7109871a]
    signer=lp(lp(v2,0)[0],0)[0]
    sd,o2=lp(signer,0)
    rec=lp(lp(sd,0)[0],0)[0]
    algo,=struct.unpack_from('<I',rec,0); dig=lp(rec,4)[0]
    se=lp(lp(signer,o2)[0],0)[0]
    salgo,=struct.unpack_from('<I',se,0)
    hs=[]
    A=raw[:bs]; B=raw[cd:e]; C=bytearray(raw[e:]); struct.pack_into('<I',C,16,bs)
    for s in (A,B,bytes(C)):
        for i in range(0,len(s),ONE_MB):
            c=s[i:i+ONE_MB]; hs.append(hashlib.sha256(b'\xa5'+struct.pack('<I',len(c))+c).digest())
    d2=hashlib.sha256(b'\x5a'+struct.pack('<I',len(hs))+b''.join(hs)).digest()
    return f"v2: algo_match={algo==salgo}(0x{algo:x}/0x{salgo:x}) digest={'OK' if d2==dig else 'FAIL'}"

def check_v1(path):
    z=zipfile.ZipFile(path)
    if 'META-INF/MANIFEST.MF' not in z.namelist(): return 'v1: NONE'
    mf=z.read('META-INF/MANIFEST.MF').decode()
    secs={}
    for chunk in mf.split('\r\n\r\n'):
        if 'Name: ' not in chunk or 'SHA-256-Digest: ' not in chunk: continue
        phys=[]
        for ln in chunk.split('\r\n'):
            if ln.startswith(' ') and phys: phys[-1]+=ln[1:]
            else: phys.append(ln)
        kv={}
        for ln in phys:
            k,_,v=ln.partition(': '); kv[k]=v
        if 'Name' in kv and 'SHA-256-Digest' in kv: secs[kv['Name']]=kv['SHA-256-Digest']
    def b64h(b): return __import__('base64').b64encode(hashlib.sha256(b).digest()).decode()
    names=[n for n in z.namelist() if not n.startswith('META-INF/') and not n.endswith('/')]
    missing=[n for n in names if n not in secs]
    bad=[n for n in names if n in secs and b64h(z.read(n))!=secs[n]]
    return f'v1: files={len(names)} covered={len(secs)} missing={len(missing)} baddigest={len(bad)}'

for p in sys.argv[1:]:
    print(p.split('/')[-1], '|', check_v1(p), '|', check_v2(p))
