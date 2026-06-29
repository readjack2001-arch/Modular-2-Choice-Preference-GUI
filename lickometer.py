"""
lickometer_final.py  —  Lickometer GUI (single file)
Run:   python lickometer_final.py [COM_PORT]
Deps:  pip install pyserial matplotlib numpy

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RUNNING MULTIPLE INSTANCES  (Task 1)

  Each running copy of this program drives ONE Arduino (its own COM port)
  and the 4 experiments on that board. To run four boards at once on the
  same computer, start the program four times, one per COM port. Options:

    • From a terminal (recommended, fully independent processes):
          python lickometer_final.py COM3
          python lickometer_final.py COM4
          python lickometer_final.py COM5
          python lickometer_final.py COM6
      The COM port passed on the command line just pre-fills the Port box.
      You can also type / change the port in the GUI before connecting.

    • From Spyder: open a new console per board
      (Consoles ▸ Open an IPython console) and run the file in each, OR
      set Run ▸ Configuration ▸ "Execute in an external system terminal"
      and launch it once per board. Set a different port in each GUI.

  The window title shows the active port so the four windows are easy to
  tell apart. Calibration is stored per-port; flag / plot / save settings
  are shared across all instances (see Task 3 below).

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
Edit only the USER CONFIGURATION block below. Anything you set in the GUI
(calibration, flag thresholds, plot axes, save folder) is persisted to
lickometer_settings.json and re-loaded automatically next time (Task 3),
so these constants are only the first-run defaults.
"""

# ══════════════════════════════════════════════════════════════════════════════
# USER CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

SERIAL_PORT     = "COM3"       # Linux/Mac: "/dev/ttyUSB0" or "/dev/cu.usbserial-…"
BAUD_RATE       = 115200

# ── MONITOR tab raster params (the live 4-row quadrant view) ──────────────────
# These are first-run defaults; all three are also editable in the GUI on the
# "Raster Plot Visuals" tab (and persist to lickometer_settings.json).
TIMEBIN_MS      = 1000           # monitor raster bin width in ms
GUI_REFRESH_MS  = 1000           # monitor raster redraw interval in ms
SECONDS_PER_ROW = 600            # x-axis span per monitor raster row (seconds)

# Number of most-recent rows shown in the monitor quadrant raster (fixed view,
# no scrolling — this is the rendering-performance fix).
MONITOR_VISIBLE_ROWS = 4

# ── FULL-VIEW tab params (one tab per experiment, imshow heat-map) ────────────
# The full-view tabs show the WHOLE experiment in a fixed-size image that is
# refreshed every AUTOSAVE_MINUTES from the in-memory event log. Coarse bins —
# no fine resolution needed here. All editable on the Raster Plot Visuals tab.
FULL_ROWS            = 24         # number of rows in the full-view grid
FULL_SECONDS_PER_ROW = 3600      # seconds represented by one full-view row
FULL_BIN_SECONDS     = 60        # seconds per full-view bin (60 → 60 bins/row)

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

# ── Flag / watchdog thresholds (Task 2) — first-run defaults, editable in GUI ──
NO_LICK_MINUTES         = 30    # 2b: flag if no lick at all for longer than this
PROLONGED_BOUT_MINUTES  = 1     # 2b: flag a continuous lick bout longer than this
PROLONGED_LICK_SECONDS  = 5     # 2b: flag a single continuous lick longer than this
BOUT_GAP_SECONDS        = 10    # 2b: a gap longer than this ends a lick "bout"
LOAD_NOCHANGE_MINUTES   = 30    # 2c: sample window — licks but load unchanged
LOAD_NOLICK_MINUTES     = 30    # 2c: sample window — load changed but no licks
LOAD_CHANGE_TOLERANCE_G = 0.5   # 2c: load swing (g) below this counts as "no change"

# ── Raster plot visuals (Task 5) — first-run defaults, editable in GUI ──
LOAD_YMIN   = 30.0    # bottom of the load-cell scale (g) — zoom to the working
                      #   bottle-weight range; readings below this clip to baseline
LOAD_YMAX   = 60.0    # top of the load-cell scale (g)
LOAD_YTICKS = 4       # number of tick marks on the load-cell scale

# ── Autosave (Task 6) ──
# How often (minutes) to overwrite each running experiment's raster PNG +
# event-log NPY in the chosen save folder. Also drives the full-view refresh
# and the monitor event-log scrolling window. Editable on the setup page and
# on the Data tab. Default 15.
AUTOSAVE_MINUTES = 15

# ── Watchdog poll interval (how often flag conditions are checked) ──
WATCHDOG_MS = 2000

# ══════════════════════════════════════════════════════════════════════════════
# END USER CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

import sys, threading, queue, time, re, datetime, os, json, builtins
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
from matplotlib.lines import Line2D
from matplotlib.cm import ScalarMappable
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
# ── Data-series colours: Paul Tol "muted" qualitative scheme (colour-blind
#    safe — distinguishable under deuteranopia/protanopia/tritanopia). ──
CLR_L      = "#CC6677"   # left  lick / left  load   (Tol rose)
CLR_R      = "#88CCEE"   # right lick / right load   (Tol cyan)
CLR_EXP    = "#DDCC77"   # onset / offset markers     (Tol sand)
CLR_LOAD_L = "#44AA99"   # full-view L load line      (Tol teal)
CLR_LOAD_R = "#AA4499"   # full-view R load line      (Tol purple)
# ── UI status colours (left as conventional go/stop affordances; the Start/
#    Stop buttons also carry text labels, so they aren't colour-coded alone). ──
CLR_GRN = "#30D158"
CLR_RED = "#FF453A"

FONT    = ("Segoe UI", 9)
FONTB   = ("Segoe UI", 9, "bold")
FONTM   = ("Courier New", 9)

# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS PERSISTENCE  (Task 3)
# ══════════════════════════════════════════════════════════════════════════════
#
# Everything you set in the GUI is written to lickometer_settings.json next to
# this script and reloaded on every launch. Flag thresholds, plot axes, save
# folder and weight interval are SHARED across all instances. Calibration
# (load-cell ratios + touch thresholds) is stored PER PORT, because each Arduino
# has its own physical load cells.
#
# Saves are atomic (write temp + os.replace) and merge-on-write (re-read the
# file, update only this instance's section, write back) so four instances can
# share one file without clobbering each other.

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:                       # e.g. interactive / some Spyder configs
    _HERE = os.getcwd()
SETTINGS_FILE = os.path.join(_HERE, "lickometer_settings.json")


def set_settings_file(path: str):
    """Point all settings reads/writes at a specific JSON file.

    The hub launches each GUI instance with its OWN settings file inside that
    instance's folder, so calibrations / flag thresholds / plot visuals are
    unique per instance (Task H3). load_settings(), _write_settings() and the
    save_* helpers all read this module global at call time, so reassigning it
    here before MainWindow builds is sufficient — no other code changes needed.
    """
    global SETTINGS_FILE
    if path:
        SETTINGS_FILE = os.path.abspath(path)

DEFAULT_SETTINGS = {
    "shared": {
        "flags": {
            "no_lick_minutes":         NO_LICK_MINUTES,
            "prolonged_bout_minutes":  PROLONGED_BOUT_MINUTES,
            "prolonged_lick_seconds":  PROLONGED_LICK_SECONDS,
            "bout_gap_seconds":        BOUT_GAP_SECONDS,
            "load_nochange_minutes":   LOAD_NOCHANGE_MINUTES,
            "load_nolick_minutes":     LOAD_NOLICK_MINUTES,
            "load_change_tolerance_g": LOAD_CHANGE_TOLERANCE_G,
        },
        "plot": {
            "load_ymin":   LOAD_YMIN,
            "load_ymax":   LOAD_YMAX,
            "load_yticks": LOAD_YTICKS,
            # Load-cell display (Task V1 / LC27)
            "load_show":      1,     # 1/0: capture + plot load cell data at all
            "load_linewidth": 1.2,   # full-view (Box tab) load line width
            # Monitor (live 4-row quadrant) raster timing
            "monitor_timebin_ms":      TIMEBIN_MS,
            "monitor_seconds_per_row": SECONDS_PER_ROW,
            "monitor_refresh_ms":      GUI_REFRESH_MS,
            # Full-view (imshow) grid geometry
            "full_rows":            FULL_ROWS,
            "full_seconds_per_row": FULL_SECONDS_PER_ROW,
            "full_bin_seconds":     FULL_BIN_SECONDS,
        },
        "save_folder":      "",
        "weight_interval":  30,
        "autosave_minutes": AUTOSAVE_MINUTES,
        # ── Hub-provided instance config (Task H2/H3/H4) ──
        "num_boxes":        4,     # 1-4: how many boxes this instance drives
        "sketch_name":      "",    # filename of the Arduino sketch flashed
        "sketch_path":      "",    # full path of the Arduino sketch flashed
    },
    # "ports": { "COM3": {"thresholds": {...}, "calibration": {...}}, ... }
    "ports": {},
}


def _deep_merge(base: dict, over: dict) -> dict:
    """Return base updated with over (recursively); base is not mutated."""
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings() -> dict:
    """Load settings from JSON file, merging with defaults for any missing keys."""
    try:
        with open(SETTINGS_FILE, "r") as f:
            data = json.load(f)
    except Exception:
        data = {}
    return _deep_merge(DEFAULT_SETTINGS, data)


def _write_settings(data: dict):
    """Atomically write the settings dict to JSON (temp-file + os.replace)."""
    tmp = SETTINGS_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, SETTINGS_FILE)          # atomic on the same filesystem
    except Exception as e:
        print(f"[settings] save failed: {e}")


def save_shared(section: str, values: dict):
    """Re-read file, update shared[section], write back (merge-on-write)."""
    data = load_settings()
    data.setdefault("shared", {}).setdefault(section, {})
    if isinstance(data["shared"][section], dict):
        data["shared"][section].update(values)
    else:
        data["shared"][section] = values
    _write_settings(data)


def save_shared_value(key: str, value):
    """Update a single top-level shared key in the settings file."""
    data = load_settings()
    data.setdefault("shared", {})[key] = value
    _write_settings(data)


def save_port_section(port: str, section: str, values: dict):
    """Update ports[port][section] (e.g. 'thresholds' or 'calibration')."""
    data = load_settings()
    p = data.setdefault("ports", {}).setdefault(port, {})
    cur = p.setdefault(section, {})
    if isinstance(cur, dict):
        cur.update(values)
    else:
        p[section] = values
    _write_settings(data)

# ══════════════════════════════════════════════════════════════════════════════
# PORT CLEANUP  (Task 4)
# ══════════════════════════════════════════════════════════════════════════════
#
# Before opening a port we close any serial handle this process / kernel still
# holds on it. The registry lives on `builtins` so it SURVIVES re-running the
# script inside the same Spyder kernel — that is the usual cause of "I can't
# connect, some hidden instance still owns the port": the previous run's Serial
# object is still open in the kernel. We close it here before reconnecting.
#
# NOTE: a port held by a *different OS process* cannot be force-released from
# Python on Windows. If the open still fails, we surface the clear "unable to
# connect - check connection" error (Task 2a) so you know to close other apps.

if not hasattr(builtins, "_LICKOMETER_OPEN_PORTS"):
    builtins._LICKOMETER_OPEN_PORTS = {}
_OPEN_PORTS: dict = builtins._LICKOMETER_OPEN_PORTS   # {port_name: serial.Serial}


def cleanup_port(port: str):
    """Close any serial handle this kernel/process is still holding on `port`."""
    obj = _OPEN_PORTS.pop(port, None)
    if obj is not None:
        try:
            if obj.is_open:
                obj.close()
                print(f"[cleanup] closed stale handle on {port}")
        except Exception as e:
            print(f"[cleanup] {e}")
    # Sweep anything else pointing at the same port name, just in case.
    for p, o in list(_OPEN_PORTS.items()):
        try:
            if getattr(o, "port", None) == port:
                if o.is_open:
                    o.close()
                _OPEN_PORTS.pop(p, None)
        except Exception:
            _OPEN_PORTS.pop(p, None)

# ══════════════════════════════════════════════════════════════════════════════
# SERIAL READER
# ══════════════════════════════════════════════════════════════════════════════

_EVT_RE = re.compile(r"^(\d+),(\d+),([\d.+-]+)$")


class SerialReader:
    """
    Background thread reads Arduino serial output.
    Parsed events  → self.queue       {"ts":int,"id":int,"amp":float}
    Raw text lines → self.raw_queue   str   (for the terminal tab)

    Task 2a: connect() NO LONGER falls back to simulation on failure. It closes
    stale handles first (Task 4), tries to open, and returns True/False. The
    simulation code below is kept but its call sites are commented out.
    """

    def __init__(self):
        """Initialise queues, serial state, and connection metadata."""
        self.queue       = queue.Queue()
        self.raw_queue   = queue.Queue(maxsize=500)
        self._ser        = None
        self._running    = False
        self.sim_mode    = False
        self.port        = SERIAL_PORT
        self.baud        = BAUD_RATE
        self.last_error  = ""
        # Protects all access to self._ser so that send() (called from the
        # Tk main thread) and _read_loop() (background thread) never race.
        self._ser_lock   = threading.Lock()

    def connect(self) -> bool:
        """Open the serial port and start the background reader thread. Returns True on success.

        Special case: a port of "SIM" (case-insensitive) starts the built-in
        simulator instead of opening real hardware, so the whole GUI can be
        exercised end-to-end with no Arduino attached.
        """
        if str(self.port).strip().upper() == "SIM":
            self.last_error = ""
            self._push_raw("[Serial] SIM mode — generating synthetic events")
            print("[Serial] SIM mode — generating synthetic events")
            self._start_sim()
            return True
        if not _SERIAL_OK:
            self.last_error = "pyserial not installed (pip install pyserial)"
            self._push_raw(f"[Serial] {self.last_error}")
            print(f"[Serial] {self.last_error}")
            # self._start_sim()   # Task 2a: do NOT auto-fall-back to simulation
            return False
        cleanup_port(self.port)                       # Task 4
        try:
            ser = _serial.Serial(self.port, self.baud, timeout=1)
            with self._ser_lock:
                self._ser = ser
            _OPEN_PORTS[self.port] = ser              # register for Task 4 cleanup
            self._running = True
            threading.Thread(target=self._read_loop, daemon=True).start()
            self.last_error = ""
            return True
        except Exception as e:
            self.last_error = str(e)
            self._push_raw(f"[Serial] {e}")
            print(f"[Serial] {e}")
            # self._start_sim()   # Task 2a: do NOT auto-fall-back to simulation
            return False

    def send(self, cmd: str):
        """Send a newline-terminated command to the Arduino under the serial lock.

        _ser_lock prevents this from racing with _read_loop(), which also
        acquires the lock during each readline() call. _push_raw is outside
        the lock because it only touches the thread-safe raw_queue.
        """
        with self._ser_lock:
            if self._ser and self._ser.is_open:
                self._ser.write((cmd + "\r\n").encode())
        self._push_raw(f">> {cmd}")

    def disconnect(self):
        """Stop the reader thread and close the serial port."""
        self._running = False
        with self._ser_lock:
            if self._ser:
                try:
                    self._ser.close()
                except Exception:
                    pass
                _OPEN_PORTS.pop(self.port, None)      # Task 4: deregister

    # ── Internal ──────────────────────────────────────────────────────────────

    def _read_loop(self):
        """Background thread: reads lines from the serial port and puts parsed events on the queue.

        Each readline() is wrapped in _ser_lock so it cannot run concurrently
        with send() or disconnect().  Only serial.SerialException is silently
        swallowed (and logged); other exceptions are re-raised so genuine bugs
        are not hidden.
        """
        while self._running:
            try:
                with self._ser_lock:
                    if not (self._ser and self._ser.is_open):
                        # Port closed externally — stop the loop cleanly.
                        break
                    raw = self._ser.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="ignore").strip()
                self._push_raw(line)
                msg = self._parse(line)
                if msg:
                    self.queue.put(msg)
            except _serial.SerialException as e:
                # Transient port error (e.g. USB glitch). Log once and retry.
                self._push_raw(f"[Serial] {e}")
                print(f"[Serial] {e}")
                time.sleep(0.1)
            except Exception as e:
                # Unexpected error — log it but keep running.
                self._push_raw(f"[Serial] unexpected: {e}")
                print(f"[Serial] unexpected: {e}")
                time.sleep(0.1)

    def _parse(self, line: str):
        """Parse one raw serial line into an event dict, or return None if unrecognised."""
        if line.startswith("#"):
            return None
        m = _EVT_RE.match(line)
        if m:
            return {"ts": int(m.group(1)), "id": int(m.group(2)),
                    "amp": float(m.group(3))}
        return None

    def _push_raw(self, line: str):
        """Push a raw text line onto raw_queue for the terminal tab (non-blocking, drops on overflow)."""
        try:
            self.raw_queue.put_nowait(line)
        except queue.Full:
            pass

    # ── Simulation (RETAINED for manual testing, but never auto-started) ───────
    # To test the GUI without hardware you can manually call self._start_sim()
    # from a console; nothing in normal operation calls it anymore.

    def _start_sim(self):
        """Start the simulation loop (no hardware needed; for offline GUI testing only)."""
        self.sim_mode = True
        self._running = True
        threading.Thread(target=self._sim_loop, daemon=True).start()

    def _sim_loop(self):
        """Generate synthetic lick and load-cell events at a 50 ms tick rate for offline testing."""
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


