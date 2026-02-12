# -*- coding: utf-8 -*-
# bundle_io.py
from __future__ import annotations
import json
from typing import Dict, Any, List, Tuple
from models import Database, Node, new_id

def _collect_subtree(db: Database, node_id: str) -> List[str]:
    out = []
    def walk(nid: str):
        if nid not in db.nodes:
            return
        out.append(nid)
        n = db.nodes[nid]
        if n.type == "folder":
            for cid in n.children:
                walk(cid)
    walk(node_id)
    return out

def export_bundle(db: Database, folder_id: str) -> Dict[str, Any]:
    ids = _collect_subtree(db, folder_id)
    nodes = {}
    for nid in ids:
        n = db.nodes[nid]
        # store raw-ish dict (compatible with our db format)
        nodes[nid] = {
            "id": n.id,
            "type": n.type,
            "name": n.name,
            "children": list(n.children),
            "content": None if n.type == "folder" else {
                "read_rich": n.content.read_rich if n.content else {"text":"", "tags":[]},
                "copy_blocks": n.content.copy_blocks if n.content else [{"text":"", "tags":[]}],
            }
        }
    return {"bundle_root_id": folder_id, "nodes": nodes}

def save_bundle(path: str, bundle: Dict[str, Any]):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)

def load_bundle(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def import_bundle_into_folder(db: Database, bundle: Dict[str, Any], target_folder_id: str) -> Tuple[bool, str]:
    if target_folder_id not in db.nodes or db.nodes[target_folder_id].type != "folder":
        return False, "Target folder is invalid."

    nodes_raw = bundle.get("nodes", {})
    bundle_root_id = bundle.get("bundle_root_id")
    if not nodes_raw or not bundle_root_id or bundle_root_id not in nodes_raw:
        return False, "Bundle is missing required data."

    # Remap IDs to avoid collisions
    id_map: Dict[str, str] = {}
    for old_id in nodes_raw.keys():
        id_map[old_id] = new_id()

    # Create nodes
    for old_id, d in nodes_raw.items():
        newnid = id_map[old_id]
        ntype = d.get("type", "folder")
        name = d.get("name", "Imported")
        children = [id_map[c] for c in d.get("children", []) if c in id_map]
        content = None
        if ntype == "file":
            c = d.get("content") or {}
            content = c  # stored in same shape our models understand
        # Build Node using our models shape
        node = Node(
            id=newnid,
            type=ntype,
            name=name,
            children=children if ntype == "folder" else [],
            content=None,
        )
        if ntype == "file":
            # content is dict; ui/models will upgrade on save/load, but we want runtime content:
            # quick minimal conversion:
            from models import FileContent, blank_rich
            read_rich = c.get("read_rich") if isinstance(c.get("read_rich"), dict) else blank_rich(c.get("read_text",""))
            blocks = c.get("copy_blocks", [])
            upgraded_blocks = []
            for b in blocks:
                upgraded_blocks.append(b if isinstance(b, dict) else blank_rich(str(b)))
            if not upgraded_blocks:
                upgraded_blocks = [blank_rich("")]

            from models import FileContent, blank_rich
            read_rich = c.get("read_rich") if isinstance(c.get("read_rich"), dict) else blank_rich(c.get("read_text",""))
            blocks = c.get("copy_blocks", [])
            upgraded_blocks = []
            for b in blocks:
                upgraded_blocks.append(b if isinstance(b, dict) else blank_rich(str(b)))
            if not upgraded_blocks:
                upgraded_blocks = [blank_rich("")]
            node.content = FileContent(read_rich=read_rich, copy_blocks=upgraded_blocks)


        db.nodes[newnid] = node

    # Attach imported root under target folder
    imported_root_new = id_map[bundle_root_id]
    db.nodes[target_folder_id].children.append(imported_root_new)

    return True, "Imported."

