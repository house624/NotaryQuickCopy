# -*- coding: utf-8 -*-
from __future__ import annotations
from tkinter import Tk


def copy_to_clipboard(root: Tk, text: str):
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update_idletasks()


def safe_name(name: str) -> str:
    name = (name or "").strip()
    return name if name else "Untitled"
