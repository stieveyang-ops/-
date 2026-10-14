#!/usr/bin/env python
"""Desktop front-end for the independent prospective difficulty tool.

This GUI deliberately lives outside ``aizynth-reaction-difficulty``.  It only
launches ``prospective_score.py`` with a per-run output directory, then reads
that run's manifest and scored routes for display.  No Stage 1--11 artifact,
label, model, ranking, or project configuration is edited by this file.
"""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk


PROGRESS_PREFIX = "@@PROGRESS@@ ";


TOOL_DIR = Path(__file__).resolve().parent
SCORER = TOOL_DIR / "prospective_score.py"
PYTHON = Path(os.environ.get("AIZYNTH_PYTHON", "")) if os.environ.get("AIZYNTH_PYTHON") else None
DEFAULT_OUTPUT_ROOT = (TOOL_DIR.parent / "prospective_runs").resolve()
PROJECT_DIR = (TOOL_DIR.parent / "frozen_project").resolve()


def safe_target_id(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return value.strip("._-") or "prospective_001"


class ProspectiveGUI(tk.Tk):
    # Design tokens (display-only, Google-inspired light theme).
    # Layout constants for the expanded advanced-settings panel are here too,
    # because they only control how the same controls are shown.
    BG = "#F8FAFD"
    SURFACE = "#FFFFFF"
    SURFACE_SECONDARY = "#F1F3F4"
    PRIMARY = "#0B57D0"
    PRIMARY_HOVER = "#0842A0"
    PRIMARY_SOFT = "#E8F0FE"
    TEXT = "#202124"
    TEXT_SECONDARY = "#5F6368"
    BORDER = "#E0E3EB"
    BORDER_CONTROL = "#70757A"
    SUCCESS = "#137333"
    SUCCESS_SOFT = "#E6F4EA"
    WARNING = "#9A6700"
    WARNING_SOFT = "#FEF7E0"
    DANGER = "#B3261E"
    DANGER_SOFT = "#FCE8E6"
    FOCUS = "#0B57D0"
    PANEL_WIDTH = 332

    def __init__(self) -> None:
        super().__init__()
        self.title("Independent Prospective Scoring System")
        self.geometry("1440x900")
        self.minsize(1024, 720)
        self.configure(bg=self.BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._process: subprocess.Popen[str] | None = None
        self._last_output: Path | None = None
        self.python_path: Path | None = PYTHON.resolve() if PYTHON else self._discover_python()
        self._routes: list[dict] = []
        self._panel_expanded = False
        self._hover_row: str | None = None
        self._toast_after: str | None = None
        self._elapsed_after: str | None = None
        self._run_started: float | None = None
        self._build_style()
        self._build_ui()
        self._refresh_layout()
        self.after(150, self._poll_queue)
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, _event: object) -> None:
        # Only guard the window-wide relayout; Tk handles the per-widget
        # geometry after grid/pack manager re-entry.
        if getattr(self, "_relayout_after", None) is None:
            self._relayout_after = self.after(200, self._refresh_layout)

    def _refresh_layout(self) -> None:
        """Toggle the advanced-settings panel based on the measured width.

        The search call itself always reads the current variables, so this
        layout switch can never change a parameter value.
        """
        self._relayout_after = None
        width = self.winfo_width()
        if width > 1:
            if width >= 1120:
                self._set_panel(True)
            else:
                self._set_panel(False)

    def _set_panel(self, expanded: bool) -> None:
        """Expand or collapse the advanced-settings panel (display only)."""
        self._panel_expanded = expanded
        if expanded:
            self.outer.grid_columnconfigure(2, minsize=self.PANEL_WIDTH)
            self.panel.grid()
            self.advanced_toggle.configure(text="Hide advanced settings \u25B4")
        else:
            self.panel.grid_remove()
            self.outer.grid_columnconfigure(2, minsize=0)
            self.advanced_toggle.configure(text="Advanced settings \u25BE")

    @staticmethod
    def _discover_python() -> Path | None:
        candidates = []
        for env_name in ("CONDA_PREFIX", "AIZYNTH_CONDA_PREFIX"):
            value = os.environ.get(env_name)
            if value:
                candidates.append(Path(value) / "python.exe")
        candidates.extend([Path("python.exe"), Path("python")])
        for candidate in candidates:
            if candidate.name in {"python.exe", "python"} and (candidate.is_file() or str(candidate) in {"python.exe", "python"}):
                return candidate
        return None

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        # Font scale: Times New Roman ships with Windows, matching the requested
        # native equivalent of Roboto. Weight, spacing and position build the
        # hierarchy instead of oversized text.
        style.configure("App.TFrame", background=self.BG)
        style.configure("Body.TFrame", background=self.BG)
        style.configure("Surface.TFrame", background=self.SURFACE)
        style.configure("Soft.TFrame", background=self.SURFACE_SECONDARY)
        style.configure("H1.TLabel", background=self.BG, foreground=self.TEXT, font=("Times New Roman", 28, "bold"))
        style.configure("H2.TLabel", background=self.SURFACE, foreground=self.TEXT, font=("Times New Roman", 20, "bold"))
        style.configure("H3.TLabel", background=self.SURFACE, foreground=self.TEXT, font=("Times New Roman", 13, "bold"))
        style.configure("Body.TLabel", background=self.BG, foreground=self.TEXT_SECONDARY, font=("Times New Roman", 14))
        style.configure("Muted.TLabel", background=self.SURFACE, foreground=self.TEXT_SECONDARY, font=("Times New Roman", 12))
        style.configure("Field.TLabel", background=self.SURFACE, foreground=self.TEXT, font=("Times New Roman", 13))
        style.configure("Field.TLabel2", background=self.BG, foreground=self.TEXT, font=("Times New Roman", 13))
        style.configure("Hint.TLabel", background=self.SURFACE, foreground=self.TEXT_SECONDARY, font=("Times New Roman", 12))
        style.configure("Chip.TLabel", background=self.BG, foreground=self.TEXT_SECONDARY, font=("Times New Roman", 12))
        style.configure("ChipValue.TLabel", background=self.BG, foreground=self.TEXT, font=("Times New Roman", 12, "bold"))
        style.configure("Toast.TLabel", background="#202124", foreground="#FFFFFF", font=("Times New Roman", 11))
        style.configure("StatusTitle.TLabel", background=self.SURFACE, foreground=self.TEXT, font=("Times New Roman", 13, "bold"))
        style.configure("StatusBody.TLabel", background=self.SURFACE, foreground=self.TEXT_SECONDARY, font=("Times New Roman", 12))
        style.configure("StatusPercent.TLabel", background=self.SURFACE, foreground=self.PRIMARY, font=("Times New Roman", 15, "bold"))
        style.configure("EmptyTitle.TLabel", background=self.SURFACE, foreground=self.TEXT, font=("Times New Roman", 14, "bold"))
        style.configure("EmptyBody.TLabel", background=self.SURFACE, foreground=self.TEXT_SECONDARY, font=("Times New Roman", 12))
        style.configure("Treeview", background=self.SURFACE, fieldbackground=self.SURFACE, foreground=self.TEXT, rowheight=40, borderwidth=0, font=("Times New Roman", 12))
        style.configure("Treeview.Heading", background=self.SURFACE_SECONDARY, foreground=self.TEXT_SECONDARY, font=("Times New Roman", 12, "bold"), padding=(8, 9), borderwidth=0)
        style.map("Treeview.Heading", background=[("active", self.SURFACE_SECONDARY)])
        style.map("Treeview", background=[("selected", self.PRIMARY_SOFT)], foreground=[("selected", self.TEXT)])
        style.configure("Vertical.TScrollbar", background=self.SURFACE_SECONDARY, troughcolor=self.SURFACE, bordercolor=self.SURFACE, arrowcolor=self.TEXT_SECONDARY, width=12)
        style.configure("TCheckbutton", background=self.SURFACE, foreground=self.TEXT, font=("Times New Roman", 12))
        style.map("TCheckbutton", background=[("active", self.SURFACE)], foreground=[("active", self.TEXT)])
        style.configure("Horizontal.TProgressbar", troughcolor=self.SURFACE_SECONDARY, background=self.PRIMARY, bordercolor=self.SURFACE, lightcolor=self.PRIMARY, darkcolor=self.PRIMARY, thickness=6)
        style.configure("Spin.TSpinbox", arrowsize=0, fieldbackground=self.SURFACE, background=self.SURFACE, foreground=self.TEXT, bordercolor=self.BORDER, lightcolor=self.BORDER, darkcolor=self.BORDER, insertcolor=self.TEXT, padding=(9, 6))
        style.map("Spin.TSpinbox", fieldbackground=[("focus", self.SURFACE)], bordercolor=[("focus", self.FOCUS)])
        style.configure("Stepper.TButton", background=self.SURFACE, foreground=self.TEXT, borderwidth=0, padding=(7, 3), width=2, font=("Times New Roman", 12))
        style.map("Stepper.TButton", background=[("pressed", self.PRIMARY_SOFT), ("active", self.SURFACE_SECONDARY)], foreground=[("disabled", self.TEXT_SECONDARY)])
        style.configure("Policy.TCombobox", fieldbackground=self.SURFACE, background=self.SURFACE, foreground=self.TEXT, arrowcolor=self.TEXT_SECONDARY, bordercolor=self.BORDER, lightcolor=self.BORDER, darkcolor=self.BORDER, insertcolor=self.TEXT, padding=(9, 6))
        style.map("Policy.TCombobox", fieldbackground=[("readonly", self.SURFACE)], selectbackground=[("readonly", self.PRIMARY_SOFT)], selectforeground=[("readonly", self.TEXT)], bordercolor=[("focus", self.FOCUS)])
        style.configure("Panel.TFrame", background=self.SURFACE)
        style.configure("Group.TFrame", background=self.SURFACE)

    def _build_ui(self) -> None:
        # ---------------------------------------------------------------- root
        self.outer = ttk.Frame(self, style="App.TFrame")
        self.outer.pack(fill="both", expand=True)
        self.outer.columnconfigure(1, weight=1)
        self.outer.rowconfigure(0, weight=1)

        # -------------------------------------------------------------- header
        header = tk.Frame(self.outer, bg=self.SURFACE, height=64, highlightthickness=1, highlightbackground=self.BORDER)
        header.grid(row=0, column=0, columnspan=3, sticky="ew")
        header.pack_propagate(False)
        header_left = tk.Frame(header, bg=self.SURFACE)
        header_left.pack(side="left", padx=(24, 0))
        tk.Label(header_left, text="\u2687", bg=self.SURFACE, fg=self.PRIMARY, font=("Times New Roman", 18)).pack(side="left")
        tk.Label(header_left, text="  Independent Prospective Scoring System", bg=self.SURFACE, fg=self.TEXT, font=("Times New Roman", 15, "bold")).pack(side="left")
        header_right = tk.Frame(header, bg=self.SURFACE)
        header_right.pack(side="right", padx=(0, 24))
        self.advanced_toggle = tk.Button(header_right, text="Advanced settings \u25BE", command=self._toggle_panel, bg=self.SURFACE, activebackground=self.SURFACE_SECONDARY, fg=self.TEXT, activeforeground=self.TEXT, relief="flat", cursor="hand2", font=("Times New Roman", 12), padx=14, pady=9)
        self.advanced_toggle.pack(side="left", padx=(0, 8))
        self.open_button = tk.Button(header_right, text="Open last dashboard", command=self.open_last_dashboard, state="disabled", bg=self.SURFACE, activebackground=self.SURFACE_SECONDARY, fg=self.TEXT_SECONDARY, activeforeground=self.TEXT_SECONDARY, disabledforeground="#B9BEC6", relief="flat", cursor="hand2", font=("Times New Roman", 12), padx=14, pady=9)
        self.open_button.pack(side="left")

        # ------------------------------------------------------------- content
        content = tk.Frame(self.outer, bg=self.BG)
        content.grid(row=1, column=1, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        canvas = tk.Canvas(content, bg=self.BG, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        vbar = ttk.Scrollbar(content, orient="vertical", command=canvas.yview, style="Vertical.TScrollbar")
        vbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=vbar.set)
        body = ttk.Frame(canvas, style="Body.TFrame")
        self._body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(self._body_window, width=e.width))

        hero = ttk.Frame(body, style="Body.TFrame", padding=(48, 40, 48, 0))
        hero.grid(row=0, column=0, sticky="ew")
        hero.columnconfigure(0, weight=1)
        ttk.Label(hero, text="Explore a Target Molecule", style="H1.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(hero, text="Discover retrosynthetic routes and evaluate synthesis difficulty.", style="Body.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))

        # ------------------------------------------------------ search card
        search_card = tk.Frame(body, bg=self.SURFACE, highlightthickness=1, highlightbackground=self.BORDER)
        search_card.grid(row=1, column=0, sticky="ew", padx=48, pady=(24, 0))
        search_card.columnconfigure(0, weight=1)
        ttk.Label(search_card, text="Target molecule SMILES", style="Field.TLabel").grid(row=0, column=0, sticky="w", padx=24, pady=(20, 0))
        self.smiles_var = tk.StringVar(value="")
        self.smiles_entry = tk.Entry(search_card, textvariable=self.smiles_var, bg=self.SURFACE, fg=self.TEXT, insertbackground=self.TEXT, relief="flat", font=("Times New Roman", 14), highlightthickness=2, highlightbackground=self.BORDER_CONTROL, highlightcolor=self.FOCUS)
        self.smiles_entry.grid(row=1, column=0, sticky="ew", ipady=10, padx=24, pady=(8, 0))
        self.smiles_entry.bind("<Return>", lambda _event: self.run_search())
        self._set_placeholder("Enter or paste a target molecule SMILES")
        self.input_error = tk.Label(search_card, text="", bg=self.SURFACE, fg=self.DANGER, font=("Times New Roman", 12), anchor="w")
        self.input_error.grid(row=2, column=0, sticky="ew", padx=24)
        ttk.Label(search_card, text="SMILES is kept exactly as typed - no characters are altered before the search.", style="Hint.TLabel").grid(row=3, column=0, sticky="w", padx=24, pady=(0, 16))

        id_frame = tk.Frame(search_card, bg=self.SURFACE)
        id_frame.grid(row=4, column=0, sticky="ew", padx=24)
        id_frame.columnconfigure(1, weight=1)
        ttk.Label(id_frame, text="Target ID", style="Field.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 16))
        self.target_id_var = tk.StringVar(value="my_compound_003")
        self.target_id_entry = tk.Entry(id_frame, textvariable=self.target_id_var, bg=self.SURFACE, fg=self.TEXT, insertbackground=self.TEXT, relief="flat", font=("Times New Roman", 12), highlightthickness=1, highlightbackground=self.BORDER, highlightcolor=self.FOCUS)
        self.target_id_entry.grid(row=0, column=1, sticky="ew", ipady=7)
        self.copy_button = tk.Button(id_frame, text="Copy", command=self._copy_target_id, bg=self.SURFACE, activebackground=self.SURFACE_SECONDARY, fg=self.TEXT, activeforeground=self.TEXT, relief="flat", cursor="hand2", font=("Times New Roman", 12), padx=12, pady=6)
        self.copy_button.grid(row=0, column=2, padx=(12, 0))

        button_row = tk.Frame(search_card, bg=self.SURFACE)
        button_row.grid(row=5, column=0, sticky="w", padx=24, pady=(20, 24))
        self.run_button = tk.Button(button_row, text="\u2315  Run Search", command=self.run_search, bg=self.PRIMARY, activebackground=self.PRIMARY_HOVER, fg="white", activeforeground="white", disabledforeground="#E4E8EE", relief="flat", cursor="hand2", font=("Times New Roman", 13, "bold"), padx=28, pady=12)
        self.run_button.pack(side="left")
        self.run_button.bind("<Enter>", lambda _e: self.run_button.configure(bg=self.PRIMARY_HOVER))
        self.run_button.bind("<Leave>", lambda _e: self.run_button.configure(bg=self.PRIMARY))

        chips = ttk.Frame(search_card, style="Surface.TFrame")
        chips.grid(row=6, column=0, sticky="w", padx=24, pady=(0, 20))
        self.iteration_var = tk.StringVar(value="100")
        self.time_var = tk.StringVar(value="120")
        self.transforms_var = tk.StringVar(value="6")
        self.max_routes_var = tk.StringVar(value="10")
        self.min_routes_var = tk.StringVar(value="3")
        chips_cols = [
            ("MCTS", self.iteration_var, ""),
            ("Time", self.time_var, "s"),
            ("Max steps", self.transforms_var, ""),
        ]
        for col, (name, var, unit) in enumerate(chips_cols):
            chip = tk.Frame(chips, bg=self.BG, highlightthickness=1, highlightbackground=self.BORDER)
            chip.grid(row=0, column=col, sticky="w", padx=(0, 8), ipadx=10, ipady=6)
            self._chip_label = tk.Label(chip, text=f"{name} ", bg=self.BG, fg=self.TEXT_SECONDARY, font=("Times New Roman", 12))
            self._chip_label.pack(side="left")
            self._chip_value = tk.Label(chip, textvariable=var, bg=self.BG, fg=self.TEXT, font=("Times New Roman", 12, "bold"))
            self._chip_value.pack(side="left")
            if unit:
                tk.Label(chip, text=f" {unit}", bg=self.BG, fg=self.TEXT_SECONDARY, font=("Times New Roman", 12)).pack(side="left")

        # ------------------------------------------------------ status card
        status_card = tk.Frame(body, bg=self.SURFACE, highlightthickness=1, highlightbackground=self.BORDER)
        status_card.grid(row=2, column=0, sticky="ew", padx=48, pady=(24, 0))
        status_card.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="")
        self.status_dot = tk.Canvas(status_card, width=30, height=30, bg=self.SURFACE, highlightthickness=0)
        self.status_dot.grid(row=0, column=0, rowspan=2, padx=(24, 12), pady=18, sticky="w")
        self._status_dot_item = self.status_dot.create_oval(5, 5, 25, 25, fill=self.TEXT_SECONDARY, outline="")
        self.status_title = tk.Label(status_card, text="Ready to search", bg=self.SURFACE, fg=self.TEXT, font=("Times New Roman", 13, "bold"), anchor="w")
        self.status_title.grid(row=0, column=1, sticky="ew", pady=(18, 2), padx=(0, 24))
        self.status_body = tk.Label(status_card, text="Enter a target SMILES to explore possible synthesis routes.", bg=self.SURFACE, fg=self.TEXT_SECONDARY, font=("Times New Roman", 12), anchor="w", justify="left")
        self.status_body.grid(row=1, column=1, sticky="ew", pady=(0, 18), padx=(0, 24))
        self.percent_var = tk.StringVar(value="")
        self.percent_label = tk.Label(status_card, textvariable=self.percent_var, bg=self.SURFACE, fg=self.PRIMARY, font=("Times New Roman", 15, "bold"))
        self.percent_label.grid(row=2, column=1, sticky="e", padx=(0, 24), pady=(0, 12))
        self.progress = ttk.Progressbar(status_card, mode="indeterminate", maximum=100.0, style="Horizontal.TProgressbar")
        self.progress.grid(row=2, column=0, sticky="ew", padx=(24, 12), pady=(0, 12))

        # ------------------------------------------------------ results card
        results_card = tk.Frame(body, bg=self.SURFACE, highlightthickness=1, highlightbackground=self.BORDER)
        results_card.grid(row=3, column=0, sticky="nsew", padx=48, pady=(24, 0))
        results_card.columnconfigure(0, weight=1)
        results_card.rowconfigure(1, weight=1)
        ttk.Label(results_card, text="Ranked routes", style="H2.TLabel").grid(row=0, column=0, sticky="w", padx=24, pady=(20, 12))
        table_frame = tk.Frame(results_card, bg=self.SURFACE)
        table_frame.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 20))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.route_tree = ttk.Treeview(table_frame, columns=("rank", "route", "solved", "steps", "bottleneck", "mean", "confidence"), show="headings", height=7)
        widths = {"rank": 70, "route": 190, "solved": 90, "steps": 70, "bottleneck": 105, "mean": 115, "confidence": 105}
        headings = {"rank": "New rank", "route": "Route", "solved": "Solved", "steps": "Steps", "bottleneck": "Bottleneck", "mean": "Mean difficulty", "confidence": "Confidence"}
        for column in self.route_tree["columns"]:
            self.route_tree.heading(column, text=headings[column])
            self.route_tree.column(column, width=widths[column], anchor="center" if column != "route" else "w")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.route_tree.yview, style="Vertical.TScrollbar")
        self.route_tree.configure(yscrollcommand=scrollbar.set)
        self.route_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.route_tree.bind("<<TreeviewSelect>>", self._show_route_detail)
        self.route_tree.tag_configure("hover", background=self.SURFACE_SECONDARY)
        self.route_tree.tag_configure("even", background="#FBFCFE")
        self.route_tree.tag_configure("odd", background=self.SURFACE)
        self.route_tree.bind("<Motion>", self._on_tree_hover)
        self.route_tree.bind("<Leave>", self._on_tree_leave)
        self.empty_label = tk.Label(table_frame, text="\u2687  No routes yet", bg=self.SURFACE, fg=self.TEXT, font=("Times New Roman", 14, "bold"), bd=0, highlightthickness=0)
        self.empty_hint = tk.Label(table_frame, text="Run a search to explore and compare retrosynthetic routes.", bg=self.SURFACE, fg=self.TEXT_SECONDARY, font=("Times New Roman", 12), bd=0, highlightthickness=0)
        self._on_routes_change()

        # ------------------------------------------------------- detail card
        details_card = tk.Frame(body, bg=self.SURFACE, highlightthickness=1, highlightbackground=self.BORDER)
        details_card.grid(row=4, column=0, sticky="ew", padx=48, pady=(24, 0))
        details_card.columnconfigure(0, weight=1)
        details_card.rowconfigure(1, weight=1)
        ttk.Label(details_card, text="Selected route details", style="H2.TLabel").grid(row=0, column=0, sticky="w", padx=24, pady=(20, 12))
        self.detail = tk.Text(details_card, height=9, bg=self.SURFACE, fg=self.TEXT, insertbackground=self.TEXT, relief="flat", wrap="word", font=("Times New Roman", 11), padx=24, pady=12, highlightthickness=1, highlightbackground=self.BORDER)
        self.detail.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 20))
        self.detail.configure(state="disabled")
        self._set_detail("Select a route above to inspect its steps, scores and reaction SMILES.")

        footer = ttk.Frame(body, style="Body.TFrame", padding=(48, 24, 48, 32))
        footer.grid(row=5, column=0, sticky="ew")
        ttk.Label(footer, text="Independent Prospective Scoring System \u00B7 The original project configuration is never overwritten by this interface.", style="Chip.TLabel").grid(row=0, column=0, sticky="w")

        # ------------------------------------------------- advanced panel
        self.panel = tk.Frame(self.outer, bg=self.SURFACE, highlightthickness=1, highlightbackground=self.BORDER)
        self.panel.grid(row=1, column=2, sticky="nsew")
        panel_body = tk.Frame(self.panel, bg=self.SURFACE)
        panel_body.pack(fill="both", expand=True, padx=20, pady=16)
        ttk.Label(panel_body, text="Advanced search settings", style="H3.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 16))

        group1 = ttk.Frame(panel_body, style="Group.TFrame")
        group1.grid(row=1, column=0, sticky="ew", pady=(0, 20))
        group1.columnconfigure(0, weight=1)
        ttk.Label(group1, text="SEARCH LIMITS", style="Field.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 12))
        self._spin_field(group1, 1, "Iteration limit (MCTS)", self.iteration_var, 1, 100000)
        self._spin_field(group1, 3, "Time limit (seconds)", self.time_var, 1, 86400)
        self._spin_field(group1, 5, "Max reaction steps", self.transforms_var, 1, 100)

        group2 = ttk.Frame(panel_body, style="Group.TFrame")
        group2.grid(row=2, column=0, sticky="ew", pady=(0, 20))
        group2.columnconfigure(0, weight=1)
        ttk.Label(group2, text="ROUTE DISCOVERY", style="Field.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 12))
        self._spin_field(group2, 1, "Max routes shown", self.max_routes_var, 1, 1000)
        self._spin_field(group2, 3, "Min routes requested", self.min_routes_var, 0, 1000)
        ttk.Label(group2, text="Expansion policy", style="Field.TLabel").grid(row=5, column=0, sticky="w", pady=(0, 6))
        policy = ttk.Combobox(group2, style="Policy.TCombobox", state="readonly", values=("uspto",), width=22)
        policy.set("uspto")
        policy.grid(row=6, column=0, sticky="ew", ipady=2)

        group3 = ttk.Frame(panel_body, style="Group.TFrame")
        group3.grid(row=3, column=0, sticky="ew")
        group3.columnconfigure(0, weight=1)
        ttk.Label(group3, text="OUTPUT & RESOURCES", style="Field.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 12))
        ttk.Label(group3, text="Building-block stock", style="Field.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Label(group3, text="zinc", style="Field.TLabel").grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Label(group3, text="Fixed by the current search tool", style="Hint.TLabel").grid(row=3, column=0, sticky="w", pady=(2, 12))
        self.auto_open_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(group3, text="Open dashboard after PASS", variable=self.auto_open_var).grid(row=4, column=0, sticky="w", pady=(4, 0))

        # ----------------------------------------------------------- toast
        self.toast_frame = tk.Frame(self, bg="#202124")
        self.toast_label = tk.Label(self.toast_frame, text="", bg="#202124", fg="white", font=("Times New Roman", 11), padx=16, pady=8)
        self.toast_label.pack()

    def _spin_field(self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar, low: int, high: int) -> None:
        ttk.Label(parent, text=label, style="Field.TLabel").grid(row=row, column=0, sticky="w", pady=(0, 6))
        spin = ttk.Spinbox(parent, from_=low, to=high, textvariable=variable, width=20, style="Spin.TSpinbox")
        spin.grid(row=row + 1, column=0, sticky="ew", ipady=4, pady=(0, 12))
        controls = ttk.Frame(parent, style="Group.TFrame")
        controls.grid(row=row + 1, column=0, sticky="e", padx=4, pady=(0, 12))
        ttk.Button(controls, text="\u2212", style="Stepper.TButton", width=2, command=lambda: self._step(variable, low, high, -1)).pack(side="left", padx=(0, 1))
        ttk.Button(controls, text="\u002B", style="Stepper.TButton", width=2, command=lambda: self._step(variable, low, high, 1)).pack(side="left")

    @staticmethod
    def _step(variable: tk.StringVar, low: int, high: int, delta: int) -> None:
        """Display-only nudging used by the custom stepper buttons."""
        try:
            value = int(variable.get())
        except ValueError:
            return
        value = max(low, min(high, value + delta))
        variable.set(str(value))

    def _toggle_panel(self) -> None:
        """Toggle the advanced settings panel (display only)."""
        self._set_panel(not self._panel_expanded)

    def _set_placeholder(self, text: str) -> None:
        """Gray placeholder for the SMILES entry; typing or focus removes it."""
        self._smiles_placeholder = text
        self._smiles_placeholder_active = True
        self.smiles_entry.configure(fg=self.TEXT_SECONDARY)
        self.smiles_entry.insert(0, text)
        self.smiles_entry.bind("<FocusIn>", self._on_smiles_focus_in, add="+")
        self.smiles_entry.bind("<FocusOut>", self._on_smiles_focus_out, add="+")

    def _on_smiles_focus_in(self, _event: object) -> None:
        if self._smiles_placeholder_active:
            self._smiles_placeholder_active = False
            self.smiles_entry.delete(0, "end")
            self.smiles_entry.configure(fg=self.TEXT)

    def _on_smiles_focus_out(self, _event: object) -> None:
        if not self.smiles_entry.get().strip():
            self._smiles_placeholder_active = True
            self.smiles_entry.configure(fg=self.TEXT_SECONDARY)
            self.smiles_entry.insert(0, self._smiles_placeholder)

    def _copy_target_id(self) -> None:
        """Copy the Target ID text to the clipboard (display convenience only)."""
        value = self.target_id_var.get().strip()
        if value:
            self.clipboard_clear()
            self.clipboard_append(value)
            self._show_toast("Target ID copied")

    def _show_toast(self, text: str, duration_ms: int = 2200) -> None:
        """Brief toast for completed user actions (never for fake progress)."""
        if self._toast_after is not None:
            self.after_cancel(self._toast_after)
        self.toast_label.configure(text=text)
        self.toast_frame.place(relx=0.5, rely=0.92, anchor="s")
        self._toast_after = self.after(duration_ms, self._hide_toast)

    def _hide_toast(self) -> None:
        self._toast_after = None
        self.toast_frame.place_forget()

    def _set_status(self, state: str, title: str, body: str = "", percentage: float | None = None, stage: str | None = None) -> None:
        """Update the status component (colors + text)."""
        palette = {
            "idle": (self.TEXT_SECONDARY, self.SURFACE_SECONDARY),
            "invalid": (self.DANGER, self.DANGER_SOFT),
            "running": (self.PRIMARY, self.PRIMARY_SOFT),
            "success": (self.SUCCESS, self.SUCCESS_SOFT),
            "empty": (self.WARNING, self.WARNING_SOFT),
            "error": (self.DANGER, self.DANGER_SOFT),
        }
        fill, bg = palette.get(state, (self.TEXT_SECONDARY, self.SURFACE_SECONDARY))
        self.status_dot.itemconfigure(self._status_dot_item, fill=fill)
        self.status_dot.configure(bg=bg)
        self.status_title.configure(text=title, bg=bg)
        self.status_body.configure(text=body, bg=bg)
        if percentage is not None:
            self.progress.configure(mode="determinate")
            self.progress["value"] = max(0.0, min(100.0, percentage))
            self.percent_var.set(f"{percentage:.0f}%")
        else:
            self.progress.stop()
            self.progress.configure(mode="indeterminate")
            self.percent_var.set("")
        if stage:
            self.status_title.configure(text=f"{title} \u00B7 {stage}")

    def _on_routes_change(self) -> None:
        """Show an empty-state overlay while the route table has no rows."""
        has_routes = bool(self.route_tree.get_children())
        if has_routes:
            self.empty_label.place_forget()
            self.empty_hint.place_forget()
        else:
            self.empty_label.place(relx=0.5, rely=0.42, anchor="center")
            self.empty_hint.place(relx=0.5, rely=0.62, anchor="center")

    def _on_tree_hover(self, event: object) -> None:
        """Subtle row highlight while the pointer moves over the table."""
        row = self.route_tree.identify_row(event.y)
        current = self._hover_row
        if row != current:
            if current:
                self.route_tree.item(current, tags=())
            if row:
                self.route_tree.item(row, tags=("hover",))
            self._hover_row = row

    def _on_tree_leave(self, _event: object) -> None:
        if self._hover_row:
            self.route_tree.item(self._hover_row, tags=())
        self._hover_row = None

    def _set_detail(self, text: str) -> None:
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def _numeric_inputs(self) -> dict[str, int | float]:
        try:
            values: dict[str, int | float] = {
                "iteration_limit": int(self.iteration_var.get()),
                "time_limit": float(self.time_var.get()),
                "max_transforms": int(self.transforms_var.get()),
                "max_routes": int(self.max_routes_var.get()),
                "min_routes": int(self.min_routes_var.get()),
            }
        except ValueError as exc:
            raise ValueError("Search parameters must be numeric.") from exc
        if values["iteration_limit"] <= 0 or values["time_limit"] <= 0 or values["max_transforms"] <= 0:
            raise ValueError("Iteration limit, time limit, and max reaction steps must be positive.")
        if values["min_routes"] < 0 or values["max_routes"] <= 0 or values["min_routes"] > values["max_routes"]:
            raise ValueError("Min routes must be between 0 and Max routes.")
        return values

    def run_search(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        smiles = self.smiles_var.get().strip()
        if getattr(self, "_smiles_placeholder_active", False):
            smiles = ""
        target_id = safe_target_id(self.target_id_var.get())
        self.input_error.configure(text="")
        if not smiles:
            self.input_error.configure(text="Please enter a target molecule SMILES.")
            self._set_status("invalid", "SMILES is required", "Enter or paste a target molecule SMILES to continue.")
            self.smiles_entry.focus_set()
            return
        if self.python_path is None or (self.python_path.name not in {"python.exe", "python"} and not self.python_path.is_file()) or not SCORER.is_file() or not PROJECT_DIR.is_dir():
            self.input_error.configure(text="The configured AiZynthFinder environment, scorer, or frozen project directory is missing.")
            self._set_status("error", "Environment unavailable", "The scorer or frozen project directory could not be found.")
            return
        try:
            params = self._numeric_inputs()
        except ValueError as exc:
            self.input_error.configure(text=str(exc))
            self._set_status("invalid", "Invalid search settings", str(exc))
            return
        self.target_id_var.set(target_id)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = DEFAULT_OUTPUT_ROOT / f"{target_id}_{timestamp}"
        output_dir.mkdir(parents=True, exist_ok=True)
        command = [
            str(self.python_path), "-s", str(SCORER),
            "--project-dir", str(PROJECT_DIR),
            "--smiles", smiles,
            "--target-id", target_id,
            "--output-dir", str(output_dir),
            "--iteration-limit", str(params["iteration_limit"]),
            "--time-limit", str(params["time_limit"]),
            "--max-transforms", str(params["max_transforms"]),
            "--max-routes", str(params["max_routes"]),
            "--min-routes", str(params["min_routes"]),
            "--progress",
        ]
        self._last_output = output_dir
        self._set_detail("Running prospective search...\n\nThe frozen Stage 1-11 project remains read-only.\n")
        self._run_started = datetime.now().timestamp()
        self._tick_elapsed()
        self._set_status("running", "Search running", f"Exploring retrosynthetic routes for {target_id}...", percentage=0.0)
        self.run_button.configure(state="disabled", text="\u2315  Searching...")
        self.open_button.configure(state="disabled")
        thread = threading.Thread(target=self._run_worker, args=(command, output_dir), daemon=True)
        thread.start()

    def _tick_elapsed(self) -> None:
        """Refresh the elapsed-time hint while the search runs (text only)."""
        if self._process is None or self._process.poll() is not None:
            self._elapsed_after = None
            return
        if self._run_started is not None:
            elapsed = int(datetime.now().timestamp() - self._run_started)
            self.status_title.configure(text=f"Search running \u00B7 {elapsed}s")
        self._elapsed_after = self.after(1000, self._tick_elapsed)

    def _handle_progress(self, payload: str) -> None:
        try:
            event = json.loads(payload)
            percent = float(event["percent"])
        except Exception:
            # A malformed progress line must never break the run display.
            return
        text = str(event.get("text", ""))
        stage = str(event.get("stage", ""))
        eta = event.get("eta_seconds")
        percent = max(0.0, min(100.0, percent))
        self.progress.configure(mode="determinate")
        self.progress["value"] = percent
        self.percent_var.set(f"{percent:.0f}%")
        self._set_status("running", "Search running", text or "Working...", percentage=percent, stage=stage or None)

    def _handle_finished(self, payload: dict) -> None:
        output_dir = Path(payload["output_dir"])
        return_code = int(payload["return_code"])
        manifest_path = output_dir / "prospective_manifest.json"
        blocker_path = output_dir / "prospective_blocker.json"
        if self._elapsed_after is not None:
            self.after_cancel(self._elapsed_after)
            self._elapsed_after = None
        if return_code != 0 or not manifest_path.is_file():
            error = "Prospective run was BLOCKED."
            if blocker_path.is_file():
                try:
                    blocker = json.loads(blocker_path.read_text(encoding="utf-8"))
                    error = f"BLOCKED: {blocker.get('error', 'see prospective_blocker.json')}"
                except Exception:
                    pass
            self._finish_ui(False, error + f"\nOutput: {output_dir}")
            return
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            routes_payload = json.loads((output_dir / "scored_routes.json").read_text(encoding="utf-8"))
            target_id = str(manifest.get("target_id", self.target_id_var.get()))
            self._routes = list(routes_payload.get("targets", {}).get(target_id, []))
            self._render_routes()
            if self._routes:
                self._finish_ui(True, f"PASS - {len(self._routes)} routes scored\nOutput: {output_dir}\nDashboard: {output_dir / 'prospective_dashboard.html'}")
            else:
                self._finish_ui(True, "The search completed, but no routes were returned.\nSee the search log and prospective_blocker.json for details.")
            if self.auto_open_var.get():
                self.open_last_dashboard()
        except Exception as exc:
            self._finish_ui(False, f"Run completed but the result could not be displayed: {type(exc).__name__}: {exc}")

    def _finish_ui(self, success: bool, message: str) -> None:
        self.progress.stop()
        self.run_button.configure(state="normal", text="\u2315  Run Search")
        self.open_button.configure(state="normal" if self._last_output and (self._last_output / "prospective_dashboard.html").is_file() else "disabled")
        if success:
            if self._routes:
                self._set_status("success", "Search completed", f"{len(self._routes)} routes found", percentage=100.0)
            else:
                self._set_status("empty", "Search completed - no routes", "No retrosynthetic routes were returned. Check the search log for details.", percentage=None)
            self.percent_var.set("")
            self._set_detail(message)
        else:
            self._set_status("error", "Search failed", message, percentage=None)
            self.percent_var.set("")
            self._set_detail(message)

    def _run_worker(self, command: list[str], output_dir: Path) -> None:
        try:
            process = subprocess.Popen(command, cwd=str(TOOL_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            self._process = process
            lines: list[str] = []
            assert process.stdout is not None
            for line in process.stdout:
                stripped = line.rstrip()
                if stripped.startswith(PROGRESS_PREFIX):
                    self._queue.put(("progress", stripped[len(PROGRESS_PREFIX):]))
                    continue
                lines.append(stripped)
            return_code = process.wait()
            self._queue.put(("finished", {"return_code": return_code, "output_dir": output_dir, "log": "\n".join(lines)}))
        except Exception as exc:
            self._queue.put(("error", f"{type(exc).__name__}: {exc}"))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "error":
                    self._finish_ui(False, str(payload))
                elif kind == "progress":
                    self._handle_progress(str(payload))
                elif kind == "finished":
                    self._handle_finished(payload)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        self.after(150, self._poll_queue)

    def _render_routes(self) -> None:
        for item in self.route_tree.get_children():
            self.route_tree.delete(item)
        for index, route in enumerate(self._routes):
            values = (
                route.get("new_rank", index + 1),
                route.get("route_id", ""),
                "Yes" if route.get("solved") else "No",
                route.get("number_of_reactions", 0),
                self._fmt(route.get("difficulty_bottleneck")),
                self._fmt(route.get("difficulty_mean")),
                route.get("route_confidence", "N/A"),
            )
            tags = ("even",) if index % 2 == 0 else ("odd",)
            self.route_tree.insert("", "end", iid=str(index), values=values, tags=tags)
        if self._routes:
            first = self.route_tree.get_children()[0]
            self.route_tree.selection_set(first)
            self.route_tree.focus(first)
            self._show_route_detail()
        else:
            self._set_detail("AiZynthFinder returned no route rows. Check the search log and prospective_blocker.json if present.")
        self._on_routes_change()

    @staticmethod
    def _fmt(value: object) -> str:
        if value is None:
            return "-"
        try:
            return f"{float(value):.3f}"
        except Exception:
            return str(value)

    def _show_route_detail(self, _event: object | None = None) -> None:
        selected = self.route_tree.selection()
        if not selected:
            return
        route = self._routes[int(selected[0])]
        lines = [
            f"Route: {route.get('route_id')}",
            f"New rank: {route.get('new_rank')}    Original rank: {route.get('original_rank')}    Rank change: {route.get('rank_change')}",
            f"Solved: {route.get('solved')}    Reactions: {route.get('number_of_reactions')}",
            f"Bottleneck difficulty: {self._fmt(route.get('difficulty_bottleneck'))}    Mean: {self._fmt(route.get('difficulty_mean'))}",
            f"Route uncertainty: {self._fmt(route.get('route_uncertainty'))}    Confidence: {route.get('route_confidence')}",
            "",
            str(route.get("route_explanation", "")),
            "",
        ]
        for step in route.get("steps", []):
            lines.extend([
                f"Step {step.get('step_id')} · difficulty {self._fmt(step.get('reaction_difficulty'))} · confidence {step.get('confidence')}",
                f"  d_feas={self._fmt(step.get('d_feas'))}  d_prec={self._fmt(step.get('d_prec'))}  d_sc={self._fmt(step.get('d_sc'))}  uncertainty={self._fmt(step.get('uncertainty'))}",
                f"  reaction: {step.get('reaction_smiles')}",
                f"  precursor(s): {step.get('precursor_smiles')}",
                f"  product: {step.get('product_smiles')}",
                "",
            ])
        self._set_detail("\n".join(lines))

    def open_last_dashboard(self) -> None:
        if self._last_output is None:
            return
        dashboard = self._last_output / "prospective_dashboard.html"
        if not dashboard.is_file():
            return
        ok = False
        if sys.platform == "win32":
            # Measured on this machine (and standard on Windows): os.startfile
            # reliably opens the HTML in the default browser, while a file://
            # URI handed to webbrowser/os.startfile can silently fail when the
            # path contains percent-encoded non-ASCII characters (returns True
            # but no browser opens). os.startfile expects a plain path.
            try:
                os.startfile(str(dashboard.resolve()))
                ok = True
            except OSError:
                ok = False
        if not ok:
            try:
                ok = bool(webbrowser.open(dashboard.resolve().as_uri()))
            except Exception:
                ok = False
        if not ok:
            messagebox.showwarning(
                "Dashboard not opened",
                "The dashboard could not be opened automatically.\n"
                "You can open it manually from:\n"
                + str(dashboard.resolve()),
            )

    def _on_close(self) -> None:
        if self._process is not None and self._process.poll() is None:
            if not messagebox.askyesno("Search running", "A prospective search is still running. Close the interface anyway?"):
                return
        self.destroy()


if __name__ == "__main__":
    ProspectiveGUI().mainloop()
