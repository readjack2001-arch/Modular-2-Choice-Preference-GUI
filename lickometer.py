"""
lickometer.py  —  Lickometer GUI system (single file)
python lickometer.py

Install:  pip install pyserial matplotlib numpy

────────────────────────────────────────────────────────────────────────────────
ARDUINO SERIAL PROTOCOL
  The Arduino must send newline-terminated lines in these formats:

    SENSOR,<pin_id>,<value>,<timestamp_ms>
        Touch sensor pins  → value is 0 or 1  (boolean, 1 = touching)
        Load cell pins     → value is a float  (raw ADC counts)
    TS,<arduino_millis>
        Heartbeat, sent every ~1 second

  Everything else is silently ignored (handy for debug prints).
  Example:
      SENSOR,CH0,1,14523      ← left lick channel of exp 1 just touched
      SENSOR,CH4,12045.3,14523 ← left load cell of exp 1
      TS,15000

────────────────────────────────────────────────────────────────────────────────
EDIT THE SECTION MARKED "USER CONFIGURATION" BELOW — nowhere else needed.

# ══════════════════════════════════════════════════════════════════════════════
# USER CONFIGURATION  ← only section you need to touch
# ══════════════════════════════════════════════════════════════════════════════
"""
SERIAL_PORT       = "COM3"      # e.g. "/dev/ttyUSB0" on Linux/Mac

TIMEBIN_MS        = 50          # raster bin width (ms)
LOAD_CELL_POLL_MS = 50          # record load cell every N ms
GUI_REFRESH_MS    = 5000        # raster redraws every N ms
TIMESTAMP_POLL_MS = 1000        # Arduino heartbeat interval (ms) — informational

SECONDS_PER_ROW   = 60          # x-axis width of each raster row (seconds)

# Spike heights in the raster plot
SPIKE_HEIGHT_EXP  = 2           # onset / offset markers
SPIKE_HEIGHT_LICK = 1           # lick onset / offset

# Pin IDs — must match exactly what the Arduino sends as <pin_id>
# Fill in your real channel names; placeholders shown here.
EXPERIMENT_PINS = {
    1: {"left_lick": "9",  "right_lick": "8",
        "left_load": "1",  "right_load": "0"},
    2: {"left_lick": "11",  "right_lick": "10",
        "left_load": "3",  "right_load": "2"},
    3: {"left_lick": "13",  "right_lick": "12",
        "left_load": "5", "right_load": "4"},
    4: {"left_lick": "15", "right_lick": "14",
        "left_load": "7", "right_load": "6"},
}
"""// events
// 0 = board 0 right load (0)
// 1 = board 0 left load (1)
// 2 = board 1 right load (2)
// 3 = board 1 left load (3)
// 4 = board 2 right load (4)
// 5 = board 2 left load (5)
// 6 = board 3 right load (6)
// 7 = board 3 left load (7)
// 8/16 = board 0 right spout (0)
// 9/17 = board 0 left spout (1)
// 10/18 = board 1 right spout (2)
// 11/19 = board 1 left spout (3)
// 12/20 = board 2 right spout (4)
// 13/21 = board 2 left spout (5)
// 14/22 = board 3 right spout(6)
// 15/23 = board 3 left spout (7)"""
# ══════════════════════════════════════════════════════════════════════════════
# END USER CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

# ── Event IDs (do not change — they define the saved .npy schema) ─────────────
EVT_EXP_ONSET      = 0
EVT_EXP_OFFSET     = 1
EVT_LEFT_LICK_ON   = 2
EVT_LEFT_LICK_OFF  = 3
EVT_RIGHT_LICK_ON  = 4
EVT_RIGHT_LICK_OFF = 5
EVT_LEFT_LOAD      = 6
EVT_RIGHT_LOAD     = 7

EVENT_NAMES = {
    EVT_EXP_ONSET:      "Experiment onset",
    EVT_EXP_OFFSET:     "Experiment offset",
    EVT_LEFT_LICK_ON:   "Left lick onset",
    EVT_LEFT_LICK_OFF:  "Left lick offset",
    EVT_RIGHT_LICK_ON:  "Right lick onset",
    EVT_RIGHT_LICK_OFF: "Right lick offset",
    EVT_LEFT_LOAD:      "Left load cell",
    EVT_RIGHT_LOAD:     "Right load cell",
}

EVENT_TAGS = {
    EVT_EXP_ONSET:      "exp",
    EVT_EXP_OFFSET:     "exp",
    EVT_LEFT_LICK_ON:   "left",
    EVT_LEFT_LICK_OFF:  "left",
    EVT_RIGHT_LICK_ON:  "right",
    EVT_RIGHT_LICK_OFF: "right",
    EVT_LEFT_LOAD:      "load",
    EVT_RIGHT_LOAD:     "load",
}

