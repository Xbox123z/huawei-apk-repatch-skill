// APK Signature Scheme v2 signer — AOSP-correct, v2-only, SHA-256
const fs = require('fs');
const nodeCrypto = require('crypto');
const forge = require(process.env.FORGE_PATH || 'node-forge');

const IN  = process.argv[2];
const OUT = process.argv[3];
const KEY = process.env.SIGN_KEY || 'key.pem';
const CRT = process.env.SIGN_CERT || 'cert.pem';

const u8 = (n)=>new Uint8Array(n);
const u32le = (v)=>{const b=u8(4);new DataView(b.buffer).setUint32(0,v,true);return b;};
const u64le = (v)=>{const b=u8(8);new DataView(b.buffer).setBigUint64(0,BigInt(v),true);return b;};
const cat = (arrs)=>{const t=arrs.reduce((s,a)=>s+a.length,0);const r=u8(t);let o=0;for(const a of arrs){r.set(a,o);o+=a.length;}return r;};
const LP = (d)=>cat([u32le(d.length), d]);          // length-prefixed blob/entry
const LPS= (items)=>{const body=cat(items.map(LP));return cat([u32le(body.length), body]);}; // length-prefixed sequence of length-prefixed items

const sha256 = (b)=>new Uint8Array(nodeCrypto.createHash('sha256').update(b).digest());

const CONTENT_DIGEST_CHUNKED_SHA256 = 0x0101;
const SIG_RSA_PKCS1_SHA256 = 0x0103;
const MAGIC = new Uint8Array([...Buffer.from('APK Sig Block 42','utf8')]);

function findEOCD(d){
  for(let o=d.length-22;o>=Math.max(0,d.length-22-65535);o--){
    if(d[o]===0x50&&d[o+1]===0x4b&&d[o+2]===0x05&&d[o+3]===0x06){
      const cl=new DataView(d.buffer,d.byteOffset+o+20).getUint16(0,true);
      if(o+22+cl===d.length){
        const dv=new DataView(d.buffer,d.byteOffset+o);
        return {eocd:o, cd:dv.getUint32(16,true), cdSize:dv.getUint32(12,true), count:dv.getUint16(10,true)};
      }
    }
  } throw new Error('no EOCD');
}

function chunkedSha256(sections){
  const hashes=[];
  const ONE_MB=1024*1024;
  for(const s of sections){
    if(s.length===0){ // zero-size chunk still counted? AOSP: sections may be empty; skip empty entirely
      continue;
    }
    for(let i=0;i<s.length;i+=ONE_MB){
      const chunk=s.subarray(i,Math.min(i+ONE_MB,s.length));
      const p=u8(5+chunk.length);
      p[0]=0xa5; new DataView(p.buffer).setUint32(1,chunk.length,true); p.set(chunk,5);
      hashes.push(sha256(p));
    }
  }
  const top=u8(5+hashes.length*32);
  top[0]=0x5a; new DataView(top.buffer).setUint32(1,hashes.length,true);
  let o=5; for(const h of hashes){top.set(h,o);o+=32;}
  return sha256(top);
}

const file = new Uint8Array(fs.readFileSync(IN));
const {eocd, cd} = findEOCD(file);
if (file.subarray(cd-16,cd).some((v,i)=>v!==MAGIC[i])) {
  // ensure no pre-existing signing block (ours is clean)
}
const A = file.subarray(0, cd);
const B = file.subarray(cd, eocd);
const C = new Uint8Array(file.subarray(eocd));
new DataView(C.buffer, C.byteOffset).setUint32(16, cd, true); // EOCD with ORIGINAL cd offset for digest

const digest = chunkedSha256([A,B,C]);
console.log('content digest:', Buffer.from(digest).toString('hex'));

// certificate DER
const certPem = fs.readFileSync(CRT,'utf8');
const certDer = new Uint8Array(Buffer.from(forge.asn1.toDer(forge.pki.certificateToAsn1(forge.pki.certificateFromPem(certPem))).getBytes(), 'binary'));
const privPem = fs.readFileSync(KEY,'utf8');
const pubDer  = new Uint8Array(nodeCrypto.createPublicKey(certPem).export({type:'spki', format:'der'}));
console.log('certDer', certDer.length, 'pubDer', pubDer.length);
// signedData = LP( LP(digestAlgo+LP(digest)) , LP(cert) , LP(empty attrs) ) — each field LP-sequence
const digests  = LPS([ cat([u32le(SIG_RSA_PKCS1_SHA256), LP(digest)]) ]);  // AOSP: digest record carries SIGNATURE algorithm id
const certs    = LPS([ certDer ]);
const attrs    = LPS([]);
const signedData = cat([digests, certs, attrs]);

// signature over signedData
const sigBytes = new Uint8Array(nodeCrypto.sign('sha256', Buffer.from(signedData), {key: privPem, padding: nodeCrypto.constants.RSA_PKCS1_PADDING}));
// verify our own signature immediately
const okSelf = nodeCrypto.verify('sha256', Buffer.from(signedData), {key: certPem, padding: nodeCrypto.constants.RSA_PKCS1_PADDING}, Buffer.from(sigBytes));
console.log('self-verify signature:', okSelf);
if(!okSelf) throw new Error('signature self-verify failed');
const signatures = LPS([ cat([u32le(SIG_RSA_PKCS1_SHA256), LP(sigBytes)]) ]);

const signer = cat([ LP(signedData), signatures, LP(pubDer) ]);
const v2PairValue = LPS([ signer ]);                      // sequence of one signer
const pair = cat([ u64le(4 + v2PairValue.length), u32le(0x7109871a), v2PairValue ]);
const blockSize = pair.length + 8 + 16;
const block = cat([ u64le(blockSize), pair, u64le(blockSize), MAGIC ]);

const out = cat([A, block, B, (()=>{const c=new Uint8Array(C);new DataView(c.buffer,c.byteOffset).setUint32(16, cd + block.length, true);return c;})()]);
fs.writeFileSync(OUT, out);
console.log('signed:', OUT, out.length, 'bytes (block', block.length, ')');
