# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, filedialog


class TextPrompt(tk.Toplevel):
    def __init__(self, master, title: str, label: str, initial: str = "", ok_text="OK"):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.result = None

        self.transient(master)
        self.grab_set()

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text=label).pack(anchor="w")

        self.var = tk.StringVar(value=initial)
        ent = ttk.Entry(frm, textvariable=self.var, width=50)
        ent.pack(fill="x", pady=(6, 10))
        ent.focus_set()
        ent.selection_range(0, "end")

        btns = ttk.Frame(frm)
        btns.pack(fill="x")

        ttk.Button(btns, text="Cancel", command=self._cancel).pack(side="right")
        ttk.Button(btns, text=ok_text, command=self._ok).pack(side="right", padx=(0, 8))

        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())

        self.update_idletasks()
        x = master.winfo_rootx() + 80
        y = master.winfo_rooty() + 80
        self.geometry(f"+{x}+{y}")

    def _ok(self):
        self.result = self.var.get()
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def ask_text(master, title: str, label: str, initial: str = "", ok_text="OK"):
    dlg = TextPrompt(master, title=title, label=label, initial=initial, ok_text=ok_text)
    master.wait_window(dlg)
    return dlg.result


def ask_save_json(master, default_name="quickcopy_bundle.json"):
    return filedialog.asksaveasfilename(
        parent=master,
        title="Export bundle",
        defaultextension=".json",
        initialfile=default_name,
        filetypes=[("JSON files", "*.json")],
    )


def ask_open_json(master):
    return filedialog.askopenfilename(
        parent=master,
        title="Import bundle",
        filetypes=[("JSON files", "*.json")],
    )
