"""Preview quality (like Premiere / DaVinci): Full, 1/2, 1/4, 1/8 of the export size for the preview picture and for
Play. Lower = smoother on slow computers; the export is always full quality. One setting for the whole software
(every preview has the menu; changing one changes all, remembered after a restart)."""
QUALITIES = {"Full": 1.0, "1/2": 0.5, "1/4": 0.25, "1/8": 0.125}
DEFAULT = "1/4"
_state = {"value": DEFAULT, "prefs": None, "save": None}
_menus = []          # (StringVar, callback)


def init(prefs, save):
    _state["prefs"], _state["save"] = prefs, save
    v = (prefs or {}).get("preview_quality")
    if v in QUALITIES:
        _state["value"] = v


def value():
    return _state["value"]


def factor():
    return QUALITIES.get(_state["value"], 0.5)


def set_value(v):
    if v not in QUALITIES:
        return
    _state["value"] = v
    p = _state["prefs"]
    if p is not None:
        p["preview_quality"] = v
        try:
            _state["save"] and _state["save"](p)
        except Exception:
            pass
    for var, cb in list(_menus):
        try:
            if var.get() != v:
                var.set(v)
            if cb:
                cb()
        except Exception:
            try:
                _menus.remove((var, cb))
            except ValueError:
                pass


def menu(parent, on_change=None, width=80):
    """An option menu 'Preview: Full / 1/2 / 1/4 / 1/8'. on_change() runs (for every preview) after a change."""
    import tkinter as tk
    import customtkinter as ctk
    var = tk.StringVar(value=_state["value"])
    _menus.append((var, on_change))
    return ctk.CTkOptionMenu(parent, values=list(QUALITIES), variable=var, width=width,
                             command=lambda v: set_value(v))
