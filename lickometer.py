# -*- coding: utf-8 -*-
"""
Created on Tue Jun 23 12:22:24 2026

@author: readj
"""

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

TIMEBIN_MS      = 500           # raster bin width in ms
GUI_REFRESH_MS  = 1000         # raster redraw interval in ms
SECONDS_PER_ROW = 3600           # x-axis span per raster row (seconds)

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
LOAD_YMIN   = 0.0     # bottom of the load-cell scale (g)
LOAD_YMAX   = 60.0    # top of the load-cell scale (g)
LOAD_YTICKS = 4       # number of tick marks on the load-cell scale

# ── Autosave (Task 6) ──
AUTOSAVE_HOURS = 6     # autosave each running experiment to the save folder

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
        },
        "save_folder":     "",
        "weight_interval": 30,
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
    try:
        with open(SETTINGS_FILE, "r") as f:
            data = json.load(f)
    except Exception:
        data = {}
    return _deep_merge(DEFAULT_SETTINGS, data)


def _write_settings(data: dict):
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
        self.queue       = queue.Queue()
        self.raw_queue   = queue.Queue(maxsize=500)
        self._ser        = None
        self._running    = False
        self.sim_mode    = False
        self.port        = SERIAL_PORT
        self.baud        = BAUD_RATE
        self.last_error  = ""

    def connect(self) -> bool:
        if not _SERIAL_OK:
            self.last_error = "pyserial not installed (pip install pyserial)"
            self._push_raw(f"[Serial] {self.last_error}")
            print(f"[Serial] {self.last_error}")
            # self._start_sim()   # Task 2a: do NOT auto-fall-back to simulation
            return False
        cleanup_port(self.port)                       # Task 4
        try:
            self._ser     = _serial.Serial(self.port, self.baud, timeout=1)
            _OPEN_PORTS[self.port] = self._ser        # register for Task 4 cleanup
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
            _OPEN_PORTS.pop(self.port, None)          # Task 4: deregister

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
                # Task 2: an I/O hiccup must not stop the program. Log and keep going.
                self._push_raw(f"[Serial] read error: {e}")
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

    # ── Simulation (RETAINED for manual testing, but never auto-started) ───────
    # To test the GUI without hardware you can manually call self._start_sim()
    # from a console; nothing in normal operation calls it anymore.

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

        # Task 2 flag-detection state (edge-triggered so flags don't spam)
        self._fs:          Dict[str, bool] = {}
        self._load_a_last: int = 0     # last time the "no change" check sampled
        self._load_b_last: int = 0     # last time the "change w/o licks" check sampled

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
        self._fs.clear()
        self._load_a_last = 0
        self._load_b_last = 0
        self.add(0, _EXP_ONSET)

    def stop(self, ts: int):
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
            flags: List[str] = []

            on_l  = [r.timestamp_ms for r in log if r.event_id == _L_ON]
            on_r  = [r.timestamp_ms for r in log if r.event_id == _R_ON]
            off_l = [r.timestamp_ms for r in log if r.event_id == _L_OFF]
            off_r = [r.timestamp_ms for r in log if r.event_id == _R_OFF]
            onsets = sorted(on_l + on_r)

            # ── 2b-i: no lick at all for longer than X minutes ────────────────
            nolick_ms = cfg["no_lick_minutes"] * 60_000
            last_lick = onsets[-1] if onsets else 0
            cond = (now - last_lick) > nolick_ms
            if cond and not self._fs.get("nolick"):
                flags.append(
                    f"longer than {cfg['no_lick_minutes']:g} minutes with no lick")
            self._fs["nolick"] = cond

            # ── 2b-ii: prolonged single continuous lick (> X seconds) ─────────
            plick_ms = cfg["prolonged_lick_seconds"] * 1000
            for side, ons, offs in (("L", on_l, off_l), ("R", on_r, off_r)):
                oo = _open_onset(ons, offs)
                key = f"plick_{side}"
                c = oo is not None and (now - oo) > plick_ms
                if c and not self._fs.get(key):
                    flags.append(
                        f"prolonged lick longer than "
                        f"{cfg['prolonged_lick_seconds']:g} seconds ({side})")
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
            if bout_cond and not self._fs.get("bout"):
                flags.append(
                    f"prolonged lick bout longer than "
                    f"{cfg['prolonged_bout_minutes']:g} minutes")
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
                            f"no change in load cell value after "
                            f"{cfg['load_nochange_minutes']:g} minutes of "
                            f"licking ({side})")

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
                            f"changes in load cell value despite no licks in "
                            f"past {cfg['load_nolick_minutes']:g} minutes ({side})")

            return flags
        except Exception as e:
            print(f"[watchdog] exp {self.exp_id}: {e}")
            return []

    @staticmethod
    def _load_range(log, load_eid, t0, t1) -> Optional[float]:
        amps = [r.amplitude for r in log
                if r.event_id == load_eid and t0 < r.timestamp_ms <= t1]
        if len(amps) < 2:
            return None
        return max(amps) - min(amps)

