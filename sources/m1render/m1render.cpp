// m1render.cpp - rendu autonome de la partie son d'une cartouche Neo Geo
//   Z80 (M1) + YM2610 (ymfm) + VROM ADPCM-A/B
//
// Carte mémoire / ports Z80 (d'après le comportement documenté de MAME, à confirmer jeu par jeu) :
//   0000-7FFF M1 fixe | 8000-BFFF banque 16K (IN 0x0B) | C000-DFFF banque 8K (IN 0x0A)
//   E000-EFFF banque 4K (IN 0x09) | F000-F7FF banque 2K (IN 0x08) | F800-FFFF RAM 2K
//   Le numéro de banque = octet HAUT de l'adresse de port.
//   Port 0x00 : lecture = commande son ; 0x04-0x07 : YM2610 ; OUT 0x08 : NMI on ; OUT 0x18 : NMI off
//   OUT 0x0C : réponse au 68000 (ignorée)
//
// Horloges : maître 24167829 Hz ; Z80 = /6 ; YM2610 = /3 ; 1 échantillon (fidélité MIN) = 144 horloges YM = 72 cycles Z80.

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <unordered_map>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#include <shellapi.h>
#endif

extern "C" {
#include "z80/z80.h"
}
#include "ymfm/ymfm_opn.h"

static constexpr uint32_t YM_CLOCK = 8055943;
static constexpr uint32_t Z80_CLOCK = 4027971;
static constexpr uint32_t CYC_PER_SAMPLE = 72;
static constexpr uint32_t OUT_RATE = YM_CLOCK / 144;  // 55944 Hz

using Bytes = std::vector<uint8_t>;

// Chemins en UTF-8 dans tout le programme.  Windows : fopen() passe par la page de code ANSI, un chemin avec des
// caractères hors de cette page (nom de compte cyrillique sur un Windows français…) devient « ??? » -> _wfopen().
static FILE* xfopen(const char* path, const char* mode) {
#ifdef _WIN32
  auto wide = [](const char* s) {
    int n = MultiByteToWideChar(CP_UTF8, 0, s, -1, nullptr, 0);
    std::wstring w(n > 0 ? n - 1 : 0, L'\0');
    if (n > 1) MultiByteToWideChar(CP_UTF8, 0, s, -1, &w[0], n);
    return w;
  };
  return _wfopen(wide(path).c_str(), wide(mode).c_str());
#else
  return fopen(path, mode);
#endif
}

static bool load_file(const char* path, Bytes& out) {
  FILE* f = xfopen(path, "rb");
  if (!f) return false;
  fseek(f, 0, SEEK_END);
  long n = ftell(f);
  fseek(f, 0, SEEK_SET);
  out.resize(n);
  size_t r = n ? fread(out.data(), 1, n, f) : 0;
  fclose(f);
  return (long)r == n;
}

struct Options {
  bool stream = false;
  bool ev = false;
  bool pcs = false;
  bool ymlog = false;
  std::vector<int> pre;
  std::vector<int> post;
  double post_delay = 0.03;
  double pre_delay = 0.5;
  double ssg_gain = 1.0;
  int trace = 0;
};

class Machine : public ymfm::ymfm_interface {
 public:
  struct Ev { uint32_t t; uint16_t reg; uint8_t val; uint8_t pad; };
  // va / vb : tenues par l'appelant pendant toute la vie de la machine (pas de copie : jusqu'à 32 Mo par commande)
  Machine(const Bytes& m1, const Bytes& va, const Bytes& vb, const Options& o)
      : m1_(m1), va_(va), vb_(vb), opt_(o), chip_(*this) {
    // M1 : arrondi à une puissance de 2 pour que le modulo se comporte comme un bus d'adresses
    size_t sz = 1;
    while (sz < m1_.size()) sz <<= 1;
    m1_.resize(std::max<size_t>(sz, 0x8000), 0);
    memset(ram_, 0, sizeof ram_);
    // banques au reset = correspondance directe (comme MAME : F000/E000/C000/8000), certains drivers
    // (Magician Lord…) sautent en zone banquée avant de programmer les banques
    bank_[0] = 0x1E; bank_[1] = 0x0E; bank_[2] = 0x06; bank_[3] = 0x02;
    timer_[0] = timer_[1] = -1;
    chip_.set_fidelity(ymfm::OPN_FIDELITY_MIN);
    chip_.reset();
    z80_init(&cpu_);
    cpu_.read_byte = &Machine::rb;
    cpu_.write_byte = &Machine::wb;
    cpu_.port_in = &Machine::pin;
    cpu_.port_out = &Machine::pout;
    cpu_.userdata = this;
    next_sample_cyc_ = CYC_PER_SAMPLE;
  }

