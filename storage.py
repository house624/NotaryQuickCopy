# -*- coding: utf-8 -*-
import json
import os
import sys
from pathlib import Path
from models import Database, blank_database, db_from_dict, db_to_dict


APP_NAME = "NotaryQuickCopy"
DATA_FILENAME = "data.json"


def get_app_data_dir() -> Path:
    """
    Returns the correct per-user application data directory:

    Windows:
        C:\\Users\\<User>\\AppData\\Roaming\\NotaryQuickCopy

    macOS:
        ~/Library/Application Support/NotaryQuickCopy

    Linux:
        ~/.config/NotaryQuickCopy
    """

    if sys.platform.startswith("win"):
        base = Path(os.getenv("APPDATA", Path.home()))
        return base / APP_NAME

    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME

    else:
        # Linux / fallback
        return Path.home() / ".config" / APP_NAME


class Storage:
    def __init__(self, path: str | None = None):
        
        #path is ignored now - kept only for compatibility.
        #Data is always stored in the proper app data directory.
        
        self.app_dir = get_app_data_dir()
        self.app_dir.mkdir(parents=True, exist_ok=True)

        self.path = self.app_dir / DATA_FILENAME

    def load_or_create_blank(self) -> Database:
        if not self.path.exists():
            db = blank_database()
            self.save(db)
            return db
        return self.load()

    def load(self) -> Database:
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return db_from_dict(data)

    def save(self, db: Database):
        data = db_to_dict(db)

        tmp_path = self.path.with_suffix(".tmp")

        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        os.replace(tmp_path, self.path)