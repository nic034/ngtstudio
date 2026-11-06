import faulthandler, sys; faulthandler.dump_traceback_later(400, exit=True, file=sys.stderr)
import runpy, time, os, types, subprocess, wave
sys.argv = ["ngt_studio.py"]
import tkinter as tk, numpy as np
OUT = "./pyvid"
os.makedirs(OUT, exist_ok=True)
def ml(self, *a):
    import gc
    for o in gc.get_objects():
        if hasattr(o, 'load_folder') and hasattr(o, 'play_sel') and not isinstance(o, type): P = o; break
    self.geometry("1280x720+0+0"); self.update()
    t0 = time.time()
    while time.time() - t0 < 0.6: self.update(); time.sleep(0.02)
    self.nametowidget(self.winfo_children()[0]).select(1)
    pl = P.player
    def fake_play():
        pl.pos, pl.in_loop, pl.loops, pl.paused, pl.fade_pos = 0, False, 0, False, None; pl.stream = object(); pl.playing = True
    def fake_stop():
        pl.playing = pl.paused = False; pl.stream = None
    pl.play = fake_play; pl.stop = fake_stop
    P.load_folder('./testdata/en_out')
    def wait(c, t=60):
        t0 = time.time()
        while time.time() - t0 < t and not c(): self.update(); time.sleep(0.02)
    wait(lambda: P.slide.get("path") and P.pic_box, 40)
    P.tree.selection_set(P.ft_iid[(P.files[0], 4)]); P.play_sel()
    wait(lambda: P.cur is not None and P.cur[1] == 4 and pl.intro is not None, 60)
    sc = P.scope_data(P.cur)                       # precalcul des oscilloscopes (rendus solo par voix)
    wait(lambda: sc and len(sc["pcm"]) >= len(sc["voices"]), 300)
    print("scope ready:", len(sc["pcm"]), "voices")
    pl.seek(0.0)
    for _ in range(30): self.update(); time.sleep(0.02)
    rec = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-video_size", "1280x720", "-framerate", "30",
                            "-i", os.environ["DISPLAY"], "-c:v", "libx264", "-preset", "ultrafast", "-qp", "0", OUT + "/screen.mkv"],
                           stdin=subprocess.PIPE)
    t0 = time.time(); last = t0; chunks = []; acts = {10: "fs", 17: "v", 24: "v", 30.2: "close"}; done = set()
    while True:
        now = time.time(); el = now - t0
        n = int((now - last) * 48000)
        if n > 0:
            buf = np.zeros((n, 2), np.float32); pl._cb(buf, n, None, None); chunks.append(buf.copy()); last += n / 48000
        for t, a in acts.items():
            if el >= t and t not in done:
                done.add(t)
                if a == "fs": P.on_dbl(types.SimpleNamespace(x=P.pic_box[0] + 20, y=P.pic_box[1] + 20))
                elif a == "v": P.fs_mode()
                else: P.fs_close()
        self.update()
        if el > 31.5: break
        time.sleep(0.01)
    rec.communicate(b"q"); 
    a = np.clip(np.concatenate(chunks) * 32767, -32768, 32767).astype("<i2")
    w = wave.open(OUT + "/audio.wav", "wb"); w.setnchannels(2); w.setsampwidth(2); w.setframerate(48000); w.writeframes(a.tobytes()); w.close()
    print("audio s:", len(a) / 48000, "track:", P.v_status.get())
    self.tk.eval(self.tk.call('wm', 'protocol', self, 'WM_DELETE_WINDOW'))
tk.Tk.mainloop = ml
runpy.run_path(os.environ.get("NGT_STUDIO", "ngt_studio.py"), run_name="__main__")
