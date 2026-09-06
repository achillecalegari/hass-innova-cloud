#!/usr/bin/env python3
"""Dump the Swift reflection metadata (__swift5_fieldmd) of an app binary: for every struct/enum,
its stored properties with their (partially demangled) types. Combined with extract_namemaps.py
this gives the complete protobuf schema of a SwiftProtobuf-based app: numbers from the name maps,
types from here (Sb=Bool, Sf=Float, SS=String, s6UInt32V=UInt32, Foundation.Data=bytes,
`Sg` suffix = Optional, Say...G = Array, SDy...G = Dictionary/map).

Usage: python tools/swift_fields.py /Applications/Innova.app/Wrapper/Innova.app/Innova > fields.txt
"""
import struct, re, sys, json, subprocess
import argparse
_ap = argparse.ArgumentParser(description='Dump Swift reflection field metadata (property names and types) from an app binary')
_ap.add_argument('binary', nargs='?', default='/Applications/Innova.app/Wrapper/Innova.app/Innova')
_ap.add_argument('--all', action='store_true', help='every type, not only protobuf/service ones')
_args = _ap.parse_args()
path=_args.binary
data=open(path,'rb').read()
# parse mach-o 64 load commands to get sections + segment vmaddr->fileoff mapping
magic,cputype,cpusub,filetype,ncmds,sizeofcmds,flags,res=struct.unpack('<IiiIIIII',data[:32])
assert magic==0xfeedfacf
off=32; segs=[]; sects={}
for _ in range(ncmds):
    cmd,cmdsize=struct.unpack('<II',data[off:off+8])
    if cmd==0x19:
        segname=data[off+8:off+24].rstrip(b'\0').decode()
        vmaddr,vmsize,fileoff,filesize=struct.unpack('<QQQQ',data[off+24:off+56])
        nsects=struct.unpack('<I',data[off+64:off+68])[0]
        segs.append((vmaddr,vmsize,fileoff))
        so=off+72
        for _ in range(nsects):
            sname=data[so:so+16].rstrip(b'\0').decode()
            addr,size,soff=struct.unpack('<QQI',data[so+32:so+52])
            sects[sname]=(addr,size,soff); so+=80
    off+=cmdsize

# --- chained fixups imports
imports=[]
off2=32
for _ in range(ncmds):
    cmd,cmdsize=struct.unpack('<II',data[off2:off2+8])
    if cmd==0x80000034:
        dataoff,datasize=struct.unpack('<II',data[off2+8:off2+16])
        hdr=struct.unpack('<7I',data[dataoff:dataoff+28])
        ver,starts_off,imports_off,symbols_off,imports_count,imports_format,symbols_format=hdr
        for i in range(imports_count):
            if imports_format==1:
                v=struct.unpack('<I',data[dataoff+imports_off+4*i:dataoff+imports_off+4*i+4])[0]
                name_off=v>>9
            elif imports_format==2:
                v=struct.unpack('<Q',data[dataoff+imports_off+8*i:dataoff+imports_off+8*i+8])[0]
                name_off=v>>32
            else:
                v=struct.unpack('<Q',data[dataoff+imports_off+8*i:dataoff+imports_off+8*i+8])[0]
                name_off=v>>32
            s=data[dataoff+symbols_off+name_off:]
            imports.append(s[:s.index(b'\0')].decode())
    off2+=cmdsize
def demangle_simple(sym):
    m=re.match(r'^_\$s(.*?)(Mn|N|Ma)$',sym)
    body=m.group(1) if m else sym
    parts=re.findall(r'(\d+)([A-Za-z_][A-Za-z0-9_]*)',body)
    out=[];i=0
    s=body
    while s:
        m=re.match(r'(\d+)',s)
        if m:
            n=int(m.group(1)); s=s[len(m.group(1)):]; out.append(s[:n]); s=s[n:]
        else:
            out.append(s); break
    return '.'.join(out)

def va2off(va):
    for vmaddr,vmsize,fileoff in segs:
        if vmaddr<=va<vmaddr+vmsize: return va-vmaddr+fileoff
    raise ValueError(hex(va))
def cstr(o):
    j=data.index(b'\0',o); return data[o:j]
def relptr(o):
    r=struct.unpack('<i',data[o:o+4])[0]
    return None if r==0 else o+r
def mangled(o):
    # symbolic references: bytes 0x01-0x1f followed by 4-byte relative pointer; keep as marker
    out=b''; i=o
    while data[i]!=0:
        b=data[i]
        if 1<=b<=0x1f:
            rel=struct.unpack('<i',data[i+1:i+5])[0]; tgt=i+1+rel
            if b in (1,2):
                # context descriptor pointer -> try reading its name (nominal type descriptor: name at +8 rel)
                try:
                    if b==2:
                        v=struct.unpack('<Q',data[tgt:tgt+8])[0]
                        if v>>63:
                            ordinal=v & 0xFFFFFF
                            out+=('{'+demangle_simple(imports[ordinal])+'}').encode(); i+=5; continue
                        cand=[v & 0xFFFFFFFFF, (v & 0xFFFFFFFFF)+0x100000000, v & 0xFFFFFFFFFFFF]
                        tgt=None
                        for c in cand:
                            try: tgt=va2off(c); break
                            except ValueError: pass
                        if tgt is None: raise ValueError('ptr')
                    nm=cstr(relptr(tgt+8)).decode()
                    # parent name
                    par=relptr(tgt+4)
                    chain=[nm]
                    while par is not None:
                        try:
                            kind=struct.unpack('<I',data[par:par+4])[0]&0x1f
                            if kind in (0,): break  # module
                            pn=cstr(relptr(par+8)).decode(); chain.append(pn); par=relptr(par+4)
                        except Exception: break
                    out+=('{'+'.'.join(reversed(chain))+'}').encode()
                except Exception:
                    out+=b'{ext}'
            else:
                out+=b'{sym%d}'%b
            i+=5
        else:
            out+=bytes([b]); i+=1
    return out.decode('utf-8','replace')
addr,size,soff=sects['__swift5_fieldmd']
end=soff+size; o=soff; types=[]
while o<end:
    tn_off=relptr(o); sup=relptr(o+4)
    kind,recsize,nfields=struct.unpack('<HHI',data[o+8:o+16])
    tname=mangled(tn_off) if tn_off else '?'
    fields=[]
    fo=o+16
    for _ in range(nfields):
        flags=struct.unpack('<I',data[fo:fo+4])[0]
        mt=relptr(fo+4); fn=relptr(fo+8)
        fields.append({'name':cstr(fn).decode() if fn else '', 'type':mangled(mt) if mt else '', 'indirect':bool(flags&1)})
        fo+=recsize
    types.append({'kind':kind,'name':tname,'fields':fields})
    o=fo
sel=types if _args.all else [t for t in types if re.search(r'Messages_|Services_',t['name'])]
json.dump(sel,open('swift_fields.json','w'),indent=1)
print(len(types),'types,',len(sel),'proto types',file=sys.stderr)
for t in sel:
    print(f"== [{t['kind']}] {t['name']}")
    for f in t['fields']:
        print(f"   {f['name']}: {f['type']}")
