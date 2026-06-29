"""
lickometer_final.py  —  Lickometer GUI (single file)
Run:   python lickometer_final.py
Deps:  pip install pyserial matplotlib numpy

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ARDUINO SERIAL PROTOCOL  (from lickometer_risha_final.ino)

  Every line during streaming:
      timestamp_ms,id,amplitude
      e.g.  14523,0,12.4    ← board-0 right load, 12.4 g
            14650,8,1       ← ch-0 lick onset
            14780,16,0      ← ch-0 lick offset

  ID map:
      0-7   load cells   (0=brd0-right, 1=brd0-left, 2=brd1-right … 7=brd3-left)
      8-15  lick ONSET   (channels 0-7)
      16-23 lick OFFSET  (channels 0-7, i.e. onset_id + 8)

  Lines starting with '#' are comments/headers and are silently ignored.
  Everything else that doesn't match  digits,digits,number  is ignored.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Edit only the USER CONFIGURATION block below.
"""

# ══════════════════════════════════════════════════════════════════════════════
# USER CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

SERIAL_PORT     = "COM3"       # Linux/Mac: "/dev/ttyUSB0" or "/dev/cu.usbserial-…"
BAUD_RATE       = 115200

TIMEBIN_MS      = 50           # raster bin width in ms
GUI_REFRESH_MS  = 1000         # raster redraw interval in ms
SECONDS_PER_ROW = 60           # x-axis span per raster row (seconds)

# Map experiment 1-4 to Arduino channel IDs.
#   left/right lick onset IDs are 8-15; offset = onset + 8
#   load cell IDs are 0-7
#   Board 0 → Exp 1, Board 1 → Exp 2, etc.
#   right spout → even channel; left spout → odd channel
EXPERIMENT_CHANNELS = {
    1: {"left_onset": 9,  "right_onset": 8,  "left_load": 1, "right_load": 0},
    2: {"left_onset": 11, "right_onset": 10, "left_load": 3, "right_load": 2},
    3: {"left_onset": 13, "right_onset": 12, "left_load": 5, "right_load": 4},
    4: {"left_onset": 15, "right_onset": 14, "left_load": 7, "right_load": 6},
}

# ══════════════════════════════════════════════════════════════════════════════
# END USER CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

import threading, queue, time, re, datetime, os
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np

try:
    import serial as _serial
    _SERIAL_OK = True
except ImportError:
    _SERIAL_OK = False

# ── Derived ────────────────────────────────────────────────────────────────────
BINS_PER_ROW = (SECONDS_PER_ROW * 1000) // TIMEBIN_MS  # 1200 at defaults

# ── Palette (dark theme) ───────────────────────────────────────────────────────
BG      = "#1C1C1E"
BG_PNL  = "#2C2C2E"
BG_ALT  = "#3A3A3C"
FG      = "#F2F2F7"
FG_MUT  = "#8E8E93"
CLR_L   = "#FF6B6B"   # left lick / left load
CLR_R   = "#4DA6FF"   # right lick / right load
CLR_EXP = "#FFD60A"   # onset/offset markers
CLR_GRN = "#30D158"
CLR_RED = "#FF453A"

FONT    = ("Segoe UI", 9)
FONTB   = ("Segoe UI", 9, "bold")
FONTM   = ("Courier New", 9)

# ══════════════════════════════════════════════════════════════════════════════
# SERIAL READER
# ══════════════════════════════════════════════════════════════════════════════

_EVT_RE = re.compile(r"^(\d+),(\d+),([\d.+-]+)$")


