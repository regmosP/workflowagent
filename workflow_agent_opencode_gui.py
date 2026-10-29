#!/usr/bin/env python3
"""OpenCode-style light GUI for Workflow Agent."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from workflow_agent_gui import HarnessGui


class OpenCodeStyleGui(HarnessGui):
    def __init__(self) -> None:
        super().__init__()
        self.title("Workflow Agent")
        self.geometry("1280x860")
        self._apply_light_theme()
        self._add_status_bar()

    def _apply_light_theme(self) -> None:
        background = "#ffffff"
        panel = "#f7f8fa"
        panel_alt = "#e5e7eb"
        foreground = "#111827"
        muted = "#6b7280"
        accent = "#2563eb"
        input_bg = "#ffffff"

        self.configure(bg=background)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=background, foreground=foreground, fieldbackground=input_bg, bordercolor=panel_alt, lightcolor=panel_alt, darkcolor=panel_alt)
        style.configure("TFrame", background=background)
        style.configure("TLabelframe", background=background, bordercolor=panel_alt, relief="solid")
        style.configure("TLabelframe.Label", background=background, foreground=accent, font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", background=background, foreground=foreground)
        style.configure("TButton", background=panel, foreground=foreground, borderwidth=1, focusthickness=0, padding=(10, 5))
        style.map("TButton", background=[("active", "#eef2ff")], foreground=[("active", accent)])
        style.configure("TCheckbutton", background=background, foreground=foreground)
        style.map("TCheckbutton", background=[("active", background)], foreground=[("active", accent)])
        style.configure("TEntry", fieldbackground=input_bg, foreground=foreground, insertcolor=foreground)
        style.configure("TCombobox", fieldbackground=input_bg, background=panel, foreground=foreground, arrowcolor=accent)
        style.configure("TSpinbox", fieldbackground=input_bg, foreground=foreground, arrowsize=12)

        self._theme_text_widgets(self, input_bg, foreground, accent, muted)
        self._theme_frames(self, panel)

    def _theme_text_widgets(self, widget: tk.Widget, background: str, foreground: str, accent: str, muted: str) -> None:
        for child in widget.winfo_children():
            if isinstance(child, tk.Text):
                child.configure(
                    bg=background,
                    fg=foreground,
                    insertbackground=accent,
                    selectbackground="#dbeafe",
                    selectforeground=foreground,
                    relief=tk.FLAT,
                    borderwidth=6,
                    font=("Cascadia Mono", 10),
                )
            elif isinstance(child, tk.Label):
                child.configure(bg=background, fg=muted)
            elif isinstance(child, tk.Canvas):
                child.configure(bg="#ffffff", highlightthickness=0)
            self._theme_text_widgets(child, background, foreground, accent, muted)

    def _theme_frames(self, widget: tk.Widget, panel: str) -> None:
        for child in widget.winfo_children():
            if isinstance(child, tk.Frame):
                child.configure(bg=panel)
            self._theme_frames(child, panel)

    def _add_status_bar(self) -> None:
        status = tk.Label(
            self,
            text="模式: code / convert / skill    模型: 本地或 OpenAI-compatible API    安全: 外部路径弹窗确认",
            anchor=tk.W,
            bg="#f3f4f6",
            fg="#6b7280",
            padx=12,
            pady=6,
            font=("Segoe UI", 9),
        )
        status.pack(side=tk.BOTTOM, fill=tk.X)


def main() -> None:
    OpenCodeStyleGui().mainloop()


if __name__ == "__main__":
    main()
