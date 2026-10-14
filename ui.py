"""
Herald — Desktop UI
Ashborne / ashborne.dev

A tkinter dashboard in the Ashborne dark eldritch aesthetic.
Runs alongside herald.py — communicates via a shared state object.

Launch: python ui.py (standalone preview)
        Or imported and driven by herald.py
"""

import tkinter as tk
from tkinter import scrolledtext
import threading
import time
from datetime import datetime


# ── Ashborne palette ───────────────────────────────────────────────────────────
BG          = "#1a1610"   # near-black warm
BG_PANEL    = "#201c15"   # slightly lighter panel
BG_INPUT    = "#161210"   # input field background
AMBER       = "#c8861e"   # primary accent
AMBER_DIM   = "#7a5010"   # muted amber for borders
OFF_WHITE   = "#d4c9a8"   # main text
DIM_TEXT    = "#6b6047"   # secondary/dim text
SUCCESS     = "#4a7c4e"   # success green
DANGER      = "#8b2e2e"   # danger red
BORDER      = "#2a2318"   # subtle border

# ── Typography ─────────────────────────────────────────────────────────────────
FONT_DISPLAY = ("Georgia", 18, "bold")
FONT_HEADING = ("Georgia", 11, "bold")
FONT_BODY    = ("Georgia", 10)
FONT_MONO    = ("Courier New", 9)
FONT_MONO_SM = ("Courier New", 8)
FONT_STATUS  = ("Courier New", 10, "bold")


# ── Shared state (herald.py writes, ui.py reads) ───────────────────────────────
class HeraldState:
    def __init__(self):
        self.status       = "IDLE"          # IDLE | LISTENING | THINKING | SPEAKING
        self.last_input   = ""
        self.last_response= ""
        self.conversation = []              # list of (role, text, timestamp)
        self.active_timers= []              # list of timer labels
        self.now_playing  = ""             # current Spotify track
        self.pending_edit = None           # self-edit awaiting approval
        self._lock        = threading.Lock()

    def update(self, **kwargs):
        with self._lock:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def add_message(self, role: str, text: str):
        with self._lock:
            ts = datetime.now().strftime("%H:%M")
            self.conversation.append((role, text, ts))
            if role == "user":
                self.last_input = text
            else:
                self.last_response = text


