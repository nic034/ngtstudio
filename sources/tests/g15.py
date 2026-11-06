import faulthandler,sys; faulthandler.dump_traceback_later(200, exit=True, file=sys.stderr)
import sys, runpy, time, os
sys.argv=["ngt_studio.py"]
import tkinter as tk, numpy as np
def ml(self,*a):
    import gc
    for o in gc.get_objects():
        if hasattr(o,'load_folder') and hasattr(o,'play_sel') and not isinstance(o,type): P=o;break
    t0=time.time()
    while time.time()-t0<0.6: self.update(); time.sleep(0.02)
    pl=P.player
    def fake_play():
        pl.pos,pl.in_loop,pl.loops,pl.paused=0,False,0,False; pl.stream=object(); pl.playing=True
    pl.play=fake_play; pl.stop=lambda: setattr(pl,'playing',False)
    G=P.__class__.__init__.__globals__
    P.load_files(G["ngt_group_files"](sorted(__import__("glob").glob("./testdata/out_ngt2/**/*.ngt",recursive=True))))
    def wait(c,t=60):
        t0=time.time()
        while time.time()-t0<t and not c(): self.update(); time.sleep(0.05)
    print("status:",P.v_status.get())
    for gid in P.tree.get_children(): print("  ",P.tree.item(gid,"text"),P.tree.item(gid,"values"))
    f=P.files[0]; P.tree.selection_set(P.ft_iid[(f,3)]); P.play_sel()
    wait(lambda: P.cur is not None and P.cur[1]==3 and pl.intro is not None)
    buf=np.zeros((1600,2),np.float32)
    for _ in range(30): pl._cb(buf,1600,None,None); self.update()
    wait(lambda: "intact" in str(P.tree.item(P.game_iid[f],"values")) or "ALTERED" in str(P.tree.item(P.game_iid[f],"values")), 30)
    print("playing:",P.v_status.get(),"| pos %.2fs"%pl.position_s(),"| integrity:",P.tree.item(P.game_iid[f],"values")[2])
    self.tk.eval(self.tk.call('wm','protocol',self,'WM_DELETE_WINDOW'))
tk.Tk.mainloop=ml
runpy.run_path(os.environ.get("NGT_STUDIO", "ngt_studio.py"),run_name="__main__")
