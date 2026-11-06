import faulthandler,sys; faulthandler.dump_traceback_later(130, exit=True, file=sys.stderr)
import sys, runpy, time, os, types
sys.argv=["ngt_studio.py"]
import tkinter as tk, numpy as np
def ml(self,*a):
    import gc
    for o in gc.get_objects():
        if hasattr(o,'load_folder') and hasattr(o,'play_sel') and not isinstance(o,type): P=o;break
    t0=time.time()
    while time.time()-t0<0.6: self.update(); time.sleep(0.02)
    self.nametowidget(self.winfo_children()[0]).select(1)
    # fake audio device: playing state without sound card; we pull frames ourselves
    pl=P.player
    def fake_play():
        pl.pos,pl.in_loop,pl.loops,pl.paused=0,False,0,False; pl.stream=object(); pl.playing=True; return None
    pl.play=fake_play
    def fake_stop():
        pl.playing=pl.paused=False; pl.stream=None
    pl.stop=fake_stop
    P.load_folder('./testdata/en_out')
    P.tree.selection_set(P.ft_iid[(P.files[0],9)]); P.play_sel()
    def wait(c,t=30):
        t0=time.time()
        while time.time()-t0<t and not c(): self.update(); time.sleep(0.02)
    wait(lambda: P.cur is not None and P.cur[1]==9)
    buf=np.zeros((1600,2),np.float32)
    def run(sec):
        t0=time.time()
        while time.time()-t0<sec:
            pl._cb(buf,1600,None,None); self.update(); time.sleep(0.02)
    run(3)
    print("status:",P.v_status.get()," pos %.2fs"%pl.position_s(), "keys lit:",len(P.kb_on))
    y_voice,voice_h,vbw=P.vgeom
    ev=lambda v: types.SimpleNamespace(x=int(12+v*vbw+vbw/2), y=int(y_voice+voice_h/2))
    before=pl.intro; pos0=pl.position_s()
    P.on_mix_click(ev(3))                     # mute FM4
    wait(lambda: pl.intro is not before, 20); run(0.3)
    print("after mute FM4: muted",sorted(P.muted),"swapped:",pl.intro is not before,"pos %.2f -> %.2f"%(pos0,pl.position_s()),"| status:",P.v_status.get())
    P.on_mix_click(ev(13), solo=True)          # solo ADPCM-B
    b2=pl.intro; wait(lambda: pl.intro is not b2, 20); run(0.5)
    print("solo B: muted count",len(P.muted),"| status:",P.v_status.get(), "| intro rms %.4f"%np.sqrt((pl.intro**2).mean()))
    P.on_mix_click(ev(13), solo=True); b3=pl.intro; wait(lambda: pl.intro is not b3, 20); run(0.3)
    print("un-solo: muted",sorted(P.muted))
    P.on_mix_click(ev(0)); P.on_mix_click(ev(7)); b4=pl.intro; wait(lambda: pl.intro is not b4,20); run(1.0)
    self.update(); time.sleep(0.2); self.update()
    from PIL import ImageGrab
    ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).save(os.environ["SHOT"])
    print("keys lit at screenshot:",len(P.kb_on), "muted:",[P.VOICES_SHORT[v] if hasattr(P,'VOICES_SHORT') else v for v in sorted(P.muted)])
    self.tk.eval(self.tk.call('wm','protocol',self,'WM_DELETE_WINDOW'))
tk.Tk.mainloop=ml
runpy.run_path(os.environ.get("NGT_STUDIO", "ngt_studio.py"),run_name="__main__")