class SerialReader:
    """
    Background thread reads Arduino serial output.
    Parsed events  → self.queue       {"ts":int,"id":int,"amp":float}
    Raw text lines → self.raw_queue   str   (for the terminal tab)
    Falls back to simulation if pyserial missing or port fails.
    """

    def __init__(self):
        self.queue     = queue.Queue()
        self.raw_queue = queue.Queue(maxsize=500)
        self._ser      = None
        self._running  = False
        self.sim_mode  = False
        self.port      = SERIAL_PORT
        self.baud      = BAUD_RATE

    def connect(self) -> bool:
        if not _SERIAL_OK:
            #self._start_sim()
            print("not okay")
            return False
        try:
            self._ser     = _serial.Serial(self.port, self.baud, timeout=1)
            self._running = True
            threading.Thread(target=self._read_loop, daemon=True).start()
            return True
        except Exception as e:
            print(f"[Serial] {e}")
            self._start_sim()
            return False

    def send(self, cmd: str):
        if self._ser and self._ser.is_open:
            self._ser.write((cmd + "\r\n").encode())
        self._push_raw(f">> {cmd}")

    def disconnect(self):
        self._running = False
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass

    # ── Internal ──────────────────────────────────────────────────────────────

    def _read_loop(self):
        while self._running:
            try:
                raw = self._ser.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="ignore").strip()
                self._push_raw(line)
                msg = self._parse(line)
                if msg:
                    self.queue.put(msg)
            except Exception as e:
                print(f"[Serial] {e}")
                time.sleep(0.1)

    def _parse(self, line: str):
        if line.startswith("#"):
            return None
        m = _EVT_RE.match(line)
        if m:
            return {"ts": int(m.group(1)), "id": int(m.group(2)),
                    "amp": float(m.group(3))}
        return None

    def _push_raw(self, line: str):
        try:
            self.raw_queue.put_nowait(line)
        except queue.Full:
            pass

    # ── Simulation ────────────────────────────────────────────────────────────

    def _start_sim(self):
        self.sim_mode = True
        self._running = True
        threading.Thread(target=self._sim_loop, daemon=True).start()

    def _sim_loop(self):
        import random, math
        t         = 0
        lick_on   = {i: False for i in range(8)}
        lick_rem  = {i: 0     for i in range(8)}
        load_base = [12000, 11500, 13000, 12800, 11200, 13500, 12200, 11800]
        load_tick = 0

        while self._running:
            t += 50
            for ch in range(8):
                on_id  = 8  + ch
                off_id = 16 + ch
                if lick_on[ch]:
                    lick_rem[ch] -= 50
                    if lick_rem[ch] <= 0:
                        lick_on[ch] = False
                        msg = {"ts": t, "id": off_id, "amp": 0.0}
                        self.queue.put(msg)
                        self._push_raw(f"{t},{off_id},0")
                else:
                    if random.random() < 0.015:
                        lick_on[ch]  = True
                        lick_rem[ch] = random.randint(100, 700)
                        msg = {"ts": t, "id": on_id, "amp": 1.0}
                        self.queue.put(msg)
                        self._push_raw(f"{t},{on_id},1")

            load_tick += 50
            if load_tick >= 200:
                load_tick = 0
                for ld in range(8):
                    val = load_base[ld] + math.sin(t / 9000) * 400 + random.gauss(0, 12)
                    self.queue.put({"ts": t, "id": ld, "amp": round(val, 1)})
                    self._push_raw(f"{t},{ld},{val:.1f}")

            time.sleep(0.05)

# ══════════════════════════════════════════════════════════════════════════════
# EXPERIMENT MODEL
# ══════════════════════════════════════════════════════════════════════════════

# Internal event IDs (saved to .npy — independent of Arduino IDs)
_EXP_ONSET  = 0;  _EXP_OFFSET  = 1
_L_ON       = 2;  _L_OFF       = 3
_R_ON       = 4;  _R_OFF       = 5
_L_LOAD     = 6;  _R_LOAD      = 7

_EVT_NAME = {
    _EXP_ONSET: "Exp onset",   _EXP_OFFSET: "Exp offset",
    _L_ON:      "L lick ON",   _L_OFF:      "L lick OFF",
    _R_ON:      "R lick ON",   _R_OFF:      "R lick OFF",
    _L_LOAD:    "L load",      _R_LOAD:     "R load",
}
_EVT_TAG = {
    _EXP_ONSET: "exp",  _EXP_OFFSET: "exp",
    _L_ON:      "left", _L_OFF:      "left",
    _R_ON:      "right",_R_OFF:      "right",
    _L_LOAD:    "load", _R_LOAD:     "load",
}


@dataclass
class EventRow:
    timestamp_ms: int
    event_id:     int
    amplitude:    float


class ExperimentModel:
    def __init__(self, exp_id: int):
        self.exp_id = exp_id
        ch = EXPERIMENT_CHANNELS[exp_id]
        self.l_on_id   = ch["left_onset"]
        self.r_on_id   = ch["right_onset"]
        self.l_off_id  = self.l_on_id  + 8
        self.r_off_id  = self.r_on_id  + 8
        self.l_load_id = ch["left_load"]
        self.r_load_id = ch["right_load"]

        self.cal_left:  float = 1.0
        self.cal_right: float = 1.0

        self._log:  List[EventRow] = []
        self._lock  = threading.Lock()
        self.running:  bool          = False
        self.start_ts: Optional[int] = None

    def owns(self, aid: int) -> bool:
        return aid in (self.l_on_id, self.r_on_id,
                       self.l_off_id, self.r_off_id,
                       self.l_load_id, self.r_load_id)

    def elapsed(self, ts: int) -> int:
        return max(0, ts - self.start_ts) if self.start_ts is not None else 0

    def add(self, ts_ms: int, eid: int, amp: float = 0.0):
        with self._lock:
            self._log.append(EventRow(ts_ms, eid, amp))

    def get_log(self) -> List[EventRow]:
        with self._lock:
            return list(self._log)

    def export_npy(self, path: str):
        log = self.get_log()
        if not log:
            return
        arr = np.array(
            [(r.timestamp_ms, r.event_id, r.amplitude) for r in log],
            dtype=[("timestamp_ms", np.int64),
                   ("event_id",     np.int8),
                   ("amplitude",    np.float32)])
        np.save(path, arr)

    def ingest(self, ts: int, aid: int, amp: float):
        if not self.running:
            return
        el = self.elapsed(ts)
        if   aid == self.l_on_id:  self.add(el, _L_ON,  1.0)
        elif aid == self.l_off_id: self.add(el, _L_OFF, 1.0)
        elif aid == self.r_on_id:  self.add(el, _R_ON,  1.0)
        elif aid == self.r_off_id: self.add(el, _R_OFF, 1.0)
        elif aid == self.l_load_id:self.add(el, _L_LOAD, amp * self.cal_left)
        elif aid == self.r_load_id:self.add(el, _R_LOAD, amp * self.cal_right)

    def start(self, ts: int):
        with self._lock:
            self._log.clear()
        self.start_ts = ts
        self.running  = True
        self.add(0, _EXP_ONSET)

    def stop(self, ts: int):
        if self.running:
            self.running = False
            self.add(self.elapsed(ts), _EXP_OFFSET)

