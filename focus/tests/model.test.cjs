// Run:  node --test focus/tests
// Every rule here is a classic-widget rule the Focus panel must keep.
const test = require('node:test');
const assert = require('node:assert/strict');
const M = require('../model.js');

const stageMsg = (extra) => Object.assign({
  type: 'compliance_alert', missing_items: [], covered_ids: [], stage: 'INCOME',
  sections: [{ key: 'ONB', label: 'Onboarding', done: 5, total: 5, current: false },
             { key: 'INCOME', label: 'Income', done: 1, total: 4, current: true },
             { key: 'EXP', label: 'Expenditure', done: 0, total: 6, current: false }],
  section_checks: [
    { id: 'i1', label: 'Take-home pay asked', done: true, evidence: 'what comes in', parts: [] },
    { id: 'i2', label: 'Every source of income', done: false, prompt: 'Ask about all income',
      missing_parts: ['Partner'], parts: [{ text: 'Partner', done: false, na: false }, { text: 'Benefits', done: true, na: false }] },
    { id: 'i3', label: 'Evidence of benefits', done: false, parts: [] }],
  still_to_do: [], open_criticals: [], warnings: [], trigger_actions: []
}, extra || {});

const card = (id, extra) => Object.assign({ id, label: id + ' label', severity: 'high',
  message: id + ' message', script: 'say ' + id, alternatives: [], occurrence: 1 }, extra || {});

test('a good-job message without stage fields never blanks the checklist or the cards', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ trigger_actions: [card('A')] }), 0, 10);
  M.applyMessage(m, { type: 'compliance_alert', missing_items: [], covered_ids: ['i1'], praise: [{ id: 'i1' }] }, 1, 11);
  assert.equal(m.checks.length, 3);
  assert.equal(m.actions.length, 1);
  assert.equal(M.stageInfo(m).label, 'Income');
});

test('the newest correction card is always first, whatever order the server sends', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ trigger_actions: [card('OLD')] }), 0, 10);
  M.applyMessage(m, stageMsg({ trigger_actions: [card('OLD'), card('NEW')] }), 5, 20);
  const keys = M.attention(m).filter(i => i.kind === 'high').map(i => i.row.id);
  assert.deepEqual(keys, ['NEW', 'OLD']);
});

test('a new card is reported as new exactly once', () => {
  const m = M.newCall();
  assert.equal(M.applyMessage(m, stageMsg({ trigger_actions: [card('A')] }), 0, 1).newCard, true);
  assert.equal(M.applyMessage(m, stageMsg({ trigger_actions: [card('A')] }), 1, 2).newCard, false);
});

test('a card that clears itself goes after its seconds and never comes back', () => {
  const m = M.newCall();
  const c = card('G', { coaching_only: true, script: null, auto_clear_seconds: 60 });
  M.applyMessage(m, stageMsg({ trigger_actions: [c] }), 0, 10);
  assert.equal(M.expire(m, 59000), false);
  assert.equal(m.actions.length, 1);
  assert.equal(M.expire(m, 60000), true);
  assert.equal(m.actions.length, 0);
  M.applyMessage(m, stageMsg({ trigger_actions: [c] }), 61000, 70);   // server keeps sending it
  assert.equal(m.actions.length, 0);
});

test('the same mistake made a second time is a second card, even after the first expired', () => {
  const m = M.newCall();
  const first = card('G', { auto_clear_seconds: 0, occurrence: 1 });
  M.applyMessage(m, stageMsg({ trigger_actions: [first] }), 0, 1);
  M.expire(m, 1);
  M.applyMessage(m, stageMsg({ trigger_actions: [first, card('G', { auto_clear_seconds: 0, occurrence: 2 })] }), 2, 3);
  assert.deepEqual(m.actions.map(r => r.occurrence), [2]);
});

test('an auto-clear of zero means immediately, not never', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ trigger_actions: [card('Z', { auto_clear_seconds: 0 })] }), 0, 1);
  assert.equal(M.expire(m, 0), true);
});

test('the safety card is shown once, taken down when resolved, and never raised again', () => {
  const m = M.newCall();
  M.applyMessage(m, { type: 'crisis_alert', line: 'script', resources: [] }, 0, 1);
  assert.equal(M.attention(m)[0].kind, 'safety');
  M.applyMessage(m, stageMsg({ crisis_resolved: true }), 1, 2);
  assert.equal(M.attention(m).some(i => i.kind === 'safety'), false);
  M.applyMessage(m, { type: 'crisis_alert', line: 'script', resources: [] }, 2, 3);
  assert.equal(M.attention(m).some(i => i.kind === 'safety'), false);
});

test('safety outranks a correction, and a correction outranks the next thing to say', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ trigger_actions: [card('A', { severity: 'critical' })] }), 0, 1);
  M.applyMessage(m, { type: 'crisis_alert', line: 's', resources: [] }, 1, 2);
  assert.deepEqual(M.attention(m).map(i => i.kind), ['safety', 'critical', 'next']);
});

