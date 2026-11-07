// Small UI toolkit for the touch screen: form rows, number fields (slider + typed value), dialogs, sheets, toasts.

export function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c !== null && c !== undefined && c !== false) el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
}

export const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };

let uid = 0;
const nid = (p) => `${p}_${++uid}`;

export function section(title, sub) {
  return h("div", { class: "sect" }, h("div", { class: "sect-title" }, title), sub ? h("div", { class: "note" }, sub) : null);
}
export const note = (text) => h("div", { class: "note" }, text);

export function button(text, onClick, cls = "") {
  return h("button", { class: "btn " + cls, type: "button", onclick: (e) => { e.preventDefault(); onClick && onClick(e); } }, text);
}

// slider + number box. Double-tap the name to reset (when def is given).
export class NumField {
  constructor(label, lo, hi, step, value, { fmt = 2, onChange = null, def = null, live = true } = {}) {
    this.lo = lo; this.hi = hi; this.step = step; this.fmt = fmt; this.onChange = onChange;
    const id = nid("nf");
    this.range = h("input", { type: "range", min: lo, max: hi, step, id });
    this.box = h("input", { type: "number", min: lo, max: hi, step, inputmode: "decimal", class: "num" });
    this.label = h("label", { for: id, class: "nf-label" }, label);
    this.el = h("div", { class: "nf" }, h("div", { class: "nf-top" }, this.label, this.box), this.range);
    this.set(value);
    this.range.addEventListener("input", () => { this.set(+this.range.value); if (live) this.fire(); });
    this.range.addEventListener("change", () => { if (!live) this.fire(); });
    this.box.addEventListener("change", () => { this.set(+this.box.value); this.fire(); });
    if (def !== null) {
      let last = 0;
      const reset = () => { this.set(def); this.fire(); };
      this.label.addEventListener("dblclick", reset);
      this.label.addEventListener("touchend", () => { const now = Date.now(); if (now - last < 350) reset(); last = now; });
      this.label.title = "Double-tap to reset";
    }
  }
  clamp(v) { v = Number(v); if (!Number.isFinite(v)) v = this.lo; return Math.min(this.hi, Math.max(this.lo, v)); }
  set(v, notify = false) {
    this.v = this.clamp(v);
    this.range.value = this.v;
    this.box.value = Number(this.v.toFixed(this.fmt));
    if (notify) this.fire();
  }
  get() { return this.v; }
  fire() { if (this.onChange) this.onChange(this.v); }
}

export function selectField(label, options, value, onChange) {
  const id = nid("sel");
  const sel = h("select", { id }, ...options.map((o) => {
    const [v, t] = Array.isArray(o) ? o : [o, o];
    return h("option", { value: v }, t);
  }));
  sel.value = String(value);
  sel.addEventListener("change", () => onChange && onChange(sel.value));
  const el = h("div", { class: "row" }, h("label", { for: id }, label), sel);
  return { el, input: sel, set: (v) => { sel.value = String(v); }, get: () => sel.value };
}

export function checkField(label, value, onChange) {
  const id = nid("chk");
  const box = h("input", { type: "checkbox", id });
  box.checked = !!value;
  box.addEventListener("change", () => onChange && onChange(box.checked));
  const el = h("label", { class: "check", for: id }, box, h("span", {}, label));
  return { el, input: box, set: (v) => { box.checked = !!v; }, get: () => box.checked };
}

export function textField(label, value, onChange, { placeholder = "", type = "text", multiline = false, inputmode = null } = {}) {
  const id = nid("txt");
  const input = multiline ? h("textarea", { id, rows: 3, placeholder }) : h("input", { id, type, placeholder, inputmode });
  input.value = value ?? "";
  input.addEventListener(multiline ? "input" : "change", () => onChange && onChange(input.value));
  const el = h("div", { class: multiline ? "col" : "row" }, label ? h("label", { for: id }, label) : null, input);
  return { el, input, set: (v) => { input.value = v ?? ""; }, get: () => input.value };
}

export function colorField(label, value, onChange) {
  const id = nid("col");
  const input = h("input", { type: "color", id });
  input.value = /^#[0-9a-fA-F]{6}$/.test(value) ? value : "#000000";
  const hex = h("span", { class: "hex" }, input.value.toUpperCase());
  input.addEventListener("input", () => { hex.textContent = input.value.toUpperCase(); onChange && onChange(input.value.toUpperCase()); });
  const el = h("div", { class: "row" }, h("label", { for: id }, label), h("div", { class: "colwrap" }, input, hex));
  return { el, input, set: (v) => { input.value = v; hex.textContent = String(v).toUpperCase(); }, get: () => input.value.toUpperCase() };
}

