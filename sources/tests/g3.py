import os, sys, runpy, time
sys.argv=["ngt_studio.py"]
import tkinter as tk
def ml(self,*a):
    import gc
    for o in gc.get_objects():
        if hasattr(o,'load_folder') and hasattr(o,'play_sel') and not isinstance(o,type): P=o;break
    P.load_folder('./testdata/en_out'); self.update()
    P.play_sel()
    t=time.time()
    while time.time()-t<20 and not P.cur: self.update(); time.sleep(0.05)
    print("cur",P.cur)
    P.step(1)
    t=time.time()
    while time.time()-t<20 and P.cur!=('./testdata/en_out/aof2/Art of Fighting 2.ngt',1): self.update(); time.sleep(0.05)
    print("after next",P.cur, "sel",P.sel_track())
    P.step(-1)
    t=time.time()
    while time.time()-t<20 and P.cur and P.cur[1]!=0: self.update(); time.sleep(0.05)
    print("after prev",P.cur)
    # player autoloop logic
    import numpy as np
    pl=P.player; pl.autoloop=False
    pl.load(np.zeros((100,2),np.float32),np.zeros((50,2),np.float32)); pl.playing=True
    out=np.zeros((400,2),np.float32); pl._cb(out,400,None,None)
    print("autoloop off -> playing:",pl.playing,"loops",pl.loops)
    pl.autoloop=True; pl.load(np.zeros((100,2),np.float32),np.zeros((50,2),np.float32)); pl.playing=True
    pl._cb(out,400,None,None); print("autoloop on -> playing:",pl.playing,"loops",pl.loops)
    self.destroy()
tk.Tk.mainloop=ml
runpy.run_path(os.environ.get("NGT_STUDIO", "ngt_studio.py"),run_name="__main__")