  // --- ymfm_interface ---
  void ymfm_set_timer(uint32_t tnum, int32_t duration) override {
    timer_[tnum & 1] = duration < 0 ? -1 : (int64_t)cpu_.cyc + duration / 2;  // horloges YM -> cycles Z80
  }
  void ymfm_update_irq(bool asserted) override { irq_ = asserted; }
  uint8_t ymfm_external_read(ymfm::access_class t, uint32_t addr) override {
    const Bytes& r = (t == ymfm::ACCESS_ADPCM_B) ? vb_ : va_;
    if (r.empty()) return 0;
    return r[addr % r.size()];
  }

  // --- exécution ---
  // exécute jusqu'à produire n échantillons ; renvoie via out (stéréo entrelacé)
  void run_samples(size_t n, std::vector<int16_t>* out) {
    size_t produced = 0;
    while (produced < n) {
      if (opt_.pcs && tracing_) pcseen_[cpu_.pc] = 1;
      z80_step(&cpu_);
      for (int t = 0; t < 2; t++)
        if (timer_[t] >= 0 && (int64_t)cpu_.cyc >= timer_[t]) {
          timer_[t] = -1;
          m_engine->engine_timer_expired(t);
        }
      if (irq_ && cpu_.iff1 && !cpu_.int_pending) z80_gen_int(&cpu_, 0xFF);
      while ((int64_t)cpu_.cyc >= next_sample_cyc_ && produced < n) {
        ymfm::ym2610::output_data o;
        chip_.generate(&o, 1);
        gen_count_++;
        double ssg = o.data[2] * opt_.ssg_gain;
        double l = o.data[0] + ssg, r = o.data[1] + ssg;
        if (out) {
          out->push_back((int16_t)std::max(-32768.0, std::min(32767.0, l)));
          out->push_back((int16_t)std::max(-32768.0, std::min(32767.0, r)));
        }
        next_sample_cyc_ += CYC_PER_SAMPLE;
        produced++;
      }
    }
  }

  void send_command(uint8_t c) {
    latch_ = c;
    tracing_ = true;
    cmd_cyc_ = cpu_.cyc;
    k0_ = (uint32_t)gen_count_;
    if (nmi_en_) z80_gen_nmi(&cpu_);
    else nmi_pend_ = true;
  }

  void send_command_keep(uint8_t c) {  // octet supplémentaire d'une commande multi-octets (garde l'origine des temps)
    latch_ = c;
    if (nmi_en_) z80_gen_nmi(&cpu_);
    else nmi_pend_ = true;
  }
  // début de la capture : état des registres YM au moment de la commande + journal vidé
  void begin_capture() { memcpy(snap_, shadow_, sizeof snap_); ev_.clear(); }
  const uint8_t* snap() const { return snap_; }
  uint32_t k0() const { return k0_; }
  const std::vector<Ev>& raw() const { return raw_; }
  // rejeu exact : applique les écritures brutes (offset 0..3, donnée) juste avant l'échantillon d'indice t,
  // depuis la remise à zéro de la puce ; ne restitue que les échantillons à partir de 'skip'
  void replay(const std::vector<Ev>& ev, size_t skip, size_t total, std::vector<int16_t>& out) {
    size_t i = 0;
    for (size_t n = 0; n < total; n++) {
      while (i < ev.size() && ev[i].t <= n) { chip_.write(ev[i].reg & 3, ev[i].val); i++; }
      ymfm::ym2610::output_data o;
      chip_.generate(&o, 1);
      if (n < skip) continue;
      double ssg = o.data[2] * opt_.ssg_gain;
      double l = o.data[0] + ssg, r = o.data[1] + ssg;
      out.push_back((int16_t)std::max(-32768.0, std::min(32767.0, l)));
      out.push_back((int16_t)std::max(-32768.0, std::min(32767.0, r)));
    }
  }
  bool nmi_enabled() const { return nmi_en_; }
  const std::vector<Ev>& events() const { return ev_; }
  const uint8_t* pcseen() const { return pcseen_; }
  uint32_t fp() const { return fp_; }
  int fpn() const { return fpn_; }
  int fm_on() const { return fm_on_; }
  int ssg_on() const { return ssg_on_; }
  int ada_on() const { return ada_on_; }
  int adb_on() const { return adb_on_; }
  unsigned long cycles() const { return cpu_.cyc; }
  uint16_t pc() const { return cpu_.pc; }

