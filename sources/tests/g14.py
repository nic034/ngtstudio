import faulthandler,sys; faulthandler.dump_traceback_later(200, exit=True, file=sys.stderr)
import sys, runpy, time, os, glob
sys.argv=["ngt_studio.py"]
import tkinter as tk
def ml(self,*a):
    import gc
    C=None
    for o in gc.get_objects():
        if hasattr(o,'pick_bios') and hasattr(o,'compute') and not isinstance(o,type): C=o;break
    t0=time.time()
    while time.time()-t0<0.6: self.update(); time.sleep(0.02)
    nb=self.nametowidget(self.winfo_children()[0]); tabs=nb.tabs()
    for t in tabs:
        if "art" in nb.tab(t,"text"): nb.select(t)
    def wait(c,t=60):
        t0=time.time()
        while time.time()-t0<t and not c(): self.update(); time.sleep(0.05)
    C.add(["./testdata/en_out/aof2/Art of Fighting 2.ngt","./testdata/cb/out/countb/countb.ngt"])
    wait(lambda: C.ev is not None)
    print("standard:", C.v_info.get()); print("  ", [l[1].cget("text") for l in C.labs])
    C.v_prof.set("extended"); C.changed(); e0=C.ev
    wait(lambda: C.ev is not e0 and C.ev["profile"]=="extended")
    print("extended:", [l[1].cget("text") for l in C.labs][:2])
    C.v_bios.set("./testdata/neogeo.zip")
    import ngt_mod
    rep,files=ngt_mod.build_cart(C.pack, C.v_prof.get(), C.v_bios.get(), "./g14out")
    print("build ok:",len(files),"files")
    self.update(); time.sleep(0.3); self.update()
    from PIL import ImageGrab
    ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).save(os.environ["SHOT"])
    self.tk.eval(self.tk.call('wm','protocol',self,'WM_DELETE_WINDOW'))
tk.Tk.mainloop=ml
import types
g=runpy.run_path(os.environ.get("NGT_STUDIO", "ngt_studio.py"),run_name="__notmain__")
sys.modules["ngt_mod"]=types.SimpleNamespace(**g)
g["main"]()
