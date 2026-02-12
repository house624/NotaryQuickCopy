# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Literal, Dict, Any
import uuid

NodeType = Literal["folder", "file", "shortcut"]


def new_id() -> str:
    return str(uuid.uuid4())


def blank_rich_doc() -> Dict[str, Any]:
    return {"text": "", "tags": []}


@dataclass
class FileContent:
    read_doc: Dict[str, Any] = field(default_factory=blank_rich_doc)
    copy_docs: List[Dict[str, Any]] = field(default_factory=lambda: [blank_rich_doc()])


@dataclass
class Node:
    id: str
    type: NodeType
    name: str

    # folder
    children: List[str] = field(default_factory=list)

    # file
    content: Optional[FileContent] = None

    # shortcut
    target_id: Optional[str] = None  # points to a file node id


@dataclass
class Database:
    quickcopy_root_id: str
    favorites_root_id: str
    nodes: Dict[str, Node] = field(default_factory=dict)


def blank_database() -> Database:
    fav_root = Node(id=new_id(), type="folder", name="Favorites", children=[])
    qc_root = Node(id=new_id(), type="folder", name="QuickCopy", children=[])
    db = Database(
        quickcopy_root_id=qc_root.id,
        favorites_root_id=fav_root.id,
        nodes={
            fav_root.id: fav_root,
            qc_root.id: qc_root,
        },
    )
    return db


# ---- serialization helpers ----
def db_to_dict(db: Database) -> Dict[str, Any]:
    out_nodes: Dict[str, Any] = {}
    for node_id, node in db.nodes.items():
        d = {
            "id": node.id,
            "type": node.type,
            "name": node.name,
            "children": list(node.children),
            "content": None,
            "target_id": node.target_id,
        }
        if node.type == "file" and node.content is not None:
            d["content"] = {
                "read_doc": node.content.read_doc,
                "copy_docs": node.content.copy_docs,
            }
        out_nodes[node_id] = d

    return {
        "quickcopy_root_id": db.quickcopy_root_id,
        "favorites_root_id": db.favorites_root_id,
        "nodes": out_nodes,
    }


def _upgrade_legacy_content(content_raw: Any) -> FileContent:
    """
    Backwards compatibility:
    old format used: read_text: str and copy_blocks: list[str]
    """
    if not isinstance(content_raw, dict):
        return FileContent()

    # New format
    if "read_doc" in content_raw or "copy_docs" in content_raw:
        read_doc = content_raw.get("read_doc") or blank_rich_doc()
        copy_docs = content_raw.get("copy_docs") or [blank_rich_doc()]
        if not copy_docs:
            copy_docs = [blank_rich_doc()]
        return FileContent(read_doc=read_doc, copy_docs=copy_docs)

    # Legacy format
    read_text = content_raw.get("read_text", "") or ""
    copy_blocks = content_raw.get("copy_blocks", []) or []
    if not copy_blocks:
        copy_blocks = [""]
    read_doc = {"text": read_text, "tags": []}
    copy_docs = [{"text": s, "tags": []} for s in copy_blocks]
    return FileContent(read_doc=read_doc, copy_docs=copy_docs)


def db_from_dict(data: Dict[str, Any]) -> Database:
    if not isinstance(data, dict):
        return blank_database()

    nodes_raw = data.get("nodes", {})
    nodes: Dict[str, Node] = {}

    # Legacy support: if old file had root_id, treat it as quickcopy root
    legacy_root_id = data.get("root_id")

    for node_id, d in (nodes_raw or {}).items():
        if not isinstance(d, dict):
            continue
        ntype = d.get("type", "folder")
        content = None
        target_id = d.get("target_id")

        if ntype == "file":
            content = _upgrade_legacy_content(d.get("content") or {})

        # Old app used "pinned": bool. We convert pinned files into favorites shortcuts later.
        node = Node(
            id=d.get("id", node_id),
            type=ntype if ntype in ("folder", "file", "shortcut") else "folder",
            name=d.get("name", "Untitled"),
            children=list(d.get("children", [])),
            content=content,
            target_id=target_id,
        )
        nodes[node.id] = node

    # If this is a new-format DB
    qc_root = data.get("quickcopy_root_id")
    fav_root = data.get("favorites_root_id")

    # If legacy: build new roots + attach old root under quickcopy
    if (not qc_root) or (qc_root not in nodes):
        db = blank_database()
        # If legacy root exists and is a folder, attach it inside QuickCopy
        if legacy_root_id and legacy_root_id in nodes and nodes[legacy_root_id].type == "folder":
            # merge nodes
            db.nodes.update(nodes)
            db.nodes[db.quickcopy_root_id].children.append(legacy_root_id)
        else:
            db.nodes.update(nodes)
        return db

    # Ensure favorites root
    if (not fav_root) or (fav_root not in nodes):
        fav = Node(id=new_id(), type="folder", name="Favorites", children=[])
        nodes[fav.id] = fav
        fav_root = fav.id

    db = Database(quickcopy_root_id=qc_root, favorites_root_id=fav_root, nodes=nodes)

    # Convert any old pinned files into favorites shortcuts if "pinned" existed
    # (Safe even if pinned not present)
    for nid, raw in (nodes_raw or {}).items():
        if isinstance(raw, dict) and raw.get("pinned") is True:
            # raw pinned file id => create shortcut in favorites if not already
            file_id = raw.get("id", nid)
            _ensure_favorite_shortcut(db, file_id)

    return db


def _ensure_favorite_shortcut(db: Database, file_id: str):
    fav_root = db.nodes.get(db.favorites_root_id)
    if not fav_root or fav_root.type != "folder":
        return
    # If shortcut already exists, skip
    for cid in fav_root.children:
        n = db.nodes.get(cid)
        if n and n.type == "shortcut" and n.target_id == file_id:
            return
    target = db.nodes.get(file_id)
    if not target or target.type != "file":
        return
    sc = Node(id=new_id(), type="shortcut", name=target.name, target_id=file_id)
    db.nodes[sc.id] = sc
    fav_root.children.append(sc.id)