# ══════════════════════════════════════════════════════════════════════════════
# RASTER PANEL
# ══════════════════════════════════════════════════════════════════════════════

class RasterPanel:
    """
    Matplotlib raster embedded in a Tk widget for one experiment.

    Lick events → filled BLOCKS from onset to offset (no gaps between bins).
    Load cell   → translucent shaded area + line, superimposed on top.
    Rows grow dynamically as recording extends past each minute.

    Task 5: load traces now use FIXED, user-settable limits (load_ymin/ymax)
    instead of per-row min/max, and dotted tick marks are drawn at load_yticks
    levels with a gram scale labelled on the right margin.
    """

    def __init__(self, parent: tk.Widget, exp_id: int):
        self.exp_id = exp_id
        # Task 5 axis config (overwritten from settings by MainWindow)
        self.load_ymin   = LOAD_YMIN
        self.load_ymax   = LOAD_YMAX
        self.load_yticks = LOAD_YTICKS

        self._fig   = Figure(figsize=(6, 2.6), dpi=96, facecolor=BG_PNL)
        self._ax    = self._fig.add_subplot(111)
        self._fig.subplots_adjust(left=0.06, right=0.94, top=0.90, bottom=0.20)
        self._canvas = FigureCanvasTkAgg(self._fig, master=parent)
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._style_ax(self._ax, 1)
        self._canvas.draw_idle()

    def set_load_axis(self, ymin: float, ymax: float, yticks: int):
        self.load_ymin   = ymin
        self.load_ymax   = ymax
        self.load_yticks = max(2, int(yticks))

    def update(self, events: List[EventRow]):
        ax = self._ax
        ax.cla()

        if not events:
            self._style_ax(ax, 1)
            self._draw_load_ticks(ax, 1)
            self._canvas.draw_idle()
            return

        max_ms = max(e.timestamp_ms for e in events)
        n_rows = max(1, int(np.ceil(max_ms / (SECONDS_PER_ROW * 1000))))
        self._style_ax(ax, n_rows)

        # Alternating row backgrounds
        for r in range(n_rows):
            if r % 2 == 1:
                ax.axhspan(r, r + 1, color=BG_ALT, zorder=0, linewidth=0)

        # Load-cell tick marks (Task 5) sit under the data
        self._draw_load_ticks(ax, n_rows)

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

        # ── Load cell area plots (Task 5: fixed limits) ────────────────────────
        span = self.load_ymax - self.load_ymin
        if span > 0:
            for load_eid, color in ((_L_LOAD, CLR_L), (_R_LOAD, CLR_R)):
                evts = [e for e in events if e.event_id == load_eid]
                if len(evts) < 2:
                    continue
                amps = np.array([e.amplitude for e in evts])
                norm = np.clip((amps - self.load_ymin) / span, 0.0, 1.0)

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

    def _draw_load_ticks(self, ax, n_rows: int):
        """Task 5: dotted reference lines + gram labels for the load scale."""
        span = self.load_ymax - self.load_ymin
        if span <= 0:
            return
        ticks = np.linspace(self.load_ymin, self.load_ymax,
                            max(2, int(self.load_yticks)))
        for r in range(n_rows):
            for tg in ticks:
                frac = (tg - self.load_ymin) / span
                y = r + frac * 0.65
                ax.plot([0, BINS_PER_ROW], [y, y],
                        color=FG_MUT, alpha=0.10, linewidth=0.5,
                        linestyle=(0, (2, 3)), zorder=1)
        # gram scale labelled once, on the right margin of the bottom row
        for tg in ticks:
            frac = (tg - self.load_ymin) / span
            ax.text(BINS_PER_ROW * 1.01, frac * 0.65, f"{tg:g}",
                    fontsize=5, color=FG_MUT, va="center", ha="left")
        ax.text(BINS_PER_ROW * 1.01, 0.70, "g",
                fontsize=5, color=FG_MUT, va="center", ha="left")

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
                 reader: SerialReader, arduino_ts: list, host):
        super().__init__(master, bg=BG_PNL,
                         highlightbackground=BG_ALT, highlightthickness=1)
        self.model        = model
        self._reader      = reader
        self._arduino_ts  = arduino_ts
        self._host        = host          # MainWindow, for save folder etc.
        self._refresh_job = None
        self._autosave_job = None
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
        # apply current plot-visual settings from host
        pv = self._host.plot_settings()
        self._raster.set_load_axis(pv["load_ymin"], pv["load_ymax"],
                                   pv["load_yticks"])

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

    def apply_plot_settings(self):
        """Called by MainWindow when the Raster plot visuals tab changes."""
        pv = self._host.plot_settings()
        self._raster.set_load_axis(pv["load_ymin"], pv["load_ymax"],
                                   pv["load_yticks"])
        self._raster.update(self.model.get_log())

    # ── Controls ──────────────────────────────────────────────────────────────

    def _run(self):
        if not self.model.running:
            self.model.start(self._arduino_ts[0])
            self._run_btn.config(state=tk.DISABLED)
            self._stop_btn.config(state=tk.NORMAL)
            self._shown = 0
            self._schedule()
            self._schedule_autosave()        # Task 6

    def _stop_and_save(self):
        if self.model.running:
            self.model.stop(self._arduino_ts[0])
        if self._refresh_job:
            self.after_cancel(self._refresh_job)
        if self._autosave_job:
            self.after_cancel(self._autosave_job)
            self._autosave_job = None
        self._refresh()  # final flush

        stem = f"exp{self.model.exp_id}_{datetime.datetime.now():%Y%m%d_%H%M%S}"
        # Task 6: default the dialog to the configured save folder.
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
            self._raster.save_png(png)
            messagebox.showinfo("Saved",
                f"Log  → {npy}\nPlot → {png}")

        self._run_btn.config(state=tk.NORMAL)
        self._stop_btn.config(state=tk.DISABLED)
        self._status.set("Stopped")

    # ── Autosave every AUTOSAVE_HOURS (Task 6) ────────────────────────────────

    def _schedule_autosave(self):
        interval_ms = int(AUTOSAVE_HOURS * 3600 * 1000)
        self._autosave_job = self.after(interval_ms, self._autosave_tick)

    def _autosave_tick(self):
        if not self.model.running:
            return
        folder = self._host.get_save_folder()
        if folder and os.path.isdir(folder):
            stem = (f"exp{self.model.exp_id}_autosave_"
                    f"{datetime.datetime.now():%Y%m%d_%H%M%S}")
            try:
                self.model.export_npy(os.path.join(folder, stem + ".npy"))
                self._raster.save_png(os.path.join(folder, stem + ".png"))
                self._host.emit_alert(self.model.exp_id,
                                      f"autosaved to {folder}", level="info")
            except Exception as e:
                self._host.emit_alert(self.model.exp_id,
                                      f"autosave failed: {e}", level="error")
        else:
            self._host.emit_alert(self.model.exp_id,
                                  "autosave skipped — no save folder set",
                                  level="error")
        self._schedule_autosave()            # keep autosaving while running

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
    def __init__(self, initial_port: Optional[str] = None):
        super().__init__()

        # Task 3: load persisted settings first so everything populates from them.
        self._settings = load_settings()
        port = initial_port or self._settings["shared"].get("port") or SERIAL_PORT

        self.title(f"Lickometer  ·  Columbia AIC  ·  {port}")
        self.configure(bg=BG)
        self.geometry("1440x980")

        self._reader     = SerialReader()
        self._reader.port = port
        self._models     = {i: ExperimentModel(i) for i in range(1, 5)}
        self._arduino_ts = [0]
        self._connected  = False
        self._streaming  = False
        self._last_raw:  Dict[int, float] = {}   # {arduino_id: last_amp}
        self._snaps:     Dict[tuple, float] = {} # {(load_id, "50g"|"bottle"): val}
        self._quadrants: List[ExpQuadrant] = []

        # Apply persisted calibration to the models before the GUI builds.
        self._apply_loaded_calibration(port)

        self._build(port)
        self._refresh_loaded_into_gui()          # Task 3: populate GUI fields

        # Task 2: start the flag watchdog (runs in the Tk main loop).
        self.after(WATCHDOG_MS, self._watchdog_tick)

    # ══════════════════════════════════════════════════════════════════════════
    # SETTINGS HELPERS (Task 3)
    # ══════════════════════════════════════════════════════════════════════════

    def _apply_loaded_calibration(self, port: str):
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
        if hasattr(self, "_plot_vars"):
            out = {}
            for k, v in self._plot_vars.items():
                try:
                    out[k] = float(v.get())
                except (ValueError, tk.TclError):
                    out[k] = self._settings["shared"]["plot"][k]
            out["load_yticks"] = int(out["load_yticks"])
            return out
        return dict(self._settings["shared"]["plot"])

    def get_save_folder(self) -> str:
        if hasattr(self, "_folder_var"):
            return self._folder_var.get().strip()
        return self._settings["shared"].get("save_folder", "")

    # ══════════════════════════════════════════════════════════════════════════
    # LAYOUT
    # ══════════════════════════════════════════════════════════════════════════

    def _build(self, port: str):
        # Top strip
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

        exp_tab   = tk.Frame(nb, bg=BG);  nb.add(exp_tab,   text="  Experiments  ")
        cal_tab   = tk.Frame(nb, bg=BG);  nb.add(cal_tab,   text="  Calibration  ")
        flag_tab  = tk.Frame(nb, bg=BG);  nb.add(flag_tab,  text="  Flag Settings  ")
        vis_tab   = tk.Frame(nb, bg=BG);  nb.add(vis_tab,   text="  Raster Plot Visuals  ")
        data_tab  = tk.Frame(nb, bg=BG);  nb.add(data_tab,  text="  Data  ")
        term_tab  = tk.Frame(nb, bg=BG);  nb.add(term_tab,  text="  Terminal  ")

        self._build_quad_tab(exp_tab)
        self._build_cal_tab(cal_tab)
        self._build_flag_tab(flag_tab)
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
        def lbl(text):
            return tk.Label(parent, text=text, font=FONT, bg=BG_PNL, fg=FG)

        def btn(text, cmd, bg=BG_ALT, fg=FG, **kw):
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

    # ── Tab: Experiments (4 quadrants) ────────────────────────────────────────

    def _build_quad_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        positions = {1: (0, 0), 2: (0, 1), 3: (1, 0), 4: (1, 1)}
        for exp_id, (row, col) in positions.items():
            q = ExpQuadrant(parent, self._models[exp_id],
                            self._reader, self._arduino_ts, host=self)
            q.grid(row=row, column=col, sticky="nsew", padx=3, pady=3)
            self._quadrants.append(q)

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
            tk.Button(th, text="Set", font=FONTB,
                      bg=BG_ALT, fg=FG, relief=tk.FLAT, padx=6,
                      command=lambda ch=ch: self._set_threshold(ch)
                      ).grid(row=r, column=c * 3 + 2, padx=4)

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
                    tk.Button(grid, text=lbl_txt, font=FONTB,
                              bg=BG_ALT, fg=FG, relief=tk.FLAT, padx=6,
                              command=lambda k=key, sk=snap_key, lid=load_id:
                                      self._snap(k, sk, lid)
                              ).grid(row=r, column=4 + ci * 2, padx=2)

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

        # ── Alerts log ────────────────────────────────────────────────────────
        tk.Label(parent, text="Alerts log", font=FONTB, bg=BG, fg=FG
                 ).pack(anchor="w", padx=16, pady=(6, 2))
        self._alert_text = tk.Text(parent, bg=BG_PNL, fg=FG, font=FONTM,
                                   relief=tk.FLAT, state=tk.DISABLED,
                                   wrap=tk.WORD, height=12)
        asb = ttk.Scrollbar(parent, orient=tk.VERTICAL,
                            command=self._alert_text.yview)
        self._alert_text.configure(yscrollcommand=asb.set)
        asb.pack(side=tk.RIGHT, fill=tk.Y)
        self._alert_text.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 8))
        self._alert_text.tag_configure("error", foreground=CLR_RED)
        self._alert_text.tag_configure("flag",  foreground=CLR_EXP)
        self._alert_text.tag_configure("info",  foreground=FG_MUT)

    # ── Tab: Raster Plot Visuals (Task 5) ─────────────────────────────────────

    def _build_visuals_tab(self, parent):
        tk.Label(parent,
                 text="Load-cell axis limits and tick marks for the raster "
                      "plots. Applies to all four experiments and is saved "
                      "(shared across instances).",
                 font=FONT, bg=BG, fg=FG_MUT, wraplength=900, justify="left"
                 ).pack(anchor="w", padx=16, pady=(12, 6))

        f = tk.Frame(parent, bg=BG_PNL, padx=16, pady=12)
        f.pack(fill=tk.X, padx=16, pady=(0, 8))

        self._plot_vars: Dict[str, tk.StringVar] = {}
        plot = self._settings["shared"]["plot"]
        rows = [
            ("load_ymin",   "Load axis minimum (g):"),
            ("load_ymax",   "Load axis maximum (g):"),
            ("load_yticks", "Number of tick marks:"),
        ]
        for i, (key, label) in enumerate(rows):
            tk.Label(f, text=label, font=FONT, bg=BG_PNL, fg=FG
                     ).grid(row=i, column=0, sticky="w", pady=5, padx=(0, 16))
            v = tk.StringVar(value=str(plot[key]))
            self._plot_vars[key] = v
            tk.Spinbox(f, from_=0, to=999999, increment=1,
                       textvariable=v, width=10, font=FONTM,
                       bg=BG_ALT, fg=FG, relief=tk.FLAT
                       ).grid(row=i, column=1, sticky="w", padx=4)

        tk.Button(f, text="Apply & Save", font=FONTB,
                  bg=CLR_GRN, fg="white", activebackground="#25A244",
                  relief=tk.FLAT, padx=10, pady=3,
                  command=self._apply_plot_settings
                  ).grid(row=len(rows), column=0, sticky="w", pady=(10, 0))

    # ── Tab: Data / Save folder (Task 6) ──────────────────────────────────────

    def _build_data_tab(self, parent):
        tk.Label(parent,
                 text="Choose the folder that Stop & Save defaults to and that "
                      f"autosave writes to every {AUTOSAVE_HOURS} hours while an "
                      "experiment is running. The path is saved and restored "
                      "(shared across instances).",
                 font=FONT, bg=BG, fg=FG_MUT, wraplength=900, justify="left"
                 ).pack(anchor="w", padx=16, pady=(12, 6))

        f = tk.Frame(parent, bg=BG_PNL, padx=16, pady=12)
        f.pack(fill=tk.X, padx=16, pady=(0, 8))

        tk.Label(f, text="Save folder:", font=FONT, bg=BG_PNL, fg=FG
                 ).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self._folder_var = tk.StringVar(
            value=self._settings["shared"].get("save_folder", ""))
        tk.Entry(f, textvariable=self._folder_var, width=70,
                 font=FONTM, bg=BG_ALT, fg=FG,
                 insertbackground=FG, relief=tk.FLAT
                 ).grid(row=0, column=1, sticky="w", padx=4)
        tk.Button(f, text="Browse…", font=FONTB,
                  bg=BG_ALT, fg=FG, relief=tk.FLAT, padx=10,
                  command=self._browse_folder
                  ).grid(row=0, column=2, padx=4)
        tk.Button(f, text="Save path", font=FONTB,
                  bg=CLR_GRN, fg="white", activebackground="#25A244",
                  relief=tk.FLAT, padx=10,
                  command=self._save_folder_path
                  ).grid(row=0, column=3, padx=4)

    # ── Tab: Terminal ─────────────────────────────────────────────────────────

    def _build_terminal_tab(self, parent):
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
        for q in self._quadrants:
            q.apply_plot_settings()

    # ══════════════════════════════════════════════════════════════════════════
    # ALERTS  (Task 2)
    # ══════════════════════════════════════════════════════════════════════════

    def emit_alert(self, exp_id, text: str, level: str = "flag"):
        """Show an alert in the GUI (alerts log + bottom banner) and terminal."""
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        who   = "SYSTEM" if exp_id in (None, 0) else f"Exp {exp_id}"
        tag   = "ERROR" if level == "error" else ("INFO" if level == "info" else "FLAG")
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
            colour = CLR_RED if level == "error" else (
                FG_MUT if level == "info" else CLR_EXP)
            self._alert_banner.config(text=line, fg=colour)

    def _watchdog_tick(self):
        # Task 2: never let watchdog errors stop the loop.
        try:
            if self._connected and self._streaming:
                now = self._arduino_ts[0]
                cfg = self.flag_settings()
                for exp_id, model in self._models.items():
                    for f in model.check_flags(now, cfg):
                        self.emit_alert(exp_id, f, level="flag")
        except Exception as e:
            print(f"[watchdog] {e}")
        finally:
            self.after(WATCHDOG_MS, self._watchdog_tick)

    # ══════════════════════════════════════════════════════════════════════════
    # ACTIONS
    # ══════════════════════════════════════════════════════════════════════════

    def _toggle_connect(self):
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
        # Task 3: persist per-port threshold
        save_port_section(self._reader.port, "thresholds", {str(ch): n})

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
        ratio = None
        if v50 is not None and vbot is not None and vbot != 0:
            ratio = v50 / vbot
            self._snap_svars[(exp_id, side, "ratio")].set(f"{ratio:.5f}")
            m = self._models[exp_id]
            if side == "Left":
                m.cal_left  = ratio
            else:
                m.cal_right = ratio

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

    def _apply_plot_settings(self):
        vals = {}
        for k, v in self._plot_vars.items():
            try:
                vals[k] = float(v.get())
            except ValueError:
                messagebox.showerror("Bad value", f"{k} must be a number.")
                return
        vals["load_yticks"] = int(vals["load_yticks"])
        if vals["load_ymax"] <= vals["load_ymin"]:
            messagebox.showerror("Bad axis", "Maximum must exceed minimum.")
            return
        save_shared("plot", vals)                        # Task 3
        self._settings["shared"]["plot"].update(vals)
        for q in self._quadrants:                        # Task 5: live redraw
            q.apply_plot_settings()
        self.emit_alert(None, "raster plot visuals updated", level="info")

    def _browse_folder(self):
        folder = filedialog.askdirectory(
            title="Choose save folder",
            initialdir=self._folder_var.get().strip() or _HERE)
        if folder:
            self._folder_var.set(folder)
            self._save_folder_path()

    def _save_folder_path(self):
        folder = self._folder_var.get().strip()
        save_shared_value("save_folder", folder)         # Task 3
        self._settings["shared"]["save_folder"] = folder
        self.emit_alert(None, f"save folder set: {folder}", level="info")

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
        if self._connected:
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
    # Task 1: optional COM port from the command line pre-fills the Port box,
    #         making it trivial to launch one instance per Arduino.
    init_port = sys.argv[1] if len(sys.argv) > 1 else None
    MainWindow(initial_port=init_port).mainloop()