 private:
  static uint8_t rb(void* u, uint16_t a) { return ((Machine*)u)->rd(a); }
  static void wb(void* u, uint16_t a, uint8_t v) { ((Machine*)u)->wr(a, v); }
  static uint8_t pin(z80* z, uint8_t p) { return ((Machine*)z->userdata)->io_in(z, p); }
  static void pout(z80* z, uint8_t p, uint8_t v) { ((Machine*)z->userdata)->io_out(z, p, v); }

  uint8_t rd(uint16_t a) const {
    const size_t sz = m1_.size();
    if (a < 0x8000) return m1_[a % sz];
    if (a < 0xC000) return m1_[((size_t)bank_[3] * 0x4000 + (a - 0x8000)) % sz];
    if (a < 0xE000) return m1_[((size_t)bank_[2] * 0x2000 + (a - 0xC000)) % sz];
    if (a < 0xF000) return m1_[((size_t)bank_[1] * 0x1000 + (a - 0xE000)) % sz];
    if (a < 0xF800) return m1_[((size_t)bank_[0] * 0x0800 + (a - 0xF000)) % sz];
    return ram_[a - 0xF800];
  }
  void wr(uint16_t a, uint8_t v) {
    if (a >= 0xF800) ram_[a - 0xF800] = v;
  }

  uint8_t io_in(z80* z, uint8_t p) {
    uint8_t v = 0;
    switch (p) {
      case 0x00: v = latch_; break;
      case 0x04: case 0x05: case 0x06: case 0x07: v = chip_.read(p & 3); break;
      case 0x08: case 0x09: case 0x0A: case 0x0B: bank_[p - 0x08] = z->port_hi; break;
      default: break;
    }
    trace('R', p, v);
    return v;
  }
  void io_out(z80* z, uint8_t p, uint8_t v) {
    (void)z;
    switch (p) {
      case 0x00: nmi_pend_ = false; break;
      case 0x04: case 0x05: case 0x06: case 0x07: {
        chip_.write(p & 3, v);
        if (opt_.stream) { Ev e; e.t = (uint32_t)gen_count_; e.reg = (uint16_t)(p & 3); e.val = v; e.pad = 0; raw_.push_back(e); }
        // l'YM2610 n'a qu'UN registre d'adresse partagé : une écriture de données n'a d'effet que si elle suit
        // une adresse du même bloc (port 4 -> données port 5 ; port 6 -> données port 7)
        if (p == 0x04) { caddr_ = v; break; }
        if (p == 0x06) { caddr_ = (uint16_t)(0x100 | v); break; }
        bool hi = (p == 0x07);
        if (hi != ((caddr_ & 0x100) != 0)) break;     // ignorée par la puce
        uint16_t reg = caddr_;
        if (tracing_ && (cpu_.cyc - cmd_cyc_) < 3UL * Z80_CLOCK) {
          fp_ = (fp_ ^ (reg * 257u + v)) * 16777619u; fpn_++;
          if (opt_.ymlog) fprintf(stderr, "%.3f %s %02X=%02X\n", (cpu_.cyc - cmd_cyc_) / (double)Z80_CLOCK, hi ? "hi" : "lo", reg & 0xFF, v);
        }
        shadow_[reg] = v;
        if (reg >= 0x2D && reg <= 0x2F) shadow_[0x2D] = (uint8_t)reg;
        if (opt_.ev && tracing_) {
          Ev e; e.t = (uint32_t)(gen_count_ - k0_);
          e.reg = reg; e.val = v; e.pad = 0;
          ev_.push_back(e);
        }
        if (!hi) {
          if (reg == 0x28 && (v & 0xF0)) fm_on_++;
          else if (reg >= 0x08 && reg <= 0x0A && (v & 0x0F)) ssg_on_++;
          else if (reg == 0x10 && (v & 0x80)) adb_on_++;
        } else if (reg == 0x100 && !(v & 0x80) && (v & 0x3F)) ada_on_++;
        break;
      }
      case 0x08:
        nmi_en_ = true;
        if (nmi_pend_) { nmi_pend_ = false; z80_gen_nmi(&cpu_); }
        break;
      case 0x18: nmi_en_ = false; break;
      default: break;
    }
    trace('W', p, v);
  }
  void trace(char d, uint8_t p, uint8_t v) {
    if (opt_.trace > 0 && tracing_ && traced_ < opt_.trace && !(p >= 0x04 && p <= 0x07 && traced_ > 40)) {
      fprintf(stderr, "[%10lu] pc=%04X %c port %02X = %02X\n", cpu_.cyc, cpu_.pc, d, p, v);
      traced_++;
    }
  }