# ── Palette ────────────────────────────────────────────────────────────────────
BG_MAIN    = "#FFFFFF"
BG_PANEL   = "#F1EFE8"
BG_CARD    = "#FFFFFF"
CLR_DARK   = "#2C2C2A"
CLR_MUTED  = "#888780"
CLR_GREEN  = "#3B6D11"
CLR_RED    = "#D85A30"
CLR_BLUE   = "#185FA5"
CLR_ROW_ALT = "#F1EFE8"

FONT_UI    = ("Segoe UI", 9)
FONT_BOLD  = ("Segoe UI", 9, "bold")
FONT_MONO  = ("Courier New", 10)

# ══════════════════════════════════════════════════════════════════════════════
# IMPORTS
# ══════════════════════════════════════════════════════════════════════════════

import threading
import queue
import time
import re
import datetime
import os
from dataclasses import dataclass
from typing import List, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np

try:
    import serial
    _SERIAL_OK = True
except ImportError:
    _SERIAL_OK = False

# ══════════════════════════════════════════════════════════════════════════════
# SERIAL READER
# ══════════════════════════════════════════════════════════════════════════════

_SENSOR_RE = re.compile(r"^SENSOR,(\w+),([\d.+-]+),(\d+)$")
_TS_RE     = re.compile(r"^TS,(\d+)$")


class SerialReader:
    """
    Daemon thread that reads from the Arduino serial port.
    Pushes parsed dicts onto self.queue:
        {"type": "sensor", "pin": str, "value": float, "ts": int}
        {"type": "ts",     "ts": int}
    Falls back to simulation mode if pyserial is unavailable or port fails.
    """

    def __init__(self, port: str, baudrate: int = 115200):
        self.port     = port
        self.baudrate = baudrate
        self.queue    = queue.Queue()
        self._ser     = None
        self._running = False
        self.sim_mode = False

    def connect(self) -> bool:
        if not _SERIAL_OK:
            self._start_sim()
            return False
        try:
            self._ser     = serial.Serial(self.port, self.baudrate, timeout=1)
            self._running = True
            threading.Thread(target=self._read_loop, daemon=True).start()
            return True
        except Exception as e:
            print(f"[SerialReader] {e}")
            self._start_sim()
            return False

    def disconnect(self):
        self._running = False
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass

    def _read_loop(self):
        while self._running:
            try:
                raw = self._ser.readline()
                if raw:
                    msg = self._parse(raw.decode("utf-8", errors="ignore").strip())
                    if msg:
                        self.queue.put(msg)
            except Exception as e:
                print(f"[SerialReader] read error: {e}")
                time.sleep(0.1)

    def _parse(self, line: str):
        m = _SENSOR_RE.match(line)
        if m:
            return {"type": "sensor", "pin": m.group(1),
                    "value": float(m.group(2)), "ts": int(m.group(3))}
        m = _TS_RE.match(line)
        if m:
            return {"type": "ts", "ts": int(m.group(1))}
        return None

    def _start_sim(self):
        self.sim_mode = True
        self._running = True
        threading.Thread(target=self._sim_loop, daemon=True).start()

    def _sim_loop(self):
        """
        Simulates 4 experiments × (left touch, right touch, left load, right load).
        Touch pins send 0 or 1.  Load pins send a slow drifting float.
        """
        import random, math
        t_ms = 0
        # build flat list of all pins
        touch_pins = []
        load_pins  = []
        for exp_id in range(1, 5):
            p = EXPERIMENT_PINS[exp_id]
            touch_pins += [p["left_lick"], p["right_lick"]]
            load_pins  += [p["left_load"], p["right_load"]]

        lick_state    = {p: 0   for p in touch_pins}  # 0 or 1
        lick_duration = {p: 0   for p in touch_pins}  # ms remaining in lick

        while self._running:
            t_ms += 50
            for pin in touch_pins:
                if lick_state[pin] == 1:
                    lick_duration[pin] -= 50
                    if lick_duration[pin] <= 0:
                        lick_state[pin] = 0
                else:
                    if random.random() < 0.02:          # 2% chance of lick per 50 ms
                        lick_state[pin]    = 1
                        lick_duration[pin] = random.randint(100, 600)
                self.queue.put({"type": "sensor", "pin": pin,
                                "value": float(lick_state[pin]), "ts": t_ms})

            for i, pin in enumerate(load_pins):
                base = 10000 + i * 1500
                val  = base + math.sin(t_ms / 8000) * 300 + random.gauss(0, 8)
                self.queue.put({"type": "sensor", "pin": pin,
                                "value": round(val, 1), "ts": t_ms})

            if t_ms % 1000 == 0:
                self.queue.put({"type": "ts", "ts": t_ms})

            time.sleep(0.05)