export class Progress {
  constructor() {
    this.fill = h("div", { class: "pfill" });
    this.status = h("div", { class: "status" }, "Ready");
    this.el = h("div", { class: "progress" }, h("div", { class: "pbar" }, this.fill), this.status);
  }
  set(frac, text) {
    if (frac !== null && frac !== undefined) this.fill.style.width = `${Math.round(Math.max(0, Math.min(1, frac)) * 100)}%`;
    if (text !== undefined) this.status.textContent = text;
  }
}

export class LogBox {
  constructor(height = 140) { this.el = h("pre", { class: "log", style: { maxHeight: height + "px" } }); }
  add(line) {
    this.el.textContent += line + "\n";
    if (this.el.textContent.length > 60000) this.el.textContent = this.el.textContent.slice(-40000);
    this.el.scrollTop = this.el.scrollHeight;
  }
  clear() { this.el.textContent = ""; }
}

export class Chips {
  constructor(names, onPick) {
    this.btns = {};
    this.el = h("div", { class: "chips" });
    for (const n of names) {
      const b = h("button", { class: "chip", type: "button", onclick: () => this.pick(n) }, n);
      this.btns[n] = b;
      this.el.append(b);
    }
    this.onPick = onPick;
    this.cur = null;
  }
  pick(n, quiet = false) {
    if (!this.btns[n]) n = Object.keys(this.btns)[0];
    this.cur = n;
    for (const [k, b] of Object.entries(this.btns)) b.classList.toggle("on", k === n);
    this.btns[n].scrollIntoView({ block: "nearest", inline: "center" });
    if (!quiet && this.onPick) this.onPick(n);
  }
}

// ------------------------------------------------------------------ dialogs
let layer = null;
function overlayRoot() {
  if (!layer) { layer = h("div", { id: "modal-layer" }); document.body.append(layer); }
  return layer;
}
const openStack = [];
export function closeTop() {
  const top = openStack.pop();
  if (top) { top.close(top.cancelValue); return true; }
  return false;
}

export function modal(build, { cancelValue = null, cls = "" } = {}) {
  return new Promise((resolve) => {
    const back = h("div", { class: "modal-back" });
    const box = h("div", { class: "modal " + cls });
    back.append(box);
    const entry = {
      cancelValue,
      close: (v) => {
        const i = openStack.indexOf(entry);
        if (i >= 0) openStack.splice(i, 1);
        back.remove();
        resolve(v);
      },
    };
    openStack.push(entry);
    back.addEventListener("click", (e) => { if (e.target === back) entry.close(cancelValue); });
    build(box, entry.close);
    overlayRoot().append(back);
  });
}

export function alertBox(msg, title = "Chauhan Clipping") {
  return modal((box, close) => {
    box.append(h("div", { class: "modal-title" }, title), h("div", { class: "modal-msg" }, msg),
      h("div", { class: "modal-btns" }, button("OK", () => close(true), "primary")));
  }, { cancelValue: true });
}

// buttons: [[label, value, cls], ...]
export function ask(msg, buttons, title = "Chauhan Clipping") {
  return modal((box, close) => {
    box.append(h("div", { class: "modal-title" }, title), h("div", { class: "modal-msg" }, msg),
      h("div", { class: "modal-btns" }, ...buttons.map(([l, v, c]) => button(l, () => close(v), c || ""))));
  });
}
export const confirmBox = (msg, yes = "Yes", no = "No") => ask(msg, [[no, false], [yes, true, "primary"]]);

export function promptBox(msg, value = "", title = "Chauhan Clipping") {
  return modal((box, close) => {
    const input = h("input", { type: "text" });
    input.value = value;
    box.append(h("div", { class: "modal-title" }, title), h("div", { class: "modal-msg" }, msg), input,
      h("div", { class: "modal-btns" }, button("Cancel", () => close(null)), button("OK", () => close(input.value), "primary")));
    setTimeout(() => { input.focus(); input.select(); }, 50);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") close(input.value); });
  });
}

// a full-height sheet with a title and any content; returns {box, close, done}
export function sheet(title, build) {
  return modal((box, close) => {
    box.append(h("div", { class: "sheet-head" }, h("div", { class: "modal-title" }, title), button("Close", () => close(null), "quiet small")));
    const body = h("div", { class: "sheet-body" });
    box.append(body);
    build(body, close);
  }, { cls: "sheet" });
}

let toastEl = null, toastTimer = 0;
export function toast(msg, ms = 2600) {
  if (!toastEl) { toastEl = h("div", { class: "toast" }); document.body.append(toastEl); }
  toastEl.textContent = msg;
  toastEl.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove("show"), ms);
}
