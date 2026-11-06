import sys, os, wave, runpy, numpy as np
G = runpy.run_path(os.environ.get("NGT_STUDIO", "ngt_studio.py"), run_name="x")
from scipy.signal import resample_poly
wav,trk=sys.argv[1],int(sys.argv[2])
w=wave.open(wav); x=np.frombuffer(w.readframes(w.getnframes()),"<i2").reshape(-1,2).astype(float).mean(1)
meta,pcm=G["render_track"](__import__("os").environ.get("NGT","./testdata/en_out/aof2/Art of Fighting 2.ngt"),trk); r=pcm.astype(float).mean(1)
if meta["loop_start"]:
    ls=meta["loop_start"]-meta["k0"]; le=meta["loop_end"]-meta["k0"]; r=np.concatenate([r[:le],r[ls:le]])
r=resample_poly(r,48000,55555)
H=480; e=lambda a: np.sqrt((a[:len(a)//H*H].reshape(-1,H)**2).mean(1))
ex,er=e(x),e(r)
t0=int(float(__import__("os").environ.get("T0","0"))*100); on=t0+int(np.argmax(ex[t0:]>200)); onr=int(np.argmax(er>200)); a=ex[on:]; b=er[onr:]
n=min(len(a),len(b)); out=[]
for s in range(0,n-500,1000):
    c,l=max((np.corrcoef(a[s:s+500],b[s+l:s+500+l])[0,1],l) for l in range(-30,31) if s+l>=0 and s+500+l<=len(b))
    out.append("%.0fs:%.2f/%+dms"%(s*0.01,c,l*10))
print("piste",trk,"début %.2fs |"%(on*0.01)," ".join(out))
