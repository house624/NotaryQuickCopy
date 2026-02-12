# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox

from storage import Storage
from ui_explorer import ExplorerView
from ui_file_view import FileView


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Notary QuickCopy")
        self.geometry("1200x750")
        self.minsize(1000, 650)

        self.storage = Storage("data.json")
        self.db = self.storage.load_or_create_blank()

        self._build_ui()
        self._install_global_mousewheel()

    def _build_ui(self):
        top = ttk.Frame(self, padding=(10, 10, 10, 6))
        top.pack(side="top", fill="x")

        # Keep title only (no status area)
        self.title_label = ttk.Label(top, text="Notary QuickCopy", font=("Segoe UI", 14, "bold"))
        self.title_label.pack(side="left")

        self.container = ttk.Frame(self)
        self.container.pack(fill="both", expand=True)

        self.explorer = ExplorerView(
            master=self.container,
            db=self.db,
            on_open_file=self.open_file,
            on_db_changed=self._on_db_changed,
            set_status=self.set_status,  # no-op, keeps compatibility
        )
        self.file_view = FileView(
            master=self.container,
            db=self.db,
            on_back=self.back_to_explorer,
            on_db_changed=self._on_db_changed,
            set_status=self.set_status,  # no-op, keeps compatibility
        )

        self.explorer.grid(row=0, column=0, sticky="nsew")
        self.file_view.grid(row=0, column=0, sticky="nsew")

        self.container.rowconfigure(0, weight=1)
        self.container.columnconfigure(0, weight=1)

        self.show_explorer()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---- Status is intentionally disabled (per your request) ----
    def set_status(self, _text: str):
        # No status UI anywhere
        return

    def _on_db_changed(self):
        try:
            self.storage.save(self.db)
        except Exception as e:
            messagebox.showerror("Save error", f"Could not save data.json:\n\n{e}")

    def show_explorer(self):
        # Keep app header stable (FileView will handle in-screen titles)
        self.explorer.refresh_all()
        self.explorer.tkraise()

    def open_file(self, file_id: str, return_state: dict | None = None):
        # Keep app header stable (FileView will handle in-screen titles)
        self.file_view.open_file(file_id=file_id, return_state=return_state)
        self.file_view.tkraise()

    def back_to_explorer(self, return_state: dict | None = None):
        self.explorer.refresh_all(return_state=return_state)
        self.explorer.tkraise()

    def on_close(self):
        try:
            self.storage.save(self.db)
        except Exception:
            pass
        self.destroy()

    # ---- Global mousewheel scrolling (works anywhere scrollable) ----
    def _install_global_mousewheel(self):
        # Windows / macOS
        self.bind_all("<MouseWheel>", self._on_global_mousewheel, add="+")
        self.bind_all("<Shift-MouseWheel>", self._on_global_shift_mousewheel, add="+")
        # Linux
        self.bind_all("<Button-4>", self._on_global_linux_wheel_up, add="+")
        self.bind_all("<Button-5>", self._on_global_linux_wheel_down, add="+")

    def _find_scroll_target(self, widget):
        """
        Walk up the widget hierarchy looking for something scrollable.
        Supports: Text, Canvas, Treeview, Listbox, and anything with yview().
        """
        w = widget
        while w is not None:
            # Prefer widgets that expose yview (Text/Canvas/Treeview/Listbox/etc.)
            if hasattr(w, "yview") and callable(getattr(w, "yview")):
                return w
            w = w.master
        return None

    def _scroll_widget(self, w, units: int):
        try:
            w.yview_scroll(units, "units")
        except Exception:
            pass

    def _scroll_widget_x(self, w, units: int):
        try:
            if hasattr(w, "xview") and callable(getattr(w, "xview")):
                w.xview_scroll(units, "units")
        except Exception:
            pass

    def _on_global_mousewheel(self, event):
        target = self._find_scroll_target(self.winfo_containing(event.x_root, event.y_root))
        if not target:
            return

        # Windows: event.delta is multiples of 120
        if event.delta > 0:
            self._scroll_widget(target, -3)
        else:
            self._scroll_widget(target, 3)

    def _on_global_shift_mousewheel(self, event):
        target = self._find_scroll_target(self.winfo_containing(event.x_root, event.y_root))
        if not target:
            return

        if event.delta > 0:
            self._scroll_widget_x(target, -3)
        else:
            self._scroll_widget_x(target, 3)

    def _on_global_linux_wheel_up(self, event):
        target = self._find_scroll_target(self.winfo_containing(event.x_root, event.y_root))
        if target:
            self._scroll_widget(target, -3)

    def _on_global_linux_wheel_down(self, event):
        target = self._find_scroll_target(self.winfo_containing(event.x_root, event.y_root))
        if target:
            self._scroll_widget(target, 3)


if __name__ == "__main__":
    app = App()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    app.mainloop()