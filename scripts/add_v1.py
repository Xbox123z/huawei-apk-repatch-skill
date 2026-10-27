import zipfile, struct, zlib, os, hashlib, base64, subprocess, sys, json

KEY=os.environ.get('SIGN_KEY','key.pem'); CRT=os.environ.get('SIGN_CERT','cert.pem')
CRLF='\r\n'

def wrap(line):
    out=[]; b=line.encode(); first=True
    while True:
        budget=70 if first else 69
        chunk=b[:budget]
        while len(chunk)<len(b) and (b[len(chunk)]&0xC0)==0x80: chunk=chunk[:-1]
        out.append((b'' if first else b' ')+chunk)
        b=b[len(chunk):]; first=False
        if not b: break
    return CRLF.join(x.decode() for x in out)

def dosdate(dt):
    y,mo,da,h,mi,s=(dt if len(dt)==6 else (*dt,0))[:6]
    return ((h<<11)|(mi<<5)|(s//2)), (((max(y,1980)-1980)<<9)|(mo<<5)|da)

def resign(src, dst):
    z=zipfile.ZipFile(src); raw=open(src,'rb').read()
    # 读原始数据（按 LFH 偏移）
    entries=[]
    for info in z.infolist():
        lh=info.header_offset
        nlh,elh=struct.unpack_from('<HH',raw,lh+26)
        doff=lh+30+nlh+elh
        data=raw[doff:doff+info.compress_size]
        entries.append(dict(name=info.filename, method=info.compress_type, data=data,
                            usize=info.file_size, crc=info.CRC, date=info.date_time, extattr=info.external_attr))
    # 剔除官方签名三件套 + stamp
    def is_sig(n):
        return n in ('stamp-cert-sha256',) or (n.startswith('META-INF/') and n.endswith(('.RSA','.DSA','.EC','.SF','.MF')))
    kept=[e for e in entries if not is_sig(e['name'])]
    # v1 摘要（解压内容）
    def content_of(e):
        return zlib.decompressobj(-15).decompress(e['data']) if e['method']==8 else e['data']
    mf=[];sfp=[]
    for e in kept:
        if e['name'].endswith('/'): continue
        c=content_of(e)
        d=base64.b64encode(hashlib.sha256(c).digest()).decode()
        sec=wrap(f'Name: {e["name"]}')+CRLF+wrap(f'SHA-256-Digest: {d}')+CRLF+CRLF
        mf.append(sec)
        sd=base64.b64encode(hashlib.sha256(sec.encode()).digest()).decode()
        sfp.append(wrap(f'Name: {e["name"]}')+CRLF+wrap(f'SHA-256-Digest: {sd}')+CRLF+CRLF)
    manifest=(wrap('Manifest-Version: 1.0')+CRLF+CRLF+''.join(mf)).encode()
    md=base64.b64encode(hashlib.sha256(manifest).digest()).decode()
    sf=(wrap('Signature-Version: 1.0')+CRLF+wrap('Created-By: 1.0 (Android)')+CRLF+
        wrap(f'SHA-256-Digest-Manifest: {md}')+CRLF+wrap('X-Android-APK-Signed: 2')+CRLF+CRLF+
        ''.join(sfp)).encode()
    open('_sf.tmp','wb').write(sf)
    rsa=subprocess.run(['openssl','smime','-sign','-noattr','-signer',CRT,'-inkey',KEY,'-in','_sf.tmp',
                        '-outform','DER'],capture_output=True,check=True).stdout
    # 组装（arsc/so 对齐）
    out_entries=[]
    def add(name,method,data,usize,dt,extattr,crc):
        out_entries.append((name.encode(),method,data,usize,dt,extattr,crc))
    man=next((e for e in kept if e['name']=='AndroidManifest.xml'),None)
    if man: kept.remove(man); add(man['name'],man['method'],man['data'],man['usize'],man['date'],man['extattr'],man['crc'])
    arsc=next((e for e in kept if e['name']=='resources.arsc'),None)
    if arsc: kept.remove(arsc); add(arsc['name'],0,arsc['data'],arsc['usize'],arsc['date'],arsc['extattr'],arsc['crc'])
    for e in kept: add(e['name'],e['method'],e['data'],e['usize'],e['date'],e['extattr'],e['crc'])
    add('META-INF/MANIFEST.MF',0,manifest,len(manifest),(2026,1,1,0,0,0),0,zlib.crc32(manifest)&0xffffffff)
    add('META-INF/CERT.SF',0,sf,len(sf),(2026,1,1,0,0,0),0,zlib.crc32(sf)&0xffffffff)
    add('META-INF/CERT.RSA',0,rsa,len(rsa),(2026,1,1,0,0,0),0,zlib.crc32(rsa)&0xffffffff)
    f=open(dst,'wb'); cd=bytearray(); off=0
    for name,method,data,usize,dt,extattr,crc in out_entries:
        if method==0 and name.endswith(b'.so'): align=4096
        elif name==b'resources.arsc': align=4
        elif method==0: align=8   # 所有 STORE 条目 ≥8 字节对齐：Hermes 的 index.android.bundle 靠 mmap 读，mod8!=0 会报 "Compiling JS failed: Buffer misaligned."
        else: align=1
        t,d=dosdate(dt)
        pad=(-(off+30+len(name)))%align
        extra=b'\x00'*pad
        lh=struct.pack('<IHHHHHIIIHH',0x04034b50,20,0,method,t,d,crc,len(data),usize,len(name),len(extra))
        f.write(lh+name+extra+data)
        lo=off; off+=len(lh)+len(name)+len(extra)+len(data)
        cdh=struct.pack('<IHHHHHHIIIHHHHHII',0x02014b50,0,20,0,method,t,d,crc,len(data),usize,
                        len(name),len(extra),0,0,0,extattr,lo)
        cd+=cdh+name+extra
    cd_off=off; f.write(bytes(cd))
    f.write(struct.pack('<IHHHHIIH',0x06054b50,0,0,len(out_entries),len(out_entries),len(cd),cd_off,0))
    f.close()
    zz=zipfile.ZipFile(dst); assert zz.testzip() is None
    print('resigned', dst, os.path.getsize(dst))

if __name__=='__main__':
    resign('grok99/base_patched.apk','g99s/base.apk')
    for n in ['cfg-en','cfg-zh','cfg-hdpi','cfg-armeabi_v7a']:
        resign(f'grok99/{n}.apk', f'g99s/{n}.apk')
