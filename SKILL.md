---
name: figma-build
description: Building Figma and FigJam content from a plugin — the sizing and font rules that fail silently, the clamps that stop one bad value killing a build, reading comments back through the REST API, and the loop that tells you whether your code actually ran. Use when writing or debugging a Figma plugin, generating frames or wireframes programmatically, or when a build aborts mid-draw, a layout collapses, text wraps one character per line, frames overlap something already on the page, or it "looks the same" after a rebuild.
---

# Figma build

Everything here failed silently first. Nothing throws, nothing warns, and the
canvas just looks wrong.

## The loop, before anything else

**Stamp the build and clear your own output.** Otherwise you can debug "it looks
the same" for a long time when Figma is serving a cached bundle.

```js
const BUILD = "15:03";                 // bump on every bundle
function clearPrevious() {
  const mine = figma.currentPage.children.filter(n => /^\d\d · /.test(n.name));
  mine.forEach(n => n.remove());
  return mine.length;
}
figma.closePlugin("Build " + BUILD + " — replaced " + removed + " frames.");
```

Two numbers in the toast, and both are diagnostic. A stale stamp means the
bundle is cached: remove the plugin, re-import the manifest, reopen the tab.
`Replaced 0` with frames visibly on the canvas means the same thing.

Without this, a plugin that re-creates frames stacks a second set on top of the
first and nothing tells you which you are looking at. Counting copies of a
frame name is how you prove whether a run happened at all.

---

## One bad value kills the whole build

Every failure in this file is the same shape: a single value the API rejects,
thrown mid-draw, leaving a half-rendered page that reads as a *layout* problem.
Typical culprits: a negative width, a pinned 10px text height, an unloaded font
weight.

**Clamp at the boundary instead of trusting the arithmetic.**

```js
function W1(v, min){ const n = Number(v); return (isFinite(n) && n > 0) ? n : (min || 1); }
```

Route every width, height and text width through it. A clamp costs one
wrong-looking box; a throw costs the page.

The arithmetic that bites is a fixed subtraction that only holds at one width:

```js
const FEED = DW - PAD*2 - 400;   // 840 at 1440.  MINUS 50 at 390.
```

Any constant subtracted from the canvas width needs a breakpoint guard, or it
goes negative on the small one.

**Symptom to recognise:** the wide frames look finished and the narrow ones are
absent or half-drawn, overlapping something else. That is not a positioning bug.
Read the error toast — it names the property and the node.

---

## Never draw at the origin

A plugin that starts at `(0, 0)` lands on top of whatever is already there, and
a cleaner that only removes its *own* frames will not save you: two plugins
sharing a page both believe the canvas is empty.

Measure first, then start clear:

```js
let startY = 0;
figma.currentPage.children.forEach(n => { startY = Math.max(startY, n.y + n.height); });
if (figma.currentPage.children.length) startY += 600;
```

Label each row on the canvas, and make the cleaner match everything the build
emits — frames *and* labels — or re-running leaves orphan text behind.

---

## Text sizing, in this exact order

The single most expensive mistake. Figma recomputes a text node's height when
its **content** changes, not when you resize it.

```js
const str = String(s);
const t = figma.createText();
t.fontName = { family: "Inter", style: weight };
t.characters = str;                    // 1. FIRST
t.fontSize = size;                     // 2. styles next
t.lineHeight = { unit: "PERCENT", value: 145 };
if (width) {
  t.textAutoResize = "HEIGHT";         // 3. does NOT stick on an empty node
  t.resize(width, t.height);           //    never a literal height
  t.characters = str;                  // 4. force a re-measure at the new width
} else {
  t.textAutoResize = "WIDTH_AND_HEIGHT";
}
```

- `textAutoResize = "HEIGHT"` set **before** the node has characters is dropped.
  Reordering to put content last without moving the property makes it worse.
- `resize(w, 10)` pins the height at 10 forever. Pass `t.height`.
- Re-assigning the same string is the belt-and-braces re-measure.

**Symptom:** every text with an explicit width is ~10px tall, every text without
one is correct, and every frame whose height comes only from text collapses to
its padding.

---

## `width` means fixed width — which axis is not obvious

```js
if (opts.horizontal) {
  f.primaryAxisSizingMode = width ? "FIXED" : "AUTO";   // width IS the primary axis
  f.counterAxisSizingMode = "AUTO";
} else {
  f.counterAxisSizingMode = width ? "FIXED" : "AUTO";   // width is the counter axis
  f.primaryAxisSizingMode = "AUTO";
}
```

Setting `counterAxisSizingMode` on a horizontal frame fixes its **height** and
leaves the width hugging. Every row built that way has no spare width, so no
child can grow into it.

**Resize before setting the sizing modes**, or the explicit size fights the hug.

---

## A column that fills a row

```js
function growCol(n) { n.layoutGrow = 1; n.counterAxisSizingMode = "FIXED"; return n; }
```

A vertical frame created with `width: null` hugs. Give it `layoutGrow = 1` and
STRETCH children and you have a circular constraint: the parent sizes to the
children, the children size to the parent. Figma resolves it at the minimum.