# ══════════════════════════════════════════════════════════════════════════════
# EXPERIMENT MODEL  (data / logic — no GUI)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class EventRow:
    timestamp_ms: int
    event_id:     int
    amplitude:    float


class ExperimentModel:
    """
    Per-experiment state and event log.

    Touch sensor input is BOOLEAN (0 or 1):
      • First 1 after a 0  → lick onset  (amplitude = 1)
      • First 0 after a 1  → lick offset (amplitude = 1)

    Load cell input is a raw float multiplied by the calibration ratio.
    Recording is throttled to LOAD_CELL_POLL_MS.
    """

    def __init__(self, exp_id: int):
        self.exp_id = exp_id
        self.pins   = EXPERIMENT_PINS[exp_id]

        # Load cell calibration ratios (set from snap UI)
        self.cal_left_load:  float = 1.0
        self.cal_right_load: float = 1.0

        # Touch state: track previous boolean value to detect edges
        self._prev_left:  int = 0
        self._prev_right: int = 0

        # Load cell poll throttle
        self._last_load_ms: int = -1

        # Event log
        self._log:  List[EventRow] = []
        self._lock  = threading.Lock()

        self.running:   bool          = False
        self.start_ts:  Optional[int] = None

    # ── Event log ──────────────────────────────────────────────────────────────

    def add_event(self, ts_ms: int, event_id: int, amplitude: float = 0.0):
        with self._lock:
            self._log.append(EventRow(ts_ms, event_id, amplitude))

    def get_log_copy(self) -> List[EventRow]:
        with self._lock:
            return list(self._log)

    def export_npy(self, path: str):
        log = self.get_log_copy()
        if not log:
            return
        arr = np.array(
            [(r.timestamp_ms, r.event_id, r.amplitude) for r in log],
            dtype=[("timestamp_ms", np.int64),
                   ("event_id",     np.int8),
                   ("amplitude",    np.float32)],
        )
        np.save(path, arr)

    def elapsed_ms(self, arduino_ts: int) -> int:
        return max(0, arduino_ts - self.start_ts) if self.start_ts is not None else 0

    # ── Touch (boolean) lick detection ────────────────────────────────────────

    def process_touch(self, pin: str, value: float, arduino_ts: int):
        """
        value must be 0 or 1.
        Logs onset on first 1, offset on first 0 after 1.
        Amplitude is always 1.
        """
        if not self.running:
            return
        elapsed = self.elapsed_ms(arduino_ts)
        v = int(round(value))   # coerce to 0 / 1

        is_left  = (pin == self.pins["left_lick"])
        is_right = (pin == self.pins["right_lick"])

        if is_left:
            if v == 1 and self._prev_left == 0:
                self.add_event(elapsed, EVT_LEFT_LICK_ON,  1.0)
            elif v == 0 and self._prev_left == 1:
                self.add_event(elapsed, EVT_LEFT_LICK_OFF, 1.0)
            self._prev_left = v

        elif is_right:
            if v == 1 and self._prev_right == 0:
                self.add_event(elapsed, EVT_RIGHT_LICK_ON,  1.0)
            elif v == 0 and self._prev_right == 1:
                self.add_event(elapsed, EVT_RIGHT_LICK_OFF, 1.0)
            self._prev_right = v

    # ── Load cell ──────────────────────────────────────────────────────────────

    def process_load_cell(self, pin: str, value: float, arduino_ts: int):
        if not self.running:
            return
        elapsed = self.elapsed_ms(arduino_ts)

        # Throttle to LOAD_CELL_POLL_MS
        if self._last_load_ms >= 0 and (elapsed - self._last_load_ms) < LOAD_CELL_POLL_MS:
            return
        self._last_load_ms = elapsed

        if pin == self.pins["left_load"]:
            self.add_event(elapsed, EVT_LEFT_LOAD,  value * self.cal_left_load)
        elif pin == self.pins["right_load"]:
            self.add_event(elapsed, EVT_RIGHT_LOAD, value * self.cal_right_load)

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self, arduino_ts: int):
        with self._lock:
            self._log.clear()
        self._prev_left    = 0
        self._prev_right   = 0
        self._last_load_ms = -1
        self.start_ts      = arduino_ts
        self.running       = True
        self.add_event(0, EVT_EXP_ONSET)

    def stop(self, arduino_ts: int):
        if self.running:
            self.running = False
            self.add_event(self.elapsed_ms(arduino_ts), EVT_EXP_OFFSET)