test('only severity critical is drawn as critical; high and normal are put-right amber', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ trigger_actions: [card('C', { severity: 'critical' }), card('N', { severity: 'normal' })] }), 0, 1);
  const k = Object.fromEntries(M.attention(m).filter(i => i.row && i.row.id).map(i => [i.row.id, i.kind]));
  assert.equal(k.C, 'critical');
  assert.equal(k.N, 'high');
});

test('vulnerability questions made due by a disclosure come before the next ordinary check', () => {
  const m = M.newCall();
  const msg = stageMsg();
  msg.section_checks.push({ id: 'v1', label: 'Ask if safe', done: false, urgent: true, urgent_reason: 'A vulnerability has been disclosed - ask these now' });
  msg.section_checks.push({ id: 'v2', label: 'Ask about support', done: false, urgent: true });
  M.applyMessage(m, msg, 0, 1);
  const a = M.attention(m);
  assert.deepEqual(a.map(i => i.kind), ['urgent', 'next']);
  assert.equal(a[0].rows.length, 2);
  assert.equal(a[1].row.id, 'i2');
});

test('critical checks left behind in an earlier stage are queued, not dropped', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ open_criticals: [{ id: 'dpa', label: 'Data protection', section_label: 'Onboarding' }] }), 0, 1);
  assert.ok(M.attention(m).some(i => i.kind === 'missed' && i.row.id === 'dpa'));
});

test('the next thing to say is the first outstanding check in the stage', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg(), 0, 1);
  assert.equal(M.attention(m).find(i => i.kind === 'next').row.id, 'i2');
});

test('the old matcher, with no stages, still gets a next thing to say - the red one first', () => {
  const m = M.newCall();
  M.applyMessage(m, { type: 'compliance_alert', missing_items: [
    { id: 'a', label: 'Amber thing', level: 'amber' }, { id: 'r', label: 'Red thing', level: 'red', suggestion_text: 'Say it' }] }, 0, 1);
  const n = M.attention(m).find(i => i.kind === 'next');
  assert.equal(n.row.id, 'r');
  assert.equal(n.row.prompt, 'Say it');
});

test('a forbidden phrase is a critical card, shown once however often it is sent', () => {
  const m = M.newCall();
  M.applyMessage(m, { type: 'compliance_alert', forbidden_hits: [{ id: 'f', label: 'guaranteed' }] }, 0, 1);
  M.applyMessage(m, { type: 'compliance_alert', forbidden_hits: [{ id: 'f', label: 'guaranteed' }] }, 1, 2);
  const f = M.attention(m).filter(i => i.forbidden);
  assert.equal(f.length, 1);
  assert.equal(f[0].kind, 'critical');
});

test('a forbidden-only message never touches the checklist', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg(), 0, 1);
  M.applyMessage(m, { type: 'compliance_alert', forbidden_hits: [{ id: 'f', label: 'x' }], missing_items: [] }, 1, 2);
  assert.equal(m.checks.length, 3);
});

test('a forbidden-only message leaves the old matcher’s missing list as it was', () => {
  // The classic panel returns before update_missing on such a message, so
  // the outstanding chips stay on screen (_handle_server_message).
  const m = M.newCall();
  M.applyMessage(m, { type: 'compliance_alert', missing_items: [{ id: 'r', label: 'Explain fees', level: 'red' }] }, 0, 1);
  M.applyMessage(m, { type: 'compliance_alert', forbidden_hits: [{ id: 'f', label: 'x' }], missing_items: [] }, 1, 2);
  assert.equal(m.missing.length, 1);
  assert.equal(M.attention(m).find(i => i.kind === 'next').row.id, 'r');
});

test('parts the customer ruled out leave the count; a done one stays', () => {
  const parts = M.liveParts({ parts: [{ text: 'a', done: false, na: true }, { text: 'b', done: true, na: true }, { text: 'c', done: false, na: false }] });
  assert.deepEqual(parts.map(p => p.text), ['b', 'c']);
});

test('the stage bar marks done, here and to-do, and a finished later stage stays done', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg(), 0, 1);
  const s = M.stageInfo(m);
  assert.deepEqual(s.segments, ['done', 'here', 'todo']);
  assert.equal(s.index, 1);
  assert.equal(s.total, 3);
});

test('still-to-do rows are grouped by the stage they came from, in call order', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ still_to_do: [
    { id: 'a', label: 'A', section_label: 'Onboarding' }, { id: 'b', label: 'B', section_label: 'Fact Find' },
    { id: 'c', label: 'C', section_label: 'Onboarding' }] }), 0, 1);
  const c = M.checklist(m);
  assert.deepEqual(c.earlier.map(g => g.section), ['Onboarding', 'Fact Find']);
  assert.deepEqual(c.earlier[0].rows.map(r => r.id), ['a', 'c']);
  assert.equal(c.earlierCount, 3);
});

