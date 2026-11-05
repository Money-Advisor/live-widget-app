// Run:  node --test focus/tests/*.test.cjs
// The CAT flags section (2.9.66): the rules the bar, the sheet and the pop are
// drawn from. Sample wording only - every name, figure and quote is made up.
const test = require('node:test');
const assert = require('node:assert/strict');
const M = require('../model.js');

const stageMsg = (extra) => Object.assign({
  type: 'compliance_alert', missing_items: [], covered_ids: [], stage: 'INCOME',
  sections: [{ key: 'INCOME', label: 'Income', done: 1, total: 4, current: true }],
  section_checks: [{ id: 'i1', label: 'Every source of income', done: false, parts: [] }],
  still_to_do: [], open_criticals: [], warnings: [], trigger_actions: []
}, extra || {});

const item = (id, kind, extra) => Object.assign({
  id: 'cat.flag.' + id, occurrence: 1, kind, pill: 'CAT needs an answer', title: id + ' title',
  section: 'Income', text: id + ' text', why: null, sent_text: null, back: null,
  payments_label: null, payments: [], quote: null, candidates_label: null, candidates: [],
  status: null, listen: null
}, extra || {});

const cat = (items, done) => ({ items: items || [], done: done || [] });

// Today's CAT card in trigger_actions, as the server keeps sending it for older widgets.
const oldCatCard = { id: 'cat.flag.poa', label: 'CAT needs an answer', title: 'CAT needs an answer', severity: 'high',
  message: 'Proof of Address: can the customer send proof of their address?', occurrence: 1, in_cat_section: true };
const correction = { id: 'Q17.X', label: 'Affordability steering', severity: 'critical', message: 'You suggested a figure.', occurrence: 1 };

test('without cat_section there is no CAT section and every card is drawn as before', () => {
  const m = M.newCall();
  const r = M.applyMessage(m, stageMsg({ trigger_actions: [oldCatCard, correction] }), 0, 10);
  assert.equal(m.cat, null);
  assert.equal(M.catView(m), null);
  assert.deepEqual(r.newCat, []);
  assert.deepEqual(m.actions.map(a => a.id).sort(), ['Q17.X', 'cat.flag.poa']);
  assert.equal(M.fixCount(M.attention(m)), 2);
});

test('beside a cat_section, a card marked in_cat_section is not drawn, counted or queued', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ trigger_actions: [oldCatCard, correction], cat_section: cat([item('poa', 'ask')]) }), 0, 10);
  assert.deepEqual(m.actions.map(a => a.id), ['Q17.X']);
  const att = M.attention(m);
  assert.equal(att.some(i => i.row && i.row.id === 'cat.flag.poa'), false);
  assert.equal(M.fixCount(att), 1);
});

test('a card NOT marked in_cat_section is still drawn beside a cat_section', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ trigger_actions: [Object.assign({}, oldCatCard, { in_cat_section: false })], cat_section: cat([]) }), 0, 10);
  assert.deepEqual(m.actions.map(a => a.id), ['cat.flag.poa']);
});

test('an empty cat_section still shows the bar, with nothing to act on', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ cat_section: cat([]) }), 0, 10);
  const v = M.catView(m);
  assert.ok(v);
  assert.equal(v.count, 0);
  assert.equal(v.summary, 'Nothing to act on');
  assert.deepEqual(v.groups, []);
});

test('a good-job message without stage fields keeps the section; a full state without it takes it away', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ cat_section: cat([item('a', 'ask')]) }), 0, 10);
  M.applyMessage(m, { type: 'compliance_alert', missing_items: [], covered_ids: ['i1'] }, 1, 11);
  assert.equal(M.catView(m).count, 1);
  M.applyMessage(m, stageMsg(), 2, 12);
  assert.equal(M.catView(m), null);
});

test('the count is what is to ask, check or confirm - never what is waiting for CAT', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ cat_section: cat([item('a', 'ask'), item('b', 'ask'), item('c', 'check'), item('w', 'waiting')]) }), 0, 10);
  const v = M.catView(m);
  assert.equal(v.count, 3);
  assert.equal(v.summary, '2 to ask · 1 to check');
});

test('with all three kinds to act on, the bar says how many in one figure', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ cat_section: cat([item('a', 'ask'), item('c', 'check'), item('u', 'unsure')]) }), 0, 10);
  assert.equal(M.catView(m).summary, '3 to act on');
  M.applyMessage(m, stageMsg({ cat_section: cat([item('u', 'unsure'), item('v', 'unsure')]) }), 1, 11);
  assert.equal(M.catView(m).summary, '2 to confirm');
});

test('with nothing to act on, the bar says what is waiting for CAT', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ cat_section: cat([item('w', 'waiting'), item('x', 'waiting')]) }), 0, 10);
  const v = M.catView(m);
  assert.equal(v.count, 0);
  assert.equal(v.summary, '2 waiting for CAT');
});

test('flags still in a pop are neither counted nor listed until they land', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ cat_section: cat([item('a', 'ask'), item('c', 'check')]) }), 0, 10);
  const hidden = { 'cat.flag.a#1': true };
  const v = M.catView(m, hidden);
  assert.equal(v.count, 1);
  assert.equal(v.summary, '1 to check');
  assert.deepEqual(v.groups.map(g => g.kind), ['check']);
});

