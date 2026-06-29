"""
lickometer_hub.py  —  Lickometer experiment HUB (multi-instance launcher)
Run:   python lickometer_hub.py
Deps:  pip install pyserial    (matplotlib/numpy are only needed by the GUI it launches)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT THIS IS

  A small control window that launches and tracks multiple lickometer GUI
  instances — one per Arduino / COM port — without closing itself. From here
  you (Task H1-H4):

    1) Pick any detected COM port and open a lickometer GUI for it. The hub
       stays open so you can open another port's instance, up to four (or as
       many boards as you have). Each instance is its own independent window
       and its own OS process (clean, separate serial ownership).

    2) Choose how many boxes (1-4) that instance drives. The instance lays its
       Monitor tab out to match (1 box fills the view; 2-4 use a 2×2 grid with
       only that many panes populated) and shows exactly that many Box tabs.

    3) Choose a parent folder + a name for a NEW per-instance folder. The hub
       creates:
           <parent>/<name>/
           <parent>/<name>/data/                 ← autosaved per-box data
           <parent>/<name>/lickometer_settings.json   ← this instance's settings
       So each instance keeps its own calibration / flag / visual settings.

    4) Select an Arduino sketch (.ino) and upload it to the board on that COM
       port (needs arduino-cli on PATH). The sketch name + path are recorded in
       that instance's settings json.

  The launched GUI is lickometer_finalx6.py (expected next to this file; the
  path is editable below). It is started with:

      python lickometer_finalx6.py --config <instance>/_launch_config.json

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import sys
import json
import time
import shlex
import threading
import subprocess
import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# COM-port enumeration (optional — manual entry still works without it).
try:
    from serial.tools import list_ports as _list_ports
    _SERIAL_OK = True
except Exception:
    _SERIAL_OK = False

# ── arduino-cli resolution ───────────────────────────────────────────────────
# Resolve the arduino-cli executable relative to THIS script so it works no
# matter what the current working directory is when the hub is launched. If a
# bundled binary is found next to this file it's used directly; otherwise we
# fall back to the bare name and let the OS search PATH.
def _resolve_arduino_cli():
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("arduino-cli.exe", "arduino-cli"):
        candidate = os.path.join(here, name)
        if os.path.isfile(candidate):
            return candidate
    return "arduino-cli"  # rely on PATH

ARDUINO_CLI = _resolve_arduino_cli()

# ── Theme (matches the GUI) ──────────────────────────────────────────────────
BG     = "#1C1C1E"
BG_PNL = "#2C2C2E"
BG_ALT = "#3A3A3C"
FG     = "#F2F2F7"
FG_MUT = "#8E8E93"
CLR_GRN = "#30D158"
CLR_RED = "#FF453A"
CLR_BLU = "#0A84FF"

FONT  = ("Segoe UI", 10)
FONTB = ("Segoe UI", 10, "bold")
FONTM = ("Courier New", 10)

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = os.getcwd()

DEFAULT_GUI = os.path.join(_HERE, "lickometer_finalx6.py")
# Common Arduino board fully-qualified board names for the upload step.
COMMON_FQBN = [
    "arduino:avr:mega",
    "arduino:avr:uno",
    "arduino:avr:nano",
    "arduino:avr:leonardo",
    "arduino:samd:mkrzero",
]

# Default Arduino↔event id map (must match the GUI's EXPERIMENT_CHANNELS). The
# hub setup page pre-populates these and lets the user override them per box;
# the chosen map is passed to the GUI in the launch config.
DEFAULT_EVENT_CHANNELS = {
    1: {"left_onset": 9,  "right_onset": 8,  "left_load": 1, "right_load": 0},
    2: {"left_onset": 11, "right_onset": 10, "left_load": 3, "right_load": 2},
    3: {"left_onset": 13, "right_onset": 12, "left_load": 5, "right_load": 4},
    4: {"left_onset": 15, "right_onset": 14, "left_load": 7, "right_load": 6},
}
_EVT_KEYS = ("left_onset", "right_onset", "left_load", "right_load")
_EVT_LABELS = {"left_onset": "L lick", "right_onset": "R lick",
               "left_load": "L load", "right_load": "R load"}


def find_ports():
    """Return a sorted list of detected COM port device names (or [] if none)."""
    if not _SERIAL_OK:
        return []
    try:
        return sorted(p.device for p in _list_ports.comports())
    except Exception:
        return []


def port_descriptions():
    """Return {device: 'device — description'} for the ports combobox tooltip text."""
    out = {}
    if not _SERIAL_OK:
        return out
    try:
        for p in _list_ports.comports():
            desc = (p.description or "").strip()
            out[p.device] = f"{p.device} — {desc}" if desc else p.device
    except Exception:
        pass
    return out


class Hub(tk.Tk):
    """The hub control window: configure a port and launch a GUI instance for it."""

    def __init__(self):
        """Build the hub window and load the port list."""
        super().__init__()
        self.title("Lickometer Hub  ·  Columbia AIC")
        self.configure(bg=BG)
        self.geometry("820x720")

        # Track launched instances: list of dicts {port, proc, folder, boxes}.
        self._instances = []

        self._build()
        self._refresh_ports()
        self.after(1500, self._poll_instances)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ──────────────────────────────────────────────────────────────────────────
    # LAYOUT
    # ──────────────────────────────────────────────────────────────────────────

    def _build(self):
        """Assemble the hub: port picker, instance config, sketch upload, log."""
        # ── Header ────────────────────────────────────────────────────────────
        head = tk.Frame(self, bg=BG_PNL, pady=8)
        head.pack(fill=tk.X)
        tk.Label(head, text="Lickometer Hub", font=("Segoe UI", 15, "bold"),
                 bg=BG_PNL, fg=FG).pack(side=tk.LEFT, padx=14)
        tk.Label(head,
                 text="Open one lickometer window per Arduino. This hub stays "
                      "open so you can open as many as you need.",
                 font=FONT, bg=BG_PNL, fg=FG_MUT, wraplength=520, justify="left"
                 ).pack(side=tk.LEFT, padx=4)

        # ── Activity log pinned to the bottom (always visible) ────────────────
        # Packed BEFORE the scroll area so it reserves space at the bottom and
        # can never be pushed off-screen by tall card content.
        logwrap = tk.Frame(self, bg=BG)
        logwrap.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=(0, 10))

        # ── Scrollable area holding all the setup cards ───────────────────────
        scroll_host = tk.Frame(self, bg=BG)
        scroll_host.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        _canvas = tk.Canvas(scroll_host, bg=BG, highlightthickness=0)
        _vbar = ttk.Scrollbar(scroll_host, orient=tk.VERTICAL,
                              command=_canvas.yview)
        _canvas.configure(yscrollcommand=_vbar.set)
        _vbar.pack(side=tk.RIGHT, fill=tk.Y)
        _canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # `body` is the inner frame; every self._card(body, ...) lands here and
        # scrolls with the canvas.
        body = tk.Frame(_canvas, bg=BG, padx=14, pady=10)
        _body_win = _canvas.create_window((0, 0), window=body, anchor="nw")

        def _sync_scrollregion(_e=None):
            _canvas.configure(scrollregion=_canvas.bbox("all"))
        body.bind("<Configure>", _sync_scrollregion)

        def _match_width(e):
            # Keep the inner frame as wide as the canvas so cards fill_X works.
            _canvas.itemconfigure(_body_win, width=e.width)
        _canvas.bind("<Configure>", _match_width)

        # Mouse-wheel scrolling, active only while the pointer is over the cards
        # (so it doesn't hijack the log's own scroll). Handles Win/macOS/Linux.
        def _on_wheel(e):
            if e.num == 4:
                _canvas.yview_scroll(-1, "units")
            elif e.num == 5:
                _canvas.yview_scroll(1, "units")
            else:
                _canvas.yview_scroll(int(-e.delta / 120), "units")
        def _wheel_on(_e):
            _canvas.bind_all("<MouseWheel>", _on_wheel)
            _canvas.bind_all("<Button-4>", _on_wheel)
            _canvas.bind_all("<Button-5>", _on_wheel)
        def _wheel_off(_e):
            _canvas.unbind_all("<MouseWheel>")
            _canvas.unbind_all("<Button-4>")
            _canvas.unbind_all("<Button-5>")
        _canvas.bind("<Enter>", _wheel_on)
        _canvas.bind("<Leave>", _wheel_off)

        self.minsize(640, 480)

        # ── 1. COM port ───────────────────────────────────────────────────────
        card1 = self._card(body, "1 · COM port")
        prow = tk.Frame(card1, bg=BG_PNL)
        prow.pack(fill=tk.X, pady=2)
        tk.Label(prow, text="Port:", font=FONT, bg=BG_PNL, fg=FG
                 ).pack(side=tk.LEFT, padx=(0, 6))
        self._port_var = tk.StringVar()
        self._port_combo = ttk.Combobox(prow, textvariable=self._port_var,
                                        width=28, font=FONTM, state="normal")
        self._port_combo.pack(side=tk.LEFT, padx=4)
        tk.Button(prow, text="Refresh", font=FONTB, bg=BG_ALT, fg=FG,
                  relief=tk.FLAT, padx=10, command=self._refresh_ports
                  ).pack(side=tk.LEFT, padx=6)
        self._port_hint = tk.Label(prow, text="", font=FONT,
                                    bg=BG_PNL, fg=FG_MUT)
        self._port_hint.pack(side=tk.LEFT, padx=8)

        # ── 2. Boxes ──────────────────────────────────────────────────────────
        card2 = self._card(body, "2 · Number of boxes for this instance (1-4)")
        brow = tk.Frame(card2, bg=BG_PNL)
        brow.pack(fill=tk.X, pady=2)
        self._boxes_var = tk.IntVar(value=4)
        for n in (1, 2, 3, 4):
            tk.Radiobutton(brow, text=str(n), variable=self._boxes_var, value=n,
                           font=FONTB, bg=BG_PNL, fg=FG, selectcolor=BG_ALT,
                           activebackground=BG_PNL, activeforeground=FG,
                           indicatoron=True
                           ).pack(side=tk.LEFT, padx=10)
        tk.Label(brow, text="The Monitor layout and the number of Box tabs "
                            "follow this value.",
                 font=FONT, bg=BG_PNL, fg=FG_MUT).pack(side=tk.LEFT, padx=12)

        # ── 3. Folder ─────────────────────────────────────────────────────────
        card3 = self._card(body, "3 · Instance folder")
        f1 = tk.Frame(card3, bg=BG_PNL)
        f1.pack(fill=tk.X, pady=2)
        tk.Label(f1, text="Parent path:", font=FONT, bg=BG_PNL, fg=FG, width=12,
                 anchor="w").pack(side=tk.LEFT)
        self._parent_var = tk.StringVar()
        tk.Entry(f1, textvariable=self._parent_var, width=48, font=FONTM,
                 bg=BG_ALT, fg=FG, insertbackground=FG, relief=tk.FLAT
                 ).pack(side=tk.LEFT, padx=4)
        tk.Button(f1, text="Browse…", font=FONTB, bg=BG_ALT, fg=FG,
                  relief=tk.FLAT, padx=10, command=self._browse_parent
                  ).pack(side=tk.LEFT, padx=6)
        f2 = tk.Frame(card3, bg=BG_PNL)
        f2.pack(fill=tk.X, pady=2)
        tk.Label(f2, text="New folder:", font=FONT, bg=BG_PNL, fg=FG, width=12,
                 anchor="w").pack(side=tk.LEFT)
        self._newfolder_var = tk.StringVar(
            value=f"lickometer_{datetime.datetime.now():%Y%m%d}")
        tk.Entry(f2, textvariable=self._newfolder_var, width=30, font=FONTM,
                 bg=BG_ALT, fg=FG, insertbackground=FG, relief=tk.FLAT
                 ).pack(side=tk.LEFT, padx=4)
        tk.Label(f2, text="→  <parent>/<new folder>/  with  data/  +  "
                          "lickometer_settings.json inside",
                 font=FONT, bg=BG_PNL, fg=FG_MUT).pack(side=tk.LEFT, padx=8)

        # Day number — data is written into a per-day subfolder (Day<N>) so the
        # hub can be re-run each day without overwriting previous days' data.
        f3 = tk.Frame(card3, bg=BG_PNL)
        f3.pack(fill=tk.X, pady=2)
        tk.Label(f3, text="Day number:", font=FONT, bg=BG_PNL, fg=FG, width=12,
                 anchor="w").pack(side=tk.LEFT)
        self._day_var = tk.IntVar(value=1)
        tk.Spinbox(f3, from_=1, to=999, textvariable=self._day_var, width=6,
                   font=FONTM, bg=BG_ALT, fg=FG, relief=tk.FLAT
                   ).pack(side=tk.LEFT, padx=4)
        tk.Label(f3, text="→  data saved under  <new folder>/Day<N>/  "
                          "(settings stay shared across days)",
                 font=FONT, bg=BG_PNL, fg=FG_MUT).pack(side=tk.LEFT, padx=8)

        # ── 4. Arduino sketch ─────────────────────────────────────────────────
        card4 = self._card(body, "4 · Arduino sketch (optional upload)")
        s1 = tk.Frame(card4, bg=BG_PNL)
        s1.pack(fill=tk.X, pady=2)
        tk.Label(s1, text="Sketch (.ino):", font=FONT, bg=BG_PNL, fg=FG,
                 width=12, anchor="w").pack(side=tk.LEFT)
        self._sketch_var = tk.StringVar()
        tk.Entry(s1, textvariable=self._sketch_var, width=44, font=FONTM,
                 bg=BG_ALT, fg=FG, insertbackground=FG, relief=tk.FLAT
                 ).pack(side=tk.LEFT, padx=4)
        tk.Button(s1, text="Browse…", font=FONTB, bg=BG_ALT, fg=FG,
                  relief=tk.FLAT, padx=10, command=self._browse_sketch
                  ).pack(side=tk.LEFT, padx=6)
        s2 = tk.Frame(card4, bg=BG_PNL)
        s2.pack(fill=tk.X, pady=2)
        tk.Label(s2, text="Board (FQBN):", font=FONT, bg=BG_PNL, fg=FG,
                 width=12, anchor="w").pack(side=tk.LEFT)
        self._fqbn_var = tk.StringVar(value=COMMON_FQBN[0])
        ttk.Combobox(s2, textvariable=self._fqbn_var, values=COMMON_FQBN,
                     width=26, font=FONTM, state="normal"
                     ).pack(side=tk.LEFT, padx=4)
        self._upload_btn = tk.Button(
            s2, text="Upload sketch to this port", font=FONTB,
            bg=CLR_BLU, fg="white", relief=tk.FLAT, padx=12,
            command=self._upload_sketch)
        self._upload_btn.pack(side=tk.LEFT, padx=8)
        s3 = tk.Frame(card4, bg=BG_PNL)
        s3.pack(fill=tk.X, pady=2)
        self._autoupload_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            s3, text="Auto-upload this sketch before opening the instance "
                     "(so the Arduino needn't be pre-flashed)",
            variable=self._autoupload_var, font=FONT, bg=BG_PNL, fg=FG,
            selectcolor=BG_ALT, activebackground=BG_PNL, activeforeground=FG
            ).pack(side=tk.LEFT, padx=(98, 0))

        # ── 5. Event-id map (advanced) ────────────────────────────────────────
        card_evt = self._card(
            body, "5 · Arduino event-id map (advanced — defaults usually fine)")
        tk.Label(card_evt,
                 text="Maps each box's lick/load events to Arduino channel ids. "
                      "Lick-OFF ids are derived as lick-ON + 8.",
                 font=FONT, bg=BG_PNL, fg=FG_MUT).pack(anchor="w", pady=(0, 4))
        eg = tk.Frame(card_evt, bg=BG_PNL); eg.pack(fill=tk.X)
        tk.Label(eg, text="Box", font=FONTB, bg=BG_PNL, fg=FG_MUT
                 ).grid(row=0, column=0, padx=6, pady=2)
        for c, key in enumerate(_EVT_KEYS):
            tk.Label(eg, text=_EVT_LABELS[key], font=FONTB, bg=BG_PNL, fg=FG_MUT
                     ).grid(row=0, column=c + 1, padx=6, pady=2)
        self._evt_vars = {}
        for box in range(1, 5):
            tk.Label(eg, text=str(box), font=FONTM, bg=BG_PNL, fg=FG
                     ).grid(row=box, column=0, padx=6, pady=1)
            for c, key in enumerate(_EVT_KEYS):
                var = tk.IntVar(value=DEFAULT_EVENT_CHANNELS[box][key])
                self._evt_vars[(box, key)] = var
                tk.Spinbox(eg, from_=0, to=63, textvariable=var, width=4,
                           font=FONTM, bg=BG_ALT, fg=FG, relief=tk.FLAT
                           ).grid(row=box, column=c + 1, padx=4, pady=1)
        tk.Button(card_evt, text="Reset to defaults", font=FONTB, bg=BG_ALT,
                  fg=FG, relief=tk.FLAT, padx=8,
                  command=self._reset_event_map).pack(anchor="w", pady=(4, 0))

        # ── GUI script path + launch ──────────────────────────────────────────
        card5 = self._card(body, "Launch")
        g1 = tk.Frame(card5, bg=BG_PNL)
        g1.pack(fill=tk.X, pady=2)
        tk.Label(g1, text="GUI script:", font=FONT, bg=BG_PNL, fg=FG, width=12,
                 anchor="w").pack(side=tk.LEFT)
        self._gui_var = tk.StringVar(value=DEFAULT_GUI)
        tk.Entry(g1, textvariable=self._gui_var, width=48, font=FONTM,
                 bg=BG_ALT, fg=FG, insertbackground=FG, relief=tk.FLAT
                 ).pack(side=tk.LEFT, padx=4)
        tk.Button(g1, text="Browse…", font=FONTB, bg=BG_ALT, fg=FG,
                  relief=tk.FLAT, padx=10, command=self._browse_gui
                  ).pack(side=tk.LEFT, padx=6)

        launch_row = tk.Frame(card5, bg=BG_PNL)
        launch_row.pack(fill=tk.X, pady=(8, 2))
        tk.Button(launch_row, text="▶  Open lickometer instance", font=FONTB,
                  bg=CLR_GRN, fg="white", activebackground="#25A244",
                  relief=tk.FLAT, padx=16, pady=6, command=self._launch_instance
                  ).pack(side=tk.LEFT)
        self._inst_lbl = tk.Label(launch_row, text="0 instances open",
                                   font=FONT, bg=BG_PNL, fg=FG_MUT)
        self._inst_lbl.pack(side=tk.LEFT, padx=14)

        # ── Log ───────────────────────────────────────────────────────────────
        # Lives in the pinned `logwrap` (bottom of the window), not in the
        # scrollable card area, so it is always on screen.
        tk.Label(logwrap, text="Activity log", font=FONTB, bg=BG, fg=FG
                 ).pack(anchor="w", pady=(8, 2))
        self._log = tk.Text(logwrap, bg=BG_PNL, fg=FG, font=FONTM, relief=tk.FLAT,
                            height=8, wrap=tk.WORD, state=tk.DISABLED)
        lsb = ttk.Scrollbar(logwrap, orient=tk.VERTICAL, command=self._log.yview)
        self._log.configure(yscrollcommand=lsb.set)
        lsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._log.tag_configure("err", foreground=CLR_RED)
        self._log.tag_configure("ok",  foreground=CLR_GRN)
        self._log.tag_configure("info", foreground=FG_MUT)

        if not _SERIAL_OK:
            self.log("pyserial not found — COM ports can't be auto-detected. "
                     "Type the port manually (e.g. COM3). Install with "
                     "'pip install pyserial'.", "err")

    def _card(self, parent, title):
        """Create a titled card frame and return its inner content frame."""
        tk.Label(parent, text=title, font=FONTB, bg=BG, fg=FG
                 ).pack(anchor="w", pady=(8, 1))
        f = tk.Frame(parent, bg=BG_PNL, padx=12, pady=10)
        f.pack(fill=tk.X)
        return f

    # ──────────────────────────────────────────────────────────────────────────
    # LOG
    # ──────────────────────────────────────────────────────────────────────────

    def log(self, msg, tag="info"):
        """Append a timestamped line to the activity log (thread-safe via after)."""
        def _do():
            stamp = datetime.datetime.now().strftime("%H:%M:%S")
            self._log.config(state=tk.NORMAL)
            self._log.insert(tk.END, f"[{stamp}] {msg}\n", (tag,))
            self._log.see(tk.END)
            self._log.config(state=tk.DISABLED)
        try:
            self.after(0, _do)
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────────────
    # PORTS
    # ──────────────────────────────────────────────────────────────────────────

    def _refresh_ports(self):
        """Re-scan COM ports and repopulate the combobox."""
        ports = find_ports()
        self._port_combo["values"] = ports
        descs = port_descriptions()
        if ports:
            if self._port_var.get() not in ports:
                self._port_var.set(ports[0])
            self._port_hint.config(
                text=descs.get(self._port_var.get(), ""))
            self.log(f"Detected ports: {', '.join(ports)}")
        else:
            self._port_hint.config(text="(none detected — type manually)")
            self.log("No COM ports detected.", "info")

    # ──────────────────────────────────────────────────────────────────────────
    # BROWSE BUTTONS
    # ──────────────────────────────────────────────────────────────────────────

    def _browse_parent(self):
        """Pick the parent folder that the new instance folder is created in."""
        d = filedialog.askdirectory(
            title="Choose parent folder",
            initialdir=self._parent_var.get().strip() or _HERE)
        if d:
            self._parent_var.set(d)

    def _browse_sketch(self):
        """Pick an Arduino sketch file (.ino)."""
        f = filedialog.askopenfilename(
            title="Choose Arduino sketch",
            filetypes=[("Arduino sketch", "*.ino"), ("All files", "*.*")])
        if f:
            self._sketch_var.set(f)

    def _browse_gui(self):
        """Pick the lickometer GUI script to launch."""
        f = filedialog.askopenfilename(
            title="Choose lickometer GUI script",
            filetypes=[("Python", "*.py"), ("All files", "*.*")])
        if f:
            self._gui_var.set(f)

    # ──────────────────────────────────────────────────────────────────────────
    # SKETCH UPLOAD (Task H4)
    # ──────────────────────────────────────────────────────────────────────────

    def _reset_event_map(self):
        """Restore the event-id spinboxes to the built-in defaults."""
        for (box, key), var in self._evt_vars.items():
            try:
                var.set(DEFAULT_EVENT_CHANNELS[box][key])
            except Exception:
                pass

    def _collect_event_channels(self, boxes):
        """Read the event-id grid into {box: {key: id}} for the launched boxes."""
        out = {}
        for box in range(1, boxes + 1):
            out[box] = {}
            for key in _EVT_KEYS:
                try:
                    out[box][key] = int(self._evt_vars[(box, key)].get())
                except Exception:
                    out[box][key] = DEFAULT_EVENT_CHANNELS[box][key]
        return out

    def _upload_sketch(self, then=None):
        """Compile + upload the selected sketch to the selected port via arduino-cli.

        `then` (optional) is a no-arg callback run on the main thread after a
        successful upload — used by launch auto-upload to start the GUI next.
        """
        port   = self._port_var.get().strip()
        sketch = self._sketch_var.get().strip()
        fqbn   = self._fqbn_var.get().strip()
        if not port:
            messagebox.showwarning("No port", "Select or type a COM port first.")
            return
        if not sketch or not os.path.isfile(sketch):
            messagebox.showwarning("No sketch",
                                   "Choose a valid Arduino sketch (.ino).")
            return
        if not fqbn:
            messagebox.showwarning("No board",
                                   "Enter the board FQBN (e.g. arduino:avr:mega).")
            return

        self._upload_btn.config(state=tk.DISABLED, text="Uploading…")
        self.log(f"Uploading {os.path.basename(sketch)} → {port} ({fqbn})…")
        threading.Thread(target=self._upload_worker,
                         args=(port, sketch, fqbn, then), daemon=True).start()

    def _ensure_core(self, fqbn, run):
        """Ensure the platform core implied by `fqbn` is installed.

        The core (platform) id is the first two colon-separated parts of the
        FQBN — e.g. 'arduino:avr:mega' -> 'arduino:avr', 'esp32:esp32:esp32' ->
        'esp32:esp32'. If it's already installed this is a quick local check and
        nothing is downloaded. Returns True if the core is present (or was just
        installed), False if installation failed. `run` is the streaming
        subprocess helper from _upload_worker.
        """
        parts = fqbn.split(":")
        if len(parts) < 2:
            # Malformed FQBN — let the compile step surface a clear error.
            return True
        core_id = ":".join(parts[:2])

        # Already installed? Ask arduino-cli quietly (local, no network).
        try:
            p = subprocess.run([ARDUINO_CLI, "core", "list"],
                               capture_output=True, text=True, timeout=60)
            for ln in (p.stdout or "").splitlines():
                if ln.strip().lower().startswith(core_id.lower()):
                    self.log(f"Core {core_id} already installed.", "info")
                    return True
        except Exception as e:
            self.log(f"  (couldn't check installed cores: {e})", "info")

        # Not found — install it (first-time setup; needs internet).
        self.log(f"Core {core_id} not installed — fetching it now "
                 "(first-time setup, needs internet)…")
        if run([ARDUINO_CLI, "core", "update-index"]) != 0:
            self.log("Couldn't refresh the core index — check your internet "
                     "connection. Trying the install anyway…", "err")
        if run([ARDUINO_CLI, "core", "install", core_id]) != 0:
            self.log(f"Core install failed for {core_id}. Install it manually "
                     f"in a terminal:  arduino-cli core install {core_id}", "err")
            return False
        self.log(f"Core {core_id} installed.", "ok")
        return True

    def _upload_worker(self, port, sketch, fqbn, then=None):
        """Background: run arduino-cli compile + upload, streaming output to the log."""
        sketch_dir = os.path.dirname(os.path.abspath(sketch))
        try:
            # Verify arduino-cli is available.
            subprocess.run([ARDUINO_CLI, "version"],
                           capture_output=True, text=True, timeout=20)
        except FileNotFoundError:
            self.log(f"arduino-cli not found (looked for: {ARDUINO_CLI}). Put "
                     "arduino-cli.exe in the same folder as this hub script, or "
                     "install it from https://arduino.github.io/arduino-cli/ and "
                     "add it to PATH, then retry.", "err")
            self._reenable_upload()
            return
        except Exception as e:
            self.log(f"arduino-cli check failed: {e}", "err")
            self._reenable_upload()
            return

        def run(cmd):
            """Run a subprocess command, stream stdout/stderr to the log, return rc."""
            self.log("$ " + " ".join(shlex.quote(c) for c in cmd))
            try:
                p = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=300)
            except Exception as e:
                self.log(f"command failed: {e}", "err")
                return 1
            for stream in (p.stdout, p.stderr):
                if stream:
                    for ln in stream.strip().splitlines():
                        self.log("  " + ln,
                                 "err" if p.returncode else "info")
            return p.returncode

        # Make sure the board's platform core is installed before compiling,
        # so a fresh machine doesn't fail compile with "platform not installed".
        if not self._ensure_core(fqbn, run):
            self._reenable_upload()
            return

        rc = run([ARDUINO_CLI, "compile", "--fqbn", fqbn, sketch_dir])
        if rc != 0:
            self.log("Compile failed — fix the sketch / FQBN and retry.", "err")
            self._reenable_upload()
            return
        rc = run([ARDUINO_CLI, "upload", "-p", port,
                  "--fqbn", fqbn, sketch_dir])
        if rc == 0:
            self.log(f"Upload OK → {port}.", "ok")
            if then is not None:
                self.after(0, then)
        else:
            self.log("Upload failed — check the port, board and cable.", "err")
        self._reenable_upload()

    def _reenable_upload(self):
        """Re-enable the upload button from any thread."""
        try:
            self.after(0, lambda: self._upload_btn.config(
                state=tk.NORMAL, text="Upload sketch to this port"))
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────────────
    # LAUNCH INSTANCE (Task H1-H3)
    # ──────────────────────────────────────────────────────────────────────────

    def _launch_instance(self):
        """Create the instance folder layout, write the launch config, and start the GUI."""
        port   = self._port_var.get().strip()
        parent = self._parent_var.get().strip()
        name   = self._newfolder_var.get().strip()
        gui    = self._gui_var.get().strip()
        boxes  = int(self._boxes_var.get())
        day    = int(self._day_var.get())

        if not port:
            messagebox.showwarning("No port", "Select or type a COM port first.")
            return
        if not parent:
            messagebox.showwarning("No parent folder",
                                   "Choose a parent folder for the instance.")
            return
        if not name:
            messagebox.showwarning("No folder name",
                                   "Enter a name for the new instance folder.")
            return
        if not os.path.isfile(gui):
            messagebox.showerror("GUI not found",
                                 f"Could not find the GUI script:\n{gui}")
            return

        instance_folder = os.path.join(parent, name)
        day_folder      = os.path.join(instance_folder, f"Day{day}")
        data_folder     = os.path.join(day_folder, "data")
        settings_file   = os.path.join(instance_folder,
                                       "lickometer_settings.json")
        try:
            os.makedirs(data_folder, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Cannot create folder", str(e))
            return

        sketch = self._sketch_var.get().strip()
        config = {
            "port":            port,
            "num_boxes":       boxes,
            "day_number":      day,
            "instance_folder": instance_folder,
            "day_folder":      day_folder,
            "data_folder":     data_folder,
            "settings_file":   settings_file,
            "event_channels":  {str(b): m for b, m in
                                self._collect_event_channels(boxes).items()},
            "sketch_name":     os.path.basename(sketch) if sketch else "",
            "sketch_path":     sketch,
            "created":         datetime.datetime.now().isoformat(timespec="seconds"),
        }
        cfg_path = os.path.join(instance_folder, "_launch_config.json")
        try:
            with open(cfg_path, "w") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            messagebox.showerror("Cannot write config", str(e))
            return

        # Optionally flash the sketch first so the Arduino needn't be pre-loaded.
        sketch = self._sketch_var.get().strip()
        if (getattr(self, "_autoupload_var", None) and self._autoupload_var.get()
                and sketch and os.path.isfile(sketch)):
            self.log("Auto-upload requested — flashing before launch…")
            self._upload_sketch(then=lambda: self._spawn_gui(
                gui, cfg_path, port, boxes, instance_folder))
            return

        self._spawn_gui(gui, cfg_path, port, boxes, instance_folder)

    def _spawn_gui(self, gui, cfg_path, port, boxes, instance_folder):
        """Start the GUI process for a written launch config and track it."""
        try:
            proc = subprocess.Popen([sys.executable, gui, "--config", cfg_path])
        except Exception as e:
            messagebox.showerror("Launch failed", str(e))
            return

        self._instances.append(
            {"port": port, "proc": proc, "folder": instance_folder,
             "boxes": boxes})
        self.log(f"Opened instance: {port} · {boxes} box(es) · {instance_folder}",
                 "ok")
        self._update_inst_label()

        # Pre-fill a fresh folder name so the next instance doesn't collide.
        self._newfolder_var.set(
            f"lickometer_{datetime.datetime.now():%Y%m%d_%H%M%S}")

    # ──────────────────────────────────────────────────────────────────────────
    # INSTANCE TRACKING
    # ──────────────────────────────────────────────────────────────────────────

    def _poll_instances(self):
        """Drop instances whose process has exited; keep the counter accurate."""
        alive = []
        for inst in self._instances:
            if inst["proc"].poll() is None:
                alive.append(inst)
            else:
                self.log(f"Instance closed: {inst['port']}", "info")
        if len(alive) != len(self._instances):
            self._instances = alive
            self._update_inst_label()
        self.after(1500, self._poll_instances)

    def _update_inst_label(self):
        """Refresh the 'N instances open' label and list the active ports."""
        n = len(self._instances)
        ports = ", ".join(i["port"] for i in self._instances)
        txt = f"{n} instance{'s' if n != 1 else ''} open"
        if ports:
            txt += f"  ·  {ports}"
        self._inst_lbl.config(text=txt)

    def _on_close(self):
        """Confirm before closing the hub if instances are still running."""
        if self._instances:
            if not messagebox.askyesno(
                    "Close hub?",
                    f"{len(self._instances)} lickometer window(s) are still "
                    "open. They will keep running after the hub closes.\n\n"
                    "Close the hub anyway?"):
                return
        self.destroy()


if __name__ == "__main__":
    Hub().mainloop()