# ══════════════════════════════════════════════════════════════════════════════
# RASTER PANEL
# ══════════════════════════════════════════════════════════════════════════════

class RasterPanel:
    """
    Matplotlib raster embedded in a Tk widget for one experiment.

    Lick events → filled BLOCKS from onset to offset (no gaps between bins).
    Load cell   → translucent shaded area + line, superimposed on top.
    Rows grow dynamically as recording extends past each minute.
    """

    def __init__(self, parent: tk.Widget, exp_id: int):
        self.exp_id = exp_id
        self._fig   = Figure(figsize=(6, 2.6), dpi=96, facecolor=BG_PNL)
        self._ax    = self._fig.add_subplot(111)
        self._fig.subplots_adjust(left=0.06, right=0.99, top=0.90, bottom=0.20)
        self._canvas = FigureCanvasTkAgg(self._fig, master=parent)
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._style_ax(self._ax, 1)
        self._canvas.draw_idle()

    def update(self, events: List[EventRow]):
        ax = self._ax
        ax.cla()

        if not events:
            self._style_ax(ax, 1)
            self._canvas.draw_idle()
            return

        max_ms = max(e.timestamp_ms for e in events)
        n_rows = max(1, int(np.ceil(max_ms / (SECONDS_PER_ROW * 1000))))
        self._style_ax(ax, n_rows)

        # Alternating row backgrounds
        for r in range(n_rows):
            if r % 2 == 1:
                ax.axhspan(r, r + 1, color=BG_ALT, zorder=0, linewidth=0)

        # ── Filled lick blocks ─────────────────────────────────────────────────
        for on_eid, off_eid, color in ((_L_ON, _L_OFF, CLR_L),
                                        (_R_ON, _R_OFF, CLR_R)):
            on_times  = sorted(e.timestamp_ms for e in events if e.event_id == on_eid)
            off_times = sorted(e.timestamp_ms for e in events if e.event_id == off_eid)

            off_pool = list(off_times)
            pairs: List[Tuple[int, int]] = []
            for on in on_times:
                nxt = next((o for o in off_pool if o >= on), None)
                if nxt is None:
                    nxt = on + TIMEBIN_MS       # still touching → 1 bin minimum
                else:
                    off_pool.remove(nxt)
                pairs.append((on, nxt))

            for on_ms, off_ms in pairs:
                t = on_ms
                row_ms = SECONDS_PER_ROW * 1000
                while t < off_ms:
                    row     = t // row_ms
                    row_end = (row + 1) * row_ms
                    seg_end = min(off_ms, row_end)
                    x0 = (t       % row_ms) / TIMEBIN_MS
                    x1 = (seg_end % row_ms) / TIMEBIN_MS
                    if x1 == 0:
                        x1 = BINS_PER_ROW        # segment ends at row boundary
                    ax.fill_betweenx([row, row + 0.78],
                                     x0, x1,
                                     color=color, alpha=0.92,
                                     linewidth=0, zorder=3)
                    t = seg_end

        # ── Experiment onset / offset markers ──────────────────────────────────
        row_ms = SECONDS_PER_ROW * 1000
        for evt in events:
            if evt.event_id not in (_EXP_ONSET, _EXP_OFFSET):
                continue
            row   = evt.timestamp_ms // row_ms
            bin_x = (evt.timestamp_ms % row_ms) // TIMEBIN_MS
            ax.plot([bin_x, bin_x], [row, row + 0.95],
                    color=CLR_EXP, linewidth=1.8, zorder=5)

        # ── Load cell area plots ───────────────────────────────────────────────
        for load_eid, color in ((_L_LOAD, CLR_L), (_R_LOAD, CLR_R)):
            evts = [e for e in events if e.event_id == load_eid]
            if len(evts) < 2:
                continue
            amps = np.array([e.amplitude for e in evts])
            mn, mx = amps.min(), amps.max()
            if mx == mn:
                continue
            norm = (amps - mn) / (mx - mn)

            by_row: Dict[int, List[Tuple[float, float]]] = {}
            for e, n in zip(evts, norm):
                r  = e.timestamp_ms // row_ms
                bx = (e.timestamp_ms % row_ms) / TIMEBIN_MS
                by_row.setdefault(r, []).append((bx, n))

            for r, pts in by_row.items():
                xs = np.array([p[0] for p in pts])
                ys = np.array([p[1] for p in pts]) * 0.65 + r
                ax.fill_between(xs, r, ys,
                                color=color, alpha=0.18, linewidth=0, zorder=2)
                ax.plot(xs, ys, color=color, alpha=0.50,
                        linewidth=0.9, zorder=2)

        self._canvas.draw_idle()

    def save_png(self, path: str):
        self._fig.savefig(path, dpi=150, bbox_inches="tight",
                          facecolor=self._fig.get_facecolor())

    def _style_ax(self, ax, n_rows: int):
        ax.set_facecolor(BG_PNL)
        for sp in ax.spines.values():
            sp.set_color(BG_ALT)
        ax.tick_params(colors=FG_MUT, labelsize=6)

        x_ticks  = np.arange(0, BINS_PER_ROW + 1, 10_000 // TIMEBIN_MS)
        x_labels = [str(int(t * TIMEBIN_MS / 1000)) for t in x_ticks]
        ax.set_xticks(x_ticks)
        ax.set_xticklabels(x_labels, fontsize=6, color=FG_MUT)
        ax.set_xlim(0, BINS_PER_ROW)
        ax.set_xlabel("s", fontsize=6, color=FG_MUT, labelpad=1)

        ax.set_ylim(0, n_rows)
        ax.set_yticks(np.arange(n_rows) + 0.5)
        ax.set_yticklabels([f"m{r + 1}" for r in range(n_rows)],
                           fontsize=6, color=FG_MUT)

        ax.set_title(f"Exp {self.exp_id}", fontsize=8, color=FG,
                     pad=3, loc="left")
        ax.legend(
            handles=[
                mpatches.Patch(color=CLR_L,          label="L lick"),
                mpatches.Patch(color=CLR_R,          label="R lick"),
                mpatches.Patch(color=CLR_L, alpha=.4, label="L load"),
                mpatches.Patch(color=CLR_R, alpha=.4, label="R load"),
                mpatches.Patch(color=CLR_EXP,        label="Onset/Off"),
            ],
            loc="upper right", fontsize=5, framealpha=0.25,
            facecolor=BG_PNL, edgecolor=BG_ALT, labelcolor=FG,
        )


# ══════════════════════════════════════════════════════════════════════════════
# EXPERIMENT QUADRANT  (one of four panes in the main view)
# ══════════════════════════════════════════════════════════════════════════════

class ExpQuadrant(tk.Frame):
    def __init__(self, master, model: ExperimentModel,
                 reader: SerialReader, arduino_ts: list):
        super().__init__(master, bg=BG_PNL,
                         highlightbackground=BG_ALT, highlightthickness=1)
        self.model        = model
        self._reader      = reader
        self._arduino_ts  = arduino_ts
        self._refresh_job = None
        self._shown       = 0
        self._build()

    def _build(self):
        # Top bar
        top = tk.Frame(self, bg=BG_PNL, pady=3)
        top.pack(fill=tk.X, padx=4)

        tk.Label(top, text=f"Experiment {self.model.exp_id}",
                 font=FONTB, bg=BG_PNL, fg=FG).pack(side=tk.LEFT, padx=6)

        self._run_btn = tk.Button(
            top, text="▶ Run", font=FONTB,
            bg=CLR_GRN, fg="white", activebackground="#25A244",
            relief=tk.FLAT, padx=8, pady=2, command=self._run)
        self._run_btn.pack(side=tk.LEFT, padx=4)

        self._stop_btn = tk.Button(
            top, text="⏹ Stop & Save", font=FONTB,
            bg=CLR_RED, fg="white", activebackground="#CC3730",
            relief=tk.FLAT, padx=8, pady=2,
            state=tk.DISABLED, command=self._stop_and_save)
        self._stop_btn.pack(side=tk.LEFT, padx=4)

        self._status = tk.StringVar(value="Idle")
        tk.Label(top, textvariable=self._status,
                 font=FONT, bg=BG_PNL, fg=FG_MUT).pack(side=tk.LEFT, padx=10)

        # Raster plot
        plot_frame = tk.Frame(self, bg=BG_PNL)
        plot_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self._raster = RasterPanel(plot_frame, self.model.exp_id)

        # Compact event log
        log_outer = tk.Frame(self, bg=BG_PNL, height=108)
        log_outer.pack(fill=tk.X, padx=2, pady=(0, 2))
        log_outer.pack_propagate(False)

        # Apply ttk style once globally
        s = ttk.Style()
        s.theme_use("default")
        for widget, cfg in (
                ("Treeview",
                 dict(background=BG, foreground=FG, fieldbackground=BG,
                      rowheight=16, font=FONTM)),
                ("Treeview.Heading",
                 dict(background=BG_PNL, foreground=FG_MUT, font=FONTB))):
            s.configure(widget, **cfg)
        s.map("Treeview", background=[("selected", BG_ALT)])

        cols = ("ts", "id", "event", "amp")
        self._tree = ttk.Treeview(log_outer, columns=cols,
                                   show="headings", height=5)
        for c, w, lbl in (("ts", 72, "ms"), ("id", 36, "ID"),
                           ("event", 95, "Event"), ("amp", 60, "Amp")):
            self._tree.heading(c, text=lbl)
            self._tree.column(c, width=w, anchor=tk.CENTER)

        sb = ttk.Scrollbar(log_outer, orient=tk.VERTICAL,
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(fill=tk.BOTH, expand=True)

        self._tree.tag_configure("left",  foreground=CLR_L)
        self._tree.tag_configure("right", foreground=CLR_R)
        self._tree.tag_configure("exp",   foreground=CLR_EXP)
        self._tree.tag_configure("load",  foreground=FG_MUT)

    # ── Controls ──────────────────────────────────────────────────────────────

    def _run(self):
        if not self.model.running:
            self.model.start(self._arduino_ts[0])
            self._run_btn.config(state=tk.DISABLED)
            self._stop_btn.config(state=tk.NORMAL)
            self._shown = 0
            self._schedule()

    def _stop_and_save(self):
        if self.model.running:
            self.model.stop(self._arduino_ts[0])
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        self._refresh()  # final flush

        stem = f"exp{self.model.exp_id}_{datetime.datetime.now():%Y%m%d_%H%M%S}"
        npy = filedialog.asksaveasfilename(
            title=f"Save Exp {self.model.exp_id} event log",
            initialfile=stem + ".npy",
            defaultextension=".npy",
            filetypes=[("NumPy", "*.npy")])
        if npy:
            self.model.export_npy(npy)
            png = os.path.splitext(npy)[0] + ".png"
            self._raster.save_png(png)
            messagebox.showinfo("Saved",
                f"Log  → {npy}\nPlot → {png}")

        self._run_btn.config(state=tk.NORMAL)
        self._stop_btn.config(state=tk.DISABLED)
        self._status.set("Stopped")

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _schedule(self):
        self._refresh_job = self.after(GUI_REFRESH_MS, self._tick)

    def _tick(self):
        self._refresh()
        if self.model.running:
            self._schedule()

    def _refresh(self):
        events = self.model.get_log()
        self._raster.update(events)

        for e in events[self._shown:]:
            name = _EVT_NAME.get(e.event_id, f"#{e.event_id}")
            tag  = _EVT_TAG.get(e.event_id, "")
            self._tree.insert("", tk.END,
                              values=(e.timestamp_ms, e.event_id,
                                      name, f"{e.amplitude:.1f}"),
                              tags=(tag,))
        self._shown = len(events)
        if events:
            self._tree.yview_moveto(1.0)

        if self.model.running and self.model.start_ts is not None:
            el = (self._arduino_ts[0] - self.model.start_ts) / 1000
            self._status.set(f"● {el:.0f} s")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN WINDOW
# ══════════════════════════════════════════════════════════════════════════════

class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Lickometer  ·  Columbia AIC")
        self.configure(bg=BG)
        self.geometry("1440x920")

        self._reader     = SerialReader()
        self._models     = {i: ExperimentModel(i) for i in range(1, 5)}
        self._arduino_ts = [0]
        self._connected  = False
        self._streaming  = False
        self._last_raw:  Dict[int, float] = {}   # {arduino_id: last_amp}
        self._snaps:     Dict[tuple, float] = {} # {(load_id, "50g"|"bottle"): val}

        self._build()

    # ══════════════════════════════════════════════════════════════════════════
    # LAYOUT
    # ══════════════════════════════════════════════════════════════════════════

    def _build(self):
        # Top strip
        top_strip = tk.Frame(self, bg=BG_PNL, pady=5)
        top_strip.pack(fill=tk.X)
        self._build_top_strip(top_strip)

        # Notebook
        s = ttk.Style()
        s.configure("TNotebook",     background=BG,     borderwidth=0)
        s.configure("TNotebook.Tab", background=BG_PNL, foreground=FG_MUT,
                    padding=[12, 4], font=FONTB)
        s.map("TNotebook.Tab",
              background=[("selected", BG_ALT)],
              foreground=[("selected", FG)])

        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        exp_tab  = tk.Frame(nb, bg=BG);  nb.add(exp_tab,  text="  Experiments  ")
        cal_tab  = tk.Frame(nb, bg=BG);  nb.add(cal_tab,  text="  Calibration  ")
        term_tab = tk.Frame(nb, bg=BG);  nb.add(term_tab, text="  Terminal  ")

        self._build_quad_tab(exp_tab)
        self._build_cal_tab(cal_tab)
        self._build_terminal_tab(term_tab)

    # ── Top strip ─────────────────────────────────────────────────────────────

    def _build_top_strip(self, parent):
        def lbl(text):
            return tk.Label(parent, text=text, font=FONT, bg=BG_PNL, fg=FG)

        def btn(text, cmd, bg=BG_ALT, fg=FG, **kw):
            return tk.Button(parent, text=text, command=cmd,
                             font=FONTB, bg=bg, fg=fg,
                             activebackground=BG, relief=tk.FLAT,
                             padx=10, pady=3, **kw)

        lbl("Port:").pack(side=tk.LEFT, padx=(12, 4))
        self._port_var = tk.StringVar(value=SERIAL_PORT)
        tk.Entry(parent, textvariable=self._port_var, width=14,
                 font=FONTM, bg=BG_ALT, fg=FG,
                 insertbackground=FG, relief=tk.FLAT
                 ).pack(side=tk.LEFT, padx=4)

        self._conn_btn = btn("Connect", self._toggle_connect)
        self._conn_btn.pack(side=tk.LEFT, padx=6)

        self._conn_lbl = tk.Label(parent, text="⚫ Disconnected",
                                   font=FONT, bg=BG_PNL, fg=FG_MUT)
        self._conn_lbl.pack(side=tk.LEFT, padx=10)

        tk.Frame(parent, bg=FG_MUT, width=1, height=22
                 ).pack(side=tk.LEFT, padx=12, fill=tk.Y)

        lbl("Weight report interval (s):").pack(side=tk.LEFT, padx=(0, 4))
        self._interval_var = tk.StringVar(value="30")
        tk.Spinbox(parent, from_=10, to=99999,
                   textvariable=self._interval_var,
                   width=7, font=FONTM, bg=BG_ALT, fg=FG,
                   buttonbackground=BG_ALT, relief=tk.FLAT
                   ).pack(side=tk.LEFT, padx=4)
        btn("Set", self._send_interval).pack(side=tk.LEFT, padx=4)

        tk.Frame(parent, bg=FG_MUT, width=1, height=22
                 ).pack(side=tk.LEFT, padx=12, fill=tk.Y)

        self._stream_btn = tk.Button(
            parent, text="▶ Start Arduino stream", font=FONTB,
            bg=CLR_GRN, fg="white", activebackground="#25A244",
            relief=tk.FLAT, padx=10, pady=3,
            state=tk.DISABLED, command=self._toggle_stream)
        self._stream_btn.pack(side=tk.LEFT, padx=6)

        self._ts_lbl = tk.Label(parent, text="ts: —",
                                 font=FONTM, bg=BG_PNL, fg=FG_MUT)
        self._ts_lbl.pack(side=tk.RIGHT, padx=16)

    # ── Tab: Experiments (4 quadrants) ────────────────────────────────────────

    def _build_quad_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        positions = {1: (0, 0), 2: (0, 1), 3: (1, 0), 4: (1, 1)}
        for exp_id, (row, col) in positions.items():
            q = ExpQuadrant(parent, self._models[exp_id],
                            self._reader, self._arduino_ts)
            q.grid(row=row, column=col, sticky="nsew", padx=3, pady=3)

    # ── Tab: Calibration ──────────────────────────────────────────────────────

    def _build_cal_tab(self, parent):
        sc = tk.Canvas(parent, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=sc.yview)
        sc.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        sc.pack(fill=tk.BOTH, expand=True)
        body = tk.Frame(sc, bg=BG)
        sc.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>",
                  lambda e: sc.configure(scrollregion=sc.bbox("all")))

        def section(title, subtitle=""):
            tk.Label(body, text=title, font=FONTB, bg=BG, fg=FG
                     ).pack(anchor="w", padx=16, pady=(16, 1))
            if subtitle:
                tk.Label(body, text=subtitle, font=FONT, bg=BG, fg=FG_MUT
                         ).pack(anchor="w", padx=16, pady=(0, 4))
            f = tk.Frame(body, bg=BG_PNL, padx=14, pady=10)
            f.pack(fill=tk.X, padx=16, pady=(0, 4))
            return f

        # ── Hardware calibration ──────────────────────────────────────────────
        hw = section("Hardware calibration",
                     "Sends commands directly to the Arduino.")

        def hw_row(r, label, btn_text, cmd_fn):
            tk.Label(hw, text=label, font=FONT, bg=BG_PNL, fg=FG
                     ).grid(row=r, column=0, sticky="w", pady=5, padx=(0, 16))
            tk.Button(hw, text=btn_text, font=FONTB,
                      bg=BG_ALT, fg=FG, relief=tk.FLAT, padx=8,
                      command=cmd_fn
                      ).grid(row=r, column=1, sticky="w", padx=4)

        hw_row(0, "Offset calibration — all channels, bottles must be empty:",
               "Send 'o'", lambda: self._reader.send("o"))
        hw_row(1, "Gain calibration — all channels, 50g on each bottle:",
               "Send 'cg' (all)", lambda: self._reader.send("cg"))
        hw_row(3, "Touch sensor calibration:",
               "Send 't'", lambda: self._reader.send("t"))

        tk.Label(hw, text="Gain calibration — single channel (0-7):",
                 font=FONT, bg=BG_PNL, fg=FG
                 ).grid(row=2, column=0, sticky="w", pady=5, padx=(0, 16))
        self._gcal_ch = tk.StringVar(value="0")
        tk.Spinbox(hw, from_=0, to=7, textvariable=self._gcal_ch,
                   width=4, font=FONTM, bg=BG_ALT, fg=FG, relief=tk.FLAT
                   ).grid(row=2, column=1, sticky="w", padx=4)
        tk.Button(hw, text="Send 'kg'", font=FONTB,
                  bg=BG_ALT, fg=FG, relief=tk.FLAT, padx=8,
                  command=lambda: self._reader.send(f"k{self._gcal_ch.get()}g")
                  ).grid(row=2, column=2, sticky="w", padx=4)

        # ── Touch thresholds ──────────────────────────────────────────────────
        th = section("Touch sensitivity thresholds",
                     "Per channel (0-7). Range 20-255, default 130. "
                     "Persisted in Arduino EEPROM.")
        self._thresh_vars: Dict[int, tk.StringVar] = {}
        for ch in range(8):
            r, c = divmod(ch, 4)
            tk.Label(th, text=f"Ch {ch}:", font=FONT, bg=BG_PNL, fg=FG
                     ).grid(row=r, column=c * 3, padx=(10, 2), pady=4, sticky="e")
            v = tk.StringVar(value="130")
            self._thresh_vars[ch] = v
            tk.Spinbox(th, from_=20, to=255, textvariable=v, width=5,
                       font=FONTM, bg=BG_ALT, fg=FG, relief=tk.FLAT
                       ).grid(row=r, column=c * 3 + 1, padx=2)
            tk.Button(th, text="Set", font=FONTB,
                      bg=BG_ALT, fg=FG, relief=tk.FLAT, padx=6,
                      command=lambda ch=ch: self._set_threshold(ch)
                      ).grid(row=r, column=c * 3 + 2, padx=4)

        # ── Software load-cell calibration ────────────────────────────────────
        lc = section("Load cell software calibration",
                     "1. Place 50g reference on bottle → Snap 50g.\n"
                     "2. Remove reference, use actual bottle → Snap Bottle.\n"
                     "Ratio = 50g_raw ÷ bottle_raw.  Applied to all load readings.")
        grid = tk.Frame(lc, bg=BG_PNL)
        grid.pack(fill=tk.X)

        for col, hd in enumerate(["Exp", "Side", "Arduino ID",
                                   "50g raw", "", "Bottle raw", "", "Ratio"]):
            tk.Label(grid, text=hd, font=FONTB, bg=BG_PNL, fg=FG_MUT
                     ).grid(row=0, column=col, padx=6, pady=3, sticky="w")

        self._snap_svars: Dict[tuple, tk.StringVar] = {}
        r = 1
        for exp_id in range(1, 5):
            ch = EXPERIMENT_CHANNELS[exp_id]
            for side, load_id in (("Left",  ch["left_load"]),
                                   ("Right", ch["right_load"])):
                key = (exp_id, side)
                for col, txt in ((0, str(exp_id)), (1, side),
                                  (2, f"id {load_id}")):
                    tk.Label(grid, text=txt, font=FONTM if col == 2 else FONT,
                             bg=BG_PNL,
                             fg=FG_MUT if col == 2 else FG
                             ).grid(row=r, column=col, padx=6)

                for ci, snap_key in enumerate(("50g", "bottle")):
                    sv = tk.StringVar(value="—")
                    self._snap_svars[(exp_id, side, snap_key)] = sv
                    tk.Label(grid, textvariable=sv, font=FONTM,
                             bg=BG_PNL, fg=FG, width=10
                             ).grid(row=r, column=3 + ci * 2, padx=4)
                    lbl_txt = "Snap 50g" if ci == 0 else "Snap Bottle"
                    tk.Button(grid, text=lbl_txt, font=FONTB,
                              bg=BG_ALT, fg=FG, relief=tk.FLAT, padx=6,
                              command=lambda k=key, sk=snap_key, lid=load_id:
                                      self._snap(k, sk, lid)
                              ).grid(row=r, column=4 + ci * 2, padx=2)

                sv_r = tk.StringVar(value="—")
                self._snap_svars[(exp_id, side, "ratio")] = sv_r
                tk.Label(grid, textvariable=sv_r, font=FONTM,
                         bg=BG_PNL, fg=CLR_GRN
                         ).grid(row=r, column=7, padx=8)
                r += 1

    # ── Tab: Terminal ─────────────────────────────────────────────────────────

    def _build_terminal_tab(self, parent):
        tk.Label(parent,
                 text="Raw serial terminal — all Arduino output appears here. "
                      "You can also type commands directly.",
                 font=FONT, bg=BG, fg=FG_MUT
                 ).pack(anchor="w", padx=12, pady=6)

        self._term_text = tk.Text(parent, bg=BG_PNL, fg=FG,
                                   font=FONTM, relief=tk.FLAT,
                                   state=tk.DISABLED, wrap=tk.NONE)
        tsb_v = ttk.Scrollbar(parent, orient=tk.VERTICAL,
                               command=self._term_text.yview)
        tsb_h = ttk.Scrollbar(parent, orient=tk.HORIZONTAL,
                               command=self._term_text.xview)
        self._term_text.configure(yscrollcommand=tsb_v.set,
                                   xscrollcommand=tsb_h.set)
        tsb_v.pack(side=tk.RIGHT, fill=tk.Y)
        tsb_h.pack(side=tk.BOTTOM, fill=tk.X)
        self._term_text.pack(fill=tk.BOTH, expand=True, padx=6)

        cmd_row = tk.Frame(parent, bg=BG, pady=4)
        cmd_row.pack(fill=tk.X, padx=6)
        tk.Label(cmd_row, text="Send:", font=FONT, bg=BG, fg=FG
                 ).pack(side=tk.LEFT, padx=(0, 4))
        self._cmd_var = tk.StringVar()
        cmd_ent = tk.Entry(cmd_row, textvariable=self._cmd_var, width=32,
                           font=FONTM, bg=BG_PNL, fg=FG,
                           insertbackground=FG, relief=tk.FLAT)
        cmd_ent.pack(side=tk.LEFT, padx=4)
        cmd_ent.bind("<Return>", lambda _: self._send_raw_cmd())
        tk.Button(cmd_row, text="Send", font=FONTB,
                  bg=BG_ALT, fg=FG, relief=tk.FLAT, padx=8,
                  command=self._send_raw_cmd
                  ).pack(side=tk.LEFT, padx=4)
        tk.Button(cmd_row, text="Clear", font=FONTB,
                  bg=BG_ALT, fg=FG_MUT, relief=tk.FLAT, padx=8,
                  command=self._clear_terminal
                  ).pack(side=tk.LEFT, padx=4)

        self.after(300, self._poll_terminal)

    # ══════════════════════════════════════════════════════════════════════════
    # ACTIONS
    # ══════════════════════════════════════════════════════════════════════════

    def _toggle_connect(self):
        if not self._connected:
            self._reader.port = self._port_var.get().strip()
            ok = self._reader.connect()
            self._connected = True
            self._conn_btn.config(text="Disconnect")
            self._conn_lbl.config(
                text="🟢 Connected" if ok else "🟡 Simulation mode",
                fg=CLR_GRN if ok else CLR_EXP)
            self._stream_btn.config(state=tk.NORMAL)
            self._start_dispatch()
        else:
            if self._streaming:
                self._toggle_stream()
            self._reader.disconnect()
            self._connected  = False
            self._conn_btn.config(text="Connect")
            self._conn_lbl.config(text="⚫ Disconnected", fg=FG_MUT)
            self._stream_btn.config(state=tk.DISABLED)

    def _send_interval(self):
        try:
            n = int(self._interval_var.get())
            if not 10 <= n <= 99999:
                raise ValueError
        except ValueError:
            messagebox.showerror("Bad interval", "Must be 10–99999 seconds.")
            return
        self._reader.send(f"i{n}")

    def _toggle_stream(self):
        if not self._streaming:
            self._reader.send("r")
            self._streaming = True
            self._stream_btn.config(text="⏹ Stop Arduino stream",
                                     bg=CLR_RED, activebackground="#CC3730")
        else:
            self._reader.send("s")
            self._streaming = False
            self._stream_btn.config(text="▶ Start Arduino stream",
                                     bg=CLR_GRN, activebackground="#25A244")

    def _set_threshold(self, ch: int):
        try:
            n = int(self._thresh_vars[ch].get())
            if not 20 <= n <= 255:
                raise ValueError
        except ValueError:
            messagebox.showerror("Bad threshold", "Must be 20–255.")
            return
        # Arduino: send "s<ch>\r\n" then value "\r\n"
        self._reader.send(f"s{ch}")
        self.after(200, lambda: self._reader.send(str(n)))

    def _snap(self, key: tuple, snap_key: str, load_id: int):
        raw = self._last_raw.get(load_id)
        if raw is None:
            messagebox.showwarning("No data",
                f"No reading yet for load ID {load_id}. "
                "Start the Arduino stream first.")
            return
        self._snaps[(load_id, snap_key)] = raw
        exp_id, side = key
        self._snap_svars[(exp_id, side, snap_key)].set(f"{raw:.1f}")

        v50  = self._snaps.get((load_id, "50g"))
        vbot = self._snaps.get((load_id, "bottle"))
        if v50 is not None and vbot is not None and vbot != 0:
            ratio = v50 / vbot
            self._snap_svars[(exp_id, side, "ratio")].set(f"{ratio:.5f}")
            m = self._models[exp_id]
            if side == "Left":
                m.cal_left  = ratio
            else:
                m.cal_right = ratio

    def _send_raw_cmd(self):
        cmd = self._cmd_var.get().strip()
        if cmd:
            self._reader.send(cmd)
            self._cmd_var.set("")

    def _clear_terminal(self):
        self._term_text.config(state=tk.NORMAL)
        self._term_text.delete("1.0", tk.END)
        self._term_text.config(state=tk.DISABLED)

    # ══════════════════════════════════════════════════════════════════════════
    # BACKGROUND DISPATCH
    # ══════════════════════════════════════════════════════════════════════════

    def _start_dispatch(self):
        threading.Thread(target=self._dispatch_loop, daemon=True).start()
        self.after(500, self._poll_ts_label)

    def _dispatch_loop(self):
        while self._connected:
            try:
                msg = self._reader.queue.get(timeout=0.2)
            except queue.Empty:
                continue
            ts  = msg["ts"]
            aid = msg["id"]
            amp = msg["amp"]
            self._arduino_ts[0] = ts
            self._last_raw[aid] = amp
            for model in self._models.values():
                if model.owns(aid):
                    model.ingest(ts, aid, amp)

    def _poll_ts_label(self):
        self._ts_lbl.config(text=f"ts: {self._arduino_ts[0]}")
        self.after(500, self._poll_ts_label)

    def _poll_terminal(self):
        lines = []
        try:
            while True:
                lines.append(self._reader.raw_queue.get_nowait())
        except queue.Empty:
            pass
        if lines:
            self._term_text.config(state=tk.NORMAL)
            self._term_text.insert(tk.END, "\n".join(lines) + "\n")
            self._term_text.see(tk.END)
            # cap terminal at ~2000 lines
            n = int(self._term_text.index("end-1c").split(".")[0])
            if n > 2000:
                self._term_text.delete("1.0", f"{n - 1500}.0")
            self._term_text.config(state=tk.DISABLED)
        self.after(200, self._poll_terminal)


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    MainWindow().mainloop()