# ── Herald UI ─────────────────────────────────────────────────────────────────
class HeraldUI:
    def __init__(self, state: HeraldState, on_text_input=None, on_voice_trigger=None,on_apply_edit=None, on_discard_edit=None):
        self.state            = state
        self.on_text_input    = on_text_input
        self.on_voice_trigger = on_voice_trigger
        self.on_apply_edit    = on_apply_edit
        self.on_discard_edit  = on_discard_edit

        self.root = tk.Tk()
        self.root.title("Herald — Ashborne")
        self.root.configure(bg=BG)
        self.root.resizable(True, True)
        self.root.minsize(420, 600)
        # Snap to right edge at full screen height after window is ready
        self.root.after(10, self._snap_to_right)

        self._build()
        self._start_refresh()

    def _on_apply_edit(self):
        if self.on_apply_edit:
            threading.Thread(target=self.on_apply_edit, daemon=True).start()

    def _on_discard_edit(self):
        if self.on_discard_edit:
            threading.Thread(target=self.on_discard_edit, daemon=True).start()

    def _snap_to_right(self):
        screen_h = self.root.winfo_screenheight()
        screen_w = self.root.winfo_screenwidth()
        win_w    = 500
        x_pos    = screen_w - win_w
        self.root.geometry(f"{win_w}x{screen_h}+{x_pos}+0")

    def _build(self):
        root = self.root

        # ── Header ────────────────────────────────────────────────────────────
        header = tk.Frame(root, bg=BG, pady=16)
        header.pack(fill="x", padx=20)

        tk.Label(header, text="HERALD", font=FONT_DISPLAY,
                 fg=AMBER, bg=BG).pack(side="left")

        self.status_label = tk.Label(header, text="● IDLE",
                                     font=FONT_STATUS, fg=DIM_TEXT, bg=BG)
        self.status_label.pack(side="right", pady=4)

        # Divider
        tk.Frame(root, bg=AMBER_DIM, height=1).pack(fill="x", padx=20)

        # ── Now playing ───────────────────────────────────────────────────────
        now_frame = tk.Frame(root, bg=BG_PANEL, pady=6)
        now_frame.pack(fill="x", padx=20, pady=(8, 0))

        tk.Label(now_frame, text="NOW PLAYING", font=FONT_MONO_SM,
                 fg=DIM_TEXT, bg=BG_PANEL).pack(side="left", padx=10)
        self.now_playing_label = tk.Label(now_frame, text="—",
                                          font=FONT_MONO_SM, fg=OFF_WHITE, bg=BG_PANEL)
        self.now_playing_label.pack(side="left", padx=4)

        # ── Active timers ─────────────────────────────────────────────────────
        timer_frame = tk.Frame(root, bg=BG_PANEL, pady=6)
        timer_frame.pack(fill="x", padx=20, pady=(2, 0))

        tk.Label(timer_frame, text="TIMERS", font=FONT_MONO_SM,
                 fg=DIM_TEXT, bg=BG_PANEL).pack(side="left", padx=10)
        self.timers_label = tk.Label(timer_frame, text="none",
                                     font=FONT_MONO_SM, fg=OFF_WHITE, bg=BG_PANEL)
        self.timers_label.pack(side="left", padx=4)

        tk.Frame(root, bg=BORDER, height=1).pack(fill="x", padx=20, pady=8)

        # ── Conversation history ───────────────────────────────────────────────
        tk.Label(root, text="CONVERSATION", font=FONT_MONO_SM,
                 fg=DIM_TEXT, bg=BG).pack(anchor="w", padx=20)

        conv_frame = tk.Frame(root, bg=BG_PANEL, bd=0)
        conv_frame.pack(fill="both", expand=True, padx=20, pady=(4, 0))

        self.conv_text = scrolledtext.ScrolledText(
            conv_frame,
            bg          = BG_PANEL,
            fg          = OFF_WHITE,
            font        = FONT_BODY,
            relief      = "flat",
            bd          = 0,
            wrap        = tk.WORD,
            state       = "disabled",
            cursor      = "arrow",
            selectbackground = AMBER_DIM,
        )
        self.conv_text.pack(fill="both", expand=True, padx=8, pady=8)

        # Text tags
        self.conv_text.tag_configure("user",      foreground=AMBER,    font=("Georgia", 10, "bold"))
        self.conv_text.tag_configure("herald",    foreground=OFF_WHITE, font=("Georgia", 10))
        self.conv_text.tag_configure("timestamp", foreground=DIM_TEXT,  font=("Courier New", 8))
        self.conv_text.tag_configure("label",     foreground=DIM_TEXT,  font=("Courier New", 8, "bold"))

        tk.Frame(root, bg=BORDER, height=1).pack(fill="x", padx=20, pady=4)

        # ── Commands reference ─────────────────────────────────────────────────
        tk.Label(root, text="COMMANDS", font=FONT_MONO_SM,
                 fg=DIM_TEXT, bg=BG).pack(anchor="w", padx=20)

        ref_frame = tk.Frame(root, bg=BG_PANEL)
        ref_frame.pack(fill="x", padx=20, pady=(4, 0))

        commands = [
            ("Wake",     "Say 'Herald' to activate"),
            ("Sleep",    "Say 'sleep' or 'that's all'"),
            ("Apps",     "open VS Code / open Spotify"),
            ("Music",    "play Arctic Monkeys / pause music"),
            ("Discord",  "play Tyler the Creator on Discord"),
            ("Games",    "open Elden Ring / launch CS2"),
            ("Timers",   "set a timer for 20 minutes"),
            ("System",   "volume up / minimise everything"),
            ("Search",   "search for Python asyncio"),
            ("Shutdown", "shutdown Herald"),
        ]

        for label, example in commands:
            row = tk.Frame(ref_frame, bg=BG_PANEL)
            row.pack(fill="x", padx=8, pady=0)
            tk.Label(row, text=f"{label:<10}", font=FONT_MONO_SM,
                     fg=AMBER, bg=BG_PANEL, width=10, anchor="w").pack(side="left")
            tk.Label(row, text=example, font=FONT_MONO_SM,
                     fg=DIM_TEXT, bg=BG_PANEL, anchor="w").pack(side="left")

        tk.Frame(root, bg=BORDER, height=1).pack(fill="x", padx=20, pady=4)

        # ── Self-edit diff panel (hidden until needed) ─────────────────────────
        self.diff_frame = tk.Frame(root, bg=BG_PANEL)
        # Not packed until needed

        diff_header = tk.Frame(self.diff_frame, bg=BG_PANEL)
        diff_header.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(diff_header, text="PROPOSED EDIT", font=FONT_MONO_SM,
                 fg=AMBER, bg=BG_PANEL).pack(side="left")
        self.diff_file_label = tk.Label(diff_header, text="",
                                        font=FONT_MONO_SM, fg=DIM_TEXT, bg=BG_PANEL)
        self.diff_file_label.pack(side="left", padx=6)

        self.diff_text = scrolledtext.ScrolledText(
            self.diff_frame,
            bg    = BG_INPUT,
            fg    = OFF_WHITE,
            font  = FONT_MONO_SM,
            relief= "flat",
            bd    = 0,
            wrap  = tk.NONE,
            state = "disabled",
            height= 10,
        )
        self.diff_text.pack(fill="x", padx=8, pady=4)
        self.diff_text.tag_configure("add",    foreground=SUCCESS)
        self.diff_text.tag_configure("remove", foreground=DANGER)
        self.diff_text.tag_configure("meta",   foreground=AMBER)

        diff_btns = tk.Frame(self.diff_frame, bg=BG_PANEL)
        diff_btns.pack(fill="x", padx=8, pady=(0, 8))

        tk.Button(diff_btns, text="APPLY", font=FONT_MONO_SM,
                  fg=BG, bg=SUCCESS, relief="flat", padx=12, pady=6,
                  cursor="hand2", command=self._on_apply_edit
                  ).pack(side="left", padx=(0, 4))

        tk.Button(diff_btns, text="DISCARD", font=FONT_MONO_SM,
                  fg=OFF_WHITE, bg=DANGER, relief="flat", padx=12, pady=6,
                  cursor="hand2", command=self._on_discard_edit
                  ).pack(side="left")

        # ── Input area ────────────────────────────────────────────────────────
        input_frame = tk.Frame(root, bg=BG)
        input_frame.pack(fill="x", padx=20, pady=(0, 16))

        self.text_input = tk.Entry(
            input_frame,
            bg           = BG_INPUT,
            fg           = OFF_WHITE,
            font         = FONT_BODY,
            relief       = "flat",
            bd           = 0,
            insertbackground = AMBER,
        )
        self.text_input.pack(side="left", fill="x", expand=True,
                             ipady=8, ipadx=8)
        self.text_input.bind("<Return>", self._on_enter)
        self.text_input.insert(0, "Type a command...")
        self.text_input.bind("<FocusIn>",  self._clear_placeholder)
        self.text_input.bind("<FocusOut>", self._restore_placeholder)
        self._placeholder_active = True

        # Send button
        self.send_btn = tk.Button(
            input_frame,
            text            = "SEND",
            font            = FONT_MONO_SM,
            fg              = BG,
            bg              = AMBER,
            activebackground= AMBER_DIM,
            activeforeground= OFF_WHITE,
            relief          = "flat",
            bd              = 0,
            padx            = 12,
            pady            = 8,
            cursor          = "hand2",
            command         = self._on_send,
        )
        self.send_btn.pack(side="left", padx=(4, 0))

        # Mic button
        self.mic_btn = tk.Button(
            input_frame,
            text            = "MIC",
            font            = FONT_MONO_SM,
            fg              = AMBER,
            bg              = BG_PANEL,
            activebackground= AMBER_DIM,
            activeforeground= BG,
            relief          = "flat",
            bd              = 0,
            padx            = 12,
            pady            = 8,
            cursor          = "hand2",
            command         = self._on_mic,
        )
        self.mic_btn.pack(side="left", padx=(4, 0))

        # Ashborne footer
        tk.Label(root, text="ASHBORNE", font=FONT_MONO_SM,
                 fg=DIM_TEXT, bg=BG).pack(pady=(0, 8))

    # ── Input handlers ─────────────────────────────────────────────────────────
    def _clear_placeholder(self, event):
        if self._placeholder_active:
            self.text_input.delete(0, tk.END)
            self.text_input.config(fg=OFF_WHITE)
            self._placeholder_active = False

    def _restore_placeholder(self, event):
        if not self.text_input.get():
            self.text_input.insert(0, "Type a command...")
            self.text_input.config(fg=DIM_TEXT)
            self._placeholder_active = True

    def _on_enter(self, event):
        self._on_send()

    def _on_send(self):
        if self._placeholder_active:
            return
        text = self.text_input.get().strip()
        if not text:
            return
        self.text_input.delete(0, tk.END)
        self._restore_placeholder(None)
        if self.on_text_input:
            threading.Thread(target=self.on_text_input,
                             args=(text,), daemon=True).start()

    def _on_mic(self):
        if self.on_voice_trigger:
            threading.Thread(target=self.on_voice_trigger,
                             daemon=True).start()

    # ── State refresh ──────────────────────────────────────────────────────────
    def _start_refresh(self):
        self._refresh()

    def _refresh(self):
        self._update_status()
        self._update_conversation()
        self._update_now_playing()
        self._update_timers()
        self._update_diff_panel()
        self.root.after(300, self._refresh)

    def _update_status(self):
        s = self.state.status
        colours = {
            "IDLE":      DIM_TEXT,
            "LISTENING": SUCCESS,
            "THINKING":  AMBER,
            "SPEAKING":  AMBER,
        }
        symbols = {
            "IDLE":      "○",
            "LISTENING": "●",
            "THINKING":  "◆",
            "SPEAKING":  "▶",
        }
        colour = colours.get(s, DIM_TEXT)
        symbol = symbols.get(s, "○")
        self.status_label.config(text=f"{symbol} {s}", fg=colour)

    def _update_conversation(self):
        with self.state._lock:
            conv = list(self.state.conversation)

        self.conv_text.config(state="normal")
        self.conv_text.delete("1.0", tk.END)

        for role, text, ts in conv:
            if role == "user":
                self.conv_text.insert(tk.END, f"YOU  ", "label")
                self.conv_text.insert(tk.END, f"{ts}\n", "timestamp")
                self.conv_text.insert(tk.END, f"{text}\n\n", "user")
            else:
                self.conv_text.insert(tk.END, f"HERALD  ", "label")
                self.conv_text.insert(tk.END, f"{ts}\n", "timestamp")
                self.conv_text.insert(tk.END, f"{text}\n\n", "herald")

        self.conv_text.config(state="disabled")
        self.conv_text.see(tk.END)

    def _update_now_playing(self):
        np = self.state.now_playing or "—"
        self.now_playing_label.config(text=np)

    def _update_timers(self):
        timers = self.state.active_timers
        self.timers_label.config(text=", ".join(timers) if timers else "none")

    def _update_diff_panel(self):
        edit = self.state.pending_edit
        if edit and edit.get("diff"):
            self.diff_frame.pack(fill="x", padx=20, pady=(0, 4), before=self.text_input.master)
            self.diff_file_label.config(text=edit.get("file", ""))
            self.diff_text.config(state="normal")
            self.diff_text.delete("1.0", tk.END)
            for line in edit["diff"].splitlines(keepends=True):
                if line.startswith("+") and not line.startswith("+++"):
                    self.diff_text.insert(tk.END, line, "add")
                elif line.startswith("-") and not line.startswith("---"):
                    self.diff_text.insert(tk.END, line, "remove")
                elif line.startswith("@@") or line.startswith("---") or line.startswith("+++"):
                    self.diff_text.insert(tk.END, line, "meta")
                else:
                    self.diff_text.insert(tk.END, line)
            self.diff_text.config(state="disabled")
        else:
            self.diff_frame.pack_forget()

    # ── Run ───────────────────────────────────────────────────────────────────
    def run(self):
        self.root.mainloop()


# ── Standalone preview ────────────────────────────────────────────────────────
if __name__ == "__main__":
    state = HeraldState()

    # Populate with sample data for preview
    state.update(status="IDLE", now_playing="Breathe Deeper — Tame Impala")
    state.active_timers = ["tea", "standup"]
    state.add_message("user", "Open VS Code")
    state.add_message("herald", "Opened VS Code.")
    state.add_message("user", "Play Tyler the Creator on Discord")
    state.add_message("herald", "Playing Tyler the Creator on Discord with shuffle and repeat.")
    state.add_message("user", "Set a timer for 20 minutes")
    state.add_message("herald", "Timer set for 20 minutes.")

    ui = HeraldUI(state)
    ui.run()