**Symptom:** cards ~45px wide, body copy wrapping **one character per line**,
text nodes reporting `1 x 988`. Page frames three times taller than they should
be, entirely from bogus vertical space.

Prefer passing rows an explicit width over relying on STRETCH to resolve.

---

## Measure, do not look

Geometry answers the question faster than a screenshot, and it exposes every bug
above. Pull `get_metadata`, then:

- **heights ≤ 12px** → collapsed text or frames
- **widths of 1** → the circular constraint above
- **a page far taller than its HTML equivalent** → narrow wrapping, not content
- **one copy of each frame when you expected two** → the run never happened

Sanity-check totals: a block's y-ranges should tile its page with no gaps, and
the last block should end exactly at the page height.

---

## Simulating the plugin locally

A stub of the `figma` global catches throws, null appends and structural
mistakes before a round-trip. It cannot emulate text metrics, so it proves the
code runs, never that the layout is right.

**Make the stub as strict as the real API**, or it will pass builds that die in
Figma. Each of these is a bug that reached the canvas because the stub was
lenient:

```js
resize(w, h){
  if (!(w >= 0)) throw new Error('in resize: Property "width" failed validation');
  if (!(h >= 0)) throw new Error('in resize: Property "height" failed validation');
  ...
}
set fontName(v){
  if (!loaded.has(v.family + "|" + v.style))
    throw new Error('Cannot use unloaded font "' + v.family + " " + v.style + '"');
  ...
}
appendChild(c){ if (!c) throw new Error("null child"); ... }
```

Give the stub `currentPage.children`, and **seed it with the frames the real
page already holds** — that is how an origin collision shows up locally.

To check positioning, the stub also needs to compute auto-layout heights: sum
the children plus `itemSpacing` and padding for a VERTICAL frame, take the max
for a HORIZONTAL one, and return the fixed value when
`primaryAxisSizingMode === "FIXED"`. Rough is enough to catch row overlap.

Run every dispatch path, every breakpoint and every font setup, not just the
happy one:

```
Inter only · Inter + mono · all three · Inter Regular only
desktop · mobile     dark · light
```

---

## Fonts: load what you will ask for, and resolve what you get

Assigning an unloaded font throws. Two traps behind that:

- **You must pre-load every weight the code asks for.** Loading Regular, Medium
  and Bold and then requesting Semi Bold is a crash waiting for the one card
  that uses it.
- **The style name differs per family.** Inter says `"Semi Bold"`; JetBrains
  Mono says `"SemiBold"`. Asking for the right weight with the wrong spelling
  still throws.

Probe each weight separately, record what actually loaded, and resolve every
request through a fallback chain rather than assuming:

```js
const ALIAS = { "Semi Bold": ["Semi Bold","SemiBold","Medium","Bold","Regular"], … };
function font(family, style){
  for (const s of ALIAS[style]) if (LOADED[family+"|"+s]) return { family, style:s };
  for (const s of ALIAS[style]) if (LOADED["Inter|"+s]) return { family:"Inter", style:s };
  return { family:"Inter", style:"Regular" };
}
```

Never pre-load strictly in the entry point with `Promise.all` — one missing
weight there kills a build that the resolver would have handled. Report the
families you resolved to in the closing toast.

---

## One plugin, one job

Resist a dispatch switch inside a single plugin — on editor type, page name, or
selection. A page-name switch means the user must perform a ritual before the
thing works, and when it silently does the wrong thing there is nothing to read.

Two manifests with different `id` and `name` values cost nothing and remove the
whole class of problem. Figma also reuses a cached registration when a
re-imported manifest carries an `id` it already knows, so changing the `id` is
how you force a clean load.

---

## Reading comments back out

The MCP exposes `get_metadata`, `get_design_context`, `get_screenshot`,
`get_figjam`, `use_figma` — **none of them read comments**, and the Plugin API
has no comments access either. Comments live in the REST API.

```bash
curl -s -H "X-Figma-Token: $TOKEN" \
  "https://api.figma.com/v1/files/$KEY/comments"
```

Scope: **File comments → Read**. Store the token in a file (`~/.figma-token`,
chmod 600), never in the conversation. If the person cannot run a shell command,
write the file with a placeholder and `open -a TextEdit` it for them to paste into.

`/v1/me` returns **403** on a comments-scoped token. That is expected, not a
broken token. `/v1/files/:key/nodes` also 403s without `file_content:read`.

Each comment carries `client_meta`:

```json
{ "node_id": "2:95", "node_offset": { "x": 279, "y": 1257 } }
```

Map it to a block by pulling `get_metadata` and finding the child frame whose
y-range contains the offset. Threads come back flat — group by `parent_id`, and
replies often carry the actual instruction while the root is only a pointer.

Comments are per file. Moving content to a new file leaves them behind.

---

## Screenshots at scale

One capture per page plus local crops beats one call per block. Block y/height
comes from `get_metadata`, `maxDimension` at or above the frame height gives 1:1,
and the crops line up exactly.
