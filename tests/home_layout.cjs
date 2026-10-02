// The Home panel's tile placement, with no browser: homeLayout from web/app.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/app.js', 'utf8');
const code = source.slice(source.indexOf('const HOME_COLS = 4;'), source.indexOf('// A room\'s devices as layout items.'));
const context = vm.createContext({});
vm.runInContext(code + ';this.homeLayout = homeLayout;', context);
const L = (items, pin) => Object.fromEntries([...context.homeLayout(items, pin)].map(([k, v]) => [k, [v.x, v.y, v.w, v.h]]));
const t = (id, w, h, order, x, y) => ({ id, w, h, order, x, y });

// No places yet: first free cell, in order, bars and big squares included.
assert.deepEqual(L([t('a', 1, 1, 0), t('b', 2, 1, 1), t('c', 1, 1, 2), t('d', 2, 2, 3)]),
  { a: [0, 0, 1, 1], b: [1, 0, 2, 1], c: [3, 0, 1, 1], d: [0, 1, 2, 2] });

// A tile held on top of another pushes it down, and what is above moves up.
assert.deepEqual(L([t('a', 1, 1, 0, 0, 0), t('b', 1, 1, 1, 1, 0)], { id: 'c', x: 0, y: 0, w: 1, h: 1 }),
  { c: [0, 0, 1, 1], a: [0, 1, 1, 1], b: [1, 0, 1, 1] });

// A large square pushes a whole row down, and the tiles under it follow.
assert.deepEqual(L([t('a', 1, 1, 0, 0, 0), t('b', 1, 1, 1, 1, 0), t('c', 1, 1, 2, 0, 1)],
  { id: 'big', x: 0, y: 0, w: 2, h: 2 }),
  { big: [0, 0, 2, 2], a: [0, 2, 1, 1], b: [1, 2, 1, 1], c: [0, 3, 1, 1] });

// A gap above is closed; one beside is kept (free placement along a row).
assert.deepEqual(L([t('a', 1, 1, 0, 0, 3), t('b', 1, 1, 1, 3, 5)]), { a: [0, 0, 1, 1], b: [3, 0, 1, 1] });

// A tile held past the right edge is brought back inside.
assert.deepEqual(L([], { id: 'bar', x: 3, y: 0, w: 2, h: 1 }), { bar: [2, 0, 2, 1] });

// Nothing overlaps, whatever the places that were saved.
const crowd = [t('a', 2, 2, 0, 0, 0), t('b', 2, 1, 1, 1, 1), t('c', 1, 1, 2, 0, 0), t('d', 2, 2, 3, 2, 0)];
const spots = [...context.homeLayout(crowd).values()];
for (const p of spots) for (const q of spots) {
  if (p === q) continue;
  assert.ok(p.x + p.w <= q.x || q.x + q.w <= p.x || p.y + p.h <= q.y || q.y + q.h <= p.y, 'tiles overlap');
}
// Dragged to the left, the tiles it lands on make way to the right, and push
// what is in their way along.
const row = [t('a', 1, 1, 0, 0, 0), t('b', 1, 1, 1, 1, 0), t('c', 1, 1, 2, 2, 0)];
assert.deepEqual(L(row, { id: 'p', x: 1, y: 0, w: 1, h: 1, dir: { x: 1, y: 0 } }),
  { p: [1, 0, 1, 1], a: [0, 0, 1, 1], b: [2, 0, 1, 1], c: [3, 0, 1, 1] });
// ...and to the left when it is dragged to the right.
assert.deepEqual(L([t('b', 1, 1, 0, 1, 0), t('c', 1, 1, 1, 2, 0)], { id: 'p', x: 2, y: 0, w: 1, h: 1, dir: { x: -1, y: 0 } }),
  { p: [2, 0, 1, 1], c: [1, 0, 1, 1], b: [0, 0, 1, 1] });
// With no room that way they go down instead.
const crowded = [t('a', 1, 1, 0, 0, 0), t('b', 1, 1, 1, 1, 0), t('c', 1, 1, 2, 2, 0), t('d', 1, 1, 3, 3, 0)];
const full = L(crowded, { id: 'p', x: 0, y: 0, w: 1, h: 1, dir: { x: 1, y: 0 } });
assert.deepEqual(full.p, [0, 0, 1, 1]);
assert.ok(full.d[1] > 0, 'the last one had no room to the right, so it went down');
for (const id of ['a', 'b', 'c']) assert.equal(full[id][1], 0, 'the rest slid along the row');
console.log('Home panel layout checks passed');