def _open_onset(ons: List[int], offs: List[int]) -> Optional[int]:
    """Earliest lick onset that has no matching offset yet (currently open)."""
    pool = sorted(offs)
    for on in sorted(ons):
        nxt = next((o for o in pool if o >= on), None)
        if nxt is None:
            return on
        pool.remove(nxt)
    return None


@dataclass
class EventRow:
    timestamp_ms: int
    event_id:     int
    amplitude:    float


class ExperimentModel:
    def __init__(self, exp_id: int):
        """Set up channel ID mappings, calibration ratios, load-cell flag state, and an empty event log."""
        self.exp_id = exp_id
        ch = EXPERIMENT_CHANNELS[exp_id]
        self.l_on_id   = ch["left_onset"]
        self.r_on_id   = ch["right_onset"]
        self.l_off_id  = self.l_on_id  + 8
        self.r_off_id  = self.r_on_id  + 8
        self.l_load_id = ch["left_load"]
        self.r_load_id = ch["right_load"]

        self.cal_left:  float = 1.0   # software calibration ratio for left load cell
        self.cal_right: float = 1.0   # software calibration ratio for right load cell

        # Task V1: when False, load-cell events are neither captured nor plotted.
        self.capture_load: bool = True

        # ── Load-cell flag baselines (populated at runtime) ──────────────────
        # initial_load_*  : the very first calibrated reading after experiment starts;
        #                   flag fires if reading exceeds this by +0.5 g (drink event).
        # offset_weight_* : the empty-bottle snap weight from calibration UI;
        #                   flag fires if reading drops below this (bottle removed / empty).
        self.initial_load_left:   Optional[float] = None  # first L load reading this run
        self.initial_load_right:  Optional[float] = None  # first R load reading this run
        self.offset_weight_left:  Optional[float] = None  # empty-bottle weight, left side
        self.offset_weight_right: Optional[float] = None  # empty-bottle weight, right side

        # Threshold above initial weight that counts as a "drink detected" flag (g)
        self.DRINK_DELTA_G: float = 0.5

        # Edge-trigger guards for load-cell flags so they fire once per transition
        self._drink_flag_left:  bool = False  # True while left drink flag is active
        self._drink_flag_right: bool = False  # True while right drink flag is active
        self._below_flag_left:  bool = False  # True while left below-offset flag is active
        self._below_flag_right: bool = False  # True while right below-offset flag is active

        self._log:  List[EventRow] = []
        self._lock  = threading.Lock()
        self.running:  bool          = False
        self.start_ts: Optional[int] = None

        # Task 2 flag-detection state (edge-triggered so flags don't spam)
        self._fs:          Dict[str, bool] = {}
        self._load_a_last: int = 0     # last time the "no change" check sampled
        self._load_b_last: int = 0     # last time the "change w/o licks" check sampled

    def owns(self, aid: int) -> bool:
        """Return True if the given Arduino ID belongs to this experiment's channels."""
        return aid in (self.l_on_id, self.r_on_id,
                       self.l_off_id, self.r_off_id,
                       self.l_load_id, self.r_load_id)

    def elapsed(self, ts: int) -> int:
        """Return milliseconds elapsed since experiment start, clamped to 0."""
        return max(0, ts - self.start_ts) if self.start_ts is not None else 0

    def add(self, ts_ms: int, eid: int, amp: float = 0.0):
        """Append one EventRow to the thread-safe event log."""
        with self._lock:
            self._log.append(EventRow(ts_ms, eid, amp))

    def get_log(self) -> List[EventRow]:
        """Return a snapshot copy of the event log (thread-safe)."""
        with self._lock:
            return list(self._log)

    def export_npy(self, path: str):
        """Save the event log as a structured NumPy .npy file with fields timestamp_ms, event_id, amplitude."""
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
        """
        Route one Arduino event into the log and run load-cell flag checks.

        Load-cell flags (both edge-triggered, fire once per transition):
          • Drink flag  : calibrated weight exceeds initial_load by DRINK_DELTA_G.
            Stored in _drink_flag_left / _drink_flag_right; returned as a flag
            string the first time the threshold is crossed.
          • Below-offset flag : calibrated weight drops below the empty-bottle
            snap weight (offset_weight_left / offset_weight_right).
            Fires once when the reading first goes below the baseline.

        Returns a list of flag strings (empty list if no new flags this call).
        The caller (dispatch loop in MainWindow) should forward these to emit_alert.
        """
        if not self.running:
            return []
        el   = self.elapsed(ts)
        flags: List[str] = []

        # ── Touch events ─────────────────────────────────────────────────────
        if   aid == self.l_on_id:  self.add(el, _L_ON,  1.0); return flags
        elif aid == self.l_off_id: self.add(el, _L_OFF, 1.0); return flags
        elif aid == self.r_on_id:  self.add(el, _R_ON,  1.0); return flags
        elif aid == self.r_off_id: self.add(el, _R_OFF, 1.0); return flags

        # ── Load cell events ──────────────────────────────────────────────────
        elif aid == self.l_load_id:
            if not self.capture_load:        # Task V1: skip capture entirely
                return flags
            cal_val = amp * self.cal_left   # apply software calibration ratio

            # Capture the very first reading as the initial baseline.
            if self.initial_load_left is None:
                self.initial_load_left = cal_val

            self.add(el, _L_LOAD, cal_val)

            # Flag 1: drink detected — weight rose more than DRINK_DELTA_G above initial
            if self.initial_load_left is not None:
                drink_now = cal_val >= self.initial_load_left + self.DRINK_DELTA_G
                if drink_now and not self._drink_flag_left:
                    flags.append((f"Box {self.exp_id} L: drink detected "
                                  f"(+{cal_val - self.initial_load_left:.2f} g "
                                  f"above initial)", "warning"))
                elif self._drink_flag_left and not drink_now:   # F3 resolution
                    flags.append((f"Box {self.exp_id} L: drink flag resolved "
                                  f"(weight back within {self.DRINK_DELTA_G:g} g "
                                  f"of initial)", "resolved"))
                self._drink_flag_left = drink_now

            # Flag 2: below-offset — weight dropped below the empty-bottle baseline
            if self.offset_weight_left is not None:
                below_now = cal_val < self.offset_weight_left
                if below_now and not self._below_flag_left:
                    flags.append((f"Box {self.exp_id} L: load below offset weight "
                                  f"(−{self.offset_weight_left - cal_val:.2f} g "
                                  f"below offset {self.offset_weight_left:.2f} g)",
                                  "warning"))
                elif self._below_flag_left and not below_now:   # F3 resolution
                    flags.append((f"Box {self.exp_id} L: below-offset flag "
                                  f"resolved (weight back at/above offset)",
                                  "resolved"))
                self._below_flag_left = below_now

        elif aid == self.r_load_id:
            if not self.capture_load:        # Task V1: skip capture entirely
                return flags
            cal_val = amp * self.cal_right  # apply software calibration ratio

            # Capture the very first reading as the initial baseline.
            if self.initial_load_right is None:
                self.initial_load_right = cal_val

            self.add(el, _R_LOAD, cal_val)

            # Flag 1: drink detected — weight rose more than DRINK_DELTA_G above initial
            if self.initial_load_right is not None:
                drink_now = cal_val >= self.initial_load_right + self.DRINK_DELTA_G
                if drink_now and not self._drink_flag_right:
                    flags.append((f"Box {self.exp_id} R: drink detected "
                                  f"(+{cal_val - self.initial_load_right:.2f} g "
                                  f"above initial)", "warning"))
                elif self._drink_flag_right and not drink_now:   # F3 resolution
                    flags.append((f"Box {self.exp_id} R: drink flag resolved "
                                  f"(weight back within {self.DRINK_DELTA_G:g} g "
                                  f"of initial)", "resolved"))
                self._drink_flag_right = drink_now

            # Flag 2: below-offset — weight dropped below the empty-bottle baseline
            if self.offset_weight_right is not None:
                below_now = cal_val < self.offset_weight_right
                if below_now and not self._below_flag_right:
                    flags.append((f"Box {self.exp_id} R: load below offset weight "
                                  f"(−{self.offset_weight_right - cal_val:.2f} g "
                                  f"below offset {self.offset_weight_right:.2f} g)",
                                  "warning"))
                elif self._below_flag_right and not below_now:   # F3 resolution
                    flags.append((f"Box {self.exp_id} R: below-offset flag "
                                  f"resolved (weight back at/above offset)",
                                  "resolved"))
                self._below_flag_right = below_now

        return flags

    def start(self, ts: int):
        # Clear the event log and reset all per-run state for a fresh start.
        """Implement start."""
        with self._lock:
            self._log.clear()
        self.start_ts = ts
        self.running  = True
        self._fs.clear()
        self._load_a_last = 0
        self._load_b_last = 0
        # Reset load-cell baselines so they are re-captured from the first reading.
        self.initial_load_left  = None
        self.initial_load_right = None
        # Reset load flag edge-trigger guards.
        self._drink_flag_left   = False
        self._drink_flag_right  = False
        self._below_flag_left   = False
        self._below_flag_right  = False
        self.add(0, _EXP_ONSET)

    def stop(self, ts: int):
        """Stop the experiment and record the offset event."""
        if self.running:
            self.running = False
            self.add(self.elapsed(ts), _EXP_OFFSET)

    # ── Flag detection (Task 2b + 2c) ─────────────────────────────────────────
    def check_flags(self, now_ts: int, cfg: dict) -> List[str]:
        """
        Inspect the log against the current thresholds and return any NEW flags
        (edge-triggered). Never raises; on any internal error it just returns [].
        `cfg` is a snapshot of the GUI flag settings.
        """
        if not self.running or self.start_ts is None:
            return []
        try:
            now = self.elapsed(now_ts)
            log = self.get_log()
            flags: List[Tuple[str, str]] = []

            on_l  = [r.timestamp_ms for r in log if r.event_id == _L_ON]
            on_r  = [r.timestamp_ms for r in log if r.event_id == _R_ON]
            off_l = [r.timestamp_ms for r in log if r.event_id == _L_OFF]
            off_r = [r.timestamp_ms for r in log if r.event_id == _R_OFF]
            onsets = sorted(on_l + on_r)

            # ── 2b-i: no lick at all for longer than X minutes ────────────────
            nolick_ms = cfg["no_lick_minutes"] * 60_000
            last_lick = onsets[-1] if onsets else 0
            cond = (now - last_lick) > nolick_ms
            prev = self._fs.get("nolick", False)
            if cond and not prev:
                flags.append((f"longer than {cfg['no_lick_minutes']:g} minutes "
                              f"with no lick", "flag"))
            elif prev and not cond:                              # F3 resolution
                flags.append(("no-lick flag resolved (licking resumed)",
                              "resolved"))
            self._fs["nolick"] = cond

            # ── 2b-ii: prolonged single continuous lick (> X seconds) ─────────
            plick_ms = cfg["prolonged_lick_seconds"] * 1000
            for side, ons, offs in (("L", on_l, off_l), ("R", on_r, off_r)):
                oo = _open_onset(ons, offs)
                key = f"plick_{side}"
                c = oo is not None and (now - oo) > plick_ms
                prev = self._fs.get(key, False)
                if c and not prev:
                    flags.append((f"prolonged lick longer than "
                                  f"{cfg['prolonged_lick_seconds']:g} seconds "
                                  f"({side})", "flag"))
                elif prev and not c:                             # F3 resolution
                    flags.append((f"prolonged-lick flag resolved ({side})",
                                  "resolved"))
                self._fs[key] = c

            # ── 2b-iii: prolonged lick bout (> X minutes of ongoing licking) ──
            gap_ms  = cfg["bout_gap_seconds"] * 1000
            bout_ms = cfg["prolonged_bout_minutes"] * 60_000
            bout_cond = False
            if onsets:
                last = onsets[-1]
                if (now - last) <= gap_ms:          # bout still ongoing
                    bout_start = last
                    for t in reversed(onsets[:-1]):
                        if bout_start - t <= gap_ms:
                            bout_start = t
                        else:
                            break
                    if (now - bout_start) > bout_ms:
                        bout_cond = True
            prev = self._fs.get("bout", False)
            if bout_cond and not prev:
                flags.append((f"prolonged lick bout longer than "
                              f"{cfg['prolonged_bout_minutes']:g} minutes", "flag"))
            elif prev and not bout_cond:                         # F3 resolution
                flags.append(("prolonged-bout flag resolved (bout ended)",
                              "resolved"))
            self._fs["bout"] = bout_cond

            # ── 2c: load-cell sanity checks, sampled on their own windows ─────
            tol = cfg["load_change_tolerance_g"]

            # 2c-i: licks but no change in load value
            a_ms = cfg["load_nochange_minutes"] * 60_000
            if now - self._load_a_last >= a_ms:
                self._load_a_last = now
                for side, ons, load_eid in (("L", on_l, _L_LOAD),
                                            ("R", on_r, _R_LOAD)):
                    licks = sum(1 for t in ons if t > now - a_ms)
                    rng   = self._load_range(log, load_eid, now - a_ms, now)
                    if licks > 0 and rng is not None and rng <= tol:
                        flags.append(
                            (f"no change in load cell value after "
                             f"{cfg['load_nochange_minutes']:g} minutes of "
                             f"licking ({side})", "flag"))

            # 2c-ii: load value changed but no licks
            b_ms = cfg["load_nolick_minutes"] * 60_000
            if now - self._load_b_last >= b_ms:
                self._load_b_last = now
                for side, ons, load_eid in (("L", on_l, _L_LOAD),
                                            ("R", on_r, _R_LOAD)):
                    licks = sum(1 for t in ons if t > now - b_ms)
                    rng   = self._load_range(log, load_eid, now - b_ms, now)
                    if licks == 0 and rng is not None and rng > tol:
                        flags.append(
                            (f"changes in load cell value despite no licks in "
                             f"past {cfg['load_nolick_minutes']:g} minutes "
                             f"({side})", "flag"))

            return flags
        except Exception as e:
            print(f"[watchdog] exp {self.exp_id}: {e}")
            return []

    @staticmethod
    def _load_range(log, load_eid, t0, t1) -> Optional[float]:
        """Return the amplitude range (max-min) of load events in a time window, or None if fewer than 2 samples."""
        amps = [r.amplitude for r in log
                if r.event_id == load_eid and t0 < r.timestamp_ms <= t1]
        if len(amps) < 2:
            return None
        return max(amps) - min(amps)

