"""Rebuild tables from the pinned upstream splines_lung.RData; run from repo root."""
import gzip,hashlib,json,struct,sys
from pathlib import Path
raw=Path(sys.argv[1]).read_bytes()
assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()=='ad461626d8090d9d3896f84bc0faf60dc01280e2'
b=gzip.decompress(raw);pat=struct.pack('>II',14,301);pos=0;vectors=[]
while True:
 i=b.find(pat,pos)
 if i<0:break
 vectors.append(struct.unpack('>301d',b[i+8:i+8+301*8]));pos=i+8+301*8
names=['FRC.M','FRC.F','TLC.M','TLC.F','RV.M','RV.F','RVTLC.M','RVTLC.F','ERV.M','ERV.F','IC.M','IC.F','VC.M','VC.F']
assert len(vectors)==56
# The serialized list's names follow the exact sheet order in build_gli_2021_volumes.R.
for name in names:assert ('S.'+name).encode() in b
out={}
for i,name in enumerate(names):
 cols=vectors[4*i:4*i+4]
 assert cols[0]==tuple(5+j*.25 for j in range(301))
 if name.split('.')[0] in ('ERV','IC','VC'):
  assert all(v==0 for v in cols[2]) and all(v==0 for v in cols[3])
  out[name]=[list(row) for row in zip(*cols)]
Path('app/data/gli_volumes_2021.json').write_text(json.dumps({'version':1,'tables':out},separators=(',',':'))+'\n')
print('6 tables, 301 ages each; SHA256',hashlib.sha256(raw).hexdigest())