  Bytes m1_;
  const Bytes& va_;
  const Bytes& vb_;
  Options opt_;
  ymfm::ym2610 chip_;
  z80 cpu_;
  uint8_t ram_[0x800];
  uint32_t bank_[4];
  uint8_t latch_ = 0;
  bool nmi_en_ = false, nmi_pend_ = false, irq_ = false;
  int64_t timer_[2];
  int64_t next_sample_cyc_;
  int traced_ = 0;
  bool tracing_ = false;
  uint16_t caddr_ = 0;
  uint32_t k0_ = 0;
  uint64_t gen_count_ = 0;
  uint8_t shadow_[0x200] = {0};
  uint8_t snap_[0x200] = {0};
  std::vector<Ev> ev_;
  std::vector<Ev> raw_;
  uint8_t pcseen_[65536] = {0};
  unsigned long cmd_cyc_ = 0;
  uint32_t fp_ = 2166136261u; int fpn_ = 0;
  uint8_t addr_lo_ = 0, addr_hi_ = 0;
  int fm_on_ = 0, ssg_on_ = 0, ada_on_ = 0, adb_on_ = 0;
};

struct Result {
  int cmd;
  double first_sound_s = -1;  // relatif à l'envoi de la commande
  double length_s = 0;        // fin du dernier son audible
  double rendered_s = 0;
  bool ended = false;         // le son s'est terminé de lui-même (sinon : boucle / coupé par le plafond)
  int peak = 0;
  double rms = 0;
  size_t start_sample = 0;    // début dans le tampon (premier son)
  size_t end_sample = 0;
  int fm_on = 0, ssg_on = 0, ada_on = 0, adb_on = 0;
  uint32_t fp = 0; int fpn = 0;
  std::vector<Machine::Ev> events;
  uint8_t snap[0x200] = {0};
  uint32_t k0 = 0;
  std::vector<Machine::Ev> stream;
};