# ══════════════════════════════════════════════════════════════════════════════
# RASTER PANEL  (monitor tab — fixed N-most-recent-rows view)
# ══════════════════════════════════════════════════════════════════════════════
#
# RENDERING FIX (the whole point of this rewrite): the old panel kept a figure
# tall enough to hold EVERY row and wrapped it in a scrollable Tk canvas. Once an
# experiment had run for a while that was an enormous amount of (mostly
# off-screen) vector geometry being kept around and redrawn, and rendering
# ground to a halt. This version draws ONLY the most recent `visible_rows` rows
# into a small fixed-size figure, so the cost of each redraw is bounded no matter
# how long the experiment has been running.
#
# Lick events → filled BLOCKS (fill_betweenx) from onset to offset.
# Load cell   → translucent shaded area + line, fixed user-set gram limits.
# Row 0 of the visible window sits at the TOP; time flows downward and L→R.
# All timing params (bin width, seconds/row, visible rows) are per-instance and
# are pushed in from MainWindow's monitor settings.


def _fmt_hms(seconds: float) -> str:
    """Format an elapsed-seconds value as H:MM:SS (or M:SS under an hour)."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def _value_at(samples, t):
    """Last sample value at or before time t (step/zero-order hold), or None.

    `samples` is a list of (t_ms, value) sorted by time. Used to carry the most
    recent load reading forward so the trace has no gaps (Task LC24).
    """
    import bisect
    if not samples:
        return None
    ts = [s[0] for s in samples]
    i = bisect.bisect_right(ts, t) - 1
    if i < 0:
        return None
    return samples[i][1]


def _row_step_polyline(samples, row_lo_ms, row_hi_ms, tb, bpr, t_end_ms=None):
    """Step polyline for one raster row, spanning the FULL row width (Task LC24).

    Returns (xs, ys) in bin-units where xs runs 0 → bpr with zero-order-hold
    steps, so the load trace is continuous left-to-right across the whole row
    instead of starting at the first sample and ending at the last. `samples`
    is the complete (t_ms, value) history for that channel, sorted by time; the
    value carried in at the row's left edge is whatever was last seen before it.

    `t_end_ms` bounds the trace to the data's actual extent: the hold is not
    carried past it, so rows entirely after the last event stay empty (no
    drawing into the empty future). Callers prepend a (0, first_value) sample so
    the trace also reaches back to the experiment start (first-report continuity).
    """
    if t_end_ms is not None and row_lo_ms >= t_end_ms:
        return [], []                       # row is entirely past the data
    right_ms = row_hi_ms
    if t_end_ms is not None:
        right_ms = min(row_hi_ms, t_end_ms)
    right_x = (right_ms - row_lo_ms) / tb
    carried = _value_at(samples, row_lo_ms)
    in_row = [(t, v) for (t, v) in samples
              if row_lo_ms <= t < row_hi_ms and (t_end_ms is None or t <= t_end_ms)]
    xs, ys = [], []
    if carried is not None:
        xs.append(0.0); ys.append(carried)
    cur = carried
    for t, v in in_row:
        x = (t - row_lo_ms) / tb
        if cur is not None:          # horizontal hold then vertical step
            xs.append(x); ys.append(cur)
        xs.append(x); ys.append(v)
        cur = v
    if cur is not None:
        xs.append(float(right_x)); ys.append(cur)
    return xs, ys


class RasterPanel:
    """Fixed-size matplotlib raster showing the most recent rows for one exp."""

    def __init__(self, parent: tk.Widget, exp_id: int, *,
                 timebin_ms: int = TIMEBIN_MS,
                 seconds_per_row: int = SECONDS_PER_ROW,
                 visible_rows: int = MONITOR_VISIBLE_ROWS):
        """Build a single fixed-size raster figure embedded directly in `parent`."""
        self.exp_id          = exp_id
        self.timebin_ms      = max(1, int(timebin_ms))
        self.seconds_per_row = max(1, int(seconds_per_row))
        self.visible_rows    = max(1, int(visible_rows))
        # Task 5 axis config (overwritten from settings by MainWindow)
        self.load_ymin   = LOAD_YMIN
        self.load_ymax   = LOAD_YMAX
        self.load_yticks = LOAD_YTICKS
        self.load_show   = True     # Task V1
        self.load_lw     = 0.9      # monitor load line width

        # A single, fixed-size figure — no scroll canvas, no figure resizing.
        self._fig = Figure(figsize=(6, 2.6), dpi=96, facecolor=BG_PNL)
        self._ax  = self._fig.add_subplot(111)
        self._fig.subplots_adjust(left=0.10, right=0.92, top=0.86, bottom=0.18)
        self._canvas = FigureCanvasTkAgg(self._fig, master=parent)
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._render([])

    # ── derived ───────────────────────────────────────────────────────────────
    @property
    def bins_per_row(self) -> int:
        """Number of x-bins in one row at the current bin width / row span."""
        return max(1, (self.seconds_per_row * 1000) // self.timebin_ms)

    # ── configuration setters ──────────────────────────────────────────────────
    def set_load_axis(self, ymin: float, ymax: float, yticks: int,
                      show: Optional[bool] = None,
                      linewidth: Optional[float] = None):
        """Update the fixed load-cell gram limits (from the visuals tab)."""
        self.load_ymin   = ymin
        self.load_ymax   = ymax
        self.load_yticks = max(2, int(yticks))
        if show is not None:
            self.load_show = bool(show)
        if linewidth is not None:
            self.load_lw = max(0.1, float(linewidth))

    def set_time_params(self, timebin_ms: int, seconds_per_row: int,
                        visible_rows: Optional[int] = None):
        """Update the monitor raster timing (from the visuals tab)."""
        self.timebin_ms      = max(1, int(timebin_ms))
        self.seconds_per_row = max(1, int(seconds_per_row))
        if visible_rows:
            self.visible_rows = max(1, int(visible_rows))

    # ── public update ───────────────────────────────────────────────────────────
    def update(self, events: List[EventRow]):
        """Redraw the raster from the event list (only the most recent rows)."""
        self._render(events)

    def save_png(self, path: str):
        """Save the current (visible-window) raster figure to a PNG file."""
        self._fig.savefig(path, dpi=150, bbox_inches="tight",
                          facecolor=self._fig.get_facecolor())

    # ── internals ───────────────────────────────────────────────────────────────
    def _render(self, events: List[EventRow]):
        """Draw only the most recent `visible_rows` rows into the fixed figure."""
        ax = self._ax
        ax.cla()

        row_ms = self.seconds_per_row * 1000
        bpr    = self.bins_per_row
        tb     = self.timebin_ms

        max_ms    = max((e.timestamp_ms for e in events), default=0)
        last_row  = int(max_ms // row_ms)
        first_row = max(0, last_row - self.visible_rows + 1)
        n_disp    = last_row - first_row + 1            # 1 .. visible_rows
        win_lo    = first_row * row_ms                  # window lower bound (ms)

        self._style_ax(ax, first_row, n_disp, bpr, tb)

        # Alternating row backgrounds (display coords 0 .. n_disp).
        for d in range(n_disp):
            if (first_row + d) % 2 == 1:
                ax.axhspan(d, d + 1, color=BG_ALT, zorder=0, linewidth=0)

        if self.load_show:
            self._draw_load_ticks(ax, n_disp, bpr)

        # ── Filled lick blocks (kept identical in style to the old quadrant) ────
        for on_eid, off_eid, color in ((_L_ON, _L_OFF, CLR_L),
                                       (_R_ON, _R_OFF, CLR_R)):
            on_times  = sorted(e.timestamp_ms for e in events if e.event_id == on_eid)
            off_times = sorted(e.timestamp_ms for e in events if e.event_id == off_eid)
            off_pool  = list(off_times)
            for on in on_times:
                nxt = next((o for o in off_pool if o >= on), None)
                if nxt is None:
                    nxt = on + tb              # no offset yet — 1 bin minimum
                else:
                    off_pool.remove(nxt)
                nxt = max(nxt, on + tb)        # enforce a visible 1-bin minimum
                if nxt < win_lo:               # entirely before the window
                    continue
                t = on
                while t < nxt:
                    row     = t // row_ms
                    row_end = (row + 1) * row_ms
                    seg_end = min(nxt, row_end)
                    if row >= first_row:
                        d  = row - first_row
                        x0 = (t       % row_ms) / tb
                        x1 = (seg_end % row_ms) / tb
                        if x1 == 0:
                            x1 = bpr
                        ax.fill_betweenx([d, d + 0.78], x0, x1,
                                         color=color, alpha=0.92,
                                         linewidth=0, zorder=3)
                    t = seg_end

        # ── Experiment onset / offset markers ───────────────────────────────────
        for evt in events:
            if evt.event_id not in (_EXP_ONSET, _EXP_OFFSET):
                continue
            row = evt.timestamp_ms // row_ms
            if row < first_row:
                continue
            d     = row - first_row
            bin_x = (evt.timestamp_ms % row_ms) // tb
            ax.plot([bin_x, bin_x], [d, d + 0.95],
                    color=CLR_EXP, linewidth=1.8, zorder=5)

        # ── Load cell traces (Task V1/LC24/LC25/LC26) ───────────────────────────
        # V1: only when enabled. LC24: continuous zero-order-hold across the full
        # row width (no gaps). LC25: HIGH value at the TOP of the row band, low at
        # the bottom. LC26: shading stays within the row band (line → row bottom).
        span = self.load_ymax - self.load_ymin
        if self.load_show and span > 0:
            t_end = max((e.timestamp_ms for e in events), default=0)
            band_top = 0.08          # fraction below the row's top edge
            band_bot = 0.92          # fraction above the row's bottom edge
            band_h   = band_bot - band_top
            for load_eid, color in ((_L_LOAD, CLR_L), (_R_LOAD, CLR_R)):
                samples = sorted(
                    (e.timestamp_ms,
                     float(np.clip((e.amplitude - self.load_ymin) / span, 0.0, 1.0)))
                    for e in events if e.event_id == load_eid)
                if not samples:
                    continue
                # Carry the first reading back to t=0 so the trace reaches the
                # experiment start (first-report continuity, Task LC24).
                if samples[0][0] > 0:
                    samples = [(0, samples[0][1])] + samples
                for d in range(n_disp):
                    row_idx = first_row + d
                    row_lo  = row_idx * row_ms
                    row_hi  = row_lo + row_ms
                    xs, ysn = _row_step_polyline(samples, row_lo, row_hi, tb,
                                                 bpr, t_end_ms=t_end)
                    if not xs:
                        continue
                    xs  = np.asarray(xs)
                    ysn = np.asarray(ysn)
                    line_y = (d + band_bot) - ysn * band_h     # high → top
                    base_y = d + band_bot                      # row bottom
                    ax.fill_between(xs, line_y, base_y, color=color,
                                    alpha=0.16, linewidth=0, zorder=2)
                    ax.plot(xs, line_y, color=color, alpha=0.55,
                            linewidth=self.load_lw, zorder=2)

        self._canvas.draw_idle()

    def _style_ax(self, ax, first_row: int, n_disp: int, bpr: int, tb: int):
        """Style axes for the visible window; rows labelled by elapsed time."""
        ax.set_facecolor(BG_PNL)
        for sp in ax.spines.values():
            sp.set_color(BG_ALT)
        ax.tick_params(colors=FG_MUT, labelsize=6)

        # X axis labelled in MINUTES (tick spacing snapped to a nice value).
        row_s = self.seconds_per_row
        nice_s = [15, 30, 60, 120, 300, 600, 900, 1800, 3600]
        target = max(1.0, row_s / 8.0)
        tick_s = min(nice_s, key=lambda v: abs(v - target))
        step   = max(1, int(round((tick_s * 1000) / tb)))   # bins per tick
        x_ticks  = np.arange(0, bpr + 1, step)
        x_labels = [f"{(t * tb / 60000):g}" for t in x_ticks]   # bins → minutes
        ax.set_xticks(x_ticks)
        ax.set_xticklabels(x_labels, fontsize=6, color=FG_MUT)
        ax.set_xlim(0, bpr)
        ax.set_xlabel("min", fontsize=6, color=FG_MUT, labelpad=1)

        # Inverted y so the earliest visible row is at the TOP.
        ax.set_ylim(n_disp, 0)
        ax.set_yticks(np.arange(n_disp) + 0.5)
        ax.set_yticklabels(
            [_fmt_hms((first_row + d) * self.seconds_per_row)
             for d in range(n_disp)],
            fontsize=6, color=FG_MUT)

        ax.set_title(f"Box {self.exp_id}", fontsize=8, color=FG, pad=3, loc="left")
        ax.legend(
            handles=[
                mpatches.Patch(color=CLR_L,           label="L lick"),
                mpatches.Patch(color=CLR_R,           label="R lick"),
                mpatches.Patch(color=CLR_L, alpha=.4, label="L load"),
                mpatches.Patch(color=CLR_R, alpha=.4, label="R load"),
                mpatches.Patch(color=CLR_EXP,         label="Onset/Off"),
            ],
            loc="upper right", fontsize=5, framealpha=0.25,
            facecolor=BG_PNL, edgecolor=BG_ALT, labelcolor=FG, ncol=5)

    def _draw_load_ticks(self, ax, n_disp: int, bpr: int):
        """Dotted reference lines + gram labels for the load scale (Task 5).

        Faint reference lines are drawn at every tick level in every visible
        row; the right edge of each row is then labelled with the load-cell
        scale MIN (at the baseline) and MAX (at the trace peak) in grams, so
        the area-plot amplitude can be read directly off the right axis.
        """
        span = self.load_ymax - self.load_ymin
        if span <= 0:
            return
        band_top, band_bot = 0.08, 0.92
        band_h = band_bot - band_top
        ticks = np.linspace(self.load_ymin, self.load_ymax,
                            max(2, int(self.load_yticks)))
        for d in range(n_disp):
            for tg in ticks:
                frac = (tg - self.load_ymin) / span
                y = (d + band_bot) - frac * band_h        # high value → top
                ax.plot([0, bpr], [y, y], color=FG_MUT, alpha=0.10,
                        linewidth=0.5, linestyle=(0, (2, 3)), zorder=1)
        # Right-edge scale labels: MAX at the row top, MIN at the row bottom.
        for d in range(n_disp):
            ax.text(bpr * 1.01, d + band_bot, f"{self.load_ymin:g}",
                    fontsize=5, color=FG_MUT, va="center", ha="left")
            ax.text(bpr * 1.01, d + band_top, f"{self.load_ymax:g}",
                    fontsize=5, color=FG_MUT, va="center", ha="left")
        # Unit marker, once, just above the first row's max label.
        ax.text(bpr * 1.01, 0.0, "g", fontsize=5, color=FG_MUT,
                va="center", ha="left")

# ══════════════════════════════════════════════════════════════════════════════
# EXPERIMENT QUADRANT  (one of four panes in the MONITOR tab)
# ══════════════════════════════════════════════════════════════════════════════
#
# The quadrant keeps the same left-lick / right-lick / load display as before,
# but the raster now shows only the most recent rows (see RasterPanel) and the
# event-log tree shows only the most recent X minutes (X = the autosave interval
# chosen on the setup page). Old rows scroll off the top of both views.

class ExpQuadrant(tk.Frame):
    def __init__(self, master, model: ExperimentModel,
                 reader: SerialReader, arduino_ts: list, host):
        """Build one monitor pane: controls, recent-rows raster, rolling event log."""
        super().__init__(master, bg=BG_PNL,
                         highlightbackground=BG_ALT, highlightthickness=1)
        self.model        = model
        self._reader      = reader
        self._arduino_ts  = arduino_ts
        self._host        = host          # MainWindow, for save folder / params
        self._refresh_job = None
        self._shown       = 0
        # Rolling window of inserted tree rows: list of (elapsed_ms, item_id).
        self._tree_items: List[Tuple[int, str]] = []
        self._build()

    def _build(self):
        """Assemble the control strip, recent-rows raster, and rolling event log."""
        top = tk.Frame(self, bg=BG_PNL, pady=3)
        top.pack(fill=tk.X, padx=4)

        tk.Label(top, text=f"Box {self.model.exp_id}",
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

        # Recent-rows raster (fixed size, no scrolling).
        plot_frame = tk.Frame(self, bg=BG_PNL)
        plot_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        mp = self._host.monitor_settings()
        self._raster = RasterPanel(
            plot_frame, self.model.exp_id,
            timebin_ms=mp["monitor_timebin_ms"],
            seconds_per_row=mp["monitor_seconds_per_row"])
        pv = self._host.plot_settings()
        self._raster.set_load_axis(pv["load_ymin"], pv["load_ymax"],
                                   pv["load_yticks"],
                                   show=bool(pv.get("load_show", 1)))

        # Rolling event log (last X minutes only).
        log_outer = tk.Frame(self, bg=BG_PNL, height=108)
        log_outer.pack(fill=tk.X, padx=2, pady=(0, 2))
        log_outer.pack_propagate(False)

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
        for c, w, lbl in (("ts", 72, "min"), ("id", 36, "ID"),
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

    def set_run_locked(self, locked: bool):
        """Task S1: disable the Run button during the post-stream lockout.

        When unlocking, only re-enable Run if the experiment isn't already
        running (so a running box keeps Run disabled as usual).
        """
        if locked:
            self._run_btn.config(state=tk.DISABLED)
        elif not self.model.running:
            self._run_btn.config(state=tk.NORMAL)

    def apply_plot_settings(self):
        """Re-apply visuals-tab settings (load axis + monitor timing) and redraw."""
        pv = self._host.plot_settings()
        mp = self._host.monitor_settings()
        self._raster.set_load_axis(pv["load_ymin"], pv["load_ymax"],
                                   pv["load_yticks"],
                                   show=bool(pv.get("load_show", 1)))
        self._raster.set_time_params(mp["monitor_timebin_ms"],
                                     mp["monitor_seconds_per_row"])
        self._raster.update(self.model.get_log())

    # ── Controls ──────────────────────────────────────────────────────────────

    def _run(self):
        """Start the experiment: clear the log/tree and begin the monitor refresh."""
        if not self.model.running:
            self.model.start(self._arduino_ts[0])
            self._run_btn.config(state=tk.DISABLED)
            self._stop_btn.config(state=tk.NORMAL)
            self._shown = 0
            for _, iid in self._tree_items:
                try:
                    self._tree.delete(iid)
                except Exception:
                    pass
            self._tree_items.clear()
            self._host.note_run_state_changed()
            self._schedule()

    def _stop_and_save(self):
        """Stop the experiment, flush the final frame, and prompt to save .npy + .png."""
        if self.model.running:
            self.model.stop(self._arduino_ts[0])
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
            self._refresh_job = None
        self._refresh()  # final flush
        self._host.note_run_state_changed()

        stem = f"exp{self.model.exp_id}_{datetime.datetime.now():%Y%m%d_%H%M%S}"
        initdir = self._host.get_save_folder() or _HERE
        npy = filedialog.asksaveasfilename(
            title=f"Save Exp {self.model.exp_id} event log",
            initialdir=initdir,
            initialfile=stem + ".npy",
            defaultextension=".npy",
            filetypes=[("NumPy", "*.npy")])
        if npy:
            self.model.export_npy(npy)
            png = os.path.splitext(npy)[0] + ".png"
            # Save the full-experiment (imshow) view — the complete picture.
            self._host.save_full_png(self.model.exp_id, png)
            messagebox.showinfo("Saved", f"Log  → {npy}\nPlot → {png}")

        self._run_btn.config(state=tk.NORMAL)
        self._stop_btn.config(state=tk.DISABLED)
        self._status.set("Stopped")

    # ── Monitor refresh ─────────────────────────────────────────────────────────

    def _schedule(self):
        """Schedule the next monitor refresh using the host's refresh interval."""
        interval = int(self._host.monitor_settings()["monitor_refresh_ms"])
        self._refresh_job = self.after(max(100, interval), self._tick)

    def _tick(self):
        """One monitor refresh cycle: redraw, then reschedule if still running."""
        self._refresh()
        if self.model.running:
            self._schedule()

    def _refresh(self):
        """Update the recent-rows raster and scroll the event log to the last X min."""
        events = self.model.get_log()

        # Keep raster timing in sync with the visuals tab, then redraw.
        mp = self._host.monitor_settings()
        self._raster.set_time_params(mp["monitor_timebin_ms"],
                                     mp["monitor_seconds_per_row"])
        self._raster.update(events)

        # Append any newly-arrived events to the tree.
        for e in events[self._shown:]:
            name = _EVT_NAME.get(e.event_id, f"#{e.event_id}")
            tag  = _EVT_TAG.get(e.event_id, "")
            iid = self._tree.insert(
                "", tk.END,
                values=(f"{e.timestamp_ms / 60000:.3f}", e.event_id, name,
                        f"{e.amplitude:.1f}"),
                tags=(tag,))
            self._tree_items.append((e.timestamp_ms, iid))
        self._shown = len(events)

        # Drop rows older than the rolling window (X minutes from setup page).
        win_ms = int(self._host.autosave_minutes() * 60_000)
        if self.model.running and self.model.start_ts is not None:
            now_ms = max(0, self._arduino_ts[0] - self.model.start_ts)
        else:
            now_ms = events[-1].timestamp_ms if events else 0
        cutoff = now_ms - win_ms
        while self._tree_items and self._tree_items[0][0] < cutoff:
            _, iid = self._tree_items.pop(0)
            try:
                self._tree.delete(iid)
            except Exception:
                pass

        if self._tree_items:
            self._tree.yview_moveto(1.0)

        if self.model.running and self.model.start_ts is not None:
            el = (self._arduino_ts[0] - self.model.start_ts) / 1000
            self._status.set(f"● {el:.0f} s")

