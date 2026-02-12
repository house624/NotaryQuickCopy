# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import tkinter as tk
from tkinter import ttk, messagebox

from models import Database, Node, FileContent, new_id, blank_rich_doc, db_from_dict, db_to_dict
from dialogs import ask_text, ask_save_json, ask_open_json
from utils import safe_name


class ExplorerView(ttk.Frame):
    def __init__(self, master, db: Database, on_open_file, on_db_changed, set_status):
        super().__init__(master, padding=10)
        self.db = db
        self.on_open_file = on_open_file
        self.on_db_changed = on_db_changed
        self.set_status = set_status  # can be no-op (App disables status UI)

        # view state
        self.current_folder_id = db.quickcopy_root_id
        self.search_var = tk.StringVar(value="")

        self._build_ui()
        self._bind_hotkeys()

    # ---------- UI ----------
    def _build_ui(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))

        # Group 1: Create
        grp_create = ttk.LabelFrame(bar, text="Create", padding=(8, 6))
        grp_create.pack(side="left")
        ttk.Button(grp_create, text="New Folder", command=self.create_folder).pack(side="left")
        ttk.Button(grp_create, text="New File", command=self.create_file).pack(side="left", padx=(8, 0))

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)

        # Group 2: Manage
        grp_manage = ttk.LabelFrame(bar, text="Manage", padding=(8, 6))
        grp_manage.pack(side="left")
        ttk.Button(grp_manage, text="Rename", command=self.rename_selected).pack(side="left")
        ttk.Button(grp_manage, text="Delete", command=self.delete_selected).pack(side="left", padx=(8, 0))

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)

        # Group 3: Navigate
        grp_nav = ttk.LabelFrame(bar, text="Navigate", padding=(8, 6))
        grp_nav.pack(side="left")
        ttk.Button(grp_nav, text="Favorites", command=self.go_favorites).pack(side="left")
        ttk.Button(grp_nav, text="QuickCopy", command=self.go_quickcopy).pack(side="left", padx=(8, 0))

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)

        # Group 4: Transfer
        grp_transfer = ttk.LabelFrame(bar, text="Transfer", padding=(8, 6))
        grp_transfer.pack(side="left")
        ttk.Button(grp_transfer, text="Export", command=self.export_bundle).pack(side="left")
        ttk.Button(grp_transfer, text="Import", command=self.import_bundle).pack(side="left", padx=(8, 0))

        # Group 5: Search (right aligned)
        grp_search = ttk.LabelFrame(bar, text="Search", padding=(8, 6))
        grp_search.pack(side="right")
        self.search_entry = ttk.Entry(grp_search, textvariable=self.search_var, width=34)
        self.search_entry.pack(side="left", padx=(0, 8))
        ttk.Button(grp_search, text="Clear", command=self.clear_search).pack(side="left")

        self.search_entry.bind("<KeyRelease>", lambda e: self.refresh_right_list())
        self.search_entry.bind("<Escape>", lambda e: self.clear_search())

        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True)

        # Left: folders tree (two roots: Favorites and QuickCopy)
        left = ttk.Frame(panes)
        panes.add(left, weight=1)

        ttk.Label(left, text="Folders", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))

        self.folder_tree = ttk.Treeview(left, show="tree")
        self.folder_tree.pack(fill="both", expand=True, side="left")

        ysb_l = ttk.Scrollbar(left, orient="vertical", command=self.folder_tree.yview)
        ysb_l.pack(side="right", fill="y")
        self.folder_tree.configure(yscrollcommand=ysb_l.set)

        self.folder_tree.bind("<<TreeviewSelect>>", self._on_folder_select)

        # Right: contents list (Name + Type + ★)
        right = ttk.Frame(panes)
        panes.add(right, weight=3)

        header = ttk.Frame(right)
        header.pack(fill="x", pady=(0, 6))

        self.right_title = ttk.Label(header, text="Contents", font=("Segoe UI", 10, "bold"))
        self.right_title.pack(side="left")

        grp_actions = ttk.LabelFrame(header, text="Selection", padding=(8, 6))
        grp_actions.pack(side="right")
        ttk.Button(grp_actions, text="Open", command=self.open_selected).pack(side="left")
        ttk.Button(grp_actions, text="Favorite/Unfavorite", command=self.toggle_favorite_selected).pack(
            side="left", padx=(8, 0)
        )

        cols = ("type", "fav")
        self.list_tree = ttk.Treeview(right, columns=cols, show="tree headings", selectmode="browse")
        self.list_tree.heading("#0", text="Name")
        self.list_tree.heading("type", text="Type")
        self.list_tree.heading("fav", text="Favorite")
        self.list_tree.column("#0", width=520, anchor="w")
        self.list_tree.column("type", width=140, anchor="w")
        self.list_tree.column("fav", width=90, anchor="center")
        self.list_tree.pack(fill="both", expand=True, side="left")

        ysb_r = ttk.Scrollbar(right, orient="vertical", command=self.list_tree.yview)
        ysb_r.pack(side="right", fill="y")
        self.list_tree.configure(yscrollcommand=ysb_r.set)

        self.list_tree.bind("<Double-1>", lambda e: self.open_selected())
        self.list_tree.bind("<Return>", lambda e: self.open_selected())

        # Right-click menu
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Open", command=self.open_selected)
        self.menu.add_separator()
        self.menu.add_command(label="Favorite/Unfavorite", command=self.toggle_favorite_selected)
        self.menu.add_command(label="Rename", command=self.rename_selected)
        self.menu.add_command(label="Delete", command=self.delete_selected)
        self.list_tree.bind("<Button-3>", self._on_right_click)

        self.star_text = "⭐"
        self.refresh_all()

    def _bind_hotkeys(self):
        self.bind_all("<Control-f>", lambda e: self._focus_search())
        self.bind_all("<Delete>", lambda e: self.delete_selected())
        self.bind_all("<Return>", lambda e: self.open_selected())
        self.bind_all("<Escape>", lambda e: self._global_escape())

    def _global_escape(self):
        if (self.search_var.get() or "").strip():
            self.clear_search()

    def _focus_search(self):
        try:
            self.search_entry.focus_set()
            self.search_entry.selection_range(0, "end")
        except Exception:
            pass

    # ---------- Search helpers ----------
    def clear_search(self):
        if self.search_var.get() != "":
            self.search_var.set("")
        self.refresh_right_list()
        self.set_status("")

    # ---------- Navigation ----------
    def go_favorites(self):
        self.clear_search()
        self.current_folder_id = self.db.favorites_root_id
        self.refresh_right_list()
        self._select_folder_in_tree(self.current_folder_id)

    def go_quickcopy(self):
        self.clear_search()
        self.current_folder_id = self.db.quickcopy_root_id
        self.refresh_right_list()
        self._select_folder_in_tree(self.current_folder_id)

    def _select_folder_in_tree(self, folder_id: str):
        try:
            self.folder_tree.selection_set(folder_id)
            self.folder_tree.see(folder_id)
        except Exception:
            pass

    def _capture_return_state(self) -> dict:
        sel_folder = self.folder_tree.selection()
        sel_list = self.list_tree.selection()
        y0, y1 = self.list_tree.yview()
        return {
            "folder_id": sel_folder[0] if sel_folder else self.current_folder_id,
            "selected_id": sel_list[0] if sel_list else None,
            "yview": y0,
            "search": "",
        }

    # ---------- Refresh ----------
    def refresh_all(self, return_state: dict | None = None):
        self.search_var.set("")

        if return_state:
            fid = return_state.get("folder_id")
            if fid and fid in self.db.nodes:
                self.current_folder_id = fid

        self.refresh_folder_tree()
        self.refresh_right_list()

        if return_state:
            sel_id = return_state.get("selected_id")
            if sel_id and sel_id in self.db.nodes:
                try:
                    self.list_tree.selection_set(sel_id)
                    self.list_tree.see(sel_id)
                except Exception:
                    pass
            yview = return_state.get("yview")
            if yview is not None:
                try:
                    self.list_tree.yview_moveto(float(yview))
                except Exception:
                    pass

    def refresh_folder_tree(self):
        self.folder_tree.delete(*self.folder_tree.get_children())

        fav = self.db.nodes.get(self.db.favorites_root_id)
        qc = self.db.nodes.get(self.db.quickcopy_root_id)
        if fav:
            self._insert_folder("", fav, prefix="⭐ ")
            self.folder_tree.item(fav.id, open=True)
        if qc:
            self._insert_folder("", qc, prefix="📁 ")
            self.folder_tree.item(qc.id, open=True)

        self._select_folder_in_tree(self.current_folder_id)

    def _insert_folder(self, parent_iid: str, node: Node, prefix: str = "📁 "):
        if node.type != "folder":
            return
        self.folder_tree.insert(parent_iid, "end", iid=node.id, text=prefix + node.name, open=False)

        for cid in node.children:
            child = self.db.nodes.get(cid)
            if child and child.type == "folder":
                self._insert_folder(node.id, child, prefix="📁 ")

    def _on_folder_select(self, _evt):
        sel = self.folder_tree.selection()
        if not sel:
            return

        if (self.search_var.get() or "").strip():
            self.search_var.set("")

        self.current_folder_id = sel[0]
        self.refresh_right_list()

    def refresh_right_list(self):
        self.list_tree.delete(*self.list_tree.get_children())

        query = (self.search_var.get() or "").strip().lower()

        if query:
            self.right_title.config(text=f"Search results: '{query}'")
            matches = []
            for n in self.db.nodes.values():
                if query in (n.name or "").lower():
                    if n.type in ("folder", "file", "shortcut"):
                        matches.append(n)

            matches.sort(key=lambda n: (0 if n.type == "folder" else 1, (n.name or "").lower()))
            for n in matches:
                self._insert_right_row(n)
            return

        folder = self.db.nodes.get(self.current_folder_id)
        self.right_title.config(text=f"Contents: {folder.name if folder else ''}")

        if not folder or folder.type != "folder":
            return

        items = [self.db.nodes[cid] for cid in folder.children if cid in self.db.nodes]
        items.sort(key=lambda n: (0 if n.type == "folder" else 1, (n.name or "").lower()))
        for n in items:
            self._insert_right_row(n)

    def _insert_right_row(self, node: Node):
        if node.type == "folder":
            name = "📁 " + node.name
            t = "Folder"
            fav = ""
        elif node.type == "file":
            name = "📄 " + node.name
            t = "File"
            fav = self.star_text if self.is_favorited(node.id) else ""
        else:
            name = "🔗 " + node.name
            t = "Favorite Shortcut"
            fav = self.star_text

        self.list_tree.insert("", "end", iid=node.id, text=name, values=(t, fav))

    # ---------- Selection helpers ----------
    def _right_selected_node_id(self) -> str | None:
        sel = self.list_tree.selection()
        return sel[0] if sel else None

    def _left_selected_node_id(self) -> str | None:
        sel = self.folder_tree.selection()
        return sel[0] if sel else None

    def _get_selected_node_anywhere(self) -> Node | None:
        rid = self._right_selected_node_id()
        if rid and rid in self.db.nodes:
            return self.db.nodes[rid]
        lid = self._left_selected_node_id()
        if lid and lid in self.db.nodes:
            return self.db.nodes[lid]
        return None

    def open_selected(self):
        node = self._get_selected_node_anywhere()
        if not node:
            return

        if (self.search_var.get() or "").strip():
            self.search_var.set("")

        if node.type == "folder":
            self.current_folder_id = node.id
            self.refresh_right_list()
            self._select_folder_in_tree(node.id)
            return

        if node.type == "shortcut":
            target = self.db.nodes.get(node.target_id) if node.target_id else None
            if not target or target.type != "file":
                messagebox.showerror("Missing target", "This favorite shortcut points to a missing file.")
                return
            state = self._capture_return_state()
            self.on_open_file(target.id, return_state=state)
            return

        if node.type == "file":
            state = self._capture_return_state()
            self.on_open_file(node.id, return_state=state)

    # ---------- Favorites logic (shortcuts) ----------
    def is_favorited(self, file_id: str) -> bool:
        fav_root = self.db.nodes.get(self.db.favorites_root_id)
        if not fav_root or fav_root.type != "folder":
            return False
        for cid in fav_root.children:
            n = self.db.nodes.get(cid)
            if n and n.type == "shortcut" and n.target_id == file_id:
                return True
        return False

    def toggle_favorite_selected(self):
        node = self._get_selected_node_anywhere()
        if not node:
            return

        if node.type == "shortcut":
            self._remove_shortcut(node.id)
            self.on_db_changed()
            self.refresh_right_list()
            self.set_status("")
            return

        if node.type != "file":
            return

        if self.is_favorited(node.id):
            self._remove_shortcut_for_target(node.id)
            self.on_db_changed()
            self.refresh_right_list()
            self.set_status("")
        else:
            self._add_shortcut_for_target(node.id)
            self.on_db_changed()
            self.refresh_right_list()
            self.set_status("")

    def _add_shortcut_for_target(self, file_id: str):
        target = self.db.nodes.get(file_id)
        fav_root = self.db.nodes.get(self.db.favorites_root_id)
        if not target or target.type != "file" or not fav_root or fav_root.type != "folder":
            return

        for cid in fav_root.children:
            n = self.db.nodes.get(cid)
            if n and n.type == "shortcut" and n.target_id == file_id:
                return

        sc = Node(id=new_id(), type="shortcut", name=target.name, target_id=file_id)
        self.db.nodes[sc.id] = sc
        fav_root.children.append(sc.id)

    def _remove_shortcut_for_target(self, file_id: str):
        fav_root = self.db.nodes.get(self.db.favorites_root_id)
        if not fav_root or fav_root.type != "folder":
            return
        for cid in list(fav_root.children):
            n = self.db.nodes.get(cid)
            if n and n.type == "shortcut" and n.target_id == file_id:
                fav_root.children.remove(cid)
                self.db.nodes.pop(cid, None)
                return

    def _remove_shortcut(self, shortcut_id: str):
        fav_root = self.db.nodes.get(self.db.favorites_root_id)
        if fav_root and fav_root.type == "folder":
            fav_root.children = [c for c in fav_root.children if c != shortcut_id]
        self.db.nodes.pop(shortcut_id, None)

    # ---------- Create / Rename / Delete ----------
    def create_folder(self):
        parent = self.db.nodes.get(self.current_folder_id) or self.db.nodes.get(self.db.quickcopy_root_id)
        if not parent or parent.type != "folder":
            return

        name = ask_text(self, "New Folder", "Folder name:", initial="New Folder", ok_text="Create")
        if name is None:
            return
        name = safe_name(name)

        new_node = Node(id=new_id(), type="folder", name=name, children=[])
        self.db.nodes[new_node.id] = new_node
        parent.children.append(new_node.id)

        self.on_db_changed()
        self.refresh_all()

    def create_file(self):
        parent = self.db.nodes.get(self.current_folder_id) or self.db.nodes.get(self.db.quickcopy_root_id)
        if not parent or parent.type != "folder":
            return

        name = ask_text(self, "New File", "File name:", initial="New File", ok_text="Create")
        if name is None:
            return
        name = safe_name(name)

        new_node = Node(
            id=new_id(),
            type="file",
            name=name,
            content=FileContent(read_doc=blank_rich_doc(), copy_docs=[blank_rich_doc()]),
        )
        self.db.nodes[new_node.id] = new_node
        parent.children.append(new_node.id)

        self.on_db_changed()
        self.refresh_all()

    def rename_selected(self):
        node = self._get_selected_node_anywhere()
        if not node:
            return

        if node.id in (self.db.favorites_root_id, self.db.quickcopy_root_id):
            messagebox.showinfo("Rename", "Favorites and QuickCopy roots cannot be renamed.")
            return

        if node.type == "shortcut" and node.target_id in self.db.nodes:
            node = self.db.nodes[node.target_id]

        new_name = ask_text(self, "Rename", "New name:", initial=node.name, ok_text="Rename")
        if new_name is None:
            return
        node.name = safe_name(new_name)

        if node.type == "file":
            fav_root = self.db.nodes.get(self.db.favorites_root_id)
            if fav_root and fav_root.type == "folder":
                for cid in fav_root.children:
                    sc = self.db.nodes.get(cid)
                    if sc and sc.type == "shortcut" and sc.target_id == node.id:
                        sc.name = node.name

        self.on_db_changed()
        self.refresh_all()

    def delete_selected(self):
        node = self._get_selected_node_anywhere()
        if not node:
            return

        if node.id in (self.db.favorites_root_id, self.db.quickcopy_root_id):
            messagebox.showinfo("Delete", "Favorites and QuickCopy roots cannot be deleted.")
            return

        if node.type == "shortcut":
            if not messagebox.askyesno("Remove Favorite", f"Remove '{node.name}' from Favorites?"):
                return
            self._remove_shortcut(node.id)
            self.on_db_changed()
            self.refresh_right_list()
            return

        if not messagebox.askyesno("Delete", f"Delete '{node.name}'? This cannot be undone."):
            return

        parent = self._find_parent_folder(node.id)
        if parent:
            parent.children = [cid for cid in parent.children if cid != node.id]

        if node.type == "file":
            self._remove_shortcut_for_target(node.id)

        if node.type == "folder" and node.id == self.current_folder_id:
            if parent and parent.type == "folder":
                self.current_folder_id = parent.id
            else:
                self.current_folder_id = self.db.quickcopy_root_id

        self._delete_subtree(node.id)

        self.on_db_changed()
        self.refresh_all()

    def _find_parent_folder(self, child_id: str) -> Node | None:
        for n in self.db.nodes.values():
            if n.type == "folder" and child_id in n.children:
                return n
        return None

    def _delete_subtree(self, node_id: str):
        node = self.db.nodes.get(node_id)
        if not node:
            return
        if node.type == "folder":
            for cid in list(node.children):
                self._delete_subtree(cid)
        self.db.nodes.pop(node_id, None)

    # ---------- Right-click menu ----------
    def _on_right_click(self, event):
        try:
            iid = self.list_tree.identify_row(event.y)
            if iid:
                self.list_tree.selection_set(iid)
                self.list_tree.focus(iid)
        except Exception:
            pass
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                self.menu.grab_release()
            except Exception:
                pass

    # ---------- Export / Import ----------
    def export_bundle(self):
        path = ask_save_json(self, default_name="notary_quickcopy_bundle.json")
        if not path:
            return
        data = db_to_dict(self.db)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    def import_bundle(self):
        path = ask_open_json(self)
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            incoming = db_from_dict(raw)
        except Exception as e:
            messagebox.showerror("Import failed", f"Could not read bundle:\n\n{e}")
            return

        id_map = {}
        for old_id in incoming.nodes.keys():
            id_map[old_id] = (new_id() if old_id in self.db.nodes else old_id)

        for old_id, node in incoming.nodes.items():
            newnode = Node(
                id=id_map[old_id],
                type=node.type,
                name=node.name,
                children=[],
                content=node.content,
                target_id=(id_map.get(node.target_id) if node.type == "shortcut" else node.target_id),
            )
            self.db.nodes[newnode.id] = newnode

        for old_id, node in incoming.nodes.items():
            if node.type != "folder":
                continue
            self.db.nodes[id_map[old_id]].children = [id_map[c] for c in node.children if c in id_map]

        attach_under = self.db.nodes.get(self.current_folder_id)
        if not attach_under or attach_under.type != "folder":
            attach_under = self.db.nodes[self.db.quickcopy_root_id]

        qc_in = id_map.get(incoming.quickcopy_root_id)
        if qc_in and qc_in in self.db.nodes:
            attach_under.children.append(qc_in)

        fav_in = id_map.get(incoming.favorites_root_id)
        if fav_in and fav_in in self.db.nodes:
            incoming_fav_folder = self.db.nodes[fav_in]
            my_fav = self.db.nodes[self.db.favorites_root_id]
            for cid in incoming_fav_folder.children:
                if cid not in my_fav.children:
                    my_fav.children.append(cid)

        self.on_db_changed()
        self.refresh_all()