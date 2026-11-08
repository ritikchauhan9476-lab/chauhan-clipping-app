"""Project files: save the whole editing session and open it again later, like any editing software.

A project (.ccproj, a plain JSON file) remembers, for every tab: the movie, the parts, the texts and overlays,
colour / crop / background / export settings, the selected part and the exact position where you stopped.
No GUI code here, so it can be tested on its own.
"""
import json, os, time, hashlib
import engine as E

EXT = ".ccproj"
FORMAT = 1
PROJECT_DIR = os.path.join(E.BASE, "projects")
PREFS_FILE = os.path.join(PROJECT_DIR, "_prefs.json")
UNTITLED_AUTOSAVE = os.path.join(PROJECT_DIR, "_untitled.autosave")


class ProjectError(Exception):
    """A problem with a project file, with a message that can be shown to the user."""


def jsonable(x):
    """Tuples, sets and numpy-like numbers -> plain JSON types."""
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [jsonable(v) for v in x]
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    try:
        return float(x)
    except (TypeError, ValueError):
        return str(x)


def fingerprint(state):
    """Same content -> same text. Used to know whether anything changed since the last save."""
    return hashlib.sha1(json.dumps(jsonable(state), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def save(path, state):
    """Writes the project atomically (a crash while saving can never destroy the old file)."""
    data = {"app": "ChauhanClipping", "format": FORMAT, "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
            "state": jsonable(state)}
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise ProjectError("The project file was not found:\n" + path)
    except (ValueError, OSError) as e:
        raise ProjectError(f"This project file is damaged and could not be read.\n{str(e)[:120]}")
    if not isinstance(data, dict) or data.get("app") != "ChauhanClipping" or "state" not in data:
        raise ProjectError("This is not a Chauhan Clipping project file.")
    if int(data.get("format", 1)) > FORMAT:
        raise ProjectError("This project was saved by a newer version of the software. Please update the software.")
    return data["state"]


def find_movie(saved, project_path=""):
    """The movie of a saved project: the saved path, next to the project file, or in input_movies (same file name).
    Returns "" when it cannot be found."""
    if not saved:
        return ""
    cands = [saved]
    name = os.path.basename(str(saved).replace("\\", "/"))
    if project_path:
        cands.append(os.path.join(os.path.dirname(os.path.abspath(project_path)), name))
    cands.append(os.path.join(E.INPUT_DIR, name))
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return ""


def autosave_path(project_path):
    return (project_path + ".autosave") if project_path else UNTITLED_AUTOSAVE


def newer_autosave(project_path):
    """Path of an autosave that is newer than the saved project (a crash or a closed window left unsaved work)."""
    a = autosave_path(project_path)
    if not os.path.isfile(a):
        return ""
    if project_path and os.path.isfile(project_path) and os.path.getmtime(a) <= os.path.getmtime(project_path):
        return ""
    return a


def remove_autosave(project_path):
    try:
        os.remove(autosave_path(project_path))
    except OSError:
        pass


def read_prefs():
    try:
        with open(PREFS_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_prefs(prefs):
    try:
        os.makedirs(PROJECT_DIR, exist_ok=True)
        with open(PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=1)
    except OSError:
        pass


def title_of(path):
    return os.path.splitext(os.path.basename(path))[0] if path else "Untitled"