# ══════════════════════════════════════════════════════════════════════════════
# FULL-VIEW PANEL  (one tab per experiment — whole-experiment superimposed raster)
# ══════════════════════════════════════════════════════════════════════════════
#
# A FIXED-SIZE view of the entire experiment (default 24 rows × 3600 s/row) in a
# SINGLE raster. Left and right licks are superimposed as two count heat-maps in
# their own colours (left = red, right = blue, matching the monitor tab); colour
# intensity (alpha) encodes the lick count per coarse bin. On top of the licks,
# each load cell is drawn as a translucent shaded line plot in the matching
# colour, exactly like the monitor quadrants. All 24 rows hold the full data set
# overlaid — there are NOT two separate sub-plots.

class FullViewPanel(tk.Frame):
    """Whole-experiment raster: superimposed L/R lick heat-maps (left = rose,
    right = cyan, colour intensity = lick count, each with its own count
    colour-bar) plus offset load-cell line plots (left = teal, right = purple)."""

    # Sequential colormaps: faint (least-dense bin) → saturated (densest bin).
    # Tol-muted hues so L/R stay distinguishable for colour-blind viewers.
    _CMAP_L = mcolors.LinearSegmentedColormap.from_list(
        "Lrose", ["#F2DCE0", "#CC6677"])     # pale rose → Tol rose (left)
    _CMAP_R = mcolors.LinearSegmentedColormap.from_list(
        "Rcyan", ["#DCEEF7", "#88CCEE"])     # pale cyan → Tol cyan (right)

    def __init__(self, parent, exp_id: int, *,
                 rows: int = FULL_ROWS,
                 seconds_per_row: int = FULL_SECONDS_PER_ROW,
                 bin_seconds: int = FULL_BIN_SECONDS):
        """Build the main raster axis plus two lick-count colour-bars."""
        super().__init__(parent, bg=BG)
        self.exp_id          = exp_id
        self.rows            = max(1, int(rows))
        self.seconds_per_row = max(1, int(seconds_per_row))
        self.bin_seconds     = max(1, int(bin_seconds))
        # Load-cell gram axis (pushed in from the Raster Plot Visuals tab so the
        # load line plots use the same scale as the monitor quadrants).
        self.load_ymin = LOAD_YMIN
        self.load_ymax = LOAD_YMAX
        self.load_show = True       # Task V1
        self.load_lw   = 1.2        # Task LC27: half the old 2.4 default

        self._fig = Figure(figsize=(10, 6.5), dpi=96, facecolor=BG)
        # Main raster (left, wide) + two slim colour-bar axes stacked on the right.
        gs = self._fig.add_gridspec(
            2, 2, width_ratios=[40, 1], height_ratios=[1, 1],
            left=0.06, right=0.90, top=0.92, bottom=0.09,
            hspace=0.45, wspace=0.04)
        self._ax    = self._fig.add_subplot(gs[:, 0])
        self._cax_l = self._fig.add_subplot(gs[0, 1])   # left-lick count bar
        self._cax_r = self._fig.add_subplot(gs[1, 1])   # right-lick count bar
        self._canvas = FigureCanvasTkAgg(self._fig, master=self)
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.update_view([])

    # ── geometry ────────────────────────────────────────────────────────────────
    @property
    def cols(self) -> int:
        """Number of x-bins per row at the current row span / bin width."""
        return max(1, self.seconds_per_row // self.bin_seconds)

    def set_load_axis(self, ymin: float, ymax: float,
                      show: Optional[bool] = None,
                      linewidth: Optional[float] = None):
        """Set the gram limits used to normalise the load-cell line plots."""
        self.load_ymin = ymin
        self.load_ymax = ymax
        if show is not None:
            self.load_show = bool(show)
        if linewidth is not None:
            self.load_lw = max(0.1, float(linewidth))

    def reconfigure(self, rows: int, seconds_per_row: int, bin_seconds: int):
        """Change the grid geometry. Picked up on the next update_view()."""
        self.rows            = max(1, int(rows))
        self.seconds_per_row = max(1, int(seconds_per_row))
        self.bin_seconds     = max(1, int(bin_seconds))

    @staticmethod
    def build_matrices(events, rows, seconds_per_row, bin_seconds):
        """Return (left_counts, right_counts) matrices of shape (rows, cols).

        Each lick ONSET is binned by its elapsed time; a bin holds the NUMBER of
        licks that fell in it, so colour intensity can encode count. Events past
        the end of the grid are clamped into the final bin rather than dropped.
        """
        cols = max(1, seconds_per_row // bin_seconds)
        matL = np.zeros((rows, cols), dtype=np.float64)
        matR = np.zeros((rows, cols), dtype=np.float64)
        total_s = rows * seconds_per_row
        for e in events:
            if e.event_id == _L_ON:
                mat = matL
            elif e.event_id == _R_ON:
                mat = matR
            else:
                continue
            t_s = e.timestamp_ms / 1000.0
            if t_s < 0:
                continue
            if t_s >= total_s:                 # clamp into the last cell
                r, c = rows - 1, cols - 1
            else:
                r = int(t_s // seconds_per_row)
                c = int((t_s % seconds_per_row) // bin_seconds)
                r = min(r, rows - 1)
                c = min(c, cols - 1)
            mat[r, c] += 1
        return matL, matR

    @staticmethod
    def _counts_to_rgba(mat, cmap, vmax):
        """Map a count matrix through `cmap` so colour goes from faint (1 lick)
        to saturated (`vmax` licks); empty bins are fully transparent. Returns an
        (rows, cols, 4) RGBA image so two such layers can be superimposed."""
        denom = max(1e-9, float(vmax) - 1.0)
        frac  = np.clip((mat - 1.0) / denom, 0.0, 1.0)   # 1 → 0.0, vmax → 1.0
        rgba  = cmap(frac)                               # (rows, cols, 4)
        rgba[..., 3] = np.where(mat > 0, 0.80, 0.0)      # transparent where empty
        return rgba

    # ── data update / draw ──────────────────────────────────────────────────────
    def update_view(self, events):
        """Redraw the whole-experiment raster from `events`."""
        ax = self._ax
        ax.cla()
        R, C = self.rows, self.cols
        sec_row = self.seconds_per_row
        bin_s   = self.bin_seconds

        self._style_ax(ax, R, C)

        # Alternating row backgrounds for readability.
        for r in range(R):
            if r % 2 == 1:
                ax.axhspan(r, r + 1, color=BG_ALT, zorder=0, linewidth=0)

        # ── Superimposed lick heat-maps: left red, right blue, each scaled to
        #    its OWN max count so its colour-bar reads that side's range ────────
        matL, matR = self.build_matrices(events, R, sec_row, bin_s)
        maxL = float(matL.max())
        maxR = float(matR.max())
        for mat, cmap, mx in ((matL, self._CMAP_L, maxL),
                              (matR, self._CMAP_R, maxR)):
            if mx <= 0:
                continue
            rgba = self._counts_to_rgba(mat, cmap, max(mx, 2.0))
            ax.imshow(rgba, extent=(0, C, R, 0), origin="upper",
                      aspect="auto", interpolation="nearest", zorder=2)

        # ── Count colour-bars (the heat-map legends): faint = least-dense bin,
        #    saturated = densest bin, ticks show the actual lick counts ────────
        self._draw_count_bar(self._cax_l, self._CMAP_L, maxL, "L licks/bin")
        self._draw_count_bar(self._cax_r, self._CMAP_R, maxR, "R licks/bin")

        # ── Load-cell line plots (Task V1/LC24/LC25/LC27/LC28) ──────────────────
        # V1: only when enabled. LC24: zero-order-hold across the full row width.
        # LC25: HIGH value at the row TOP. LC27: editable (default-halved) width.
        span = self.load_ymax - self.load_ymin
        if self.load_show and span > 0:
            t_end = max((e.timestamp_ms for e in events), default=0)
            band_top, band_bot = 0.12, 0.88
            band_h = band_bot - band_top
            tb_ms  = bin_s * 1000                  # ms per column
            for load_eid, color in ((_L_LOAD, CLR_LOAD_L), (_R_LOAD, CLR_LOAD_R)):
                samples = sorted(
                    (e.timestamp_ms,
                     float(min(max((e.amplitude - self.load_ymin) / span, 0.0), 1.0)))
                    for e in events if e.event_id == load_eid)
                if not samples:
                    continue
                if samples[0][0] > 0:              # carry first reading back to 0
                    samples = [(0, samples[0][1])] + samples
                for r in range(R):
                    row_lo = r * sec_row * 1000
                    row_hi = (r + 1) * sec_row * 1000
                    xs, ysn = _row_step_polyline(samples, row_lo, row_hi,
                                                 tb_ms, C, t_end_ms=t_end)
                    if not xs:
                        continue
                    xs  = np.asarray(xs)
                    ysn = np.asarray(ysn)
                    line_y = (r + band_bot) - ysn * band_h   # high → top
                    ax.plot(xs, line_y, color=color, alpha=0.9,
                            linewidth=self.load_lw, zorder=4)

            # LC28: right-edge load-cell gram labels (max at row top, min at bottom).
            for r in range(R):
                ax.text(C * 1.005, r + band_top, f"{self.load_ymax:g}",
                        fontsize=6, color=FG_MUT, va="center", ha="left",
                        zorder=6)
                ax.text(C * 1.005, r + band_bot, f"{self.load_ymin:g}",
                        fontsize=6, color=FG_MUT, va="center", ha="left",
                        zorder=6)
            ax.text(C * 1.005, -0.15, "g", fontsize=6, color=FG_MUT,
                    va="center", ha="left", zorder=6)

        # Re-assert limits (imshow can otherwise rescale them).
        ax.set_xlim(0, C)
        ax.set_ylim(R, 0)
        self._canvas.draw_idle()

    def _draw_count_bar(self, cax, cmap, maxcount, label):
        """Draw a lick-count colour-bar on `cax` with ticks at the least-dense
        (1) and densest (max) bin counts."""
        cax.cla()
        vmax = max(2.0, float(maxcount))
        sm = ScalarMappable(norm=mcolors.Normalize(vmin=1, vmax=vmax), cmap=cmap)
        sm.set_array([])
        cb = self._fig.colorbar(sm, cax=cax)
        # Ticks at the extremes the user asked about: least dense vs densest.
        if maxcount >= 2:
            ticks = sorted({1, int(round(maxcount))})
        else:
            ticks = [1]
        cb.set_ticks(ticks)
        cb.set_ticklabels([str(t) for t in ticks])
        cb.set_label(label, color=FG, fontsize=7)
        cax.tick_params(colors=FG_MUT, labelsize=7)
        cb.outline.set_edgecolor(BG_ALT)

    def _style_ax(self, ax, R: int, C: int):
        """Theme + axes labels: x in minutes within a row, y by row-start time."""
        ax.set_facecolor(BG_PNL)
        for sp in ax.spines.values():
            sp.set_color(BG_ALT)
        ax.tick_params(colors=FG_MUT, labelsize=7)
        ax.set_xlim(0, C)
        ax.set_ylim(R, 0)

        # X ticks labelled in MINUTES from the start of each row.
        row_s  = self.seconds_per_row
        nice_s = [15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200]
        target = max(1.0, row_s / 6.0)
        tick_s = min(nice_s, key=lambda v: abs(v - target))
        xt, i = [], 0
        while (i * tick_s) <= row_s:
            xpos = (i * tick_s) / self.bin_seconds
            if xpos <= C:
                xt.append(xpos)
            i += 1
        # LC28: one extra tick mark at the row's right edge.
        if xt and xt[-1] < C:
            xt.append(C)
        ax.set_xticks(xt)
        ax.set_xticklabels(
            [f"{(x * self.bin_seconds / 60):g}" for x in xt],
            fontsize=7, color=FG_MUT)
        ax.set_xlabel("time within row (min)", fontsize=8, color=FG_MUT)

        # Y ticks: one per row (capped), labelled by the row's start time.
        # LC28: one extra tick beyond the usual cap.
        n_yt = min(R, 13)
        yt = sorted(set(np.linspace(0, R - 1, n_yt).round().astype(int).tolist()))
        ax.set_yticks([v + 0.5 for v in yt])
        ax.set_yticklabels([_fmt_hms(v * self.seconds_per_row) for v in yt],
                           fontsize=7, color=FG_MUT)
        ax.set_ylabel("row start", fontsize=8, color=FG_MUT)

        ax.set_title(f"Box {self.exp_id} — licks (L rose / R cyan, intensity = "
                     f"count) + load", fontsize=10, color=FG, loc="left", pad=4)
        ax.legend(
            handles=[
                mpatches.Patch(color=CLR_L, label="L lick"),
                mpatches.Patch(color=CLR_R, label="R lick"),
                Line2D([0], [0], color=CLR_LOAD_L, linewidth=2.4, label="L load"),
                Line2D([0], [0], color=CLR_LOAD_R, linewidth=2.4, label="R load"),
            ],
            loc="upper right", fontsize=6, framealpha=0.30,
            facecolor=BG_PNL, edgecolor=BG_ALT, labelcolor=FG, ncol=4)

    def save_png(self, path: str):
        """Save the full-view figure to a PNG file."""
        self._fig.savefig(path, dpi=150, bbox_inches="tight",
                          facecolor=self._fig.get_facecolor())

# ══════════════════════════════════════════════════════════════════════════════
# MAIN WINDOW
# ══════════════════════════════════════════════════════════════════════════════

# Task S1: rotating messages shown for 9 s after the Arduino stream starts, one
# every 1.5 s (6 messages × 1.5 s = 9 s), while run + calibration are locked.
INIT_MSGS = [
    "initializing...verifying mouse aliveness",
    "initializing...monitoring radiation levels",
    "initializing...putting out fires",
    "initializing...preventing cataclysmic events",
    "initializing...taking a coffee break",
    "initialization complete...ready to lick",
]
INIT_LOCKOUT_MS = 9000
INIT_STEP_MS    = 1500

class MainWindow(tk.Tk):
    def __init__(self, initial_port: Optional[str] = None,
                 hub_config: Optional[dict] = None):
        """Read persisted settings, build the full GUI, and start the flag watchdog.

        `hub_config` (Task H1-H4), when supplied by the hub launcher, carries:
            port            COM port this instance drives
            num_boxes       1-4 boxes (drives tab count + monitor layout)
            instance_folder the per-instance folder (settings json lives here)
            data_folder     subfolder where autosaved per-box data is written
            settings_file   per-instance settings json path (already applied)
            autosave_minutes  optional autosave interval
            sketch_name / sketch_path  the flashed Arduino sketch (recorded)
        When hub_config is present the mandatory setup page is skipped and these
        values are used directly; otherwise the original standalone setup page
        runs so the GUI still works when launched on its own.
        """
        super().__init__()

        self._hub_config = hub_config or {}

        # Task 3: load persisted settings first so everything populates from them.
        self._settings = load_settings()
        port = (self._hub_config.get("port") or initial_port
                or self._settings["shared"].get("port") or SERIAL_PORT)

        # Number of boxes this instance drives (Task H2). From the hub if given,
        # else from persisted settings, clamped to 1-4.
        try:
            self.num_boxes = int(self._hub_config.get(
                "num_boxes",
                self._settings["shared"].get("num_boxes", 4)))
        except (TypeError, ValueError):
            self.num_boxes = 4
        self.num_boxes = max(1, min(4, self.num_boxes))

        self.title(f"Lickometer  ·  Columbia AIC  ·  {port}  ·  "
                   f"{self.num_boxes} box{'es' if self.num_boxes != 1 else ''}")
        self.configure(bg=BG)
        self.geometry("1440x980")

        # Shared vars created up-front so the setup page and the Data tab edit
        # the SAME save-folder / autosave-interval values.
        self._folder_var = tk.StringVar(
            value=self._settings["shared"].get("save_folder", ""))
        self._autosave_min_var = tk.StringVar(
            value=str(self._settings["shared"].get("autosave_minutes",
                                                   AUTOSAVE_MINUTES)))

        # ── MANDATORY setup page (Task 1) ─────────────────────────────────────
        # Hide the main window and force the user to pick a save folder and an
        # autosave interval before anything else is shown — UNLESS the hub
        # already provided that config (Task H3), in which case we apply it and
        # skip the page entirely.
        self.alive = True
        self.withdraw()
        if self._hub_config:
            if not self._apply_hub_config():
                self.alive = False
                self.destroy()
                return
        else:
            if not self._run_setup_page():
                self.alive = False
                self.destroy()
                return
        self.deiconify()
        # Make sure the main window actually comes to the front (under Spyder it
        # can otherwise open behind the IDE or off-screen).
        self.lift()
        try:
            self.attributes("-topmost", True)
            self.after(200, lambda: self.attributes("-topmost", False))
        except Exception:
            pass
        self.focus_force()
        self._reader     = SerialReader()
        self._reader.port = port
        self._models     = {i: ExperimentModel(i)
                            for i in range(1, self.num_boxes + 1)}
        self._arduino_ts = [0]
        self._connected  = False
        self._streaming  = False
        self._last_raw:  Dict[int, float] = {}   # {arduino_id: last_amp}
        self._snaps:     Dict[tuple, float] = {} # {(load_id, "50g"|"bottle"): val}
        self._quadrants: List[ExpQuadrant] = []
        self._fullviews: Dict[int, FullViewPanel] = {}   # exp_id → full-view tab
        self._central_job = None

        # Apply persisted calibration to the models before the GUI builds.
        self._apply_loaded_calibration(port)

        self._build(port)
        self._refresh_loaded_into_gui()          # Task 3: populate GUI fields

        # Task 2: start the flag watchdog (runs in the Tk main loop).
        self.after(WATCHDOG_MS, self._watchdog_tick)
        # Task 1/6: central autosave + full-view refresh on the X-minute cycle.
        self._schedule_central()

    # ══════════════════════════════════════════════════════════════════════════
    # HUB CONFIG (Task H1-H4) — used instead of the setup page when launched
    # from the hub. Applies the per-instance folder layout and records the
    # flashed Arduino sketch into this instance's settings file.
    # ══════════════════════════════════════════════════════════════════════════

    def _apply_hub_config(self) -> bool:
        """Apply hub-provided folder/box/sketch config; returns True on success."""
        cfg = self._hub_config
        # data_folder is where autosaved per-box data is written (Task H3).
        data_folder = cfg.get("data_folder") or cfg.get("instance_folder", "")
        if data_folder:
            try:
                os.makedirs(data_folder, exist_ok=True)
            except Exception as e:
                print(f"[hub] could not create data folder: {e}")
            self._folder_var.set(data_folder)
            save_shared_value("save_folder", data_folder)
            self._settings["shared"]["save_folder"] = data_folder

        if cfg.get("autosave_minutes"):
            try:
                mins = float(cfg["autosave_minutes"])
                if mins > 0:
                    self._autosave_min_var.set(str(mins))
                    save_shared_value("autosave_minutes", mins)
                    self._settings["shared"]["autosave_minutes"] = mins
            except (TypeError, ValueError):
                pass

        # Persist box count + flashed-sketch metadata into THIS instance's
        # settings json (Task H2/H4) so each instance records its own.
        save_shared_value("num_boxes", self.num_boxes)
        self._settings["shared"]["num_boxes"] = self.num_boxes
        if cfg.get("sketch_name") or cfg.get("sketch_path"):
            save_shared_value("sketch_name", cfg.get("sketch_name", ""))
            save_shared_value("sketch_path", cfg.get("sketch_path", ""))
            self._settings["shared"]["sketch_name"] = cfg.get("sketch_name", "")
            self._settings["shared"]["sketch_path"] = cfg.get("sketch_path", "")
        return True

    # ══════════════════════════════════════════════════════════════════════════
    # MANDATORY SETUP PAGE (Task 1)
    # ══════════════════════════════════════════════════════════════════════════

    def _run_setup_page(self) -> bool:
        """Modal setup dialog: choose save folder + autosave interval.

        Returns True if the user clicked Continue with a valid folder, False if
        they cancelled / closed the window (the app then exits).
        """
        dlg = tk.Toplevel(self)
        dlg.title("Lickometer — setup")
        dlg.configure(bg=BG)

        # IMPORTANT: do NOT make this dialog transient() to `self`. The main
        # window is withdraw()n at this point, and on Windows an owned/transient
        # window whose owner is hidden is itself NOT shown by the OS — the modal
        # dialog would never appear and the app would block forever in
        # wait_window() (symptom: "kernel running, nothing pops up"). Keeping it
        # an independent top-level avoids that entirely.
        W, H = 640, 300
        dlg.update_idletasks()
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        x, y = (sw - W) // 2, max(0, (sh - H) // 3)
        dlg.geometry(f"{W}x{H}+{x}+{y}")     # explicit position (root is hidden)

        # Force it to actually appear and take focus, even under Spyder.
        dlg.deiconify()
        dlg.lift()
        try:
            dlg.attributes("-topmost", True)
            dlg.after(300, lambda: dlg.attributes("-topmost", False))
        except Exception:
            pass
        dlg.focus_force()
        dlg.grab_set()                      # make it modal (now that it is visible)
        result = {"ok": False}

        tk.Label(dlg, text="Session setup", font=("Segoe UI", 14, "bold"),
                 bg=BG, fg=FG).pack(anchor="w", padx=20, pady=(18, 4))
        tk.Label(dlg,
                 text="Choose where raster plots and event logs are saved, and "
                      "how often they autosave. Both are required before the "
                      "main window opens.",
                 font=FONT, bg=BG, fg=FG_MUT, wraplength=600, justify="left"
                 ).pack(anchor="w", padx=20, pady=(0, 12))

        body = tk.Frame(dlg, bg=BG_PNL, padx=16, pady=14)
        body.pack(fill=tk.X, padx=20)

        tk.Label(body, text="Save folder:", font=FONT, bg=BG_PNL, fg=FG
                 ).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=6)
        tk.Entry(body, textvariable=self._folder_var, width=52,
                 font=FONTM, bg=BG_ALT, fg=FG, insertbackground=FG,
                 relief=tk.FLAT).grid(row=0, column=1, sticky="w", pady=6)

        def browse():
            """Pick a folder for the setup page."""
            folder = filedialog.askdirectory(
                title="Choose save folder",
                initialdir=self._folder_var.get().strip() or _HERE,
                parent=dlg)
            if folder:
                self._folder_var.set(folder)

        tk.Button(body, text="Browse…", font=FONTB, bg=BG_ALT, fg=FG,
                  relief=tk.FLAT, padx=10, command=browse
                  ).grid(row=0, column=2, padx=6, pady=6)

        tk.Label(body, text="Autosave every (minutes):", font=FONT,
                 bg=BG_PNL, fg=FG).grid(row=1, column=0, sticky="w",
                                        padx=(0, 8), pady=6)
        tk.Spinbox(body, from_=1, to=1440, increment=1,
                   textvariable=self._autosave_min_var, width=8,
                   font=FONTM, bg=BG_ALT, fg=FG, relief=tk.FLAT
                   ).grid(row=1, column=1, sticky="w", pady=6)

        btn_row = tk.Frame(dlg, bg=BG)
        btn_row.pack(fill=tk.X, padx=20, pady=18)

        def cont():
            """Validate inputs, persist them, and close the setup page."""
            folder = self._folder_var.get().strip()
            if not folder:
                messagebox.showwarning("Folder required",
                                       "Please choose a save folder.", parent=dlg)
                return
            if not os.path.isdir(folder):
                if messagebox.askyesno(
                        "Create folder?",
                        f"'{folder}' does not exist. Create it?", parent=dlg):
                    try:
                        os.makedirs(folder, exist_ok=True)
                    except Exception as e:
                        messagebox.showerror("Cannot create",
                                             str(e), parent=dlg)
                        return
                else:
                    return
            try:
                mins = float(self._autosave_min_var.get())
                if mins <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Bad interval",
                                     "Autosave interval must be a positive "
                                     "number of minutes.", parent=dlg)
                return
            # Persist (shared across instances).
            save_shared_value("save_folder", folder)
            save_shared_value("autosave_minutes", mins)
            self._settings["shared"]["save_folder"] = folder
            self._settings["shared"]["autosave_minutes"] = mins
            result["ok"] = True
            dlg.destroy()

        tk.Button(btn_row, text="Continue ▶", font=FONTB, bg=CLR_GRN,
                  fg="white", activebackground="#25A244", relief=tk.FLAT,
                  padx=16, pady=5, command=cont).pack(side=tk.RIGHT)
        tk.Button(btn_row, text="Cancel", font=FONTB, bg=BG_ALT, fg=FG,
                  relief=tk.FLAT, padx=12, pady=5,
                  command=dlg.destroy).pack(side=tk.RIGHT, padx=8)

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        self.wait_window(dlg)
        return result["ok"]

    # ══════════════════════════════════════════════════════════════════════════
    # SETTINGS HELPERS (Task 3)
    # ══════════════════════════════════════════════════════════════════════════

    def _apply_loaded_calibration(self, port: str):
        """Apply persisted calibration ratios (from settings JSON) to the experiment models before the GUI opens."""
        psec = self._settings.get("ports", {}).get(port, {})
        cal  = psec.get("calibration", {})
        for exp_str, c in cal.items():
            try:
                exp_id = int(exp_str)
            except ValueError:
                continue
            m = self._models.get(exp_id)
            if not m:
                continue
            m.cal_left  = float(c.get("cal_left",  1.0))
            m.cal_right = float(c.get("cal_right", 1.0))

    def flag_settings(self) -> dict:
        """Current flag thresholds as floats (read from GUI vars if built)."""
        if hasattr(self, "_flag_vars"):
            out = {}
            for k, v in self._flag_vars.items():
                try:
                    out[k] = float(v.get())
                except (ValueError, tk.TclError):
                    out[k] = self._settings["shared"]["flags"][k]
            return out
        return dict(self._settings["shared"]["flags"])

    def plot_settings(self) -> dict:
        """Return current load-cell axis settings as a dict (reads live GUI vars if available)."""
        if hasattr(self, "_plot_vars"):
            out = {}
            for k, v in self._plot_vars.items():
                try:
                    out[k] = float(v.get())
                except (ValueError, tk.TclError):
                    out[k] = self._settings["shared"]["plot"][k]
            out["load_yticks"] = int(out["load_yticks"])
            if "load_show" in out:
                out["load_show"] = int(round(out["load_show"]))
            return out
        return dict(self._settings["shared"]["plot"])

    def get_save_folder(self) -> str:
        """Return the currently configured save folder path (from the GUI var if built)."""
        if hasattr(self, "_folder_var"):
            return self._folder_var.get().strip()
        return self._settings["shared"].get("save_folder", "")

    def monitor_settings(self) -> dict:
        """Monitor raster timing (bin ms, seconds/row, refresh ms) as ints."""
        keys = ("monitor_timebin_ms", "monitor_seconds_per_row",
                "monitor_refresh_ms")
        plot = self._settings["shared"]["plot"]
        out = {}
        for k in keys:
            if hasattr(self, "_monitor_vars") and k in self._monitor_vars:
                try:
                    out[k] = max(1, int(float(self._monitor_vars[k].get())))
                    continue
                except (ValueError, tk.TclError):
                    pass
            out[k] = int(plot[k])
        return out

    def full_settings(self) -> dict:
        """Full-view grid geometry (rows, seconds/row, bin seconds) as ints."""
        keys = ("full_rows", "full_seconds_per_row", "full_bin_seconds")
        plot = self._settings["shared"]["plot"]
        out = {}
        for k in keys:
            if hasattr(self, "_full_vars") and k in self._full_vars:
                try:
                    out[k] = max(1, int(float(self._full_vars[k].get())))
                    continue
                except (ValueError, tk.TclError):
                    pass
            out[k] = int(plot[k])
        return out

    def autosave_minutes(self) -> float:
        """The X-minute interval used for autosave + windows + full-view refresh."""
        try:
            v = float(self._autosave_min_var.get())
            if v > 0:
                return v
        except (ValueError, tk.TclError, AttributeError):
            pass
        return float(self._settings["shared"].get("autosave_minutes",
                                                  AUTOSAVE_MINUTES))

    def note_run_state_changed(self):
        """An experiment started/stopped — refresh full-views so they aren't stale."""
        for exp_id, fv in getattr(self, "_fullviews", {}).items():
            try:
                fv.update_view(self._models[exp_id].get_log())
            except Exception:
                pass

    def save_full_png(self, exp_id: int, path: str):
        """Render the latest full-view for `exp_id` and save it as a PNG."""
        fv = self._fullviews.get(exp_id)
        if fv is not None:
            fv.update_view(self._models[exp_id].get_log())
            fv.save_png(path)

    # ══════════════════════════════════════════════════════════════════════════
    # CENTRAL AUTOSAVE + FULL-VIEW REFRESH (Task 1/6)
    # ══════════════════════════════════════════════════════════════════════════
    #
    # A single timer driven by the X-minute interval does two things every tick:
    #   1. Re-render every full-view tab from the in-memory event log.
    #   2. Overwrite each RUNNING experiment's fixed-name NPY + PNG in the save
    #      folder (exp{N}_eventlog.npy / exp{N}_raster.png), so the same files
    #      grow with each cycle rather than spawning timestamped copies.

    def _schedule_central(self):
        """Schedule the next central tick using the current X-minute interval."""
        mins = self.autosave_minutes()
        self._central_job = self.after(max(1000, int(mins * 60_000)),
                                       self._central_tick)

    def _central_tick(self):
        """Refresh full-view tabs and autosave each running experiment."""
        try:
            for exp_id, fv in self._fullviews.items():
                fv.update_view(self._models[exp_id].get_log())

            folder = self.get_save_folder()
            running = [e for e, m in self._models.items() if m.running]
            if running and folder and os.path.isdir(folder):
                for exp_id in running:
                    stem = os.path.join(folder, f"exp{exp_id}")
                    try:
                        self._models[exp_id].export_npy(stem + "_eventlog.npy")
                        fv = self._fullviews.get(exp_id)
                        if fv is not None:
                            fv.save_png(stem + "_raster.png")
                        self.emit_alert(exp_id,
                                        f"autosaved → exp{exp_id}_eventlog.npy "
                                        f"+ exp{exp_id}_raster.png", level="info")
                    except Exception as e:
                        self.emit_alert(exp_id, f"autosave failed: {e}",
                                        level="error")
            elif running:
                self.emit_alert(None,
                                "autosave skipped — save folder missing",
                                level="error")
        except Exception as e:
            print(f"[central] {e}")
        finally:
            self._schedule_central()

    # ══════════════════════════════════════════════════════════════════════════
    # LAYOUT
    # ══════════════════════════════════════════════════════════════════════════

    def _build(self, port: str):
        # Top strip
        """Assemble the top strip, notebook tabs, and alert banner."""
        top_strip = tk.Frame(self, bg=BG_PNL, pady=5)
        top_strip.pack(fill=tk.X)
        self._build_top_strip(top_strip, port)

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

        mon_tab   = tk.Frame(nb, bg=BG);  nb.add(mon_tab,   text="  Monitor  ")
        self._build_quad_tab(mon_tab)

        # One full-experiment (imshow) tab per box (Task 3 / H2). Labelled
        # "Box N" (Task L5) and only as many as this instance drives.
        fp = self.full_settings()
        for exp_id in range(1, self.num_boxes + 1):
            t = tk.Frame(nb, bg=BG)
            nb.add(t, text=f"  Box {exp_id}  ")
            fv = FullViewPanel(
                t, exp_id,
                rows=fp["full_rows"],
                seconds_per_row=fp["full_seconds_per_row"],
                bin_seconds=fp["full_bin_seconds"])
            fv.pack(fill=tk.BOTH, expand=True)
            self._fullviews[exp_id] = fv

        cal_tab   = tk.Frame(nb, bg=BG);  nb.add(cal_tab,   text="  Calibration  ")
        flag_tab  = tk.Frame(nb, bg=BG);  nb.add(flag_tab,  text="  Flag Settings  ")
        freport_tab = tk.Frame(nb, bg=BG); nb.add(freport_tab, text="  Flags Reported  ")
        vis_tab   = tk.Frame(nb, bg=BG);  nb.add(vis_tab,   text="  Raster Plot Visuals  ")
        data_tab  = tk.Frame(nb, bg=BG);  nb.add(data_tab,  text="  Data  ")
        term_tab  = tk.Frame(nb, bg=BG);  nb.add(term_tab,  text="  Terminal  ")

        self._build_cal_tab(cal_tab)
        self._build_flag_tab(flag_tab)
        self._build_flags_reported_tab(freport_tab)   # Task F4
        self._build_visuals_tab(vis_tab)
        self._build_data_tab(data_tab)
        self._build_terminal_tab(term_tab)

        # Persistent alert banner at the very bottom (Task 2 visibility)
        banner = tk.Frame(self, bg=BG_PNL)
        banner.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Label(banner, text="Latest alert:", font=FONTB, bg=BG_PNL, fg=FG_MUT
                 ).pack(side=tk.LEFT, padx=(10, 4), pady=3)
        self._alert_banner = tk.Label(banner, text="—", font=FONTM,
                                      bg=BG_PNL, fg=FG_MUT, anchor="w")
        self._alert_banner.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=3)

    # ── Top strip ─────────────────────────────────────────────────────────────

    def _build_top_strip(self, parent, port: str):
        """Build the connection, interval, and stream-control row at the top of the window."""
        def lbl(text):
            """Create a plain label widget with standard styling."""
            return tk.Label(parent, text=text, font=FONT, bg=BG_PNL, fg=FG)

        def btn(text, cmd, bg=BG_ALT, fg=FG, **kw):
            """Create a button widget with standard styling."""
            return tk.Button(parent, text=text, command=cmd,
                             font=FONTB, bg=bg, fg=fg,
                             activebackground=BG, relief=tk.FLAT,
                             padx=10, pady=3, **kw)

        lbl("Port:").pack(side=tk.LEFT, padx=(12, 4))
        self._port_var = tk.StringVar(value=port)
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
        self._interval_var = tk.StringVar(
            value=str(self._settings["shared"].get("weight_interval", 30)))
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

        # Task S1: rotating initialisation status shown during the post-stream
        # 9-second lockout (run + calibration buttons disabled meanwhile).
        self._init_lbl = tk.Label(parent, text="", font=FONTB,
                                   bg=BG_PNL, fg=CLR_EXP)
        self._init_lbl.pack(side=tk.RIGHT, padx=10)

    # ── Tab: Experiments (4 quadrants) ────────────────────────────────────────

    def _build_quad_tab(self, parent):
        """Build the monitor grid of ExpQuadrant widgets (Task H2).

        Layout depends on how many boxes this instance drives:
          • 1 box  → a single quadrant fills the whole tab.
          • 2-4    → a fixed 2×2 grid; the first N cells are populated and any
                     remaining cells are left empty, so 3 boxes give 3 panes +
                     1 blank, etc.
        """
        n = self.num_boxes
        if n <= 1:
            parent.columnconfigure(0, weight=1)
            parent.rowconfigure(0, weight=1)
            q = ExpQuadrant(parent, self._models[1],
                            self._reader, self._arduino_ts, host=self)
            q.grid(row=0, column=0, sticky="nsew", padx=3, pady=3)
            self._quadrants.append(q)
            return

        # 2×2 grid, populate the first N cells (Task H2).
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        positions = {1: (0, 0), 2: (0, 1), 3: (1, 0), 4: (1, 1)}
        for exp_id, (row, col) in positions.items():
            if exp_id <= n:
                q = ExpQuadrant(parent, self._models[exp_id],
                                self._reader, self._arduino_ts, host=self)
                q.grid(row=row, column=col, sticky="nsew", padx=3, pady=3)
                self._quadrants.append(q)
            else:
                # Empty placeholder so the populated boxes keep their size.
                tk.Frame(parent, bg=BG_PNL, highlightbackground=BG_ALT,
                         highlightthickness=1
                         ).grid(row=row, column=col, sticky="nsew",
                                padx=3, pady=3)

    # ── Tab: Calibration ──────────────────────────────────────────────────────

    def _build_cal_tab(self, parent):
        """Build the Calibration tab: hardware commands, touch thresholds, and load-cell snap UI."""
        sc = tk.Canvas(parent, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=sc.yview)
        sc.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        sc.pack(fill=tk.BOTH, expand=True)
        body = tk.Frame(sc, bg=BG)
        sc.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>",
                  lambda e: sc.configure(scrollregion=sc.bbox("all")))

        # Task S1: every calibration-action button is collected here so the
        # 9-second post-stream lockout can disable them all together.
        self._cal_lock_buttons = []

        def section(title, subtitle=""):
            """Create a labelled section card (title + optional subtitle + inner frame)."""
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
            """Add one hardware-calibration row (label + button) to the calibration grid."""
            tk.Label(hw, text=label, font=FONT, bg=BG_PNL, fg=FG
                     ).grid(row=r, column=0, sticky="w", pady=5, padx=(0, 16))
            b = tk.Button(hw, text=btn_text, font=FONTB,
                          bg=BG_ALT, fg=FG, relief=tk.FLAT, padx=8,
                          command=cmd_fn)
            b.grid(row=r, column=1, sticky="w", padx=4)
            self._cal_lock_buttons.append(b)

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
        kgb = tk.Button(hw, text="Send 'kg'", font=FONTB,
                        bg=BG_ALT, fg=FG, relief=tk.FLAT, padx=8,
                        command=lambda: self._reader.send(f"k{self._gcal_ch.get()}g"))
        kgb.grid(row=2, column=2, sticky="w", padx=4)
        self._cal_lock_buttons.append(kgb)

        # ── Touch thresholds ──────────────────────────────────────────────────
        th = section("Touch sensitivity thresholds",
                     "Per channel (0-7). Range 20-255, default 130. "
                     "Persisted in Arduino EEPROM and in lickometer_settings.json.")
        self._thresh_vars: Dict[int, tk.StringVar] = {}
        loaded_thr = (self._settings.get("ports", {})
                      .get(self._reader.port, {}).get("thresholds", {}))
        for ch in range(8):
            r, c = divmod(ch, 4)
            tk.Label(th, text=f"Ch {ch}:", font=FONT, bg=BG_PNL, fg=FG
                     ).grid(row=r, column=c * 3, padx=(10, 2), pady=4, sticky="e")
            v = tk.StringVar(value=str(loaded_thr.get(str(ch), 130)))
            self._thresh_vars[ch] = v
            tk.Spinbox(th, from_=20, to=255, textvariable=v, width=5,
                       font=FONTM, bg=BG_ALT, fg=FG, relief=tk.FLAT
                       ).grid(row=r, column=c * 3 + 1, padx=2)
            tb_btn = tk.Button(th, text="Set", font=FONTB,
                               bg=BG_ALT, fg=FG, relief=tk.FLAT, padx=6,
                               command=lambda ch=ch: self._set_threshold(ch))
            tb_btn.grid(row=r, column=c * 3 + 2, padx=4)
            self._cal_lock_buttons.append(tb_btn)

        # ── Software load-cell calibration ────────────────────────────────────
        lc = section("Load cell software calibration",
                     "1. Place 50g reference on bottle → Snap 50g.\n"
                     "2. Remove reference, use actual bottle → Snap Bottle.\n"
                     "Ratio = 50g_raw ÷ bottle_raw.  Applied to all load readings. "
                     "Saved per-port and restored on next launch.")
        grid = tk.Frame(lc, bg=BG_PNL)
        grid.pack(fill=tk.X)

        for col, hd in enumerate(["Exp", "Side", "Arduino ID",
                                   "50g raw", "", "Bottle raw", "", "Ratio"]):
            tk.Label(grid, text=hd, font=FONTB, bg=BG_PNL, fg=FG_MUT
                     ).grid(row=0, column=col, padx=6, pady=3, sticky="w")

        self._snap_svars: Dict[tuple, tk.StringVar] = {}
        cal_loaded = (self._settings.get("ports", {})
                      .get(self._reader.port, {}).get("calibration", {}))
        r = 1
        for exp_id in range(1, self.num_boxes + 1):
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

                # restore snapped raw values + ratio if present
                csec  = cal_loaded.get(str(exp_id), {})
                side_l = side.lower()
                snaps = csec.get("snaps", {}).get(side_l, {})
                for ci, snap_key in enumerate(("50g", "bottle")):
                    init = snaps.get(snap_key)
                    sv = tk.StringVar(value=f"{init:.1f}" if init is not None else "—")
                    if init is not None:
                        self._snaps[(load_id, snap_key)] = float(init)
                    self._snap_svars[(exp_id, side, snap_key)] = sv
                    tk.Label(grid, textvariable=sv, font=FONTM,
                             bg=BG_PNL, fg=FG, width=10
                             ).grid(row=r, column=3 + ci * 2, padx=4)
                    lbl_txt = "Snap 50g" if ci == 0 else "Snap Bottle"
                    snap_btn = tk.Button(grid, text=lbl_txt, font=FONTB,
                                         bg=BG_ALT, fg=FG, relief=tk.FLAT, padx=6,
                                         command=lambda k=key, sk=snap_key,
                                         lid=load_id: self._snap(k, sk, lid))
                    snap_btn.grid(row=r, column=4 + ci * 2, padx=2)
                    self._cal_lock_buttons.append(snap_btn)

                ratio_init = csec.get(f"cal_{side_l}")
                sv_r = tk.StringVar(
                    value=f"{ratio_init:.5f}" if ratio_init else "—")
                self._snap_svars[(exp_id, side, "ratio")] = sv_r
                tk.Label(grid, textvariable=sv_r, font=FONTM,
                         bg=BG_PNL, fg=CLR_GRN
                         ).grid(row=r, column=7, padx=8)
                r += 1

    # ── Tab: Flag Settings (Task 2b/2c) ───────────────────────────────────────

    def _build_flag_tab(self, parent):
        """Build the Flag Settings tab where watchdog thresholds can be adjusted."""
        intro = ("All thresholds are live: editing a value and clicking "
                 "Apply & Save updates the running watchdog and writes the "
                 "value to lickometer_settings.json (shared across instances).")
        tk.Label(parent, text=intro, font=FONT, bg=BG, fg=FG_MUT,
                 wraplength=900, justify="left"
                 ).pack(anchor="w", padx=16, pady=(12, 6))

        f = tk.Frame(parent, bg=BG_PNL, padx=16, pady=12)
        f.pack(fill=tk.X, padx=16, pady=(0, 8))

        self._flag_vars: Dict[str, tk.StringVar] = {}
        flags = self._settings["shared"]["flags"]

        rows = [
            ("no_lick_minutes",         "No lick at all for longer than (min):"),
            ("prolonged_bout_minutes",  "Prolonged lick bout longer than (min):"),
            ("prolonged_lick_seconds",  "Prolonged single lick longer than (sec):"),
            ("bout_gap_seconds",        "Gap that ends a lick bout (sec):"),
            ("load_nochange_minutes",   "Load unchanged after licking — window (min):"),
            ("load_nolick_minutes",     "Load changed w/o licks — window (min):"),
            ("load_change_tolerance_g", "Load change tolerance (g):"),
        ]
        for i, (key, label) in enumerate(rows):
            tk.Label(f, text=label, font=FONT, bg=BG_PNL, fg=FG
                     ).grid(row=i, column=0, sticky="w", pady=5, padx=(0, 16))
            v = tk.StringVar(value=str(flags[key]))
            self._flag_vars[key] = v
            tk.Spinbox(f, from_=0, to=999999, increment=1,
                       textvariable=v, width=10, font=FONTM,
                       bg=BG_ALT, fg=FG, relief=tk.FLAT
                       ).grid(row=i, column=1, sticky="w", padx=4)

        tk.Button(f, text="Apply & Save", font=FONTB,
                  bg=CLR_GRN, fg="white", activebackground="#25A244",
                  relief=tk.FLAT, padx=10, pady=3,
                  command=self._apply_flag_settings
                  ).grid(row=len(rows), column=0, sticky="w", pady=(10, 0))

        tk.Label(parent,
                 text="Reported flags now appear on the separate "
                      "\"Flags Reported\" tab.",
                 font=FONT, bg=BG, fg=FG_MUT
                 ).pack(anchor="w", padx=16, pady=(10, 6))

    # ── Tab: Flags Reported (Task F4) ─────────────────────────────────────────

    def _build_flags_reported_tab(self, parent):
        """Build the Flags Reported tab: the live alerts/flags log (Task F4).

        This holds the log that previously lived under the Flag Settings tab.
        emit_alert() writes to self._alert_text, which is created here.
        """
        tk.Label(parent, text="Flags Reported", font=FONTB, bg=BG, fg=FG
                 ).pack(anchor="w", padx=16, pady=(12, 2))
        tk.Label(parent,
                 text="Every flag, resolution, autosave and error is logged "
                      "here as it happens. Weight over/under flags report the "
                      "size of the difference, and are followed by a "
                      "\"resolved\" entry once the condition clears.",
                 font=FONT, bg=BG, fg=FG_MUT, wraplength=900, justify="left"
                 ).pack(anchor="w", padx=16, pady=(0, 6))

        self._alert_text = tk.Text(parent, bg=BG_PNL, fg=FG, font=FONTM,
                                   relief=tk.FLAT, state=tk.DISABLED,
                                   wrap=tk.WORD)
        asb = ttk.Scrollbar(parent, orient=tk.VERTICAL,
                            command=self._alert_text.yview)
        self._alert_text.configure(yscrollcommand=asb.set)
        asb.pack(side=tk.RIGHT, fill=tk.Y)
        self._alert_text.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 8))
        self._alert_text.tag_configure("error",    foreground=CLR_RED)
        self._alert_text.tag_configure("flag",     foreground=CLR_EXP)
        self._alert_text.tag_configure("warning",  foreground=CLR_EXP)
        self._alert_text.tag_configure("resolved", foreground=CLR_GRN)
        self._alert_text.tag_configure("info",     foreground=FG_MUT)

    # ── Tab: Raster Plot Visuals (Task 5) ─────────────────────────────────────

    def _build_visuals_tab(self, parent):
        """Build the Raster Plot Visuals tab: load axis + monitor + full-view params."""
        sc = tk.Canvas(parent, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=sc.yview)
        sc.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        sc.pack(fill=tk.BOTH, expand=True)
        body = tk.Frame(sc, bg=BG)
        sc.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>",
                  lambda e: sc.configure(scrollregion=sc.bbox("all")))

        plot = self._settings["shared"]["plot"]
        self._plot_vars:    Dict[str, tk.StringVar] = {}
        self._monitor_vars: Dict[str, tk.StringVar] = {}
        self._full_vars:    Dict[str, tk.StringVar] = {}

        def section(title, subtitle, store, rows):
            """Add a labelled card of (key,label) spinbox rows into `store`."""
            tk.Label(body, text=title, font=FONTB, bg=BG, fg=FG
                     ).pack(anchor="w", padx=16, pady=(14, 1))
            tk.Label(body, text=subtitle, font=FONT, bg=BG, fg=FG_MUT,
                     wraplength=900, justify="left"
                     ).pack(anchor="w", padx=16, pady=(0, 4))
            f = tk.Frame(body, bg=BG_PNL, padx=16, pady=12)
            f.pack(fill=tk.X, padx=16, pady=(0, 4))
            for i, (key, label) in enumerate(rows):
                tk.Label(f, text=label, font=FONT, bg=BG_PNL, fg=FG
                         ).grid(row=i, column=0, sticky="w", pady=5, padx=(0, 16))
                v = tk.StringVar(value=str(plot[key]))
                store[key] = v
                tk.Spinbox(f, from_=1, to=9_999_999, increment=1,
                           textvariable=v, width=12, font=FONTM,
                           bg=BG_ALT, fg=FG, relief=tk.FLAT
                           ).grid(row=i, column=1, sticky="w", padx=4)

        section("Load-cell axis", "Gram limits + tick marks for the monitor "
                "raster load traces. Shared across all experiments.",
                self._plot_vars, [
                    ("load_ymin",   "Load axis minimum (g):"),
                    ("load_ymax",   "Load axis maximum (g):"),
                    ("load_yticks", "Number of tick marks:"),
                ])

        # ── Load-cell display (Task V1 / LC27) ────────────────────────────────
        tk.Label(body, text="Load-cell display", font=FONTB, bg=BG, fg=FG
                 ).pack(anchor="w", padx=16, pady=(14, 1))
        tk.Label(body, text="Toggle whether load-cell data is recorded and "
                 "plotted at all (Task V1). When off, no load data is captured. "
                 "Line width applies to the Box (full-view) tab load traces.",
                 font=FONT, bg=BG, fg=FG_MUT, wraplength=900, justify="left"
                 ).pack(anchor="w", padx=16, pady=(0, 4))
        lf = tk.Frame(body, bg=BG_PNL, padx=16, pady=12)
        lf.pack(fill=tk.X, padx=16, pady=(0, 4))
        self._plot_vars["load_show"] = tk.StringVar(
            value=str(plot.get("load_show", 1)))
        tk.Checkbutton(lf, text="Show / record load-cell data",
                       variable=self._plot_vars["load_show"],
                       onvalue="1", offvalue="0",
                       font=FONT, bg=BG_PNL, fg=FG, selectcolor=BG_ALT,
                       activebackground=BG_PNL, activeforeground=FG
                       ).grid(row=0, column=0, sticky="w", pady=5, padx=(0, 16))
        tk.Label(lf, text="Box-tab load line width:", font=FONT,
                 bg=BG_PNL, fg=FG).grid(row=1, column=0, sticky="w",
                                        pady=5, padx=(0, 16))
        self._plot_vars["load_linewidth"] = tk.StringVar(
            value=str(plot.get("load_linewidth", 1.2)))
        tk.Spinbox(lf, from_=0.1, to=10, increment=0.1,
                   textvariable=self._plot_vars["load_linewidth"], width=8,
                   font=FONTM, bg=BG_ALT, fg=FG, relief=tk.FLAT
                   ).grid(row=1, column=1, sticky="w", padx=4)

        section("Monitor raster timing", "Controls the live 4-row quadrant view "
                "on the Monitor tab (also settable at the top of the script).",
                self._monitor_vars, [
                    ("monitor_timebin_ms",      "Time bin width (ms):"),
                    ("monitor_seconds_per_row", "Seconds per row (s):"),
                    ("monitor_refresh_ms",      "GUI refresh interval (ms):"),
                ])

        section("Full-view grid (Experiment tabs)", "Geometry of the "
                "whole-experiment imshow heat-maps. Shared across all four "
                "Experiment tabs. Default 24 rows × 3600 s, 60 s bins.",
                self._full_vars, [
                    ("full_rows",            "Number of rows:"),
                    ("full_seconds_per_row", "Seconds per row (s):"),
                    ("full_bin_seconds",     "Seconds per bin (s):"),
                ])

        tk.Button(body, text="Apply & Save", font=FONTB,
                  bg=CLR_GRN, fg="white", activebackground="#25A244",
                  relief=tk.FLAT, padx=10, pady=4,
                  command=self._apply_plot_settings
                  ).pack(anchor="w", padx=16, pady=(8, 16))

    # ── Tab: Data / Save folder (Task 6) ──────────────────────────────────────

    def _build_data_tab(self, parent):
        """Build the Data tab: shows the active save folder + autosave interval."""
        tk.Label(parent,
                 text="Save folder and autosave interval for this session "
                      "(chosen on the setup page). Raster PNG + event-log NPY "
                      "are overwritten to fixed filenames "
                      "(exp{N}_raster.png / exp{N}_eventlog.npy) every interval "
                      "while an experiment runs. You can change them here too.",
                 font=FONT, bg=BG, fg=FG_MUT, wraplength=900, justify="left"
                 ).pack(anchor="w", padx=16, pady=(12, 6))

        f = tk.Frame(parent, bg=BG_PNL, padx=16, pady=12)
        f.pack(fill=tk.X, padx=16, pady=(0, 8))

        tk.Label(f, text="Save folder:", font=FONT, bg=BG_PNL, fg=FG
                 ).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        # Reuse the SAME StringVar created in __init__ / setup page.
        tk.Entry(f, textvariable=self._folder_var, width=70,
                 font=FONTM, bg=BG_ALT, fg=FG,
                 insertbackground=FG, relief=tk.FLAT
                 ).grid(row=0, column=1, sticky="w", padx=4, pady=4)
        tk.Button(f, text="Browse…", font=FONTB,
                  bg=BG_ALT, fg=FG, relief=tk.FLAT, padx=10,
                  command=self._browse_folder
                  ).grid(row=0, column=2, padx=4, pady=4)
        tk.Button(f, text="Save path", font=FONTB,
                  bg=CLR_GRN, fg="white", activebackground="#25A244",
                  relief=tk.FLAT, padx=10,
                  command=self._save_folder_path
                  ).grid(row=0, column=3, padx=4, pady=4)

        tk.Label(f, text="Autosave every (minutes):", font=FONT,
                 bg=BG_PNL, fg=FG).grid(row=1, column=0, sticky="w",
                                        padx=(0, 8), pady=4)
        tk.Spinbox(f, from_=1, to=1440, increment=1,
                   textvariable=self._autosave_min_var, width=8,
                   font=FONTM, bg=BG_ALT, fg=FG, relief=tk.FLAT
                   ).grid(row=1, column=1, sticky="w", padx=4, pady=4)
        tk.Button(f, text="Save interval", font=FONTB,
                  bg=CLR_GRN, fg="white", activebackground="#25A244",
                  relief=tk.FLAT, padx=10,
                  command=self._save_autosave_minutes
                  ).grid(row=1, column=2, columnspan=2, sticky="w",
                         padx=4, pady=4)

    # ── Tab: Terminal ─────────────────────────────────────────────────────────

    def _build_terminal_tab(self, parent):
        """Build the Terminal tab: raw serial text output and manual command entry."""
        tk.Label(parent,
                 text="Raw serial terminal — all Arduino output, errors and "
                      "flags appear here. You can also type commands directly.",
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
    # POPULATE GUI FROM LOADED SETTINGS (Task 3)
    # ══════════════════════════════════════════════════════════════════════════

    def _refresh_loaded_into_gui(self):
        # apply loaded plot settings to each raster
        """Populate all GUI widgets from the settings loaded at startup (Task 3 round-trip)."""
        for q in self._quadrants:
            q.apply_plot_settings()
        # Task V1: gate load capture on every model from the loaded setting.
        self._apply_load_capture()
        # Full-view tabs: apply loaded geometry + load axis, then paint logs.
        fp = self.full_settings()
        pv = self.plot_settings()
        show = bool(pv.get("load_show", 1))
        lw   = float(pv.get("load_linewidth", 1.2))
        for exp_id, fv in getattr(self, "_fullviews", {}).items():
            fv.reconfigure(fp["full_rows"], fp["full_seconds_per_row"],
                           fp["full_bin_seconds"])
            fv.set_load_axis(pv["load_ymin"], pv["load_ymax"],
                             show=show, linewidth=lw)
            fv.update_view(self._models[exp_id].get_log())

    # ══════════════════════════════════════════════════════════════════════════
    # ALERTS  (Task 2)
    # ══════════════════════════════════════════════════════════════════════════

    def emit_alert(self, exp_id, text: str, level: str = "flag"):
        """Show an alert in the GUI (alerts log + bottom banner) and terminal."""
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        who   = "SYSTEM" if exp_id in (None, 0) else f"Box {exp_id}"
        tag   = {"error": "ERROR", "info": "INFO",
                 "resolved": "RESOLVED", "warning": "FLAG"}.get(level, "FLAG")
        line  = f"[{stamp}] [{who}] {tag}: {text}"

        # terminal
        self._reader._push_raw(line)
        print(line)

        # alerts log
        if hasattr(self, "_alert_text"):
            self._alert_text.config(state=tk.NORMAL)
            self._alert_text.insert(tk.END, line + "\n", (level,))
            self._alert_text.see(tk.END)
            self._alert_text.config(state=tk.DISABLED)

        # bottom banner
        if hasattr(self, "_alert_banner"):
            if level == "error":
                colour = CLR_RED
            elif level == "info":
                colour = FG_MUT
            elif level == "resolved":
                colour = CLR_GRN
            else:
                colour = CLR_EXP
            self._alert_banner.config(text=line, fg=colour)

    def _watchdog_tick(self):
        # Task 2: never let watchdog errors stop the loop.
        """Periodic watchdog: call check_flags() on every running experiment and emit any new alerts."""
        try:
            if self._connected and self._streaming:
                now = self._arduino_ts[0]
                cfg = self.flag_settings()
                for exp_id, model in self._models.items():
                    for fmsg, flvl in model.check_flags(now, cfg):
                        self.emit_alert(exp_id, fmsg, level=flvl)
        except Exception as e:
            print(f"[watchdog] {e}")
        finally:
            self.after(WATCHDOG_MS, self._watchdog_tick)

    # ══════════════════════════════════════════════════════════════════════════
    # ACTIONS
    # ══════════════════════════════════════════════════════════════════════════

    def _toggle_connect(self):
        """Connect to or disconnect from the Arduino serial port."""
        if not self._connected:
            self._reader.port = self._port_var.get().strip()
            self.title(f"Lickometer  ·  Columbia AIC  ·  {self._reader.port}")
            ok = self._reader.connect()
            if not ok:
                # Task 2a: surface the error, do NOT enter simulation.
                self._conn_lbl.config(text="🔴 Connect failed", fg=CLR_RED)
                self.emit_alert(None, "unable to connect - check connection",
                                level="error")
                return
            self._connected = True
            self._conn_btn.config(text="Disconnect")
            self._conn_lbl.config(text="🟢 Connected", fg=CLR_GRN)
            self._stream_btn.config(state=tk.NORMAL)
            self._start_dispatch()
            # persist the port so it pre-fills next time
            save_shared_value("port", self._reader.port)
        else:
            if self._streaming:
                self._toggle_stream()
            self._reader.disconnect()
            self._connected  = False
            self._conn_btn.config(text="Connect")
            self._conn_lbl.config(text="⚫ Disconnected", fg=FG_MUT)
            self._stream_btn.config(state=tk.DISABLED)

    def _send_interval(self):
        """Validate and send the weight-report interval command to the Arduino."""
        try:
            n = int(self._interval_var.get())
            if not 10 <= n <= 99999:
                raise ValueError
        except ValueError:
            messagebox.showerror("Bad interval", "Must be 10–99999 seconds.")
            return
        self._reader.send(f"i{n}")
        save_shared_value("weight_interval", n)          # Task 3

    def _toggle_stream(self):
        """Start or stop the Arduino event stream ('r' / 's' commands)."""
        if not self._streaming:
            self._reader.send("r")
            self._streaming = True
            self._stream_btn.config(text="⏹ Stop Arduino stream",
                                     bg=CLR_RED, activebackground="#CC3730")
            self._begin_init_lockout()           # Task S1
        else:
            self._reader.send("s")
            self._streaming = False
            self._stream_btn.config(text="▶ Start Arduino stream",
                                     bg=CLR_GRN, activebackground="#25A244")
            self._cancel_init_lockout()          # Task S1

    # ── Task S1: post-stream initialisation lockout ──────────────────────────
    def _begin_init_lockout(self):
        """Lock run + calibration buttons for 9 s and rotate the init messages."""
        self._set_controls_locked(True)
        self._init_idx = 0
        self._show_next_init_msg()
        self._init_unlock_job = self.after(INIT_LOCKOUT_MS,
                                           self._end_init_lockout)

    def _show_next_init_msg(self):
        """Advance the rotating initialisation message every 1.5 s."""
        if self._init_idx < len(INIT_MSGS):
            self._init_lbl.config(text=INIT_MSGS[self._init_idx])
            self._init_idx += 1
            self._init_msg_job = self.after(INIT_STEP_MS,
                                            self._show_next_init_msg)

    def _end_init_lockout(self):
        """Re-enable run + calibration once the 9 s lockout elapses."""
        self._set_controls_locked(False)
        self._init_lbl.config(text=INIT_MSGS[-1])   # leave 'ready to lick'

    def _cancel_init_lockout(self):
        """Cancel any pending lockout (e.g. stream stopped early) and unlock."""
        for attr in ("_init_unlock_job", "_init_msg_job"):
            job = getattr(self, attr, None)
            if job is not None:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
                setattr(self, attr, None)
        self._set_controls_locked(False)
        self._init_lbl.config(text="")

    def _set_controls_locked(self, locked: bool):
        """Enable/disable every Run + calibration button together (Task S1)."""
        for q in self._quadrants:
            q.set_run_locked(locked)
        for b in getattr(self, "_cal_lock_buttons", []):
            try:
                b.config(state=(tk.DISABLED if locked else tk.NORMAL))
            except Exception:
                pass

    def _set_threshold(self, ch: int):
        """Validate and send the touch threshold for channel ch to the Arduino, then persist it."""
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
        # Task 3: persist per-port threshold
        save_port_section(self._reader.port, "thresholds", {str(ch): n})

    def _snap(self, key: tuple, snap_key: str, load_id: int):
        """Record a load-cell snap reading (50g or bottle), compute the calibration ratio, and persist it."""
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
        ratio = None
        m = self._models[exp_id]

        # When the bottle snap is recorded, store the raw value as the
        # offset_weight baseline for the below-offset load flag (Flag 2).
        # The offset is stored in raw ADC units; it will be multiplied by the
        # calibration ratio once that is computed below.
        if snap_key == "bottle":
            # Store as raw for now; recomputed after ratio is known.
            self._snaps[(load_id, "bottle_raw")] = raw

        if v50 is not None and vbot is not None and vbot != 0:
            ratio = v50 / vbot
            self._snap_svars[(exp_id, side, "ratio")].set(f"{ratio:.5f}")
            if side == "Left":
                m.cal_left  = ratio
                # Calibrated offset weight = raw bottle reading × ratio
                m.offset_weight_left  = vbot * ratio
            else:
                m.cal_right = ratio
                # Calibrated offset weight = raw bottle reading × ratio
                m.offset_weight_right = vbot * ratio

        # Task 3: persist calibration (raw snaps + ratio) per-port, per-exp.
        side_l = side.lower()
        data = load_settings()
        psec  = data.setdefault("ports", {}).setdefault(self._reader.port, {})
        cal   = psec.setdefault("calibration", {})
        csec  = cal.setdefault(str(exp_id), {})
        snaps = csec.setdefault("snaps", {}).setdefault(side_l, {})
        snaps[snap_key] = raw
        if ratio is not None:
            csec[f"cal_{side_l}"] = ratio
        _write_settings(data)

    def _apply_flag_settings(self):
        # validate
        """Validate and save the flag threshold values entered in the Flag Settings tab."""
        vals = {}
        for k, v in self._flag_vars.items():
            try:
                vals[k] = float(v.get())
            except ValueError:
                messagebox.showerror("Bad value", f"{k} must be a number.")
                return
        save_shared("flags", vals)                       # Task 3
        # reload into our cached settings so flag_settings() stays consistent
        self._settings["shared"]["flags"].update(vals)
        self.emit_alert(None, "flag thresholds updated", level="info")

    def _apply_load_capture(self):
        """Push the load-show toggle to every model so capture honours V1."""
        try:
            show = bool(self.plot_settings().get("load_show", 1))
        except Exception:
            show = True
        for m in self._models.values():
            m.capture_load = show

    def _apply_plot_settings(self):
        """Validate and apply ALL Raster Plot Visuals settings: load-cell axis,
        monitor raster timing, and full-view grid geometry."""
        vals = {}
        # ── Load-cell axis (floats) ──────────────────────────────────────────
        for k, v in self._plot_vars.items():
            try:
                vals[k] = float(v.get())
            except ValueError:
                messagebox.showerror("Bad value", f"{k} must be a number.")
                return
        vals["load_yticks"] = int(vals["load_yticks"])
        if "load_show" in vals:
            vals["load_show"] = int(round(vals["load_show"]))
        if "load_linewidth" in vals:
            vals["load_linewidth"] = max(0.1, float(vals["load_linewidth"]))
        if vals["load_ymax"] <= vals["load_ymin"]:
            messagebox.showerror("Bad axis", "Maximum must exceed minimum.")
            return

        # ── Monitor timing + full-view grid (positive ints) ──────────────────
        for store in (self._monitor_vars, self._full_vars):
            for k, v in store.items():
                try:
                    iv = int(float(v.get()))
                except ValueError:
                    messagebox.showerror("Bad value", f"{k} must be a number.")
                    return
                if iv < 1:
                    messagebox.showerror("Bad value",
                                         f"{k} must be at least 1.")
                    return
                vals[k] = iv

        save_shared("plot", vals)                        # Task 3 persist
        self._settings["shared"]["plot"].update(vals)

        # Task V1: gate load capture on every model.
        self._apply_load_capture()

        # Live redraw: monitor quadrants pull load axis + monitor timing.
        for q in self._quadrants:                        # Task 2/5
            q.apply_plot_settings()

        # Live reconfigure: full-view tabs get the new grid + load axis + repaint.
        fp = self.full_settings()                        # Task 3
        show = bool(vals.get("load_show", 1))
        lw   = float(vals.get("load_linewidth", 1.2))
        for exp_id, fv in self._fullviews.items():
            fv.reconfigure(fp["full_rows"], fp["full_seconds_per_row"],
                           fp["full_bin_seconds"])
            fv.set_load_axis(vals["load_ymin"], vals["load_ymax"],
                             show=show, linewidth=lw)
            fv.update_view(self._models[exp_id].get_log())

        self.emit_alert(None, "raster plot visuals updated", level="info")

    def _browse_folder(self):
        """Open a folder-chooser dialog and store the selected save folder."""
        folder = filedialog.askdirectory(
            title="Choose save folder",
            initialdir=self._folder_var.get().strip() or _HERE)
        if folder:
            self._folder_var.set(folder)
            self._save_folder_path()

    def _save_folder_path(self):
        """Persist the currently entered save folder path to settings."""
        folder = self._folder_var.get().strip()
        save_shared_value("save_folder", folder)         # Task 3
        self._settings["shared"]["save_folder"] = folder
        self.emit_alert(None, f"save folder set: {folder}", level="info")

    def _save_autosave_minutes(self):
        """Validate + persist the autosave interval, then reschedule the timer."""
        try:
            mins = float(self._autosave_min_var.get())
        except (ValueError, tk.TclError):
            messagebox.showerror("Bad value",
                                 "Autosave interval must be a number.")
            return
        if mins <= 0:
            messagebox.showerror("Bad value",
                                 "Autosave interval must be positive.")
            return
        save_shared_value("autosave_minutes", mins)      # Task 1/3
        self._settings["shared"]["autosave_minutes"] = mins
        # Restart the central timer so the new interval takes effect immediately.
        if getattr(self, "_central_job", None) is not None:
            try:
                self.after_cancel(self._central_job)
            except Exception:
                pass
        self._schedule_central()
        self.emit_alert(None, f"autosave interval set: {mins:g} min",
                        level="info")

    def _send_raw_cmd(self):
        """Send the raw command typed in the Terminal tab entry box to the Arduino."""
        cmd = self._cmd_var.get().strip()
        if cmd:
            self._reader.send(cmd)
            self._cmd_var.set("")

    def _clear_terminal(self):
        """Clear all text from the Terminal tab text widget."""
        self._term_text.config(state=tk.NORMAL)
        self._term_text.delete("1.0", tk.END)
        self._term_text.config(state=tk.DISABLED)

    # ══════════════════════════════════════════════════════════════════════════
    # BACKGROUND DISPATCH
    # ══════════════════════════════════════════════════════════════════════════

    def _start_dispatch(self):
        """Start the background dispatch thread and the timestamp label polling loop."""
        threading.Thread(target=self._dispatch_loop, daemon=True).start()
        self.after(500, self._poll_ts_label)

    def _dispatch_loop(self):
        """Background thread: pull events from the serial queue, update arduino_ts, and route to models."""
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
                    # ingest() returns a list of flag strings for load-cell events;
                    # forward each one to the alert banner immediately.
                    new_flags = model.ingest(ts, aid, amp)
                    for fmsg, flvl in (new_flags or []):
                        # emit_alert must run on the Tk main thread.
                        self.after(0, lambda msg=fmsg, eid=model.exp_id,
                                   lvl=flvl: self.emit_alert(eid, msg, level=lvl))

    def _poll_ts_label(self):
        """Update the timestamp label in the top strip every 500 ms (Task L14: H:MM:SS)."""
        ts_ms = self._arduino_ts[0]
        s = int(ts_ms // 1000)
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        self._ts_lbl.config(text=f"ts: {h:d}:{m:02d}:{sec:02d}")
        if self._connected:
            self.after(500, self._poll_ts_label)

    def _poll_terminal(self):
        """Drain the raw_queue and append new lines to the Terminal tab text widget."""
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
    # Task 1 / H1-H4: launch modes.
    #   • Standalone:  python lickometer_finalx6.py [COM_PORT]
    #         The optional COM port pre-fills the Port box; the mandatory setup
    #         page then asks for a save folder + autosave interval.
    #   • From the hub: python lickometer_finalx6.py --config <config.json>
    #         The JSON carries port, num_boxes, instance_folder, data_folder,
    #         settings_file, autosave_minutes and the flashed sketch name/path.
    #         The setup page is skipped and that config is applied directly.
    init_port  = None
    hub_config = None
    argv = sys.argv[1:]
    if argv and argv[0] in ("--config", "-c") and len(argv) > 1:
        try:
            with open(argv[1], "r") as _f:
                hub_config = json.load(_f)
        except Exception as _e:
            print(f"[hub] could not read config {argv[1]}: {_e}")
            hub_config = None
        if hub_config:
            # Point settings at this instance's own file BEFORE the window builds
            # so calibrations/visuals are unique per instance (Task H3).
            set_settings_file(hub_config.get("settings_file", ""))
    elif argv:
        init_port = argv[0]

    app = MainWindow(initial_port=init_port, hub_config=hub_config)
    # If the mandatory setup page was cancelled, __init__ already destroyed the
    # root window; only enter the main loop when the app is still alive.
    if getattr(app, "alive", True):
        app.mainloop()
