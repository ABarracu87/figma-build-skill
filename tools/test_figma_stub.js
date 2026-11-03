// node tools/test_figma_stub.js  -> prints "stub test PASS" or throws
const assert = require("assert");
const { createFigma } = require("./figma_stub.js");

(async () => {
  const figma = createFigma({ fonts: ["Inter|Regular", "Inter|Bold"], seed: [{ y: 0, height: 900, name: "existing" }] });

  // the failures the skill warns about must throw here, as they do in Figma
  assert.throws(() => figma.createFrame().resize(-50, 10), /width" failed validation/);
  assert.throws(() => figma.createFrame().appendChild(null), /null child/);
  await assert.rejects(figma.loadFontAsync({ family: "Inter", style: "Semi Bold" }), /could not be loaded/);
  const t = figma.createText();
  assert.throws(() => { t.fontName = { family: "Inter", style: "Bold" }; }, /unloaded font/);

  // after loading, the same calls work
  await figma.loadFontAsync({ family: "Inter", style: "Bold" });
  t.fontName = { family: "Inter", style: "Bold" };
  t.characters = "Hello";
  assert.strictEqual(t.characters, "Hello");

  // seeded frames are on the page, so "never draw at the origin" is testable
  const lowest = Math.max(...figma.currentPage.children.map(n => n.y + n.height));
  assert.strictEqual(lowest, 900);

  // rough auto-layout height: padding + children + spacing
  const col = figma.createFrame();
  Object.assign(col, { layoutMode: "VERTICAL", itemSpacing: 10, paddingTop: 5, paddingBottom: 5 });
  [40, 60].forEach(h => { const r = figma.createRectangle(); r.resize(10, h); col.appendChild(r); });
  assert.strictEqual(figma._layoutHeight(col), 5 + 40 + 10 + 60 + 5);

  figma.closePlugin("Build 15:03 — replaced 0 frames.");
  assert.ok(figma._closed && /Build 15:03/.test(figma._toast));
  console.log("stub test PASS");
})().catch(e => { console.error(e); process.exit(1); });
