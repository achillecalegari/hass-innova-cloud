#!/usr/bin/env python3
"""Extract SwiftProtobuf name maps (field/enum names and numbers) from an iOS/iPadOS app binary.

Usage: python tools/extract_namemaps.py /Applications/Innova.app/Wrapper/Innova.app/Innova

The iPad build installed on an Apple-silicon Mac is almost entirely unencrypted (FairPlay only
covers the first 4 KB of code), which is what makes this possible without a jailbreak.
Each SwiftProtobuf message stores `_NameMap(bytecode:)`: format byte 0, then opcodes
(1 same/3 standard/5 unique/7 group/9 alias, +1 = explicit delta variants, 11 reserved name,
12 reserved numbers) with NUL-terminated names; "Next" opcodes mean previous number + 1.
"""
import re, sys, json
import argparse
_ap = argparse.ArgumentParser(description='Recover protobuf field names/numbers from the SwiftProtobuf name-map bytecode embedded in an app binary')
_ap.add_argument('binary', nargs='?', default='/Applications/Innova.app/Wrapper/Innova.app/Innova')
_ap.add_argument('--json', default='namemaps.json')
_args = _ap.parse_args()
data = open(_args.binary, 'rb').read()

def read_uint(buf, i):
    val=0; shift=0
    while True:
        b=buf[i]; i+=1
        if b & 0x80: raise ValueError
        val |= (b & 0x3f) << shift
        if not (b & 0x40): return val, i
        shift += 6
        if shift > 64: raise ValueError

def read_str(buf,i):
    j=buf.index(b'\x00', i)
    s=buf[i:j]
    if not re.fullmatch(rb'[A-Za-z_][A-Za-z0-9_]*', s): raise ValueError
    return s.decode(), j+1

def parse(buf, i):
    """parse a program starting at i (format byte). returns (entries, end)"""
    fmt, i = read_uint(buf, i)
    if fmt != 0: raise ValueError
    prev=0; entries=[]
    start=i
    while i < len(buf):
        op = buf[i]
        if op == 0 or op > 12:
            break
        i+=1
        try:
            if op in (1,3,5,7,9):
                num = prev+1
            elif op in (2,4,6,8,10):
                d,i = read_uint(buf,i); d = d if d < 2**31 else d-2**32
                num = prev + d
            if op in (1,2,3,4,7,8):
                name,i = read_str(buf,i); entries.append((num,name)); prev=num
            elif op in (5,6):
                name,i = read_str(buf,i); jname,i = read_str(buf,i); entries.append((num,name+'/'+jname)); prev=num
            elif op in (9,10):
                cnt,i = read_uint(buf,i); name,i = read_str(buf,i)
                al=[]
                for _ in range(cnt):
                    a,i = read_str(buf,i); al.append(a)
                entries.append((num,name+('('+','.join(al)+')' if al else ''))); prev=num
            elif op == 11:
                name,i = read_str(buf,i); entries.append(('reserved',name))
            elif op == 12:
                lo,i=read_uint(buf,i); d,i=read_uint(buf,i); entries.append(('reserved',f'{lo}-{lo+d}'))
        except (ValueError, IndexError):
            break
    return entries, i

pat = re.compile(rb'\x00[\x01-\x0c][A-Za-z_][A-Za-z0-9_]{1,}\x00')
results=[]
seen=set()
for m in pat.finditer(data):
    off=m.start()
    if off in seen: continue
    try:
        entries,end = parse(data, off)
    except Exception:
        continue
    if len(entries) < 1: continue
    # type name: search backwards for a NUL-terminated identifier ending before off
    back = data[max(0,off-160):off]
    names = re.findall(rb'((?:Messages|Services|Google_Protobuf|Common)_[A-Za-z0-9_]+)\x00', back)
    tname = names[-1].decode() if names else None
    results.append({'offset':hex(off),'type':tname,'entries':entries})
    for k in range(off, end): seen.add(k)

# keep only those with a type name or many entries
out=[r for r in results if r['type'] or len(r['entries'])>=2]
json.dump(out, open(_args.json,'w'), indent=1)
for r in out:
    print(f"{r['offset']} {r['type']}: " + ', '.join(f"{n}={v}" for n,v in r['entries']))
print(len(out),'maps', file=sys.stderr)
