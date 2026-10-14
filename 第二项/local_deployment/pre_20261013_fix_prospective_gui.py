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
    BG = "#101217"
    SIDEBAR = "#252631"
    SURFACE = "#191c23"
    INPUT = "#0d1016"
    FG = "#f2f4f7"
    MUTED = "#a9b1bb"
    LINE = "#343b45"
    ACCENT = "#ff515a"
    ACCENT_HOVER = "#ff7077"
    BLUE = "#87b5ff"

    def __init__(self) -> None:
        super().__init__()
        self.title("AiZynthFinder - Independent Prospective Scoring")
        self.geometry("1360x860")
        self.minsize(1080, 700)
        self.configure(bg=self.BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._process: subprocess.Popen[str] | None = None
        self._last_output: Path | None = None
        self.python_path: Path | None = PYTHON.resolve() if PYTHON else self._discover_python()
        self._routes: list[dict] = []
        self._build_style()
        self._build_ui()
        self.after(150, self._poll_queue)

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
        style.configure("App.TFrame", background=self.BG)
        style.configure("Sidebar.TFrame", background=self.SIDEBAR)
        style.configure("Title.TLabel", background=self.BG, foreground=self.FG, font=("Segoe UI", 25, "bold"))
        style.configure("Subtitle.TLabel", background=self.BG, foreground=self.MUTED, font=("Segoe UI", 11))
        style.configure("Section.TLabel", background=self.BG, foreground=self.FG, font=("Segoe UI", 13, "bold"))
        style.configure("Field.TLabel", background=self.SIDEBAR, foreground=self.FG, font=("Segoe UI", 10, "bold"))
        style.configure("Hint.TLabel", background=self.SIDEBAR, foreground=self.MUTED, font=("Segoe UI", 9))
        style.configure("Status.TLabel", background=self.SURFACE, foreground=self.MUTED, font=("Segoe UI", 10))
        style.configure("Treeview", background=self.SURFACE, fieldbackground=self.SURFACE, foreground=self.FG, rowheight=30, borderwidth=0)
        style.configure("Treeview.Heading", background=self.SIDEBAR, foreground=self.FG, font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", "#35496c")], foreground=[("selected", self.FG)])
        style.configure("TNotebook", background=self.BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=self.SIDEBAR, foreground=self.FG, padding=(12, 7))
        style.configure("Horizontal.TProgressbar", troughcolor=self.SURFACE, background=self.ACCENT, bordercolor=self.SURFACE, lightcolor=self.ACCENT, darkcolor=self.ACCENT)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, style="App.TFrame")
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(outer, style="Sidebar.TFrame", padding=(24, 28, 20, 24))
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.columnconfigure(0, weight=1)

        ttk.Label(sidebar, text="SEARCH SETTINGS", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 22))
        self.iteration_var = tk.StringVar(value="100")
        self.time_var = tk.StringVar(value="120")
        self.transforms_var = tk.StringVar(value="6")
        self.max_routes_var = tk.StringVar(value="10")
        self.min_routes_var = tk.StringVar(value="3")
        self._spin_field(sidebar, 1, "Iteration limit (MCTS)", self.iteration_var, 1, 100000)
        self._spin_field(sidebar, 3, "Time limit (seconds)", self.time_var, 1, 86400)
        self._spin_field(sidebar, 5, "Max reaction steps", self.transforms_var, 1, 100)
        self._spin_field(sidebar, 7, "Max routes shown", self.max_routes_var, 1, 1000)
        self._spin_field(sidebar, 9, "Min routes requested", self.min_routes_var, 0, 1000)

        ttk.Label(sidebar, text="EXPANSION POLICY", style="Field.TLabel").grid(row=11, column=0, sticky="w", pady=(26, 6))
        policy = ttk.Entry(sidebar, state="readonly", width=25)
        policy.configure(font=("Segoe UI", 10))
        policy.grid(row=12, column=0, sticky="ew", ipady=7)
        policy.configure(state="normal")
        policy.insert(0, "uspto")
        policy.configure(state="readonly")
        ttk.Label(sidebar, text="Stock: zinc (fixed by the existing tool)", style="Hint.TLabel").grid(row=13, column=0, sticky="w", pady=(7, 0))

        ttk.Label(sidebar, text="OUTPUT", style="Field.TLabel").grid(row=14, column=0, sticky="w", pady=(26, 6))
        self.auto_open_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(sidebar, text="Open dashboard after PASS", variable=self.auto_open_var).grid(row=15, column=0, sticky="w")
        ttk.Label(sidebar, text="The original project config is never overwritten.", style="Hint.TLabel", wraplength=245).grid(row=16, column=0, sticky="w", pady=(8, 0))

        main = ttk.Frame(outer, style="App.TFrame", padding=(52, 38, 46, 30))
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(6, weight=1)

        ttk.Label(main, text="AiZynthFinder - Independent Prospective Scoring", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(main, text="Search a new compound, score each route on demand, and inspect the same difficulty report with key-line diagrams.", style="Subtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(7, 25))

        input_frame = ttk.Frame(main, style="App.TFrame")
        input_frame.grid(row=2, column=0, sticky="ew")
        input_frame.columnconfigure(0, weight=1)
        ttk.Label(input_frame, text="Target molecule SMILES", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.smiles_var = tk.StringVar(value="")
        self.smiles_entry = tk.Entry(input_frame, textvariable=self.smiles_var, bg=self.INPUT, fg=self.FG, insertbackground=self.FG, relief="flat", font=("Consolas", 12), highlightthickness=1, highlightbackground=self.LINE, highlightcolor=self.BLUE)
        self.smiles_entry.grid(row=1, column=0, sticky="ew", ipady=12, pady=(8, 10))
        self.smiles_entry.bind("<Return>", lambda _event: self.run_search())

        id_frame = ttk.Frame(input_frame, style="App.TFrame")
        id_frame.grid(row=2, column=0, sticky="ew")
        id_frame.columnconfigure(1, weight=1)
        ttk.Label(id_frame, text="Target ID", style="Subtitle.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.target_id_var = tk.StringVar(value="my_compound_003")
        self.target_id_entry = tk.Entry(id_frame, textvariable=self.target_id_var, bg=self.INPUT, fg=self.FG, insertbackground=self.FG, relief="flat", font=("Segoe UI", 11), highlightthickness=1, highlightbackground=self.LINE, highlightcolor=self.BLUE)
        self.target_id_entry.grid(row=0, column=1, sticky="ew", ipady=7)
        self.run_button = tk.Button(input_frame, text="RUN SEARCH AND SHOW ROUTES", command=self.run_search, bg=self.ACCENT, activebackground=self.ACCENT_HOVER, fg="white", activeforeground="white", relief="flat", cursor="hand2", font=("Segoe UI", 10, "bold"), padx=18, pady=10)
        self.run_button.grid(row=3, column=0, sticky="w", pady=(16, 0))
        self.open_button = tk.Button(input_frame, text="OPEN LAST DASHBOARD", command=self.open_last_dashboard, state="disabled", bg=self.SURFACE, activebackground="#2b3444", fg=self.FG, activeforeground=self.FG, relief="flat", cursor="hand2", font=("Segoe UI", 10), padx=16, pady=10)
        self.open_button.grid(row=3, column=0, sticky="w", padx=(235, 0), pady=(16, 0))

        status_frame = tk.Frame(main, bg=self.SURFACE, highlightthickness=1, highlightbackground=self.LINE)
        status_frame.grid(row=3, column=0, sticky="ew", pady=(28, 18))
        status_frame.columnconfigure(0, weight=1)
        status_frame.columnconfigure(1, weight=0)
        self.status_var = tk.StringVar(value="Ready. Enter a new target SMILES and press Run Search and Show Routes.")
        ttk.Label(status_frame, textvariable=self.status_var, style="Status.TLabel", padding=(12, 10)).grid(row=0, column=0, columnspan=2, sticky="ew")
        self.percent_var = tk.StringVar(value="")
        self.percent_label = tk.Label(status_frame, textvariable=self.percent_var, bg=self.SURFACE, fg=self.ACCENT, font=("Segoe UI", 17, "bold"))
        self.percent_label.grid(row=1, column=1, sticky="e", padx=(10, 12), pady=(0, 10))
        self.progress = ttk.Progressbar(status_frame, mode="indeterminate", maximum=100.0, style="Horizontal.TProgressbar")
        self.progress.grid(row=1, column=0, sticky="ew", padx=(12, 0), pady=(0, 10))

        ttk.Label(main, text="Ranked routes", style="Section.TLabel").grid(row=4, column=0, sticky="w", pady=(0, 8))
        table_frame = ttk.Frame(main, style="App.TFrame")
        table_frame.grid(row=5, column=0, sticky="ew")
        table_frame.columnconfigure(0, weight=1)
        self.route_tree = ttk.Treeview(table_frame, columns=("rank", "route", "solved", "steps", "bottleneck", "mean", "confidence"), show="headings", height=7)
        widths = {"rank": 60, "route": 210, "solved": 80, "steps": 70, "bottleneck": 120, "mean": 100, "confidence": 105}
        headings = {"rank": "New rank", "route": "Route", "solved": "Solved", "steps": "Steps", "bottleneck": "Bottleneck", "mean": "Mean difficulty", "confidence": "Confidence"}
        for column in self.route_tree["columns"]:
            self.route_tree.heading(column, text=headings[column])
            self.route_tree.column(column, width=widths[column], anchor="center" if column != "route" else "w")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.route_tree.yview)
        self.route_tree.configure(yscrollcommand=scrollbar.set)
        self.route_tree.grid(row=0, column=0, sticky="ew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.route_tree.bind("<<TreeviewSelect>>", self._show_route_detail)

        ttk.Label(main, text="Selected route details", style="Section.TLabel").grid(row=7, column=0, sticky="w", pady=(20, 8))
        detail_frame = ttk.Frame(main, style="App.TFrame")
        detail_frame.grid(row=8, column=0, sticky="nsew")
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(0, weight=1)
        self.detail = tk.Text(detail_frame, height=12, bg=self.SURFACE, fg=self.FG, insertbackground=self.FG, relief="flat", wrap="word", font=("Consolas", 10), padx=13, pady=12)
        self.detail.grid(row=0, column=0, sticky="nsew")
        detail_scroll = ttk.Scrollbar(detail_frame, orient="vertical", command=self.detail.yview)
        detail_scroll.grid(row=0, column=1, sticky="ns")
        self.detail.configure(yscrollcommand=detail_scroll.set, state="disabled")

    def _spin_field(self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar, low: int, high: int) -> None:
        ttk.Label(parent, text=label, style="Field.TLabel").grid(row=row, column=0, sticky="w", pady=(0, 6))
        spin = tk.Spinbox(parent, from_=low, to=high, textvariable=variable, width=22, bg=self.INPUT, fg=self.FG, buttonbackground=self.SIDEBAR, insertbackground=self.FG, relief="flat", highlightthickness=1, highlightbackground=self.LINE, highlightcolor=self.BLUE, font=("Segoe UI", 11))
        spin.grid(row=row + 1, column=0, sticky="ew", ipady=7, pady=(0, 14))

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
        target_id = safe_target_id(self.target_id_var.get())
        if not smiles:
            messagebox.showerror("Missing SMILES", "Please enter a target molecule SMILES.")
            self.smiles_entry.focus_set()
            return
        if self.python_path is None or (self.python_path.name not in {"python.exe", "python"} and not self.python_path.is_file()) or not SCORER.is_file() or not PROJECT_DIR.is_dir():
            messagebox.showerror("Environment unavailable", "The configured AiZynthFinder environment, scorer, or frozen project directory is missing.")
            return
        try:
            params = self._numeric_inputs()
        except ValueError as exc:
            messagebox.showerror("Invalid search settings", str(exc))
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
        self.status_var.set(f"Running AiZynthFinder search for {target_id} ...")
        self.run_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self._begin_progress()
        thread = threading.Thread(target=self._run_worker, args=(command, output_dir), daemon=True)
        thread.start()

    def _begin_progress(self) -> None:
        """Switch the bar to a real, measured percentage and reset it to zero."""
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress["value"] = 0.0
        self.percent_var.set("0%")

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
        label = f"{percent:.0f}%"
        if isinstance(eta, (int, float)) and stage == "search":
            label = f"{percent:.0f}%  (~{float(eta):.0f}s left)"
        self.progress.configure(mode="determinate")
        self.progress["value"] = max(0.0, min(100.0, percent))
        self.percent_var.set(label)
        if text:
            self.status_var.set(text)

    def _handle_finished(self, payload: dict) -> None:
        output_dir = Path(payload["output_dir"])
        return_code = int(payload["return_code"])
        manifest_path = output_dir / "prospective_manifest.json"
        blocker_path = output_dir / "prospective_blocker.json"
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
            self._finish_ui(True, f"PASS - {len(self._routes)} routes scored\nOutput: {output_dir}\nDashboard: {output_dir / 'prospective_dashboard.html'}")
            if self.auto_open_var.get():
                self.open_last_dashboard()
        except Exception as exc:
            self._finish_ui(False, f"Run completed but the result could not be displayed: {type(exc).__name__}: {exc}")

    def _finish_ui(self, success: bool, message: str) -> None:
        self.progress.stop()
        if success:
            self.progress.configure(mode="determinate")
            self.progress["value"] = 100.0
            self.percent_var.set("100%")
        else:
            # Keep whatever real percentage was reached, so the failure point is visible.
            pass
        self.run_button.configure(state="normal")
        self.open_button.configure(state="normal" if self._last_output and (self._last_output / "prospective_dashboard.html").is_file() else "disabled")
        self.status_var.set(message)
        if not success:
            self._set_detail(message)

    def _render_routes(self) -> None:
        for item in self.route_tree.get_children():
            self.route_tree.delete(item)
        for index, route in enumerate(self._routes):
            values = (
                route.get("new_rank", index + 1),
                route.get("route_id", ""),
                "yes" if route.get("solved") else "no",
                route.get("number_of_reactions", 0),
                self._fmt(route.get("difficulty_bottleneck")),
                self._fmt(route.get("difficulty_mean")),
                route.get("route_confidence", "not_applicable"),
            )
            self.route_tree.insert("", "end", iid=str(index), values=values)
        if self._routes:
            first = self.route_tree.get_children()[0]
            self.route_tree.selection_set(first)
            self.route_tree.focus(first)
            self._show_route_detail()
        else:
            self._set_detail("AiZynthFinder returned no route rows. Check the search log and prospective_blocker.json if present.")

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
        if dashboard.is_file():
            webbrowser.open(dashboard.resolve().as_uri())

    def _on_close(self) -> None:
        if self._process is not None and self._process.poll() is None:
            if not messagebox.askyesno("Search running", "A prospective search is still running. Close the interface anyway?"):
                return
        self.destroy()


if __name__ == "__main__":
    ProspectiveGUI().mainloop()