// rend une commande ; remplit 'pcm' (stéréo entrelacé) depuis l'envoi de la commande
static Result render_command(const Bytes& m1, const Bytes& va, const Bytes& vb, const Options& opt, int cmd,
                             double boot_s, double idle_s, double tail_s, double cap_s, std::vector<int16_t>* pcm) {
  Machine m(m1, va, vb, opt);
  m.run_samples((size_t)(boot_s * OUT_RATE), nullptr);
  for (int pc : opt.pre) {
    m.send_command((uint8_t)pc);
    m.run_samples((size_t)(opt.pre_delay * OUT_RATE), nullptr);
  }
  m.begin_capture();
  m.send_command((uint8_t)cmd);

  Result r;
  r.cmd = cmd;
  std::vector<int16_t> buf;
  buf.reserve((size_t)(std::min(cap_s, 20.0) * OUT_RATE) * 2);
  for (int pb : opt.post) {   // octets supplémentaires de la commande : l'audio produit pendant ce temps est conservé
    m.run_samples((size_t)(opt.post_delay * OUT_RATE), &buf);
    m.send_command_keep((uint8_t)pb);
  }
  const size_t win = OUT_RATE / 10;  // 0,1 s
  const size_t cap_win = (size_t)(cap_s * 10);
  const int SOUND_THR = 200, SIL_THR = 40;
  size_t quiet_wins = 0;
  size_t last_loud_win = 0;
  bool started = false;
  size_t w = 0;
  for (; w < cap_win; w++) {
    size_t before = buf.size();
    m.run_samples(win, &buf);
    int mx = 0;
    for (size_t i = before; i < buf.size(); i++) mx = std::max(mx, std::abs((int)buf[i]));
    r.peak = std::max(r.peak, mx);
    if (!started) {
      if (mx > SOUND_THR) { started = true; r.first_sound_s = w / 10.0; last_loud_win = w; quiet_wins = 0; }
      else if ((double)(w + 1) / 10.0 >= idle_s) { w++; break; }
    } else {
      if (mx > SIL_THR) { last_loud_win = w; quiet_wins = 0; }
      else { quiet_wins++; if (quiet_wins >= (size_t)(tail_s * 10)) { w++; r.ended = true; break; } }
    }
  }
  r.rendered_s = w / 10.0;
  if (started) {
    r.length_s = (last_loud_win + 1) / 10.0 - r.first_sound_s;
    if (w >= cap_win && !r.ended) r.ended = false;
    r.start_sample = (size_t)(r.first_sound_s * OUT_RATE) * 2;
    r.end_sample = std::min(buf.size(), (size_t)((last_loud_win + 1) / 10.0 * OUT_RATE) * 2);
    double acc = 0;
    size_t n = 0;
    for (size_t i = r.start_sample; i < r.end_sample; i += 2) { double v = buf[i]; acc += v * v; n++; }
    r.rms = n ? std::sqrt(acc / n) : 0;
  }
  r.fp = m.fp(); r.fpn = m.fpn();
  if (opt.ev) { r.events = m.events(); memcpy(r.snap, m.snap(), sizeof r.snap); r.k0 = m.k0(); }
  if (opt.stream) { r.stream = m.raw(); r.k0 = m.k0(); }
  if (opt.pcs) { const uint8_t* ps = m.pcseen(); for (int a = 0; a < 65536; a++) if (ps[a]) fprintf(stderr, "PC %04X\n", a); }
  r.fm_on = m.fm_on(); r.ssg_on = m.ssg_on(); r.ada_on = m.ada_on(); r.adb_on = m.adb_on();
  if (pcm) pcm->swap(buf);
  return r;
}

static void usage() {
  fprintf(stderr,
          "m1render --m1 M1.bin --va ADPCM_A.bin [--vb ADPCM_B.bin] (--cmd N | --sweep LO HI)\n"
          "         [--outdir DIR] [--keep all|music|N] [--boot S] [--idle S] [--tail S] [--cap S]\n"
          "         [--ssg-gain G] [--trace N] [--raw-from-start]\n"
          "  --cmd N       un seul code de commande son ; avec --outdir ecrit le PCM\n"
          "  --sweep LO HI balaye les codes ; une ligne JSON par code audible sur stdout\n"
          "  --keep        quels PCM ecrire : all | music (son qui ne s'arrete pas avant le plafond) | N (>= N secondes)\n"
          "Sortie PCM : stereo s16le @ %u Hz\n", OUT_RATE);
}

