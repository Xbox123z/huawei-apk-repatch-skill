import zipfile, struct, zlib, os

SRC='/data/user/0/com.dsharnessmobile.shell/files/home/grok_xapk/extracted/'
OUT='g50-unsigned.apk'
PATCHED_DEX='p50_classes.dex'

def read_local(zpath):
    raw=open(zpath,'rb').read()
    z=zipfile.ZipFile(zpath); out=[]
    for info in z.infolist():
        lh=info.header_offset
        sig,ver,fl,meth,t,d,crc,csz,usz,nl,el=struct.unpack_from('<IHHHHHIIIHH',raw,lh)
        name=raw[lh+30:lh+30+nl].decode('utf-8')
        doff=lh+30+nl+el
        out.append(dict(name=name,method=info.compress_type,data=raw[doff:doff+info.compress_size],
                        crc=info.CRC,usize=info.file_size,date=info.date_time,extattr=info.external_attr))
    return out

def parse_strings(axml):
    off=8
    sp_size,=struct.unpack_from('<I',axml,off+4)
    str_count,=struct.unpack_from('<I',axml,off+8)
    flags,=struct.unpack_from('<I',axml,off+16)
    str_off,=struct.unpack_from('<I',axml,off+20)
    utf8=(flags&0x100)!=0
    offs=struct.unpack_from('<%dI'%str_count,axml,off+28)
    ss=[]
    for i in range(str_count):
        p=off+str_off+offs[i]
        if utf8:
            n=axml[p]; p2=p+1
            if n&0x80: p2+=1
            blen=axml[p2]; p2+=1
            if blen&0x80: blen=((blen&0x7f)<<8)|axml[p2]; p2+=1
            ss.append(axml[p2:p2+blen].decode('utf-8','replace'))
        else:
            n,=struct.unpack_from('<H',axml,p)
            if n&0x8000:
                n=((n&0x7fff)<<16)|struct.unpack_from('<H',axml,p+2)[0]; p+=4
            else: p+=2
            ss.append(axml[p:p+n*2].decode('utf-16-le','replace'))
    return off+sp_size, ss

entries=read_local(SRC+'ai.x.grok.apk')
man=next(e for e in entries if e['name']=='AndroidManifest.xml')
axml=zlib.decompressobj(-15).decompress(man['data'])
after,strs=parse_strings(axml)
p=after; found=[]
while p+8<=len(axml):
    c_type,c_hdr,c_size=struct.unpack_from('<HHI',axml,p)
    if c_type==0x0102:
        ni=struct.unpack_from('<I',axml,p+20)[0]
        el=strs[ni]
        ac,=struct.unpack_from('<H',axml,p+28)
        for a in range(ac):
            ap=p+36+a*20
            an=struct.unpack_from('<I',axml,ap+4)[0]
            at,ad=struct.unpack_from('<BI',axml,ap+15)
            if el=='uses-sdk' and strs[an]=='minSdkVersion' and at==0x10 and ad==32:
                found.append(ap+16)
    if c_size==0: break
    p+=c_size
assert len(found)==1, found
patched=bytearray(axml)
struct.pack_into('<I', patched, found[0], 31)
co=zlib.compressobj(9,zlib.DEFLATED,-15)
mdata=co.compress(bytes(patched))+co.flush()
mcrc=zlib.crc32(bytes(patched))&0xffffffff
print('manifest minSdk 32->31 ok')

newdex=open(PATCHED_DEX,'rb').read()
def dosdate(dt):
    y,mo,da,h,mi,s=(dt if len(dt)==6 else (*dt,0))[:6]
    return ((h<<11)|(mi<<5)|(s//2)), (((max(y,1980)-1980)<<9)|(mo<<5)|da)

out_entries=[]
def add(name,method,data,usize,dt,extattr,crc):
    out_entries.append((name.encode(),method,data,usize,dt,extattr,crc))
add(man['name'],8,mdata,len(axml),man['date'],man['extattr'],mcrc)
arsc=next(e for e in entries if e['name']=='resources.arsc')
add('resources.arsc',0,arsc['data'],arsc['usize'],arsc['date'],arsc['extattr'],arsc['crc'])
for e in entries:
    if e['name'] in ('AndroidManifest.xml','resources.arsc','stamp-cert-sha256'): continue
    if e['name']=='classes.dex':
        add('classes.dex',0,newdex,len(newdex),e['date'],e['extattr'],zlib.crc32(newdex)&0xffffffff)
    else:
        add(e['name'],e['method'],e['data'],e['usize'],e['date'],e['extattr'],e['crc'])
# arm64 库
for e in read_local(SRC+'config.arm64_v8a.apk'):
    if e['name'] in ('AndroidManifest.xml','stamp-cert-sha256'): continue
    add(e['name'],0,e['data'],e['usize'],e['date'],e['extattr'],e['crc'])
# mdpi 资源
for e in read_local(SRC+'config.mdpi.apk'):
    if e['name'] in ('AndroidManifest.xml','resources.arsc','stamp-cert-sha256'): continue
    add(e['name'],e['method'],e['data'],e['usize'],e['date'],e['extattr'],e['crc'])
libs=[x for x in out_entries if x[0].startswith(b'lib/')]
print('entries:', len(out_entries), 'libs:', len(libs))

f=open(OUT,'wb'); cd=bytearray(); off=0
for name,method,data,usize,dt,extattr,crc in out_entries:
    if method==0 and name.endswith(b'.so'): align=4096
    elif name==b'resources.arsc': align=4
    else: align=1
    t,d=dosdate(dt)
    pad=(-(off+30+len(name)))%align
    extra=b'\x00'*pad if pad else b''
    lh=struct.pack('<IHHHHHIIIHH',0x04034b50,20,0,method,t,d,crc,len(data),usize,len(name),len(extra))
    f.write(lh+name+extra+data)
    lo=off; off+=len(lh)+len(name)+len(extra)+len(data)
    cdh=struct.pack('<IHHHHHHIIIHHHHHII',0x02014b50,0,20,0,method,t,d,crc,len(data),usize,
                    len(name),len(extra),0,0,0,extattr,lo)
    cd+=cdh+name+extra
cd_off=off; f.write(bytes(cd))
f.write(struct.pack('<IHHHHIIH',0x06054b50,0,0,len(out_entries),len(out_entries),len(cd),cd_off,0))
f.close()
assert zipfile.ZipFile(OUT).testzip() is None
print('built', OUT, os.path.getsize(OUT))