test('the sheet groups in a fixed order - your action, to ask, not sure, waiting - with their headings', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ cat_section: cat([item('w', 'waiting'), item('u', 'unsure'), item('a', 'ask'), item('c', 'check')]) }), 0, 10);
  const g = M.catView(m).groups;
  assert.deepEqual(g.map(x => x.title), ['Check your action', 'To ask', 'Not sure which one', 'Waiting for CAT']);
  assert.deepEqual(g.map(x => x.color), ['var(--red)', 'var(--amb)', 'var(--brand)', 'var(--mute)']);
});

test('an answer CAT turned down comes first in its group; the rest keep the server order', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ cat_section: cat([item('a', 'ask'), item('b', 'ask'),
    item('t', 'ask', { occurrence: 2, pill: 'Back from CAT', back: 'CAT didn’t accept the answer · ask again' })]) }), 0, 10);
  assert.deepEqual(M.catView(m).groups[0].items.map(i => i.id), ['cat.flag.t', 'cat.flag.a', 'cat.flag.b']);
});

test('each kind has its card colour', () => {
  assert.deepEqual(['ask', 'check', 'unsure', 'waiting'].map(M.catFamily), ['high', 'critical', 'next', 'sent']);
});

test('an item of an unknown kind, or with no id, is left out rather than drawn as something else', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ cat_section: cat([item('a', 'ask'), item('z', 'later'), Object.assign(item('n', 'ask'), { id: '' })]) }), 0, 10);
  assert.deepEqual(m.cat.items.map(i => i.id), ['cat.flag.a']);
});

test('a flag is announced once; the same flag coming back with a new occurrence is announced again', () => {
  const m = M.newCall();
  assert.deepEqual(M.applyMessage(m, stageMsg({ cat_section: cat([item('a', 'ask')]) }), 0, 10).newCat, ['cat.flag.a#1']);
  assert.deepEqual(M.applyMessage(m, stageMsg({ cat_section: cat([item('a', 'ask')]) }), 1, 11).newCat, []);
  assert.deepEqual(M.applyMessage(m, stageMsg({ cat_section: cat([item('a', 'ask', { occurrence: 2 })]) }), 2, 12).newCat, ['cat.flag.a#2']);
});

test('waiting for CAT is never announced; the same flag later needing an answer is', () => {
  const m = M.newCall();
  assert.deepEqual(M.applyMessage(m, stageMsg({ cat_section: cat([item('w', 'waiting')]) }), 0, 10).newCat, []);
  assert.deepEqual(M.applyMessage(m, stageMsg({ cat_section: cat([item('w', 'ask', { occurrence: 2 })]) }), 1, 11).newCat, ['cat.flag.w#2']);
});

test('several new flags in one message are announced together, in the server order', () => {
  const m = M.newCall();
  const r = M.applyMessage(m, stageMsg({ cat_section: cat([item('a', 'ask'), item('c', 'check'), item('u', 'unsure')]) }), 0, 10);
  assert.deepEqual(r.newCat, ['cat.flag.a#1', 'cat.flag.c#1', 'cat.flag.u#1']);
});

test('one new flag pops with its own pill and words, in its colour', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ cat_section: cat([item('c', 'check', { pill: 'Check your action', text: 'You dismissed a flag.' })]) }), 0, 10);
  assert.deepEqual(M.catPop(m, ['cat.flag.c#1']), { count: 1, cls: 'critical', pill: 'New · Check your action', text: 'You dismissed a flag.' });
});

test('several new flags are one amber pop listing each by title and section', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ cat_section: cat([item('a', 'ask', { title: 'Unexplained Inflow', section: 'I&E' }),
    item('u', 'unsure', { title: 'Which Aviva payment?', section: 'I&E' })]) }), 0, 10);
  const p = M.catPop(m, ['cat.flag.a#1', 'cat.flag.u#1']);
  assert.equal(p.cls, 'high');
  assert.equal(p.pill, '2 new CAT flags');
  assert.deepEqual(p.list, [{ title: 'Unexplained Inflow', section: 'I&E' }, { title: 'Which Aviva payment?', section: 'I&E' }]);
});

test('a flag that has gone leaves the pop, and a pop with none left is no pop', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ cat_section: cat([item('a', 'ask'), item('b', 'ask')]) }), 0, 10);
  M.applyMessage(m, stageMsg({ cat_section: cat([item('b', 'ask')]) }), 1, 11);
  assert.deepEqual(M.catLive(m, ['cat.flag.a#1', 'cat.flag.b#1']), ['cat.flag.b#1']);
  assert.equal(M.catPop(m, ['cat.flag.a#1', 'cat.flag.b#1']).count, 1);
  M.applyMessage(m, stageMsg({ cat_section: cat([]) }), 2, 12);
  assert.equal(M.catPop(m, ['cat.flag.a#1', 'cat.flag.b#1']), null);
});

test('done items keep their order, and one with no title is left out', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ cat_section: cat([], [{ title: 'Proof of Address', note: 'Answered · CAT accepted' }, { title: ' ', note: 'x' },
    { title: 'Right to remain', note: 'Came up on the call · warning cleared' }]) }), 0, 10);
  assert.deepEqual(M.catView(m).done.map(d => d.title), ['Proof of Address', 'Right to remain']);
});

test('a new call starts with nothing announced', () => {
  const m = M.newCall();
  assert.equal(m.cat, null);
  assert.deepEqual(m.catSeen, {});
});