// ---------------------------------------------------------------------------------------------
// LZSS du jukebox (même algorithme, octet pour octet, que lzss_compress() de ngt_studio.py) :
//   --lzss-batch IN OUT : IN = suite de [u32 LE taille][données], OUT = suite de [u32 LE taille][compressé].
//   Une ligne "P n" (n = blocs terminés) est écrite sur stdout après chaque bloc (barre de progression).
static std::vector<uint8_t> lzss_compress(const uint8_t* data, size_t n) {
  std::vector<uint8_t> out;
  std::unordered_map<uint32_t, std::vector<int32_t>> heads;
  heads.reserve(n / 2 + 16);
  size_t i = 0, fpos = 0;
  bool have_f = false;
  int nb = 8;
  uint8_t fl = 0;
  auto key = [&](size_t p) { return (uint32_t)data[p] << 16 | (uint32_t)data[p + 1] << 8 | data[p + 2]; };
  while (i < n) {
    size_t bl = 0, bd = 0;
    if (i + 3 <= n) {
      size_t lim = std::min<size_t>(130, n - i);
      auto it = heads.find(key(i));
      size_t cnt = it == heads.end() ? 0 : it->second.size();
      for (size_t q = cnt; q-- > 0;) {
        size_t j = (size_t)it->second[q], d = i - j;
        if (d > 32768) break;
        if (bl >= 3 && data[j + bl] != data[i + bl]) continue;
        size_t l = 3;
        while (l < lim && data[j + l] == data[i + l]) l++;
        if (l > bl) {
          bl = l; bd = d;
          if (l == lim) break;
        }
      }
    }
    if (nb == 8) {
      if (have_f) out[fpos] = fl;
      fpos = out.size(); have_f = true; nb = 0; fl = 0;
      out.push_back(0);
    }
    size_t end;
    if (bl >= 4 || (bl == 3 && bd <= 4096)) {
      nb++;
      size_t d = bd - 1;
      if (bl <= 10 && bd <= 4096) {
        out.push_back((uint8_t)(((bl - 3) << 4) | (d >> 8)));
        out.push_back((uint8_t)(d & 0xFF));
      } else {
        out.push_back((uint8_t)(0x80 | (bl - 3)));
        out.push_back((uint8_t)(d >> 8));
        out.push_back((uint8_t)(d & 0xFF));
      }
      end = i + bl;
    } else {
      fl |= (uint8_t)(1 << nb);
      nb++;
      out.push_back(data[i]);
      end = i + 1;
    }
    for (; i < end; i++) {
      if (i + 3 <= n) {
        uint32_t k = key(i);
        std::vector<int32_t>& l = heads[k];
        l.push_back((int32_t)i);
        if (l.size() > 48) l.erase(l.begin(), l.begin() + 16);
      }
    }
  }
  if (have_f) out[fpos] = fl;
  return out;
}

static int lzss_batch(const char* inp, const char* outp) {
  FILE* f = xfopen(inp, "rb");
  if (!f) { fprintf(stderr, "cannot read %s\n", inp); return 1; }
  std::vector<uint8_t> in;
  uint8_t buf[65536];
  size_t r;
  while ((r = fread(buf, 1, sizeof buf, f)) > 0) in.insert(in.end(), buf, buf + r);
  fclose(f);
  FILE* o = xfopen(outp, "wb");
  if (!o) { fprintf(stderr, "cannot write %s\n", outp); return 1; }
  size_t p = 0;
  int done = 0;
  while (p + 4 <= in.size()) {
    uint32_t len = in[p] | in[p + 1] << 8 | in[p + 2] << 16 | (uint32_t)in[p + 3] << 24;
    p += 4;
    if (p + len > in.size()) { fprintf(stderr, "truncated input\n"); fclose(o); return 1; }
    std::vector<uint8_t> c = lzss_compress(in.data() + p, len);
    p += len;
    uint8_t h[4] = {(uint8_t)c.size(), (uint8_t)(c.size() >> 8), (uint8_t)(c.size() >> 16), (uint8_t)(c.size() >> 24)};
    fwrite(h, 1, 4, o);
    fwrite(c.data(), 1, c.size(), o);
    printf("P %d\n", ++done);
    fflush(stdout);
  }
  fclose(o);
  return 0;
}