# ══════════════════════════════════════════════════════════════════════════════
# RASTER CANVAS
# ══════════════════════════════════════════════════════════════════════════════

BINS_PER_ROW = (SECONDS_PER_ROW * 1000) // TIMEBIN_MS   # e.g. 1200


class RasterCanvas:
    """
    Matplotlib raster-plot embedded in a Tk widget.
    X = time within each minute (50 ms bins).
    Y = minute rows, growing dynamically.
    """

    def __init__(self, parent: tk.Widget):
        self._fig, self._ax = plt.subplots(figsize=(14, 3), dpi=96)
        self._fig.patch.set_facecolor("white")
        self._setup_axes()
        embed = FigureCanvasTkAgg(self._fig, master=parent)
        embed.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._embed = embed

    def _setup_axes(self):
        ax = self._ax
        ax.set_facecolor("white")
        ax.set_xlabel("Time within minute  (s)", fontsize=9, color="#444441")
        ax.set_ylabel("Minute", fontsize=9, color="#444441")
        x_ticks  = np.arange(0, BINS_PER_ROW + 1, (10_000) // TIMEBIN_MS)
        x_labels = [str(int(t * TIMEBIN_MS / 1000)) for t in x_ticks]
        ax.set_xticks(x_ticks)
        ax.set_xticklabels(x_labels, fontsize=7)
        ax.set_xlim(0, BINS_PER_ROW)
        ax.tick_params(axis="y", labelsize=7)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#D3D1C7")
        ax.spines["bottom"].set_color("#D3D1C7")
        ax.legend(handles=[
            mpatches.Patch(color=CLR_DARK, label="Exp onset/offset"),
            mpatches.Patch(color=CLR_RED,  label="Left lick"),
            mpatches.Patch(color=CLR_BLUE, label="Right lick"),
        ], loc="upper right", fontsize=7, framealpha=0.6)

    def update(self, events: List[EventRow]):
        ax = self._ax
        ax.cla()
        self._setup_axes()

        if not events:
            self._embed.draw_idle()
            return

        max_ms = max(e.timestamp_ms for e in events)
        n_rows = max(1, int(np.ceil(max_ms / (SECONDS_PER_ROW * 1000))))

        for r in range(n_rows):
            if r % 2 == 1:
                ax.axhspan(r, r + 1, color=CLR_ROW_ALT, zorder=0)

        for evt in events:
            row_ms = SECONDS_PER_ROW * 1000
            row    = int(evt.timestamp_ms // row_ms)
            bin_x  = int((evt.timestamp_ms % row_ms) // TIMEBIN_MS)
            color, height = self._style(evt.event_id)
            ax.plot([bin_x, bin_x], [row, row + height * 0.45],
                    color=color, linewidth=0.8, alpha=0.85, zorder=2)

        ax.set_ylim(0, n_rows)
        ax.set_yticks(np.arange(n_rows) + 0.5)
        ax.set_yticklabels([f"min {r+1}" for r in range(n_rows)], fontsize=7)
        self._fig.set_size_inches(14, max(3, n_rows * 1.4))
        self._embed.draw_idle()

    def _style(self, event_id: int):
        if event_id in (EVT_EXP_ONSET, EVT_EXP_OFFSET):
            return CLR_DARK, SPIKE_HEIGHT_EXP
        elif event_id in (EVT_LEFT_LICK_ON, EVT_LEFT_LICK_OFF):
            return CLR_RED, SPIKE_HEIGHT_LICK
        elif event_id in (EVT_RIGHT_LICK_ON, EVT_RIGHT_LICK_OFF):
            return CLR_BLUE, SPIKE_HEIGHT_LICK
        else:
            return CLR_MUTED, 0.3   # load cell ticks

    def save_png(self, path: str):
        self._fig.savefig(path, dpi=150, bbox_inches="tight")


# ══════════════════════════════════════════════════════════════════════════════
# EXPERIMENT WINDOW
# ══════════════════════════════════════════════════════════════════════════════

class ExperimentWindow(tk.Toplevel):
    """One window per experiment. All 4 can be open simultaneously."""

    def __init__(self, master, model: ExperimentModel, arduino_ts: list):
        super().__init__(master)
        self.model       = model
        self._arduino_ts = arduino_ts   # mutable [int] shared with dispatcher
        self._refresh_job = None

        self.title(f"Experiment {model.exp_id}  —  Lickometer")
        self.geometry("1280x760")
        self.configure(bg=BG_MAIN)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build()

    def _build(self):
        # ── Top bar ────────────────────────────────────────────────────────────
        top = tk.Frame(self, bg=BG_PANEL, pady=6)
        top.pack(fill=tk.X)

        tk.Label(top, text=f"Experiment {self.model.exp_id}",
                 font=("Segoe UI", 11, "bold"),
                 bg=BG_PANEL, fg=CLR_DARK).pack(side=tk.LEFT, padx=16)

        self._run_btn = tk.Button(
            top, text="▶  Run", font=FONT_BOLD,
            bg="#EAF3DE", fg="#3B6D11", activebackground="#C0DD97",
            relief=tk.FLAT, padx=12, pady=4, command=self._run)
        self._run_btn.pack(side=tk.LEFT, padx=8)

        self._stop_btn = tk.Button(
            top, text="⏹  Stop & Save", font=FONT_BOLD,
            bg="#FAECE7", fg="#993C1D", activebackground="#F5C4B3",
            relief=tk.FLAT, padx=12, pady=4, state=tk.DISABLED,
            command=self._stop_and_save)
        self._stop_btn.pack(side=tk.LEFT, padx=4)

        self._status_var = tk.StringVar(value="Idle")
        tk.Label(top, textvariable=self._status_var, font=FONT_UI,
                 bg=BG_PANEL, fg=CLR_MUTED).pack(side=tk.LEFT, padx=20)

        p = self.model.pins
        tk.Label(top,
                 text=(f"Left lick: {p['left_lick']}   Right lick: {p['right_lick']}   "
                       f"Left load: {p['left_load']}   Right load: {p['right_load']}"),
                 font=("Segoe UI", 8), bg=BG_PANEL, fg=CLR_MUTED
                 ).pack(side=tk.RIGHT, padx=16)

        # ── Raster plot (scrollable) ───────────────────────────────────────────
        plot_frame = tk.Frame(self, bg=BG_MAIN)
        plot_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(6, 0))

        sc = tk.Canvas(plot_frame, bg=BG_MAIN, highlightthickness=0)
        vsb = ttk.Scrollbar(plot_frame, orient=tk.VERTICAL, command=sc.yview)
        sc.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        sc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(sc, bg=BG_MAIN)
        sc.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: sc.configure(scrollregion=sc.bbox("all")))

        self._raster = RasterCanvas(inner)

        # ── Event log table ────────────────────────────────────────────────────
        log_frame = tk.LabelFrame(self, text="Event log",
                                   font=FONT_BOLD, bg=BG_MAIN, fg=CLR_DARK,
                                   relief=tk.FLAT, pady=4)
        log_frame.pack(fill=tk.X, padx=8, pady=(4, 8))

        cols = ("timestamp_ms", "event_id", "event_name", "amplitude")
        self._tree = ttk.Treeview(log_frame, columns=cols,
                                   show="headings", height=8)
        self._tree.heading("timestamp_ms", text="Timestamp (ms)")
        self._tree.heading("event_id",     text="Event ID")
        self._tree.heading("event_name",   text="Event")
        self._tree.heading("amplitude",    text="Amplitude")
        for c in cols:
            self._tree.column(c, width=160, anchor=tk.CENTER)

        sb = ttk.Scrollbar(log_frame, orient=tk.VERTICAL,
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._tree.tag_configure("left",  foreground=CLR_RED)
        self._tree.tag_configure("right", foreground=CLR_BLUE)
        self._tree.tag_configure("exp",   foreground=CLR_DARK)
        self._tree.tag_configure("load",  foreground=CLR_MUTED)
        self._shown = 0   # rows already appended to tree

    # ── Controls ───────────────────────────────────────────────────────────────

    def _run(self):
        if not self.model.running:
            self.model.start(self._arduino_ts[0])
            self._run_btn.config(state=tk.DISABLED)
            self._stop_btn.config(state=tk.NORMAL)
            self._schedule()

    def _stop_and_save(self):
        if self.model.running:
            self.model.stop(self._arduino_ts[0])
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        self._refresh()   # final flush

        stem = (f"experiment_{self.model.exp_id}_"
                f"{datetime.datetime.now():%Y%m%d_%H%M%S}")
        npy_path = filedialog.asksaveasfilename(
            title="Save event log (.npy)",
            initialfile=stem + ".npy",
            defaultextension=".npy",
            filetypes=[("NumPy array", "*.npy")])
        if npy_path:
            self.model.export_npy(npy_path)
            png_path = os.path.splitext(npy_path)[0] + ".png"
            self._raster.save_png(png_path)
            messagebox.showinfo("Saved",
                f"Event log  →  {npy_path}\nRaster image  →  {png_path}")

        self._run_btn.config(state=tk.NORMAL)
        self._stop_btn.config(state=tk.DISABLED)
        self._status_var.set("Stopped")

    def _on_close(self):
        if self.model.running:
            if not messagebox.askyesno(
                    "Quit", "Experiment still running. Stop and discard data?"):
                return
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        self.destroy()

    # ── Refresh ────────────────────────────────────────────────────────────────

    def _schedule(self):
        self._refresh_job = self.after(GUI_REFRESH_MS, self._tick)

    def _tick(self):
        self._refresh()
        if self.model.running:
            self._schedule()

    def _refresh(self):
        events = self.model.get_log_copy()
        self._raster.update(events)

        for evt in events[self._shown:]:
            name = EVENT_NAMES.get(evt.event_id, f"evt_{evt.event_id}")
            tag  = EVENT_TAGS.get(evt.event_id, "")
            self._tree.insert("", tk.END,
                              values=(evt.timestamp_ms, evt.event_id,
                                      name, f"{evt.amplitude:.2f}"),
                              tags=(tag,))
        self._shown = len(events)
        if events:
            self._tree.yview_moveto(1.0)

        if self.model.running and self.model.start_ts is not None:
            elapsed_s = (self._arduino_ts[0] - self.model.start_ts) / 1000
            self._status_var.set(f"Running  ·  {elapsed_s:.1f} s elapsed")


# ══════════════════════════════════════════════════════════════════════════════
# CALIBRATION / SETUP WINDOW  (root window)
# ══════════════════════════════════════════════════════════════════════════════

def _card(parent) -> tk.Frame:
    return tk.Frame(parent, bg=BG_CARD,
                    highlightbackground="#D3D1C7", highlightthickness=1,
                    padx=14, pady=10)

def _lbl(parent, text, bold=False, muted=False) -> tk.Label:
    return tk.Label(parent, text=text,
                    font=FONT_BOLD if bold else FONT_UI,
                    fg=CLR_MUTED if muted else CLR_DARK,
                    bg=parent["bg"])

def _ent(parent, var, width=10) -> tk.Entry:
    return tk.Entry(parent, textvariable=var, width=width,
                    font=FONT_MONO, relief=tk.FLAT,
                    highlightbackground="#D3D1C7", highlightthickness=1)

def _btn(parent, text, cmd, bg="#EAF3DE", fg="#3B6D11") -> tk.Button:
    return tk.Button(parent, text=text, command=cmd,
                     font=FONT_BOLD, bg=bg, fg=fg,
                     activebackground="#C0DD97", relief=tk.FLAT,
                     padx=10, pady=4)


class SetupWindow(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Lickometer  ·  Setup & Calibration")
        self.geometry("880x700")
        self.configure(bg=BG_MAIN)

        self._reader      = SerialReader(SERIAL_PORT)
        self._models      = {i: ExperimentModel(i) for i in range(1, 5)}
        self._exp_windows = {}
        self._arduino_ts  = [0]     # mutable int, shared with all exp windows
        self._connected   = False
        self._last_raw    = {}      # {pin: last float value} — for snap

        # Tk variables for settings
        self._port_var      = tk.StringVar(value=SERIAL_PORT)
        self._load_poll_var = tk.StringVar(value=str(LOAD_CELL_POLL_MS))
        self._ts_poll_var   = tk.StringVar(value=str(TIMESTAMP_POLL_MS))

        # Snap storage: {(exp_id, side, "50g"|"bottle"): float}
        self._snaps       = {}
        self._snap_svars  = {}   # StringVars for the snap display labels

        self._build()

    # ── Build UI ───────────────────────────────────────────────────────────────

    def _build(self):
        # Header
        hdr = tk.Frame(self, bg=BG_PANEL, pady=10)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Lickometer  ·  Setup & Calibration",
                 font=("Segoe UI", 13, "bold"),
                 bg=BG_PANEL, fg=CLR_DARK).pack(side=tk.LEFT, padx=16)

        # Scrollable body
        outer = tk.Frame(self, bg=BG_MAIN)
        outer.pack(fill=tk.BOTH, expand=True)
        sc = tk.Canvas(outer, bg=BG_MAIN, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=sc.yview)
        sc.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        sc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        body = tk.Frame(sc, bg=BG_MAIN)
        sc.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>",
                  lambda e: sc.configure(scrollregion=sc.bbox("all")))

        self._build_connection(body)
        self._build_settings(body)
        self._build_load_cal(body)
        self._build_launch(body)

    # ── Section: Connection ────────────────────────────────────────────────────

    def _build_connection(self, parent):
        c = _card(parent)
        c.pack(fill=tk.X, padx=16, pady=(14, 6))

        _lbl(c, "Arduino connection", bold=True).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

        _lbl(c, "Serial port:").grid(row=1, column=0, sticky="w")
        _ent(c, self._port_var, width=14).grid(row=1, column=1, padx=8, sticky="w")

        self._conn_btn = _btn(c, "Connect", self._toggle_connect)
        self._conn_btn.grid(row=1, column=2, padx=8)

        self._conn_status = tk.StringVar(value="⚫  Disconnected")
        tk.Label(c, textvariable=self._conn_status, font=FONT_UI,
                 bg=BG_CARD, fg=CLR_MUTED).grid(row=1, column=3, padx=12, sticky="w")

        _lbl(c, "Live pin values:", muted=True).grid(
            row=2, column=0, sticky="w", pady=(10, 0))
        self._live_var = tk.StringVar(value="—")
        tk.Label(c, textvariable=self._live_var, font=FONT_MONO,
                 bg=BG_CARD, fg=CLR_MUTED, wraplength=580,
                 justify=tk.LEFT).grid(row=3, column=0, columnspan=4, sticky="w")

    # ── Section: Global settings ───────────────────────────────────────────────

    def _build_settings(self, parent):
        c = _card(parent)
        c.pack(fill=tk.X, padx=16, pady=6)

        _lbl(c, "Global settings", bold=True).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        def row(r, label, var, unit):
            _lbl(c, label).grid(row=r, column=0, sticky="w", pady=3)
            _ent(c, var, width=8).grid(row=r, column=1, padx=8)
            _lbl(c, unit, muted=True).grid(row=r, column=2, sticky="w")

        row(1, "Load cell poll interval:", self._load_poll_var, "ms")
        row(2, "Arduino timestamp poll:",  self._ts_poll_var,   "ms")

        _btn(c, "Apply", self._apply_settings).grid(
            row=3, column=0, pady=(10, 0), sticky="w")

    # ── Section: Load cell calibration ────────────────────────────────────────

    def _build_load_cal(self, parent):
        c = _card(parent)
        c.pack(fill=tk.X, padx=16, pady=6)

        _lbl(c, "Load cell calibration", bold=True).pack(anchor="w", pady=(0, 6))
        _lbl(c,
             "Place 50g reference on bottle → Snap.  "
             "Replace with actual bottle → Snap.  "
             "Calibration ratio = 50g_raw ÷ bottle_raw.",
             muted=True).pack(anchor="w", pady=(0, 10))

        grid = tk.Frame(c, bg=BG_CARD)
        grid.pack(fill=tk.X)

        for col, head in enumerate(
                ["Exp", "Side", "Pin", "50g raw", "", "Bottle raw", "", "Ratio"]):
            tk.Label(grid, text=head, font=FONT_BOLD, bg=BG_CARD,
                     fg=CLR_DARK).grid(row=0, column=col, padx=6, pady=4, sticky="w")

        r = 1
        for exp_id in range(1, 5):
            for side in ("left", "right"):
                pin = EXPERIMENT_PINS[exp_id][f"{side}_load"]
                key = (exp_id, side)

                tk.Label(grid, text=str(exp_id), font=FONT_UI,
                         bg=BG_CARD).grid(row=r, column=0, padx=6)
                tk.Label(grid, text=side.capitalize(), font=FONT_UI,
                         bg=BG_CARD).grid(row=r, column=1, padx=6)
                tk.Label(grid, text=pin, font=FONT_MONO,
                         bg=BG_CARD, fg=CLR_MUTED).grid(row=r, column=2, padx=6)

                for col_offset, snap_key in enumerate(("50g", "bottle")):
                    sv = tk.StringVar(value="—")
                    self._snap_svars[(exp_id, side, snap_key)] = sv
                    tk.Label(grid, textvariable=sv, font=FONT_MONO,
                             bg=BG_CARD, width=10).grid(
                             row=r, column=3 + col_offset * 2, padx=4)
                    _btn(grid, "Snap",
                         lambda k=key, sk=snap_key: self._snap(k, sk),
                         bg="#E6F1FB", fg="#185FA5").grid(
                         row=r, column=4 + col_offset * 2, padx=2)

                sv_ratio = tk.StringVar(value="—")
                self._snap_svars[(exp_id, side, "ratio")] = sv_ratio
                tk.Label(grid, textvariable=sv_ratio, font=FONT_MONO,
                         bg=BG_CARD, fg=CLR_GREEN).grid(row=r, column=7, padx=6)
                r += 1

    # ── Section: Launch ────────────────────────────────────────────────────────

    def _build_launch(self, parent):
        c = _card(parent)
        c.pack(fill=tk.X, padx=16, pady=(6, 18))

        _lbl(c, "Experiments", bold=True).pack(anchor="w", pady=(0, 8))
        _lbl(c, "Open experiment windows after calibration is complete.",
             muted=True).pack(anchor="w", pady=(0, 10))

        row = tk.Frame(c, bg=BG_CARD)
        row.pack(anchor="w")

        _btn(row, "Open all 4 experiments",
             self._open_all).pack(side=tk.LEFT, padx=(0, 12))
        for exp_id in range(1, 5):
            _btn(row, f"Exp {exp_id}",
                 lambda i=exp_id: self._open_exp(i),
                 bg=BG_PANEL, fg=CLR_DARK).pack(side=tk.LEFT, padx=4)

    # ── Actions ────────────────────────────────────────────────────────────────

    def _toggle_connect(self):
        if not self._connected:
            self._reader.port = self._port_var.get().strip()
            ok = self._reader.connect()
            self._connected = True
            self._conn_btn.config(text="Disconnect")
            if ok:
                self._conn_status.set("🟢  Connected")
            else:
                self._conn_status.set("🟡  Simulation mode (no hardware)")
            self._start_dispatch()
        else:
            self._reader.disconnect()
            self._connected = False
            self._conn_btn.config(text="Connect")
            self._conn_status.set("⚫  Disconnected")

    def _apply_settings(self):
        global LOAD_CELL_POLL_MS, TIMESTAMP_POLL_MS
        try:
            LOAD_CELL_POLL_MS = int(self._load_poll_var.get())
            TIMESTAMP_POLL_MS = int(self._ts_poll_var.get())
        except ValueError:
            messagebox.showerror("Invalid input", "Settings must be integers.")
            return
        messagebox.showinfo("Applied",
            f"Load cell poll: {LOAD_CELL_POLL_MS} ms\n"
            f"TS poll: {TIMESTAMP_POLL_MS} ms")

    def _snap(self, key: tuple, snap_key: str):
        exp_id, side = key
        pin = EXPERIMENT_PINS[exp_id][f"{side}_load"]
        raw = self._last_raw.get(pin)
        if raw is None:
            messagebox.showwarning("No data",
                f"No reading yet for {pin}. Is the Arduino sending data?")
            return
        self._snaps[(exp_id, side, snap_key)] = raw
        self._snap_svars[(exp_id, side, snap_key)].set(f"{raw:.2f}")

        v50  = self._snaps.get((exp_id, side, "50g"))
        vbot = self._snaps.get((exp_id, side, "bottle"))
        if v50 is not None and vbot is not None and vbot != 0:
            ratio = v50 / vbot
            self._snap_svars[(exp_id, side, "ratio")].set(f"{ratio:.5f}")
            model = self._models[exp_id]
            if side == "left":
                model.cal_left_load  = ratio
            else:
                model.cal_right_load = ratio

    def _open_all(self):
        for i in range(1, 5):
            self._open_exp(i)

    def _open_exp(self, exp_id: int):
        if not self._connected:
            messagebox.showwarning("Not connected",
                "Connect to the Arduino first.")
            return
        w = self._exp_windows.get(exp_id)
        if w and w.winfo_exists():
            w.lift()
            return
        win = ExperimentWindow(self, self._models[exp_id], self._arduino_ts)
        self._exp_windows[exp_id] = win

    # ── Background dispatch ────────────────────────────────────────────────────

    def _start_dispatch(self):
        self._last_raw = {}
        threading.Thread(target=self._dispatch_loop, daemon=True).start()
        self.after(200, self._poll_live_label)

    def _dispatch_loop(self):
        """Background thread: reads queue, routes sensor messages to models."""
        # Build lookup: pin -> (model, "touch"|"load")
        pin_map = {}
        for exp_id, model in self._models.items():
            p = model.pins
            pin_map[p["left_lick"]]  = (model, "touch")
            pin_map[p["right_lick"]] = (model, "touch")
            pin_map[p["left_load"]]  = (model, "load")
            pin_map[p["right_load"]] = (model, "load")

        while self._connected:
            try:
                msg = self._reader.queue.get(timeout=0.2)
            except Exception:
                continue

            if msg["type"] == "ts":
                self._arduino_ts[0] = msg["ts"]

            elif msg["type"] == "sensor":
                pin, value, ts = msg["pin"], msg["value"], msg["ts"]
                self._last_raw[pin] = value
                self._arduino_ts[0] = ts
                if pin in pin_map:
                    model, kind = pin_map[pin]
                    if kind == "touch":
                        model.process_touch(pin, value, ts)
                    else:
                        model.process_load_cell(pin, value, ts)

    def _poll_live_label(self):
        if self._last_raw:
            items = [f"{p}={'1' if v == 1.0 else ('0' if v == 0.0 else f'{v:.0f}')}"
                     for p, v in list(self._last_raw.items())[:10]]
            self._live_var.set("  |  ".join(items))
        self.after(500, self._poll_live_label)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = SetupWindow()
    app.mainloop()
