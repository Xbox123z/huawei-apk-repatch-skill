"""最小 dex 编辑器：把指定类的指定方法体替换为 [调用给定方法 + return]，原地填充 nop。"""
import struct, sys

class Dex:
    def __init__(self, data):
        self.d = bytearray(data)
        h = self.d
        assert h[:8] == b'dex\n035\x00' or h[:4]==b'dex\n', 'not dex'
        (self.string_ids_size, self.string_ids_off,
         self.type_ids_size, self.type_ids_off,
         self.proto_ids_size, self.proto_ids_off,
         self.field_ids_size, self.field_ids_off,
         self.method_ids_size, self.method_ids_off,
         self.class_defs_size, self.class_defs_off) = struct.unpack_from('<12I', h, 0x38)
        self.endian = struct.unpack_from('<I', h, 0x28)[0]
        assert self.endian == 0x12345678

    def uleb(self, off):
        r=0; shift=0
        while True:
            b=self.d[off]; off+=1
            r |= (b & 0x7f) << shift
            if not (b & 0x80): break
            shift += 7
        return r, off

    def string(self, idx):
        off, = struct.unpack_from('<I', self.d, self.string_ids_off + idx*4)
        n, off = self.uleb(off)
        return self.d[off:off+n].split(b'\x00')[0].decode('utf-8','replace')

    def find_string(self, s):
        b=s.encode()
        for i in range(self.string_ids_size):
            off, = struct.unpack_from('<I', self.d, self.string_ids_off + i*4)
            n, off2 = self.uleb(off)
            if n==len(b) and self.d[off2:off2+n]==b:
                return i
        return None

    def type_desc(self, type_idx):
        sidx, = struct.unpack_from('<I', self.d, self.type_ids_off + type_idx*4)
        return self.string(sidx)

    def find_type(self, desc):
        for i in range(self.type_ids_size):
            if self.type_desc(i)==desc: return i
        return None

    def method_at(self, midx):
        cidx, pidx, nidx = struct.unpack_from('<HHI', self.d, self.method_ids_off + midx*8)
        return self.type_desc(cidx), self.string(nidx)

    def class_def(self, type_idx):
        for i in range(self.class_defs_size):
            base = self.class_defs_off + i*32
            c, acc, sup, ifo, sfi, afo, cdo, svo = struct.unpack_from('<8I', self.d, base)
            if c == type_idx:
                return base, cdo
        return None, None

    def iter_methods(self, class_data_off):
        """yield (method_idx, access, code_off)"""
        if class_data_off == 0: return
        off = class_data_off
        sf, off = self.uleb(off); if_, off = self.uleb(off)
        dm, off = self.uleb(off); vm, off = self.uleb(off)
        for _ in range(sf+if_):  # fields skip
            _, off = self.uleb(off); _, off = self.uleb(off)
        midx = 0
        for _ in range(dm):
            d, off = self.uleb(off); midx += d
            acc, off = self.uleb(off)
            co, off = self.uleb(off)
            yield midx, acc, co
        midx = 0
        for _ in range(vm):
            d, off = self.uleb(off); midx += d
            acc, off = self.uleb(off)
            co, off = self.uleb(off)
            yield midx, acc, co

    def patch_method_to_call(self, code_off, call_midx, is_static=False, extra_ret=None):
        """把 code_item 指令区替换为: invoke-{virtual,static} {v0}, call; [move-result 若需要]; return[-void]，其余 nop。
        要求原指令区 >= 所需 u16 数。registers/ins/outs 保留原值（≥需要即可）。"""
        if code_off == 0: return False
        ins_size, outs_size, tries_size = struct.unpack_from('<HHH', self.d, code_off+2)
        insn_size, = struct.unpack_from('<I', self.d, code_off+12)  # in code units (u16)
        if tries_size: 
            # debug/try 区在指令后，替换指令区不影响 tries 结构？为安全要求无 tries
            pass
        body = code_off + 16
        ops = []
        invoke_op = 0x71 if is_static else 0x6e
        ops.append((1<<12) | invoke_op)   # 5c: A=1 (arg count)
        ops.append(call_midx & 0xffff)
        ops.append(0x0000)                # DCBA: D=v0 (p0=this)
        if extra_ret is not None:
            ops.append(0x000a | (0<<8))   # move-result v0 (op 0x0a, AA=0) -> 0x000a
            ops.append(extra_ret)
        ops.append(0x000e if extra_ret is None else 0x000f)  # return-void / return v0
        if len(ops) > insn_size: return False
        # 写指令 + nop 填充
        for i,u in enumerate(ops):
            struct.pack_into('<H', self.d, body + i*2, u)
        for i in range(len(ops), insn_size):
            struct.pack_into('<H', self.d, body + i*2, 0x0000)  # nop
        return True

    def fix_checksums(self):
        import hashlib, zlib
        # sha1 signature over everything after offset 32
        sig = hashlib.sha1(bytes(self.d[32:])).digest()
        self.d[12:12+20] = sig
        csum = zlib.adler32(bytes(self.d[12:])) & 0xffffffff
        struct.pack_into('<I', self.d, 8, csum)

def main():
    dex = Dex(open(sys.argv[1],'rb').read())
    # 目标类/方法
    target_cls = 'Lcom/pairip/licensecheck/LicenseActivity;'
    target_m   = 'onCreate'
    tidx = dex.find_type(target_cls)
    print('type_idx:', tidx)
    base, cdo = dex.class_def(tidx)
    # 找 android.app.Activity->finish 的 method id
    finish_idx = None; fin2=None
    for i in range(dex.method_ids_size):
        c, n = dex.method_at(i)
        if c=='Landroid/app/Activity;' and n=='finish':
            finish_idx=i; break
    print('Activity.finish midx:', finish_idx)
    if finish_idx is None:
        # 兜底：任何类的 finish()V
        for i in range(dex.method_ids_size):
            c, n = dex.method_at(i)
            if n=='finish':
                finish_idx=i; print('fallback finish from', c); break
    done=False
    for midx, acc, co in dex.iter_methods(cdo):
        if midx >= dex.method_ids_size: break
        c, n = dex.method_at(midx)
        if n==target_m:
            ok = dex.patch_method_to_call(co, finish_idx)
            print(f'patched {c}->{n} code_off={hex(co)} ok={ok}')
            done = ok
    if not done:
        print('FAILED to patch'); sys.exit(1)
    dex.fix_checksums()
    open(sys.argv[2],'wb').write(dex.d)
    print('wrote', sys.argv[2])

main()