int main(int argc, char** argv) {
#ifdef _WIN32
  // arguments en UTF-16 (CommandLineToArgvW) convertis en UTF-8 : aucun caractère du chemin n'est perdu
  static std::vector<std::string> u8args;
  static std::vector<char*> u8ptr;
  {
    int wc = 0;
    LPWSTR* wv = CommandLineToArgvW(GetCommandLineW(), &wc);
    if (wv) {
      for (int k = 0; k < wc; k++) {
        int n = WideCharToMultiByte(CP_UTF8, 0, wv[k], -1, nullptr, 0, nullptr, nullptr);
        std::string a(n > 0 ? n - 1 : 0, '\0');
        if (n > 1) WideCharToMultiByte(CP_UTF8, 0, wv[k], -1, &a[0], n, nullptr, nullptr);
        u8args.push_back(a);
      }
      LocalFree(wv);
      for (auto& a : u8args) u8ptr.push_back(&a[0]);
      u8ptr.push_back(nullptr);
      argc = wc;
      argv = u8ptr.data();
    }
  }
#endif
  if (argc == 4 && std::string(argv[1]) == "--lzss-batch") return lzss_batch(argv[2], argv[3]);
  const char *m1p = nullptr, *vap = nullptr, *vbp = nullptr, *outdir = ".";
  int lo = -1, hi = -1;
  double boot = 1.5, idle = 2.5, tail = 3.0, cap = 150.0;
  std::string keep = "music";
  Options opt;
  bool fp_mode = false;
  const char *replay_base = nullptr, *replay_out = nullptr;
  double replay_len = 0;
  for (int i = 1; i < argc; i++) {
    std::string a = argv[i];
    auto nx = [&](const char* name) -> const char* {
      if (i + 1 >= argc) { fprintf(stderr, "valeur manquante pour %s\n", name); exit(2); }
      return argv[++i];
    };
    if (a == "--m1") m1p = nx("--m1");
    else if (a == "--va") vap = nx("--va");
    else if (a == "--vb") vbp = nx("--vb");
    else if (a == "--cmd") { lo = hi = (int)strtol(nx("--cmd"), nullptr, 0); }
    else if (a == "--sweep") { lo = (int)strtol(nx("--sweep"), nullptr, 0); hi = (int)strtol(nx("--sweep"), nullptr, 0); }
    else if (a == "--outdir") outdir = nx("--outdir");
    else if (a == "--keep") keep = nx("--keep");
    else if (a == "--boot") boot = atof(nx("--boot"));
    else if (a == "--idle") idle = atof(nx("--idle"));
    else if (a == "--tail") tail = atof(nx("--tail"));
    else if (a == "--cap") cap = atof(nx("--cap"));
    else if (a == "--ssg-gain") opt.ssg_gain = atof(nx("--ssg-gain"));
    else if (a == "--trace") opt.trace = atoi(nx("--trace"));
    else if (a == "--fp") fp_mode = true;
    else if (a == "--ymlog") opt.ymlog = true;
    else if (a == "--pcs") opt.pcs = true;
    else if (a == "--ev") opt.ev = true;
    else if (a == "--stream") opt.stream = true;
    else if (a == "--replay") replay_base = nx("--replay");
    else if (a == "--replay-out") replay_out = nx("--replay-out");
    else if (a == "--replay-len") replay_len = atof(nx("--replay-len"));
    else if (a == "--pre") { std::string l = nx("--pre"); size_t p = 0; while (p < l.size()) { size_t q = l.find(',', p); if (q == std::string::npos) q = l.size(); opt.pre.push_back((int)strtol(l.substr(p, q - p).c_str(), nullptr, 0)); p = q + 1; } }
    else if (a == "--post") { std::string l = nx("--post"); size_t p = 0; while (p < l.size()) { size_t q = l.find(',', p); if (q == std::string::npos) q = l.size(); opt.post.push_back((int)strtol(l.substr(p, q - p).c_str(), nullptr, 0)); p = q + 1; } }
    else if (a == "--post-delay") opt.post_delay = atof(nx("--post-delay"));
    else if (a == "--pre-delay") opt.pre_delay = atof(nx("--pre-delay"));
    else { usage(); return 2; }
  }
  if (replay_base) {
    if (!vap || !replay_out) { usage(); return 2; }
    Bytes va, vb, stb;
    if (!load_file(vap, va)) { fprintf(stderr, "VROM A illisible: %s\n", vap); return 1; }
    if (vbp && !load_file(vbp, vb)) return 1;
    if (!load_file((std::string(replay_base) + ".stream").c_str(), stb) || stb.size() < 4) { fprintf(stderr, ".stream illisible\n"); return 1; }
    uint32_t k0v; memcpy(&k0v, stb.data(), 4);
    std::vector<Machine::Ev> evs((stb.size() - 4) / sizeof(Machine::Ev));
    memcpy(evs.data(), stb.data() + 4, evs.size() * sizeof(Machine::Ev));
    Bytes dummy(0x8000, 0);
    Machine m(dummy, va, vbp ? vb : va, opt);
    size_t total = (size_t)k0v + (size_t)(replay_len * OUT_RATE);
    std::vector<int16_t> out;
    m.replay(evs, k0v, total, out);
    FILE* f = xfopen(replay_out, "wb");
    if (!f) return 1;
    fwrite(out.data(), 2, out.size(), f); fclose(f);
    printf("{\"replay_samples\":%zu,\"events\":%zu,\"k0\":%u}\n", out.size() / 2, evs.size(), k0v);
    return 0;
  }
  if (!m1p || !vap || lo < 0) { usage(); return 2; }
  Bytes m1, va, vb;
  if (!load_file(m1p, m1)) { fprintf(stderr, "M1 illisible: %s\n", m1p); return 1; }
  if (!load_file(vap, va)) { fprintf(stderr, "VROM A illisible: %s\n", vap); return 1; }
  if (vbp) { if (!load_file(vbp, vb)) { fprintf(stderr, "VROM B illisible: %s\n", vbp); return 1; } }
  const Bytes& vbr = vbp ? vb : va;              // pas de ROM B séparée : ADPCM-B lit la V-ROM commune

  for (int c = lo; c <= hi; c++) {
    std::vector<int16_t> pcm;
    Result r = render_command(m1, va, vbr, opt, c, boot, idle, tail, cap, &pcm);
    if (fp_mode) printf("{\"cmd\":%d,\"fp\":\"%08x\",\"ymw\":%d,\"sound\":%s}\n", c, r.fp, r.fpn, r.first_sound_s >= 0 ? "true" : "false");
    if (r.first_sound_s < 0) {
      if (lo == hi) fprintf(stderr, "cmd 0x%02X : aucun son en %.1f s\n", c, idle);
      if (r.fm_on + r.ssg_on + r.ada_on + r.adb_on > 0)
        printf("{\"cmd\":%d,\"silent\":true,\"fm_on\":%d,\"ssg_on\":%d,\"ada_on\":%d,\"adb_on\":%d}\n",
               c, r.fm_on, r.ssg_on, r.ada_on, r.adb_on);
      continue;
    }
    bool is_music = !r.ended;
    bool write = false;
    if (keep == "all") write = true;
    else if (keep == "music") write = is_music;
    else write = r.length_s >= atof(keep.c_str());
    char path[1024] = "";
    if (write) {
      snprintf(path, sizeof path, "%s/cmd_%02X.raw", outdir, c);
      FILE* f = xfopen(path, "wb");
      if (f) {
        fwrite(pcm.data(), 2, r.end_sample, f);
        fclose(f);
      } else path[0] = 0;
    }
    if (write && opt.ev && path[0]) {
      char evp[1100]; snprintf(evp, sizeof evp, "%s/cmd_%02X.ev", outdir, c);
      FILE* fe = xfopen(evp, "wb");
      if (fe) { fwrite(r.events.data(), sizeof(Machine::Ev), r.events.size(), fe); fclose(fe); }
      if (opt.stream) {
        char stp[1100]; snprintf(stp, sizeof stp, "%s/cmd_%02X.stream", outdir, c);
        FILE* fs = xfopen(stp, "wb");
        if (fs) { fwrite(&r.k0, 4, 1, fs); fwrite(r.stream.data(), sizeof(Machine::Ev), r.stream.size(), fs); fclose(fs); }
      }
    }
    printf("{\"cmd\":%d,\"first_sound_s\":%.1f,\"length_s\":%.1f,\"ended\":%s,\"peak\":%d,\"rms\":%.0f,\"fm_on\":%d,\"ssg_on\":%d,\"ada_on\":%d,\"adb_on\":%d,\"file\":\"%s\"}\n",
           c, r.first_sound_s, r.length_s, r.ended ? "true" : "false", r.peak, r.rms, r.fm_on, r.ssg_on, r.ada_on, r.adb_on, path);
    fflush(stdout);
  }
  return 0;
}
