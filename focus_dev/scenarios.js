/* Scenarios for the Focus panel, in the server's real message shapes
 * (live_rulebook_call.py _send_state / _check_row, q17_handling card rows,
 * crisis.py, ie_panel.py, server.py session_summary). Sample wording only -
 * no customer data. Used by harness.html for screenshots and by the Qt
 * screenshot script, so both draw exactly the same states. */
(function (root) {
  'use strict';
  var SECTIONS = ['Onboarding', 'Creditor Check', 'Fact Find', 'Vulnerability', 'Assets', 'Income', 'Expenditure',
    'Affordability', 'Solutions', 'IVA Explained', 'Fees', 'Questions', 'Next Steps', 'Summary', 'Close'];
  function sections(cur) {
    return SECTIONS.map(function (l, i) {
      return { key: l.toUpperCase().replace(/ /g, '_'), label: l, done: i < cur ? 4 : (i === cur ? 2 : 0), total: 4, current: i === cur };
    });
  }
  var BASE_STATE = {
    phase: 'idle', signedOut: false, login: { busy: false, error: '', info: '', forgotBusy: false },
    user: { name: 'Sam Advisor', email: 'sam.advisor@example.co.uk', dept: 'SFM' }, company: 'The Insolvency Group',
    recording: false, hideLocked: false, paused: false, elapsed: 0, callSeq: 0, ref: '', livePipeline: true, hideFields: false,
    shift: { calls: 11, avg: '84%', flags: 3 }, micGate: false,
    mics: ['Headset Microphone (Jabra Evolve2 30)', 'Microphone Array (Realtek Audio)'], micIndex: 0,
    spks: ['Headset Earphone (Jabra Evolve2 30) [Loopback]', 'Speakers (Realtek Audio) [Loopback]'], spkIndex: 0,
    apiBase: 'https://flow.example:8001', wsUrl: 'ws://192.168.0.10:8765', version: '2.9.57', dock: 'right'
  };
  function st(extra) { return { kind: 'state', data: Object.assign({}, BASE_STATE, extra) }; }
  function live(extra) { return st(Object.assign({ phase: 'live', recording: true, hideLocked: true, callSeq: 1, ref: 'REF-48213', elapsed: 755 }, extra || {})); }

  var INCOME_CHECKS = [
    { id: 'inc.pay', label: 'Take-home pay asked', done: true, severity: 'high', evidence: 'What comes into your account each month after tax?', prompt: null, missing_parts: [], parts: [], urgent: false, urgent_reason: null, section_label: 'Income' },
    { id: 'inc.slip', label: 'Payslip requested', done: true, severity: 'normal', evidence: 'Could you send over your latest payslip?', prompt: null, missing_parts: [], parts: [], urgent: false, urgent_reason: null, section_label: 'Income' },
    { id: 'inc.all', label: 'Ask about every source of household income', done: false, severity: 'high', evidence: null,
      prompt: 'Ask about every source of income in the household.', missing_parts: ['Partner’s take-home pay', 'Any other money coming in'],
      parts: [{ text: 'Partner’s take-home pay', done: false, na: false, why: null, evidence: null },
              { text: 'Child Benefit and any tax credits', done: true, na: false, why: null, evidence: 'and you get Child Benefit' },
              { text: 'Any other money coming in', done: false, na: false, why: null, evidence: null }],
      urgent: false, urgent_reason: null, section_label: 'Income' },
    { id: 'inc.freq', label: 'Confirm how often each amount is paid', done: false, severity: 'normal', evidence: null, prompt: 'Confirm whether each amount is weekly, four-weekly or monthly.', missing_parts: [], parts: [], urgent: false, urgent_reason: null, section_label: 'Income' },
    { id: 'inc.evid', label: 'Ask for evidence of benefits', done: false, severity: 'normal', evidence: null, prompt: 'Ask for a benefit award letter or statement.', missing_parts: [], parts: [], urgent: false, urgent_reason: null, section_label: 'Income' }
  ];
  var WARNINGS = [
    { id: 'w1', severity: 'critical', text: 'Don’t suggest a figure before the client gives one.' },
    { id: 'w2', severity: 'high', text: 'Don’t quote guideline amounts as targets.' },
    { id: 'w3', severity: 'high', text: 'Don’t move money between categories to make it fit.' },
    { id: 'w4', severity: 'high', text: 'Don’t say what the IVA payment “needs” to be.' }
  ];
  var STILL = [
    { id: 'cc.spend', label: 'Ask about recent spending on credit', section_label: 'Creditor Check', severity: 'high', prompt: 'Ask about any credit taken in the last 6 months.', missing_parts: [] },
    { id: 'ff.events', label: 'Recent life events', section_label: 'Fact Find', severity: 'normal', prompt: null, missing_parts: ['Job change', 'Illness', 'Bereavement'] }
  ];
  function stage(extra) {
    return { kind: 'msg', data: Object.assign({ type: 'compliance_alert', missing_items: [], covered_ids: ['inc.pay', 'inc.slip'], audio_ts: 750.2,
      stage: 'INCOME', score: { covered: 12, total: 40, earned: 12, fraction: 0.3 }, sections: sections(5),
      section_checks: INCOME_CHECKS, still_to_do: STILL, open_criticals: [], warnings: WARNINGS, crisis_resolved: false,
      trigger_actions: [], alert: null }, extra || {}) };
  }
  var CARD_AFFORD = { id: 'Q17.AFFORD_STEER', label: 'Affordability steering', severity: 'critical',
    message: 'You suggested a food figure before the client gave their own.',
    action: 'Withdraw the figure and ask the client for their own.',
    script: '“Sorry, I shouldn’t have suggested that. What do you actually spend on food and housekeeping each month?”',
    coaching_only: false, timing: 'immediate', recovery_mode: 'script', route: null, route_name: null, resolution: '', must_not_clear: [],
    alternatives: ['“Just to check I’ve got it right, you said around £300 a month. Is that correct?”'], filled: {}, generic: [],
    quote: 'shall we put 320 for food', breach_context: '', about: 'food', occurrence: 1 };
  var CARD_CTAX = { id: 'Q17.UNRESOLVED_AMOUNTS', label: 'Council tax: two amounts', severity: 'high',
    message: 'The client gave two amounts for council tax, £120 and £135. Settle which one is right.',
    action: 'Ask the client which amount is the monthly one.',
    script: '“I’ve heard £120 and £135 for council tax. Which is the monthly amount?”',
    coaching_only: false, alternatives: [], occurrence: 1, quote: '', about: 'council tax' };
  var CARD_GUIDE = { id: 'Q17.GUIDELINE_SAID', label: 'Guideline figure said aloud', severity: 'high',
    message: 'A guideline amount was quoted to the client as a target.', action: '', script: null,
    coaching_only: true, auto_clear_seconds: 60, alternatives: [], occurrence: 1, quote: '', about: '' };
  // 2.9.58: the I&E panel's clarification popup, exactly as
  // live_rulebook_call._prompt_rows sends it - a card with its own title.
  var CARD_POPUP = { id: 'ie.prompt.income.Income.Wages', title: 'Income clarification required', label: 'Income clarification required',
    severity: 'high', message: 'The customer mentioned wages of £1,840, but whether this is weekly or monthly still needs confirming. Clarify the correct amount, frequency and whether this is household income or already included elsewhere. Do not include, exclude or duplicate it based on an assumption.',
    action: null, script: null, coaching_only: false, occurrence: 1, about: 'Wages', source: 'panel' };
  var CARD_POPUP_LONG = { id: 'ie.prompt.payer.Expenditure.Rent', title: 'Household expenditure needs confirming', label: 'Household expenditure needs confirming',
    severity: 'high', message: 'The customer indicated that someone else pays or reimburses some of rent. Clarify what amount the household actually pays before including or excluding it.',
    action: null, script: null, coaching_only: false, occurrence: 1, about: 'Rent', source: 'panel' };
  var CRISIS = { type: 'crisis_alert', line: 'I’m really sorry you’re feeling this way. You don’t have to deal with this on your own, and there are people you can talk to right now, any time of day.',
    resources: [{ name: 'Samaritans', detail: '116 123 — free, 24/7' }, { name: 'Shout', detail: 'text 85258' }, { name: 'Mind', detail: '0300 123 3393' }],
    immediate: true, escalation: 'IMMEDIATE RISK TO LIFE — stay with them and call 999 now.', evidence: 'I just don’t see the point any more', audio_ts: 812.4 };

  function ieMsg(view) {
    var income = { total: 1840, text: '£1,840', amber: false, groups: [
      { key: 'wages', label: 'Wages', icon: 'briefcase', total: 1520, text: '£1,520', unresolved: false, amber: false, dot: null,
        items: [{ key: 'wage.client', label: 'Client take-home pay', state: 'captured', value: 1520, text: '£1,520', flag: null, note: null, parts: [] }] },
      { key: 'benefits', label: 'Benefits', icon: 'hand', total: 320, text: '£320', unresolved: false, amber: false, dot: null,
        items: [{ key: 'ben.cb', label: 'Child Benefit', state: 'captured', value: 102, text: '£102', flag: null, note: null, parts: [] },
                { key: 'ben.uc', label: 'Universal Credit', state: 'captured', value: 218, text: '£218', flag: null, note: null, parts: [] }] }] };
    if (view === 'income') {
      return { kind: 'msg', data: { type: 'ie_panel', visible: true, view: 'income', solutions: false,
        header: { household: '2 adults, 1 child', vehicles: 'Pending', affordability: 'Pending' }, income: income,
        expenditure: { total: null, text: '£0', amber: false, groups: [] },
        di: { shown: false, value: null, text: 'Pending recalculation', note: null } } };
    }
    return { kind: 'msg', data: { type: 'ie_panel', visible: true, view: 'expenditure', solutions: false,
      header: { household: '2 adults, 1 child', vehicles: '1', affordability: '£100–£150' }, income: income,
      expenditure: { total: 1428, text: '£1,428', amber: true, groups: [
        { key: 'home', label: 'Home and contents', icon: 'home', total: 812, text: '£812', unresolved: false, amber: false, dot: null,
          items: [{ key: 'rent', label: 'Rent', state: 'captured', value: 650, text: '£650', flag: null, note: null, parts: [] },
                  { key: 'ctax', label: 'Council tax', state: 'captured', value: 135, text: '£135', flag: null, note: null, parts: [] },
                  { key: 'ins', label: 'Contents insurance', state: 'captured', value: 12, text: '£12', flag: null, note: null, parts: [] }] },
        { key: 'utilities', label: 'Utilities', icon: 'bolt', total: null, text: 'Unresolved', unresolved: true, amber: true, dot: null,
          items: [{ key: 'gas', label: 'Gas and electricity', state: 'captured', value: 142, text: '£142', flag: null, note: null, parts: [] },
                  { key: 'water', label: 'Water', state: 'unresolved', value: null, text: '£34 / £38', flag: 'Unresolved', note: null, parts: [] },
                  { key: 'tv', label: 'TV licence', state: 'captured', value: 15, text: '£15', flag: null, note: 'The standard licence fee', parts: [] }] },
        { key: 'comms', label: 'Communications and leisure', icon: 'phone', total: 67, text: '£67', unresolved: false, amber: false, dot: null,
          items: [{ key: 'mobile', label: 'Mobile phones', state: 'captured', value: 49, text: '£49', flag: null, note: 'Two phones: £17 and £32',
                    parts: [{ label: 'Client’s phone', text: '£17', flag: null }, { label: 'Son’s phone', text: '£32', flag: null }] },
                  { key: 'bb', label: 'Broadband', state: 'captured', value: 18, text: '£18', flag: null, note: null, parts: [] }] },
        { key: 'food', label: 'Food and housekeeping', icon: 'cart', total: 240, text: '£240', unresolved: false, amber: false, dot: null,
          items: [{ key: 'groc', label: 'Groceries', state: 'captured', value: 240, text: '£240', flag: 'Only a “yes” to the advisor’s figure', note: null, parts: [] }] },
        { key: 'travel', label: 'Travel', icon: 'car', total: null, text: 'Pending', unresolved: false, amber: false, dot: null,
          items: [{ key: 'fuel', label: 'Fuel', state: 'pending', value: null, text: '—', flag: null, parts: [] }] }] },
      di: { shown: true, value: 412, text: '£412', note: null } } };
  }

  var S = {};
  S['login'] = { size: [360, 900], steps: [st({ phase: 'login' })] };
  S['login-busy'] = { size: [360, 900], steps: [st({ phase: 'login', login: { busy: true } })], fill: { 'f-email': 'sam.advisor@example.co.uk', 'f-pw': 'password1' } };
  S['login-error'] = { size: [360, 900], steps: [st({ phase: 'login', login: { error: 'Incorrect email or password.' } })], fill: { 'f-email': 'sam.advisor@example.co.uk' } };
  S['login-forgot'] = { size: [360, 900], steps: [st({ phase: 'login', login: { info: 'If that email is registered, a reset link is on its way. Check your inbox, set a new password, then sign in here.' } })], fill: { 'f-email': 'sam.advisor@example.co.uk' } };
  S['signed-out'] = { size: [360, 900], steps: [st({ phase: 'login', signedOut: true })] };
  S['idle'] = { size: [360, 900], steps: [st({})] };
  S['idle-manual'] = { size: [360, 900], steps: [st({})], clicks: ['[data-act="manual"]'] };
  S['idle-settings'] = { size: [360, 900], steps: [st({})], clicks: ['[data-act="settings"]'] };
  var LONG_MICS = ['Microphone Array (Intel® Smart Sound Technology for Digital Microphones)',
    'Headset Microphone (Jabra Evolve2 30)', 'Microphone (Realtek(R) Audio)'];
  S['settings-dropdown'] = { size: [360, 900], steps: [st({ mics: LONG_MICS, micIndex: 0 })],
    clicks: ['[data-act="settings"]', '[data-act="dd"][data-v="mic"]'] };
  S['settings-dropdown-picked'] = { size: [360, 900], steps: [st({ mics: LONG_MICS, micIndex: 0 })],
    clicks: ['[data-act="settings"]', '[data-act="dd"][data-v="mic"]', '[data-act="ddPick"][data-k="1"]'] };
  S['mic-gate'] = { size: [360, 900], steps: [st({ micGate: true })] };
  S['starting'] = { size: [360, 900], steps: [st({ phase: 'starting', hideLocked: true })] };
  S['live-listening'] = { size: [360, 900], steps: [live({ elapsed: 4 })] };
  S['live-next'] = { size: [360, 900], steps: [live({}), stage()] };
  S['live-critical'] = { size: [360, 900], steps: [live({ elapsed: 760 }), stage({ trigger_actions: [CARD_AFFORD] }), ieMsg('income')] };
  S['live-critical-alt'] = { size: [360, 900], steps: [live({ elapsed: 760 }), stage({ trigger_actions: [CARD_AFFORD] })], clicks: ['[data-act="alt"]'] };
  S['live-three'] = { size: [360, 900], steps: [live({ elapsed: 790 }), stage({ trigger_actions: [CARD_AFFORD] }), stage({ trigger_actions: [CARD_AFFORD, CARD_CTAX, CARD_GUIDE] }), ieMsg('expenditure')] };
  S['popup-front'] = { size: [360, 900], steps: [live({ elapsed: 790 }), stage({ trigger_actions: [CARD_POPUP] })] };
  S['popup-long-title'] = { size: [360, 900], steps: [live({ elapsed: 790 }), stage({ trigger_actions: [CARD_POPUP_LONG] })] };
  S['popup-queued'] = { size: [360, 900], steps: [live({ elapsed: 790 }), stage({ trigger_actions: [CARD_POPUP] }), stage({ trigger_actions: [CARD_POPUP, CARD_CTAX] })] };
  S['popup-peek'] = { size: [416, 900], steps: [live({}), stage(), ieMsg('expenditure')], clicks: ['[data-act="collapse"]'], later: [stage({ trigger_actions: [CARD_POPUP] })] };
  S['live-queue-pick'] = { size: [360, 900], steps: [live({ elapsed: 790 }), stage({ trigger_actions: [CARD_AFFORD] }), stage({ trigger_actions: [CARD_AFFORD, CARD_CTAX, CARD_GUIDE] })], clicks: ['.qrow:nth-of-type(2)'] };
  S['live-safety'] = { size: [360, 900], steps: [live({ elapsed: 815 }), stage(), { kind: 'msg', data: CRISIS }, stage({ section_checks: INCOME_CHECKS.concat([
      { id: 'vul.safe', label: 'Ask whether they feel safe right now', done: false, urgent: true, urgent_reason: 'A vulnerability has been disclosed - ask these now', parts: [], missing_parts: [] },
      { id: 'vul.support', label: 'Ask whether anyone is supporting them', done: false, urgent: true, urgent_reason: 'A vulnerability has been disclosed - ask these now', parts: [], missing_parts: [] },
      { id: 'vul.text', label: 'Offer to text the helpline numbers', done: false, urgent: true, urgent_reason: 'A vulnerability has been disclosed - ask these now', parts: [], missing_parts: [] }]) })] };
  S['live-urgent'] = { size: [360, 900], steps: [live({ elapsed: 900 }), stage({ crisis_resolved: true, section_checks: INCOME_CHECKS.concat([
      { id: 'vul.safe', label: 'Ask whether they feel safe right now', done: true, urgent: true, parts: [], missing_parts: [] },
      { id: 'vul.support', label: 'Ask whether anyone is supporting them', done: false, urgent: true, urgent_reason: 'A vulnerability has been disclosed - ask these now', parts: [], missing_parts: [] },
      { id: 'vul.text', label: 'Offer to text the helpline numbers', done: false, urgent: true, urgent_reason: 'A vulnerability has been disclosed - ask these now', parts: [], missing_parts: [] }]) })] };
  var MISSED = [{ id: 'onb.dpa', label: 'Data protection check', section_label: 'Onboarding', prompt: 'Confirm the client’s identity before discussing the debts.', missing_parts: ['Date of birth', 'First line of address'] }];
  S['live-missed'] = { size: [360, 900], steps: [live({}), stage({ open_criticals: MISSED })] };
  S['live-missed-pick'] = { size: [360, 900], steps: [live({}), stage({ open_criticals: MISSED })], clicks: ['.qrow'] };
  S['live-paused'] = { size: [360, 900], steps: [live({ paused: true, elapsed: 1250 }), stage(), ieMsg('expenditure')] };
  S['live-buffering'] = { size: [360, 900], steps: [live({ elapsed: 1300 }), stage(), { kind: 'msg', data: { type: 'connection_status', state: 'buffering' } }] };
  S['live-transcript-failed'] = { size: [360, 900], steps: [live({ elapsed: 1300 }), stage(), { kind: 'msg', data: { type: 'transcription_status', state: 'failed' } }] };
  S['live-recording-only'] = { size: [360, 900], steps: [live({ livePipeline: false, elapsed: 310 })] };
  S['live-all-clear'] = { size: [360, 900], steps: [live({ elapsed: 1420 }), stage({ section_checks: INCOME_CHECKS.map(function (c) { return Object.assign({}, c, { done: true, prompt: null, missing_parts: [] }); }), still_to_do: [] }), ieMsg('expenditure')] };
  S['sheet-checklist'] = { size: [360, 900], steps: [live({}), stage()], clicks: ['[data-v="list"]'] };
  S['sheet-ie-income'] = { size: [360, 900], steps: [live({}), stage(), ieMsg('income')], clicks: ['[data-v="ie"]'] };
  S['sheet-ie-exp'] = { size: [360, 900], steps: [live({}), stage(), ieMsg('expenditure')], clicks: ['[data-v="ie"]', '[data-k="exp.comms"]', '[data-act="parts"]'] };
  S['sheet-dont'] = { size: [360, 900], steps: [live({}), stage()], clicks: ['[data-v="dont"]'] };
  S['sheet-newcard'] = { size: [360, 900], steps: [live({}), stage(), ieMsg('expenditure')], clicks: ['[data-v="ie"]'], later: [stage({ trigger_actions: [CARD_CTAX] })] };
  S['pinned'] = { size: [721, 900], steps: [live({}), stage({ trigger_actions: [CARD_AFFORD] }), ieMsg('expenditure')], clicks: ['[data-v="ie"]', '[data-act="pin"]'] };
  S['strip'] = { size: [64, 900], steps: [live({}), stage({ trigger_actions: [CARD_AFFORD] }), ieMsg('expenditure')], clicks: ['[data-act="collapse"]'] };
  S['strip-peek'] = { size: [416, 900], steps: [live({}), stage(), ieMsg('expenditure')], clicks: ['[data-act="collapse"]'], later: [stage({ trigger_actions: [CARD_CTAX] })] };
  S['legacy'] = { size: [360, 900], steps: [live({ elapsed: 200 }), { kind: 'msg', data: { type: 'compliance_alert', missing_items: [{ id: 'r1', label: 'Explain the fees', level: 'red', suggestion_text: 'Tell the client what the fees are and when they are paid.' }, { id: 'a1', label: 'Confirm the address', level: 'amber', suggestion_text: null }], covered_ids: [] } },
      { kind: 'msg', data: { type: 'compliance_alert', forbidden_hits: [{ id: 'f1', label: 'guaranteed write-off', level: 'red', suggestion_text: null }], missing_items: [], covered_ids: [] } }] };
  S['summary-pending'] = { size: [360, 900], steps: [st({ phase: 'summary' }), { kind: 'summary', data: { mode: 'pending', duration: 1456 } }] };
  S['summary-score'] = { size: [360, 900], steps: [st({ phase: 'summary' }), { kind: 'summary', data: { mode: 'score', duration: 1456, score: 0.82, saved: true,
      covered: new Array(41).fill(0).map(function (_, i) { return { label: 'Check ' + (i + 1), section: 'Onboarding' }; }),
      missed: [{ label: 'Ask for evidence of benefits', section: 'Income' }, { label: 'Confirm how often each amount is paid', section: 'Income' },
               { label: 'Debt Relief Order explained', section: 'Solutions' }, { label: 'Bankruptcy explained', section: 'Solutions' },
               { label: 'Fees explained', section: 'Fees' }, { label: 'Next steps agreed', section: 'Next Steps' }, { label: 'Summary given', section: 'Summary' },
               { label: 'Call closed properly', section: 'Close' }, { label: 'Recent life events', section: 'Fact Find' }] } }] };
  S['summary-all'] = { size: [360, 900], steps: S['summary-score'].steps, clicks: ['[data-act="sumAll"]'] };
  S['summary-saved'] = { size: [360, 900], steps: [st({ phase: 'summary' }), { kind: 'summary', data: { mode: 'saved_only', duration: 312, saved: true } }] };
  S['summary-saving'] = { size: [360, 900], steps: [st({ phase: 'summary' }), { kind: 'summary', data: { mode: 'score', duration: 1456, score: 0.64, saved: false, covered: [{ label: 'a', section: 'x' }], missed: [{ label: 'Fees explained', section: 'Fees' }] } }] };
  // A manager marks the front card a false positive on the live dashboard: the
  // server's next state simply no longer carries it.
  S['false-positive'] = { size: [360, 900], steps: [live({ elapsed: 790 }), stage({ trigger_actions: [CARD_AFFORD] }),
      stage({ trigger_actions: [CARD_AFFORD, CARD_CTAX] })],
      later: [stage({ trigger_actions: [CARD_AFFORD] })], laterDelay: 2300 };
  S['dock-left'] = { size: [360, 900], steps: [live({ dock: 'left' }), stage({ trigger_actions: [CARD_AFFORD] })] };

  root.FocusScenarios = S;
}(typeof self !== 'undefined' ? self : this));
