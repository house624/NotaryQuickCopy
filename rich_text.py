# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Any, List, Tuple
import tkinter as tk
from tkinter import font as tkfont

# We store tags with both config + ranges so formatting persists.


def _tag_ranges_as_pairs(text: tk.Text, tag: str) -> List[List[str]]:
    ranges = text.tag_ranges(tag)
    out = []
    for i in range(0, len(ranges), 2):
        out.append([str(ranges[i]), str(ranges[i + 1])])
    return out


def extract_rich_doc(text: tk.Text) -> Dict[str, Any]:
    """
    Returns:
      {"text": "...", "tags":[{"name":tag, "ranges":[["1.0","1.4"],...], "config":{...}}, ...]}
    """
    doc_text = text.get("1.0", "end-1c")
    tags_out = []

    for tag in text.tag_names():
        if tag in ("sel",):
            continue
        ranges = _tag_ranges_as_pairs(text, tag)
        if not ranges:
            continue

        # Only keep options we care about
        cfg = {}
        for opt in ("font", "foreground", "underline"):
            val = text.tag_cget(tag, opt)
            if val not in (None, "", "0"):
                cfg[opt] = val
        # underline can be "1" or "0"
        if text.tag_cget(tag, "underline") == "1":
            cfg["underline"] = 1

        tags_out.append({"name": tag, "ranges": ranges, "config": cfg})

    return {"text": doc_text, "tags": tags_out}


def apply_rich_doc(text: tk.Text, doc: Dict[str, Any]):
    text.configure(state="normal")
    text.delete("1.0", "end")

    if not isinstance(doc, dict):
        doc = {"text": "", "tags": []}

    content = doc.get("text", "") or ""
    text.insert("1.0", content)

    # Clear all custom tags
    for tag in list(text.tag_names()):
        if tag not in ("sel",):
            text.tag_delete(tag)

    tags = doc.get("tags", []) or []
    for t in tags:
        name = t.get("name")
        if not name:
            continue
        cfg = t.get("config") or {}
        try:
            text.tag_configure(name, **cfg)
        except Exception:
            # ignore bad configs
            try:
                text.tag_configure(name)
            except Exception:
                pass

        for r in t.get("ranges", []) or []:
            if len(r) != 2:
                continue
            try:
                text.tag_add(name, r[0], r[1])
            except Exception:
                pass


def ensure_base_tags(text: tk.Text):
    """
    Create standard tags for bold/underline and a default color tag placeholder.
    We still allow dynamic tags for any font/size/color combos.
    """
    base_font = tkfont.nametofont(text.cget("font"))
    bold_font = base_font.copy()
    bold_font.configure(weight="bold")

    text.tag_configure("BOLD", font=bold_font)
    text.tag_configure("UNDER", underline=1)


def _current_selection(text: tk.Text) -> Tuple[str, str] | None:
    try:
        start = text.index("sel.first")
        end = text.index("sel.last")
        return start, end
    except Exception:
        return None


def toggle_tag_on_selection(text: tk.Text, tag: str):
    sel = _current_selection(text)
    if not sel:
        return
    start, end = sel
    # If every char has tag, remove. Otherwise add.
    # Approx: if start has tag and end has tag.
    has = tag in text.tag_names("sel.first")
    if has:
        text.tag_remove(tag, start, end)
    else:
        text.tag_add(tag, start, end)


def set_font_family_on_selection(text: tk.Text, family: str):
    sel = _current_selection(text)
    if not sel:
        return
    start, end = sel

    # Create a tag name that is stable
    tag = f"FONT_{family}"
    base = tkfont.nametofont(text.cget("font")).copy()
    base.configure(family=family)
    text.tag_configure(tag, font=base)
    text.tag_add(tag, start, end)


def set_font_size_on_selection(text: tk.Text, size: int):
    sel = _current_selection(text)
    if not sel:
        return
    start, end = sel

    tag = f"SIZE_{size}"
    base = tkfont.nametofont(text.cget("font")).copy()
    base.configure(size=size)
    text.tag_configure(tag, font=base)
    text.tag_add(tag, start, end)


def set_color_on_selection(text: tk.Text, color_hex: str):
    sel = _current_selection(text)
    if not sel:
        return
    start, end = sel

    tag = f"COLOR_{color_hex.replace('#','')}"
    text.tag_configure(tag, foreground=color_hex)
    text.tag_add(tag, start, end)


def clear_formatting_on_selection(text: tk.Text):
    sel = _current_selection(text)
    if not sel:
        return
    start, end = sel
    for tag in text.tag_names():
        if tag == "sel":
            continue
        text.tag_remove(tag, start, end)