test('warnings with no text are dropped', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ warnings: [{ id: 'w', text: 'Do not' }, { id: 'e', text: '  ' }] }), 0, 1);
  assert.equal(m.warnings.length, 1);
});

test('transcription and connection states recover to ok', () => {
  const m = M.newCall();
  M.applyMessage(m, { type: 'transcription_status', state: 'degraded' }, 0, 1);
  M.applyMessage(m, { type: 'connection_status', state: 'buffering' }, 0, 1);
  assert.equal(m.transcription, 'degraded');
  assert.equal(m.conn, 'buffering');
  M.applyMessage(m, { type: 'transcription_status', state: 'recovered' }, 0, 1);
  M.applyMessage(m, { type: 'connection_status', state: 'resumed' }, 0, 1);
  assert.equal(m.transcription, 'ok');
  assert.equal(m.conn, 'ok');
});

test('timer and age text', () => {
  assert.equal(M.mmss(0), '00:00');
  assert.equal(M.mmss(754), '12:34');
  assert.equal(M.ago(30), 'just now');
  assert.equal(M.ago(125), '2 min ago');
});

test('a card the server sends with a title keeps it (2.9.58 I&E popups); others have none', () => {
  // The popup exactly as live_rulebook_call._prompt_rows builds it.
  const popup = { id: 'ie.prompt.income.Income.Wages', title: '  Income clarification required ', label: 'Income clarification required',
    severity: 'high', message: 'The customer mentioned wages, but the frequency still needs confirming.',
    action: null, script: null, coaching_only: false, occurrence: 1, about: 'Wages', source: 'panel' };
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ trigger_actions: [card('A'), popup] }), 0, 10);
  const byId = {};
  M.attention(m).filter(i => i.row).forEach(i => { byId[i.row.id] = i; });
  assert.equal(byId['ie.prompt.income.Income.Wages'].title, 'Income clarification required');
  assert.equal(byId['ie.prompt.income.Income.Wages'].kind, 'high');
  assert.equal(byId.A.title, '');
});

// ---- case continuity (server 25 Oct; Bilal's multi-call feature) ----

const caseInfo = (extra) => Object.assign({
  continuing: true, reference: '500123', case_number: 1, recording: 2, recordings: 2,
  last_call: { date: '14 Oct', time: '10:42', advisor: 'Priya Shah', how: 'dropped', recording: 1 },
  continue_here: { key: 'LOANS', label: 'Loans' },
  carried: { checks: 33, parts: 4, figures: 7, cards: 2 }, name_check: null
}, extra || {});

const introMsg = (extra) => stageMsg(Object.assign({
  stage: 'ONB',
  sections: [{ key: 'ONB', label: 'Onboarding', done: 5, total: 9, current: true },
             { key: 'INCOME', label: 'Income', done: 0, total: 4, current: false }]
}, extra || {}));

test('a call with no case has no banner, and nothing about it changes', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg(), 0, 1);
  assert.equal(M.caseBanner(m), null);
});

test('a callback shows the case in full while the call is on its first stage', () => {
  const m = M.newCall();
  M.applyMessage(m, introMsg({ case: caseInfo() }), 0, 1);
  const b = M.caseBanner(m);
  assert.equal(b.compact, false);
  assert.equal(b.reference, '500123');
  assert.equal(b.call, 2);
  assert.equal(b.last, 'Last call 14 Oct 10:42 \u00b7 Priya Shah \u00b7 dropped');
  assert.equal(b.here, 'Loans');
  assert.equal(b.done, 33);
  assert.equal(b.mismatch, null);
});

test('once the call moves past the first stage the banner shrinks to one line', () => {
  const m = M.newCall();
  M.applyMessage(m, stageMsg({ case: caseInfo() }), 0, 1);     // current = Income
  assert.equal(M.caseBanner(m).compact, true);
});

test('a good-job message without stage fields never loses the banner', () => {
  const m = M.newCall();
  M.applyMessage(m, introMsg({ case: caseInfo() }), 0, 1);
  M.applyMessage(m, { type: 'compliance_alert', missing_items: [], covered_ids: ['i1'] }, 1, 2);
  assert.ok(M.caseBanner(m));
});

test('a name that does not match the case is passed on to be flagged', () => {
  const m = M.newCall();
  M.applyMessage(m, introMsg({ case: caseInfo({ name_check: { mismatch: true,
    case_name: 'Sam Taylor', call_name: 'Jordan Blake' } }) }), 0, 1);
  assert.deepEqual(M.caseBanner(m).mismatch, { callName: 'Jordan Blake', caseName: 'Sam Taylor' });
});

test('where a carried item was done reads as a call, an advisor and a date', () => {
  assert.equal(M.carriedText({ recording: 1, advisor: 'Priya Shah', date: '14 Oct' }),
               'Call 1 \u00b7 Priya Shah \u00b7 14 Oct');
  assert.equal(M.carriedText({ recording: 3 }), 'Call 3');
  assert.equal(M.carriedText(null), '');
});
