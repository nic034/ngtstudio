import sys, runpy, time, os
sys.argv=["ngt_studio.py"]
import tkinter as tk, numpy as np
def ml(self,*a):
    import gc
    for o in gc.get_objects():
        if hasattr(o,'load_folder') and hasattr(o,'play_sel') and not isinstance(o,type): P=o;break
    self.update()
    C=P.cb_loop
    st=lambda: (P.v_loops.get(), P.v_next.get(), len(C.cget("values")), P.player.loops_max)
    print("start           ", st())
    P.v_next.set(True); P.opts_changed(); print("next on         ", st())
    P.v_loops.set("3 loops + fade"); P.opts_changed(); print("pick 3 (next on)", st())
    P.v_next.set(False); P.opts_changed(); print("next off        ", st())
    P.v_loops.set("1 loop + fade"); P.opts_changed(); print("pick 1          ", st())
    P.v_next.set(True); P.opts_changed(); print("next on         ", st())
    P.v_next.set(False); P.opts_changed(); print("next off        ", st())
    # player fade unit test
    pl=P.player; pl.stop=lambda: None
    intro=np.ones((100,2),np.float32); loop=np.ones((50,2),np.float32)*0.5
    pl.intro,pl.loop=intro,loop; pl.pos,pl.in_loop,pl.loops,pl.fade_pos=0,False,0,None
    pl.loops_max=2; pl.fade_s=120/48000; pl.playing=True; pl.paused=False; pl.volume=1.0
    outs=[]
    buf=np.zeros((30,2),np.float32)
    for i in range(20):
        if not pl.playing: break
        pl._cb(buf,30,None,None); outs.append(buf[:,0].copy())
    o=np.concatenate(outs)
    print("fade: stopped after %d frames (intro 100 + 2 loops 100 + fade 120 = 320), loops=%d"%(len(o),pl.loops))
    print("   level at 200:",o[199],"| at 260: %.3f"%o[259],"| at 315: %.3f"%o[314])
    self.tk.eval(self.tk.call('wm','protocol',self,'WM_DELETE_WINDOW'))
tk.Tk.mainloop=ml
runpy.run_path(os.environ.get("NGT_STUDIO", "ngt_studio.py"),run_name="__main__")
