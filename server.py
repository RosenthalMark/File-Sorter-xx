import hashlib
import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static")

BASE_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = BASE_DIR / ".file_sorter_config.json"
INDEX_FILENAME = ".ghost_media_index.json"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm"}
GIF_EXTS = {".gif"}

KEYWORDS = [
    "sissy", "joy", "feet", "tits", "ass",
    "boobs", "booty", "legs", "lingerie", "cosplay",
]

SEP = "_"
RESERVED_DIRS = {"PICS", "VIDS", "GIFS", "DUPES", "NEW CONTENT"}

JOBS = {}


def _load_cfg() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cfg(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def get_output_dir() -> Path:
    cfg = _load_cfg()
    p = cfg.get("output_dir")
    if p:
        return Path(p).expanduser()
    # default output lives next to your code
    return BASE_DIR / "MEDIA_MAIN"


def set_output_dir(p: Path) -> None:
    cfg = _load_cfg()
    cfg["output_dir"] = str(p)
    _save_cfg(cfg)


def get_source_dir() -> Path:
    cfg = _load_cfg()
    p = cfg.get("source_dir")
    if p:
        return Path(p).expanduser()
    # default source = output (so it "just works" on first run)
    return get_output_dir()


def set_source_dir(p: Path) -> None:
    cfg = _load_cfg()
    cfg["source_dir"] = str(p)
    _save_cfg(cfg)


def folders_for(output_dir: Path) -> dict:
    return {
        "PICS": output_dir / "PICS",
        "VIDS": output_dir / "VIDS",
        "GIFS": output_dir / "GIFS",
        "DUPES": output_dir / "DUPES",
        "NEW": output_dir / "NEW CONTENT",
    }


def ensure_output_folders() -> None:
    out_dir = get_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in folders_for(out_dir).values():
        p.mkdir(parents=True, exist_ok=True)


def index_path(output_dir: Path) -> Path:
    return output_dir / INDEX_FILENAME


def load_index(output_dir: Path) -> dict:
    idx_path = index_path(output_dir)
    if idx_path.exists():
        try:
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
        except Exception:
            idx = {}
    else:
        idx = {}

    idx.setdefault("hash_to_key", {})
    idx.setdefault("key_to_meta", {})
    idx.setdefault("next_id", {"PIC": 1, "VID": 1, "GIF": 1})

    # For "copy mode" scanning: remember which source paths we already processed
    idx.setdefault("hash_to_sources", {})  # hash -> list[str]

    return idx


def save_index(output_dir: Path, index: dict) -> None:
    idx_path = index_path(output_dir)
    idx_path.write_text(json.dumps(index, indent=2), encoding="utf-8")


def classify(ext: str) -> Optional[str]:
    e = ext.lower()
    if e in GIF_EXTS:
        return "GIF"
    if e in IMAGE_EXTS:
        return "PIC"
    if e in VIDEO_EXTS:
        return "VID"
    return None


def first_keyword_tag(stem: str) -> Optional[str]:
    lowered = stem.lower()
    for kw in KEYWORDS:
        if kw in lowered:
            return kw
    return None


def sanitize_piece(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-_]+", "", s)
    return s[:24]


def pad_id(n: int) -> str:
    return str(n).zfill(6)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def safe_write_unique(dest_dir: Path, filename: str, data: bytes) -> Path:
    dest = dest_dir / filename
    if not dest.exists():
        dest.write_bytes(data)
        return dest

    stem = dest.stem
    ext = dest.suffix
    i = 2
    while True:
        cand = dest_dir / f"{stem}{SEP}{i}{ext}"
        if not cand.exists():
            cand.write_bytes(data)
            return cand
        i += 1


def safe_copy_unique(src: Path, dest_dir: Path, filename: str) -> Path:
    dest = dest_dir / filename
    if not dest.exists():
        shutil.copy2(str(src), str(dest))
        return dest

    stem = dest.stem
    ext = dest.suffix
    i = 2
    while True:
        cand = dest_dir / f"{stem}{SEP}{i}{ext}"
        if not cand.exists():
            shutil.copy2(str(src), str(cand))
            return cand
        i += 1


def should_skip_scan_path(source_dir: Path, output_dir: Path, p: Path) -> bool:
    # Do not scan the output folder if it is inside the source folder
    try:
        if output_dir == p or output_dir in p.parents:
            return True
    except Exception:
        pass

    # Skip reserved folders if they exist in source
    try:
        rel_parts = p.relative_to(source_dir).parts
        if any(part in RESERVED_DIRS for part in rel_parts):
            return True
    except Exception:
        return True

    # Skip index file if it sits in source
    if p.name == INDEX_FILENAME:
        return True

    return False


def process_bytes_into_output(output_dir: Path, index: dict, original_name: str, data: bytes) -> dict:
    folders = folders_for(output_dir)
    hash_to_key = index["hash_to_key"]
    key_to_meta = index["key_to_meta"]
    next_id = index["next_id"]

    ext = Path(original_name).suffix.lower()
    media_type = classify(ext)

    if not data:
        return {"file": original_name, "status": "skipped", "reason": "empty"}
    if not media_type:
        return {"file": original_name, "status": "skipped", "reason": "unsupported type"}

    h = sha256_bytes(data)

    if h in hash_to_key:
        existing_key = hash_to_key.get(h)
        clean_stem = sanitize_piece(Path(original_name).stem) or "file"
        dupe_name = f"DUPE{SEP}{existing_key or 'UNKNOWN'}{SEP}{clean_stem}{ext}"
        saved = safe_write_unique(folders["DUPES"], dupe_name, data)
        return {
            "file": original_name,
            "status": "dupe",
            "copied_to": str(saved.relative_to(output_dir)),
            "matches_key": existing_key
        }

    tag = first_keyword_tag(Path(original_name).stem)
    tag_piece = sanitize_piece(tag)

    type_counter = int(next_id.get(media_type, 1))
    assigned_id = pad_id(type_counter)
    next_id[media_type] = type_counter + 1

    key = f"{media_type}{SEP}{assigned_id}"

    if media_type == "PIC":
        dest_dir = folders["PICS"]
    elif media_type == "VID":
        dest_dir = folders["VIDS"]
    else:
        dest_dir = folders["GIFS"]

    if tag_piece:
        new_name = f"{media_type}{SEP}{tag_piece}{SEP}{assigned_id}{ext}"
    else:
        new_name = f"{media_type}{SEP}{assigned_id}{ext}"

    saved = safe_write_unique(dest_dir, new_name, data)

    hash_to_key[h] = key
    key_to_meta[key] = {
        "original_name": original_name,
        "stored_as": str(saved.relative_to(output_dir)),
        "type": media_type,
        "tag": tag_piece or None,
        "sha256": h,
        "processed_at": datetime.now().isoformat(timespec="seconds"),
        "size_bytes": len(data),
    }

    return {
        "file": original_name,
        "status": "processed",
        "copied_to": str(saved.relative_to(output_dir)),
        "key": key
    }


def process_file_copy(source_path: Path, output_dir: Path, index: dict) -> dict:
    folders = folders_for(output_dir)
    hash_to_key = index["hash_to_key"]
    key_to_meta = index["key_to_meta"]
    next_id = index["next_id"]
    hash_to_sources = index["hash_to_sources"]

    original_name = source_path.name
    ext = source_path.suffix.lower()
    media_type = classify(ext)
    if not media_type:
        return {"file": original_name, "status": "skipped", "reason": "unsupported type"}

    h = sha256_file(source_path)
    src_str = str(source_path)
    sources = hash_to_sources.get(h, [])

    # If we have already processed this exact source path, skip it
    if src_str in sources:
        return {"file": original_name, "status": "skipped", "reason": "already processed"}

    # If hash exists from previous items, treat as dupe
    if h in hash_to_key:
        existing_key = hash_to_key.get(h)
        clean_stem = sanitize_piece(source_path.stem) or "file"
        dupe_name = f"DUPE{SEP}{existing_key or 'UNKNOWN'}{SEP}{clean_stem}{ext}"
        saved = safe_copy_unique(source_path, folders["DUPES"], dupe_name)

        sources.append(src_str)
        hash_to_sources[h] = sources

        return {
            "file": original_name,
            "status": "dupe",
            "copied_to": str(saved.relative_to(output_dir)),
            "matches_key": existing_key
        }

    tag = first_keyword_tag(source_path.stem)
    tag_piece = sanitize_piece(tag)

    type_counter = int(next_id.get(media_type, 1))
    assigned_id = pad_id(type_counter)
    next_id[media_type] = type_counter + 1

    key = f"{media_type}{SEP}{assigned_id}"

    if media_type == "PIC":
        dest_dir = folders["PICS"]
    elif media_type == "VID":
        dest_dir = folders["VIDS"]
    else:
        dest_dir = folders["GIFS"]

    if tag_piece:
        new_name = f"{media_type}{SEP}{tag_piece}{SEP}{assigned_id}{ext}"
    else:
        new_name = f"{media_type}{SEP}{assigned_id}{ext}"

    saved = safe_copy_unique(source_path, dest_dir, new_name)

    hash_to_key[h] = key
    key_to_meta[key] = {
        "original_name": original_name,
        "stored_as": str(saved.relative_to(output_dir)),
        "type": media_type,
        "tag": tag_piece or None,
        "sha256": h,
        "processed_at": datetime.now().isoformat(timespec="seconds"),
        "size_bytes": int(saved.stat().st_size),
    }

    sources.append(src_str)
    hash_to_sources[h] = sources

    return {
        "file": original_name,
        "status": "processed",
        "copied_to": str(saved.relative_to(output_dir)),
        "key": key
    }


@app.get("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/paths")
def api_paths():
    ensure_output_folders()
    return jsonify({
        "ok": True,
        "source_dir": str(get_source_dir()),
        "output_dir": str(get_output_dir()),
    })


@app.get("/api/choose_source")
def api_choose_source():
    try:
        r = subprocess.run(
            ["osascript", "-e", 'POSIX path of (choose folder with prompt "Choose SOURCE folder to scan")'],
            capture_output=True,
            text=True,
            check=True,
        )
        chosen = r.stdout.strip()
        if not chosen:
            return jsonify({"ok": False, "error": "No folder chosen"}), 400
        set_source_dir(Path(chosen))
        return jsonify({"ok": True, "source_dir": str(get_source_dir())})
    except subprocess.CalledProcessError:
        return jsonify({"ok": False, "error": "Folder chooser cancelled"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/api/choose_output")
def api_choose_output():
    try:
        r = subprocess.run(
            ["osascript", "-e", 'POSIX path of (choose folder with prompt "Choose OUTPUT folder (sorted results go here)")'],
            capture_output=True,
            text=True,
            check=True,
        )
        chosen = r.stdout.strip()
        if not chosen:
            return jsonify({"ok": False, "error": "No folder chosen"}), 400
        set_output_dir(Path(chosen))
        ensure_output_folders()
        return jsonify({"ok": True, "output_dir": str(get_output_dir())})
    except subprocess.CalledProcessError:
        return jsonify({"ok": False, "error": "Folder chooser cancelled"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/api/open_output")
def api_open_output():
    ensure_output_folders()
    try:
        subprocess.Popen(["open", str(get_output_dir())])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/api/upload")
def upload():
    ensure_output_folders()
    output_dir = get_output_dir()
    index = load_index(output_dir)

    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "error": "No files uploaded"}), 400

    results = []
    counts = {"processed": 0, "dupes": 0, "skipped": 0}

    for f in files:
        original_name = f.filename or "unnamed"
        data = f.read()

        res = process_bytes_into_output(output_dir, index, original_name, data)

        if res["status"] == "processed":
            counts["processed"] += 1
        elif res["status"] == "dupe":
            counts["dupes"] += 1
        else:
            counts["skipped"] += 1

        results.append(res)

    save_index(output_dir, index)
    return jsonify({"ok": True, "counts": counts, "results": results})


def _run_process_folder(job_id: str):
    ensure_output_folders()
    source_dir = get_source_dir()
    output_dir = get_output_dir()
    index = load_index(output_dir)

    candidates = []
    for p in source_dir.rglob("*"):
        if not p.is_file():
            continue
        if should_skip_scan_path(source_dir, output_dir, p):
            continue
        candidates.append(p)

    JOBS[job_id]["total"] = len(candidates)

    counts = {"processed": 0, "dupes": 0, "skipped": 0}

    for i, p in enumerate(candidates, start=1):
        JOBS[job_id]["current"] = i
        JOBS[job_id]["current_file"] = str(p)

        try:
            res = process_file_copy(p, output_dir, index)
            st = res.get("status")
            if st == "processed":
                counts["processed"] += 1
            elif st == "dupe":
                counts["dupes"] += 1
            else:
                counts["skipped"] += 1
        except Exception as e:
            counts["skipped"] += 1
            JOBS[job_id]["last_error"] = str(e)

        JOBS[job_id]["counts"] = counts

    save_index(output_dir, index)
    JOBS[job_id]["done"] = True
    JOBS[job_id]["ended_at"] = time.time()


@app.post("/api/process_folder")
def api_process_folder():
    ensure_output_folders()
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {
        "job_id": job_id,
        "done": False,
        "total": 0,
        "current": 0,
        "current_file": None,
        "counts": {"processed": 0, "dupes": 0, "skipped": 0},
        "started_at": time.time(),
        "ended_at": None,
        "last_error": None,
        "source_dir": str(get_source_dir()),
        "output_dir": str(get_output_dir()),
    }

    t = threading.Thread(target=_run_process_folder, args=(job_id,), daemon=True)
    t.start()

    return jsonify({"ok": True, "job_id": job_id})


@app.get("/api/job/<job_id>")
def api_job(job_id: str):
    j = JOBS.get(job_id)
    if not j:
        return jsonify({"ok": False, "error": "Unknown job"}), 404
    return jsonify({"ok": True, "job": j})


@app.get("/api/stats")
def stats():
    ensure_output_folders()
    output_dir = get_output_dir()
    index = load_index(output_dir)
    return jsonify({
        "ok": True,
        "source_dir": str(get_source_dir()),
        "output_dir": str(output_dir),
        "next_id": index.get("next_id", {"PIC": 1, "VID": 1, "GIF": 1}),
        "total_indexed": len(index.get("hash_to_key", {})),
    })


@app.get("/<path:path>")
def static_proxy(path):
    return send_from_directory(app.static_folder, path)


if __name__ == "__main__":
    ensure_output_folders()
    app.run(host="127.0.0.1", port=5050, debug=False, use_reloader=False)