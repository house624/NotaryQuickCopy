# -*- coding: utf-8 -*-
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox, colorchooser, font as tkfont
from datetime import datetime

from models import Database, FileContent, new_id, Node
from utils import copy_to_clipboard
from rich_text import (
    ensure_base_tags,
    apply_rich_doc,
    extract_rich_doc,
    toggle_tag_on_selection,
    set_font_family_on_selection,
    set_font_size_on_selection,
    set_color_on_selection,
    clear_formatting_on_selection,
)

# Persisted per-file inside read_doc
_LOCK_KEY = "_locked"
_AUTOSAVE_KEY = "_autosave"
_LAST_SAVED_KEY = "_last_saved_ts"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _fmt_ts(iso_ts: str | None) -> str:
    if not iso_ts:
        return "Never"
    try:
        dt = datetime.fromisoformat(iso_ts)
        return dt.strftime("%m/%d/%Y %I:%M %p").lstrip("0").replace("/0", "/")
    except Exception:
        return iso_ts


class FileView(ttk.Frame):
    def __init__(self, master, db: Database, on_back, on_db_changed, set_status):
        super().__init__(master, padding=10)
        self.db = db
        self.on_back = on_back
        self.on_db_changed = on_db_changed

        # Status UI is disabled in your app; keep the param for compatibility but never use it.
        self.set_status = set_status

        self.file_id: str | None = None
        self.return_state: dict | None = None

        # UI state
        self.lock_var = tk.BooleanVar(value=False)
        self.autosave_var = tk.BooleanVar(value=False)

        self.block_widgets: list[dict] = []
        self.active_text_widget: tk.Text | None = None

        # Dirty tracking
        self._last_saved_signature: tuple | None = None
        self._suspend_dirty_watch = False
        self._dirty_poll_job = None

        # Autosave loop
        self._autosave_job = None
        self._autosave_interval_ms = 8000  # feels good; change if you want (8s)

        # Saved feedback fade
        self._saved_fade_job = None

        # Meta persisted in read_doc
        self._meta = {
            _LOCK_KEY: False,
            _AUTOSAVE_KEY: False,
            _LAST_SAVED_KEY: None,
        }

        self._build_ui()
        self._bind_hotkeys()

    # ---------- UI ----------
    def _build_ui(self):
        # Header row (no big "Notary QuickCopy - File", just the file name area)
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 8))

        ttk.Button(top, text="← Back", command=self._back).pack(side="left")

        # File name (with lock icon + unsaved)
        self.lbl_title = ttk.Label(top, text="", font=("Segoe UI", 12, "bold"))
        self.lbl_title.pack(side="left", padx=(10, 10))

        # Last saved
        self.lbl_last_saved = ttk.Label(top, text="", font=("Segoe UI", 9))
        self.lbl_last_saved.pack(side="left")

        # Right controls
        right = ttk.Frame(top)
        right.pack(side="right")

        # Smooth save feedback label
        self.lbl_saved = ttk.Label(right, text="", font=("Segoe UI", 9, "bold"))
        self.lbl_saved.pack(side="right", padx=(8, 0))

        # Favorite
        self.fav_btn = ttk.Button(right, text="☆ Favorite", command=self._toggle_favorite)
        self.fav_btn.pack(side="right")

        # Save
        self.btn_save = ttk.Button(right, text="Save", command=self._save)
        self.btn_save.pack(side="right", padx=(0, 8))

        # Autosave toggle
        self.chk_autosave = ttk.Checkbutton(
            right,
            text="Auto-save",
            variable=self.autosave_var,
            command=self._on_autosave_toggled,
        )
        self.chk_autosave.pack(side="right", padx=(0, 12))

        # Lock
        self.chk_lock = ttk.Checkbutton(
            right,
            text="Locked",
            variable=self.lock_var,
            command=self._on_lock_toggled,
        )
        self.chk_lock.pack(side="right", padx=(0, 12))

        # Formatting toolbar (could be labeled, but keeping clean)
        fmt = ttk.Frame(self)
        fmt.pack(fill="x", pady=(0, 8))

        ttk.Label(fmt, text="Font:").pack(side="left")
        self.font_var = tk.StringVar(value="Segoe UI")
        families = sorted(set(tkfont.families()))
        self.font_box = ttk.Combobox(fmt, textvariable=self.font_var, values=families, width=22, state="readonly")
        self.font_box.pack(side="left", padx=(6, 10))
        self.font_box.bind("<<ComboboxSelected>>", lambda e: self._apply_font_family())

        ttk.Label(fmt, text="Size:").pack(side="left")
        self.size_var = tk.IntVar(value=11)
        self.size_box = ttk.Spinbox(
            fmt, from_=8, to=48, textvariable=self.size_var, width=5, command=self._apply_font_size
        )
        self.size_box.pack(side="left", padx=(6, 10))

        self.btn_bold = ttk.Button(fmt, text="Bold", command=lambda: self._toggle_tag("BOLD"))
        self.btn_bold.pack(side="left")

        self.btn_under = ttk.Button(fmt, text="Underline", command=lambda: self._toggle_tag("UNDER"))
        self.btn_under.pack(side="left", padx=(8, 0))

        self.btn_color = ttk.Button(fmt, text="Color", command=self._choose_color)
        self.btn_color.pack(side="left", padx=(8, 0))

        self.btn_clear = ttk.Button(fmt, text="Clear formatting", command=self._clear_formatting)
        self.btn_clear.pack(side="left", padx=(8, 0))

        # Resizable body (splitter)
        self.panes = ttk.Panedwindow(self, orient="vertical")
        self.panes.pack(fill="both", expand=True)

        # READ section (renamed per request)
        read_frame = ttk.LabelFrame(self.panes, text="Read only")
        self.panes.add(read_frame, weight=2)

        read_wrap = ttk.Frame(read_frame)
        read_wrap.pack(fill="both", expand=True, padx=8, pady=8)

        self.read_text = tk.Text(read_wrap, wrap="word", height=10)
        self.read_text.pack(side="left", fill="both", expand=True)
        ensure_base_tags(self.read_text)

        self.read_scroll = ttk.Scrollbar(read_wrap, orient="vertical", command=self.read_text.yview)
        self.read_scroll.pack(side="right", fill="y")
        self.read_text.configure(yscrollcommand=self.read_scroll.set)

        # COPY section
        copy_outer = ttk.Frame(self.panes)
        self.panes.add(copy_outer, weight=3)

        copy_frame = ttk.LabelFrame(copy_outer, text="Copy sections (Copy copies plain text to clipboard)")
        copy_frame.pack(fill="both", expand=True)

        # Canvas + scrollbar
        self.canvas = tk.Canvas(copy_frame, highlightthickness=0)
        self.scroll = ttk.Scrollbar(copy_frame, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)

        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scroll.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Footer row
        bottom = ttk.Frame(self, padding=(0, 8, 0, 0))
        bottom.pack(fill="x")

        self.btn_add_block = ttk.Button(bottom, text="+ Add copy section", command=self._add_block)
        self.btn_add_block.pack(side="left")

        # Active widget for formatting
        self.active_text_widget = self.read_text
        self.read_text.bind("<FocusIn>", lambda e: self._set_active_text(self.read_text))
        self.read_text.bind("<Button-1>", lambda e: self._set_active_text(self.read_text))

        # Context menus
        self._build_context_menus()

        # Mousewheel behavior for FileView-only widgets
        self._install_local_mousewheel()

        # Default unlocked/editable
        self._apply_lock_state_ui(locked=False)

    def _build_context_menus(self):
        # Shared context menu for text widgets
        self.text_menu = tk.Menu(self, tearoff=0)
        self.text_menu.add_command(label="Cut", command=lambda: self._ctx_event_generate("<<Cut>>"))
        self.text_menu.add_command(label="Copy", command=lambda: self._ctx_event_generate("<<Copy>>"))
        self.text_menu.add_command(label="Paste", command=lambda: self._ctx_event_generate("<<Paste>>"))
        self.text_menu.add_separator()
        self.text_menu.add_command(label="Select All", command=self._ctx_select_all)
        self.text_menu.add_separator()
        self.text_menu.add_command(label="Bold", command=lambda: self._toggle_tag("BOLD"))
        self.text_menu.add_command(label="Underline", command=lambda: self._toggle_tag("UNDER"))
        self.text_menu.add_command(label="Color…", command=self._choose_color)
        self.text_menu.add_command(label="Clear formatting", command=self._clear_formatting)

        # Bind for read_text now; copy blocks will bind when created
        self.read_text.bind("<Button-3>", lambda e, t=self.read_text: self._show_text_menu(e, t))

    def _show_text_menu(self, event, widget: tk.Text):
        self._set_active_text(widget)
        try:
            self.text_menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                self.text_menu.grab_release()
            except Exception:
                pass

    def _ctx_event_generate(self, seq: str):
        t = self._active_text()
        if not t:
            return
        # If locked, block edits (cut/paste)
        if self.lock_var.get() and seq in ("<<Cut>>", "<<Paste>>"):
            return
        try:
            t.event_generate(seq)
        except Exception:
            pass

    def _ctx_select_all(self):
        t = self._active_text()
        if not t:
            return
        try:
            t.tag_add("sel", "1.0", "end-1c")
            t.mark_set("insert", "1.0")
            t.see("insert")
        except Exception:
            pass

    def _install_local_mousewheel(self):
        # Canvas should scroll with mousewheel when hovered
        self.canvas.bind("<Enter>", lambda e: self._bind_canvas_wheel(True))
        self.canvas.bind("<Leave>", lambda e: self._bind_canvas_wheel(False))
        self.inner.bind("<Enter>", lambda e: self._bind_canvas_wheel(True))
        self.inner.bind("<Leave>", lambda e: self._bind_canvas_wheel(False))

        # Each Text widget should scroll itself
        self._bind_text_wheel(self.read_text)

    def _bind_canvas_wheel(self, enable: bool):
        if enable:
            self.canvas.bind_all("<MouseWheel>", self._on_canvas_mousewheel, add="+")
            self.canvas.bind_all("<Button-4>", self._on_canvas_linux_up, add="+")
            self.canvas.bind_all("<Button-5>", self._on_canvas_linux_down, add="+")
        else:
            # Don't aggressively unbind_all; it could remove other global handlers.
            # We'll just ignore if not inside canvas based on pointer location in handler.
            pass

    def _on_canvas_mousewheel(self, event):
        # Only scroll canvas if mouse is over the canvas region (or inner)
        w = self.winfo_containing(event.x_root, event.y_root)
        if not w:
            return
        if w == self.canvas or str(w).startswith(str(self.inner)) or str(w).startswith(str(self.canvas)):
            self.canvas.yview_scroll(-1 * int(event.delta / 120) * 3, "units")

    def _on_canvas_linux_up(self, event):
        w = self.winfo_containing(event.x_root, event.y_root)
        if not w:
            return
        if w == self.canvas or str(w).startswith(str(self.inner)) or str(w).startswith(str(self.canvas)):
            self.canvas.yview_scroll(-3, "units")

    def _on_canvas_linux_down(self, event):
        w = self.winfo_containing(event.x_root, event.y_root)
        if not w:
            return
        if w == self.canvas or str(w).startswith(str(self.inner)) or str(w).startswith(str(self.canvas)):
            self.canvas.yview_scroll(3, "units")

    def _bind_text_wheel(self, text_widget: tk.Text):
        def on_wheel(ev):
            # scroll the text widget itself
            if ev.delta > 0:
                text_widget.yview_scroll(-3, "units")
            else:
                text_widget.yview_scroll(3, "units")
            return "break"

        def on_up(ev):
            text_widget.yview_scroll(-3, "units")
            return "break"

        def on_down(ev):
            text_widget.yview_scroll(3, "units")
            return "break"

        text_widget.bind("<MouseWheel>", on_wheel)
        text_widget.bind("<Button-4>", on_up)
        text_widget.bind("<Button-5>", on_down)

    def _bind_hotkeys(self):
        self.bind_all("<Control-s>", lambda e: self._save())
        # Copy blocks quickly: Ctrl+1..9
        for i in range(1, 10):
            self.bind_all(f"<Control-Key-{i}>", lambda e, idx=i - 1: self._copy_block(idx))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    # ---------- Open / Render ----------
    def open_file(self, file_id: str, return_state: dict | None = None):
        # If switching files and current has unsaved changes, prompt
        if self.file_id and self._is_dirty():
            if not self._prompt_save_if_dirty():
                return

        self.file_id = file_id
        self.return_state = return_state

        node = self.db.nodes.get(file_id)
        if not node or node.type != "file":
            messagebox.showerror("Error", "File not found.")
            self._force_stop_dirty_poll()
            self._back(force=True)
            return

        if node.content is None:
            node.content = FileContent()

        self._render_from_content(node)
        self._refresh_fav_button()

        self._last_saved_signature = self._compute_signature_from_node(node)
        self._start_dirty_poll()

        # Start autosave loop if enabled for this file
        self._restart_autosave_loop()

    def _render_from_content(self, node: Node):
        self._suspend_dirty_watch = True
        try:
            content = node.content or FileContent()

            # Load meta
            self._meta[_LOCK_KEY] = bool(self._read_meta(content, _LOCK_KEY, False))
            self._meta[_AUTOSAVE_KEY] = bool(self._read_meta(content, _AUTOSAVE_KEY, False))
            self._meta[_LAST_SAVED_KEY] = self._read_meta(content, _LAST_SAVED_KEY, None)

            self.lock_var.set(bool(self._meta[_LOCK_KEY]))
            self.autosave_var.set(bool(self._meta[_AUTOSAVE_KEY]))

            # Apply docs
            apply_rich_doc(self.read_text, content.read_doc)
            ensure_base_tags(self.read_text)

            # Blocks
            for w in self.inner.winfo_children():
                w.destroy()
            self.block_widgets.clear()

            docs = content.copy_docs[:] if content.copy_docs else []
            if not docs:
                docs = [{"text": "", "tags": []}]

            for i, doc in enumerate(docs, start=1):
                self._create_block_row(index=i, doc=doc)

            self.canvas.yview_moveto(0)
            self.active_text_widget = self.read_text

            self._apply_lock_state_ui(locked=self.lock_var.get())
            self._update_title_and_saved_label()
        finally:
            self._suspend_dirty_watch = False

    def _read_meta(self, content: FileContent, key: str, default):
        if not content or not isinstance(content.read_doc, dict):
            return default
        return content.read_doc.get(key, default)

    # ---------- Title / last saved / dirty ----------
    def _update_title_and_saved_label(self):
        if not self.file_id:
            self.lbl_title.config(text="")
            self.lbl_last_saved.config(text="")
            return

        node = self.db.nodes.get(self.file_id)
        name = node.name if node else ""

        locked = bool(self.lock_var.get())
        icon = "🔒 " if locked else ""
        dirty = self._is_dirty()
        suffix = " (Unsaved)" if dirty else ""

        self.lbl_title.config(text=f"{icon}{name}{suffix}")
        self.lbl_last_saved.config(text=f"Last saved: {_fmt_ts(self._meta.get(_LAST_SAVED_KEY))}")

    # ---------- Lock (persisted per-file) ----------
    def _on_lock_toggled(self):
        locked = bool(self.lock_var.get())
        self._meta[_LOCK_KEY] = locked
        self._apply_lock_state_ui(locked=locked)
        self._update_title_and_saved_label()

    def _on_autosave_toggled(self):
        enabled = bool(self.autosave_var.get())
        self._meta[_AUTOSAVE_KEY] = enabled
        self._restart_autosave_loop()

    def _apply_lock_state_ui(self, locked: bool):
        editable = not locked
        state = "normal" if editable else "disabled"

        # subtle visual feedback
        bg = "#f0f0f0" if locked else "white"

        # Text widgets
        self.read_text.configure(state=state, background=bg)
        for bw in self.block_widgets:
            bw["text"].configure(state=state, background=bg)
            bw["remove_btn"].configure(state=("normal" if editable else "disabled"))
            bw["up_btn"].configure(state=("normal" if editable else "disabled"))
            bw["down_btn"].configure(state=("normal" if editable else "disabled"))

        # Add block
        self.btn_add_block.configure(state=("normal" if editable else "disabled"))

        # Formatting
        self._set_format_toolbar_enabled(editable)

        # Save always enabled when file is open
        self.btn_save.configure(state=("normal" if (self.file_id is not None) else "disabled"))

    # ---------- Blocks ----------
    def _create_block_row(self, index: int, doc: dict):
        row = ttk.Frame(self.inner, padding=(8, 8, 8, 0))
        row.pack(fill="x")

        header = ttk.Frame(row)
        header.pack(fill="x")

        lbl = ttk.Label(header, text=f"Copy section {index}", font=("Segoe UI", 10, "bold"))
        lbl.pack(side="left")

        # Reorder buttons
        btn_down = ttk.Button(header, text="↓", width=3, command=lambda: self._move_block(index - 1, +1))
        btn_down.pack(side="right")
        btn_up = ttk.Button(header, text="↑", width=3, command=lambda: self._move_block(index - 1, -1))
        btn_up.pack(side="right", padx=(0, 6))

        btn_copy = ttk.Button(header, text="Copy", command=lambda: self._copy_block(index - 1))
        btn_copy.pack(side="right", padx=(0, 8))

        btn_remove = ttk.Button(header, text="Remove", command=lambda: self._remove_block(index - 1))
        btn_remove.pack(side="right", padx=(0, 8))

        # Text + scrollbar
        text_wrap = ttk.Frame(row)
        text_wrap.pack(fill="x", pady=(6, 0))

        txtbox = tk.Text(text_wrap, wrap="word", height=6)
        txtbox.pack(side="left", fill="x", expand=True)
        ensure_base_tags(txtbox)
        apply_rich_doc(txtbox, doc)

        sb = ttk.Scrollbar(text_wrap, orient="vertical", command=txtbox.yview)
        sb.pack(side="right", fill="y")
        txtbox.configure(yscrollcommand=sb.set)

        # focus + right click menu + wheel
        txtbox.bind("<FocusIn>", lambda e, t=txtbox: self._set_active_text(t))
        txtbox.bind("<Button-1>", lambda e, t=txtbox: self._set_active_text(t))
        txtbox.bind("<Button-3>", lambda e, t=txtbox: self._show_text_menu(e, t))
        self._bind_text_wheel(txtbox)

        sep = ttk.Separator(self.inner)
        sep.pack(fill="x", pady=(10, 0))

        self.block_widgets.append(
            {
                "row": row,
                "label": lbl,
                "copy_btn": btn_copy,
                "remove_btn": btn_remove,
                "up_btn": btn_up,
                "down_btn": btn_down,
                "text": txtbox,
                "scroll": sb,
                "sep": sep,
            }
        )

        # Apply current lock state
        txtbox.configure(state=("disabled" if self.lock_var.get() else "normal"))
        btn_remove.configure(state=("disabled" if self.lock_var.get() else "normal"))
        btn_up.configure(state=("disabled" if self.lock_var.get() else "normal"))
        btn_down.configure(state=("disabled" if self.lock_var.get() else "normal"))

    def _set_active_text(self, widget: tk.Text):
        self.active_text_widget = widget

    def _renumber_blocks(self):
        for i, bw in enumerate(self.block_widgets, start=1):
            bw["label"].config(text=f"Copy section {i}")
            bw["copy_btn"].config(command=lambda idx=i - 1: self._copy_block(idx))
            bw["remove_btn"].config(command=lambda idx=i - 1: self._remove_block(idx))
            bw["up_btn"].config(command=lambda idx=i - 1: self._move_block(idx, -1))
            bw["down_btn"].config(command=lambda idx=i - 1: self._move_block(idx, +1))

    def _copy_block(self, idx: int):
        if idx < 0 or idx >= len(self.block_widgets):
            return
        text = self.block_widgets[idx]["text"].get("1.0", "end-1c")
        copy_to_clipboard(self.winfo_toplevel(), text)

    def _add_block(self):
        if self.lock_var.get():
            return
        self._create_block_row(index=len(self.block_widgets) + 1, doc={"text": "", "tags": []})
        self._renumber_blocks()
        self._update_title_and_saved_label()

    def _remove_block(self, idx: int):
        if self.lock_var.get():
            return
        if len(self.block_widgets) <= 1:
            messagebox.showinfo("Remove", "You must keep at least one copy section.")
            return
        if idx < 0 or idx >= len(self.block_widgets):
            return
        bw = self.block_widgets[idx]
        bw["row"].destroy()
        bw["sep"].destroy()
        self.block_widgets.pop(idx)
        self._renumber_blocks()
        self._update_title_and_saved_label()

    def _move_block(self, idx: int, direction: int):
        if self.lock_var.get():
            return
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self.block_widgets):
            return

        # Capture current docs from UI, reorder, then rebuild blocks
        docs = [extract_rich_doc(bw["text"]) for bw in self.block_widgets]
        docs[idx], docs[new_idx] = docs[new_idx], docs[idx]

        # Rebuild UI blocks in new order
        self._rebuild_blocks(docs)

    def _rebuild_blocks(self, docs: list[dict]):
        self._suspend_dirty_watch = True
        try:
            for w in self.inner.winfo_children():
                w.destroy()
            self.block_widgets.clear()

            if not docs:
                docs = [{"text": "", "tags": []}]

            for i, doc in enumerate(docs, start=1):
                self._create_block_row(index=i, doc=doc)

            self.canvas.yview_moveto(0)
            self._apply_lock_state_ui(locked=self.lock_var.get())
            self._update_title_and_saved_label()
        finally:
            self._suspend_dirty_watch = False

    # ---------- Formatting ----------
    def _active_text(self) -> tk.Text | None:
        return self.active_text_widget

    def _set_format_toolbar_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for w in (self.font_box, self.size_box, self.btn_bold, self.btn_under, self.btn_color, self.btn_clear):
            try:
                w.configure(state=state)
            except Exception:
                pass

    def _toggle_tag(self, tag: str):
        if self.lock_var.get():
            return
        t = self._active_text()
        if not t:
            return
        toggle_tag_on_selection(t, tag)

    def _apply_font_family(self):
        if self.lock_var.get():
            return
        t = self._active_text()
        if not t:
            return
        family = self.font_var.get()
        set_font_family_on_selection(t, family)

    def _apply_font_size(self):
        if self.lock_var.get():
            return
        t = self._active_text()
        if not t:
            return
        try:
            size = int(self.size_var.get())
        except Exception:
            return
        set_font_size_on_selection(t, size)

    def _choose_color(self):
        if self.lock_var.get():
            return
        t = self._active_text()
        if not t:
            return
        col = colorchooser.askcolor(title="Choose text color")
        if not col or not col[1]:
            return
        set_color_on_selection(t, col[1])

    def _clear_formatting(self):
        if self.lock_var.get():
            return
        t = self._active_text()
        if not t:
            return
        clear_formatting_on_selection(t)

    # ---------- Save / Dirty ----------
    def _collect_content_from_ui(self) -> FileContent:
        read_doc = extract_rich_doc(self.read_text)
        copy_docs = [extract_rich_doc(bw["text"]) for bw in self.block_widgets]
        if not copy_docs:
            copy_docs = [{"text": "", "tags": []}]

        # Preserve persisted metadata keys in read_doc
        if not isinstance(read_doc, dict):
            read_doc = {"text": "", "tags": []}
        read_doc[_LOCK_KEY] = bool(self._meta.get(_LOCK_KEY, False))
        read_doc[_AUTOSAVE_KEY] = bool(self._meta.get(_AUTOSAVE_KEY, False))
        read_doc[_LAST_SAVED_KEY] = self._meta.get(_LAST_SAVED_KEY, None)

        return FileContent(read_doc=read_doc, copy_docs=copy_docs)

    def _compute_signature_from_content(self, content: FileContent) -> tuple:
        read = content.read_doc if isinstance(content.read_doc, dict) else {"text": "", "tags": []}
        locked = bool(read.get(_LOCK_KEY, False))
        autosave = bool(read.get(_AUTOSAVE_KEY, False))
        last_saved = read.get(_LAST_SAVED_KEY, None)

        read_text = (read.get("text") or "")
        read_tags = tuple(self._freeze_tags(read.get("tags") or []))

        copy_docs = content.copy_docs or []
        frozen_copy = []
        for d in copy_docs:
            if not isinstance(d, dict):
                d = {"text": "", "tags": []}
            frozen_copy.append(((d.get("text") or ""), tuple(self._freeze_tags(d.get("tags") or []))))

        return (locked, autosave, last_saved, read_text, read_tags, tuple(frozen_copy))

    def _freeze_tags(self, tags_list) -> list:
        out = []
        for t in (tags_list or []):
            if not isinstance(t, dict):
                continue
            name = t.get("name") or ""
            cfg = t.get("config") or {}
            ranges = t.get("ranges") or []
            cfg_items = tuple(sorted((str(k), str(v)) for k, v in cfg.items()))
            rng_items = tuple(tuple(map(str, r)) for r in ranges if isinstance(r, (list, tuple)) and len(r) == 2)
            out.append((str(name), cfg_items, rng_items))
        return out

    def _compute_signature_from_node(self, node: Node) -> tuple:
        if not node.content:
            node.content = FileContent()
        return self._compute_signature_from_content(node.content)

    def _compute_current_signature(self) -> tuple | None:
        if not self.file_id:
            return None
        try:
            content = self._collect_content_from_ui()
            return self._compute_signature_from_content(content)
        except Exception:
            return None

    def _is_dirty(self) -> bool:
        if self._suspend_dirty_watch:
            return False
        if not self.file_id:
            return False
        cur = self._compute_current_signature()
        if cur is None or self._last_saved_signature is None:
            return False
        return cur != self._last_saved_signature

    def _save(self, _autosave: bool = False):
        if not self.file_id:
            return
        node = self.db.nodes.get(self.file_id)
        if not node or node.type != "file":
            return

        try:
            # Update last saved timestamp on manual save or autosave
            self._meta[_LAST_SAVED_KEY] = _now_iso()

            node.content = self._collect_content_from_ui()
            self.on_db_changed()

            self._last_saved_signature = self._compute_signature_from_node(node)
            self._refresh_fav_button()
            self._update_title_and_saved_label()

            self._show_saved_feedback()
        except Exception as e:
            if not _autosave:
                messagebox.showerror("Save error", f"Could not save:\n\n{e}")

    def _show_saved_feedback(self):
        # Smooth-ish fade: show ✓ Saved and fade out by changing the text color to match background-ish
        if self._saved_fade_job is not None:
            try:
                self.after_cancel(self._saved_fade_job)
            except Exception:
                pass
            self._saved_fade_job = None

        self.lbl_saved.config(text="✓ Saved", foreground="#1a7f37")  # subtle green

        steps = [
            (700, "#1a7f37"),   # stay green briefly
            (1100, "#5a5a5a"),  # fade to gray
            (1500, ""),         # clear
        ]

        def run_step(i=0):
            if i >= len(steps):
                return
            delay, color = steps[i]
            if color == "":
                self.lbl_saved.config(text="")
                return
            self.lbl_saved.config(foreground=color)
            self._saved_fade_job = self.after(delay, lambda: run_step(i + 1))

        run_step(0)

    # Poll to keep title updated as user types (dirty indicator)
    def _start_dirty_poll(self):
        self._force_stop_dirty_poll()

        def tick():
            if not self.winfo_exists() or not self.file_id:
                return
            if not self._suspend_dirty_watch:
                self._update_title_and_saved_label()
            self._dirty_poll_job = self.after(400, tick)

        self._dirty_poll_job = self.after(400, tick)

    def _force_stop_dirty_poll(self):
        if self._dirty_poll_job is not None:
            try:
                self.after_cancel(self._dirty_poll_job)
            except Exception:
                pass
        self._dirty_poll_job = None

    # ---------- Autosave ----------
    def _restart_autosave_loop(self):
        if self._autosave_job is not None:
            try:
                self.after_cancel(self._autosave_job)
            except Exception:
                pass
            self._autosave_job = None

        if not self.file_id:
            return

        if not bool(self.autosave_var.get()):
            return

        def loop():
            if not self.winfo_exists() or not self.file_id:
                return
            if bool(self.autosave_var.get()) and self._is_dirty():
                self._save(_autosave=True)
            self._autosave_job = self.after(self._autosave_interval_ms, loop)

        self._autosave_job = self.after(self._autosave_interval_ms, loop)

    # ---------- Prompt on exit ----------
    def _prompt_save_if_dirty(self) -> bool:
        if not self._is_dirty():
            return True

        name = ""
        if self.file_id and self.file_id in self.db.nodes:
            name = self.db.nodes[self.file_id].name

        res = messagebox.askyesnocancel("Unsaved changes", f"Save changes to '{name}'?")
        if res is None:
            return False
        if res is True:
            self._save()
            return True
        return True

    # ---------- Favorites ----------
    def _is_favorited(self) -> bool:
        if not self.file_id:
            return False
        fav_root = self.db.nodes.get(self.db.favorites_root_id)
        if not fav_root or fav_root.type != "folder":
            return False
        for cid in fav_root.children:
            n = self.db.nodes.get(cid)
            if n and n.type == "shortcut" and n.target_id == self.file_id:
                return True
        return False

    def _refresh_fav_button(self):
        self.fav_btn.config(text=("⭐ Favorited" if self._is_favorited() else "☆ Favorite"))

    def _toggle_favorite(self):
        if not self.file_id:
            return

        fav_root = self.db.nodes.get(self.db.favorites_root_id)
        if not fav_root or fav_root.type != "folder":
            return

        if self._is_favorited():
            for cid in list(fav_root.children):
                n = self.db.nodes.get(cid)
                if n and n.type == "shortcut" and n.target_id == self.file_id:
                    fav_root.children.remove(cid)
                    self.db.nodes.pop(cid, None)
                    break
            self.on_db_changed()
            self._refresh_fav_button()
            return

        target = self.db.nodes.get(self.file_id)
        if not target or target.type != "file":
            return

        sc = Node(id=new_id(), type="shortcut", name=target.name, target_id=self.file_id)
        self.db.nodes[sc.id] = sc
        fav_root.children.append(sc.id)

        self.on_db_changed()
        self._refresh_fav_button()

    # ---------- Navigation ----------
    def _back(self, force: bool = False):
        if not force:
            if self.file_id and self._is_dirty():
                if not self._prompt_save_if_dirty():
                    return

        self._force_stop_dirty_poll()

        if self._autosave_job is not None:
            try:
                self.after_cancel(self._autosave_job)
            except Exception:
                pass
            self._autosave_job = None

        self.on_back(self.return_state)