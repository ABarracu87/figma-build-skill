// Strict stub of the Figma Plugin API global, for running plugin code locally.
// It throws where Figma throws (negative sizes, unloaded fonts, null children), so a
// build that dies in Figma dies here first. It does NOT emulate text metrics: it proves
// the code runs, never that the layout is right.
//
//   const { createFigma } = require("./figma_stub.js");
//   global.figma = createFigma({ fonts: ["Inter|Regular", "Inter|Bold"], seed: [{ y: 0, height: 900 }] });
//   await require("./your-plugin.js");   // then inspect figma.currentPage.children, figma._toast
//
// fonts: "Family|Style" pairs that loadFontAsync will accept (anything else rejects).
// seed:  frames already on the page, as {x, y, width, height, name}. Seed what the real
//        page holds, or an origin collision never shows up locally.

function createFigma({ fonts = ["Inter|Regular"], seed = [] } = {}) {
  const available = new Set(fonts);
  const loaded = new Set();
  let nextId = 1;

  function node(type) {
    const n = {
      id: `0:${nextId++}`, type, name: type, x: 0, y: 0, width: 100, height: 100,
      parent: null, children: [], fills: [], visible: true, opacity: 1, removed: false,
      layoutMode: "NONE", primaryAxisSizingMode: "AUTO", counterAxisSizingMode: "AUTO",
      itemSpacing: 0, paddingTop: 0, paddingRight: 0, paddingBottom: 0, paddingLeft: 0,
      layoutGrow: 0,
      resize(w, h) {
        if (!(w >= 0)) throw new Error('in resize: Property "width" failed validation');
        if (!(h >= 0)) throw new Error('in resize: Property "height" failed validation');
        this.width = w; this.height = h;
      },
      appendChild(c) {
        if (!c) throw new Error("in appendChild: null child");
        if (c.parent) c.parent.children = c.parent.children.filter(x => x !== c);
        c.parent = this; this.children.push(c);
      },
      remove() {
        this.removed = true;
        if (this.parent) this.parent.children = this.parent.children.filter(x => x !== this);
      },
    };
    return n;
  }

  function text() {
    const t = node("TEXT");
    let font = null, chars = "";
    t.textAutoResize = "NONE";
    Object.defineProperty(t, "fontName", {
      get: () => font,
      set(v) {
        if (!loaded.has(v.family + "|" + v.style))
          throw new Error(`Cannot use unloaded font "${v.family} ${v.style}"`);
        font = v;
      },
    });
    Object.defineProperty(t, "characters", {
      get: () => chars,
      set(v) {
        if (!font && !loaded.has("Inter|Regular"))
          throw new Error('Cannot write to node with unloaded font "Inter Regular"');
        chars = String(v);
      },
    });
    return t;
  }

  // Rough auto-layout height, enough to catch overlapping rows.
  function layoutHeight(f) {
    if (f.layoutMode === "NONE" || f.primaryAxisSizingMode === "FIXED" && f.layoutMode === "VERTICAL") return f.height;
    const kids = f.children.filter(c => c.visible);
    const pad = f.paddingTop + f.paddingBottom;
    if (f.layoutMode === "VERTICAL")
      return pad + kids.reduce((s, c) => s + layoutHeight(c), 0) + Math.max(0, kids.length - 1) * f.itemSpacing;
    return pad + kids.reduce((m, c) => Math.max(m, layoutHeight(c)), 0);
  }

  const page = node("PAGE");
  page.name = "Page 1";
  seed.forEach(s => { const f = node("FRAME"); Object.assign(f, s); page.appendChild(f); });

  return {
    currentPage: page,
    root: { children: [page] },
    createFrame() { const f = node("FRAME"); page.appendChild(f); return f; },
    createRectangle() { const r = node("RECTANGLE"); page.appendChild(r); return r; },
    createText() { const t = text(); page.appendChild(t); return t; },
    loadFontAsync({ family, style }) {
      const k = family + "|" + style;
      if (!available.has(k)) return Promise.reject(new Error(`The font "${family} ${style}" could not be loaded`));
      loaded.add(k); return Promise.resolve();
    },
    notify(msg) { this._toast = msg; },
    closePlugin(msg) { this._toast = msg; this._closed = true; },
    _layoutHeight: layoutHeight,
    _toast: null, _closed: false,
  };
}

module.exports = { createFigma };
