/* Spark Flow Focus - the panel.
 *
 * Draws what the Python widget tells it, and sends back what the advisor
 * presses. It owns no recording, no sign-in and no network: every button ends
 * in a call to the SAME MainWindow method the classic screen's button calls
 * (focus_ui.py). So nothing here can lose a recording - the worst a bug in
 * this file can do is draw something wrong, and the window falls back to the
 * classic screen if the page fails to start at all.
 *
 * Drawing is done region by region. A region's HTML is rebuilt as a string
 * and only put into the page when it differs from what is there: the server
 * sends the checklist every few seconds, and replacing everything on each one
 * would replay every animation and wipe whatever the advisor was typing.
 */
(function () {
  'use strict';
  var M = window.FocusModel;

  /* ---------- icons (inline, stroke) ---------- */
  function svg(body, size, sw, fill) {
    return '<svg width="' + (size || 18) + '" height="' + (size || 18) + '" viewBox="0 0 24 24" fill="' + (fill || 'none') +
      '" stroke="' + (fill ? 'none' : 'currentColor') + '" stroke-width="' + (sw || 2) +
      '" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + body + '</svg>';
  }
  var I = {
    pause: svg('<path d="M9 5v14M15 5v14"/>', 18, 2.4),
    play: svg('<path d="M7 4.5v15a1 1 0 0 0 1.5.9l12-7.5a1 1 0 0 0 0-1.8l-12-7.5A1 1 0 0 0 7 4.5z"/>', 16, 0, 'currentColor'),
    stop: svg('<rect x="5" y="5" width="14" height="14" rx="3"/>', 16, 0, 'currentColor'),
    foldR: svg('<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M15 3v18"/><path d="m8 9 3 3-3 3"/>'),
    foldL: svg('<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M9 3v18"/><path d="m16 9-3 3 3 3"/>'),
    openR: svg('<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M15 3v18"/><path d="m11 9-3 3 3 3"/>'),
    openL: svg('<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M9 3v18"/><path d="m13 9 3 3-3 3"/>'),
    gear: svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'),
    minus: svg('<path d="M5 12h14"/>', 18, 2.4),
    x: svg('<path d="M6 6l12 12M18 6 6 18"/>', 18, 2.4),
    xr: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#B3170B" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>',
    tick: '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 5 5 9-10"/></svg>',
    tickB: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#5B3DF5" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 5 5 9-10"/></svg>',
    tickG: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#13803D" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 5 5 9-10"/></svg>',
    bigTick: '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 5 5 9-10"/></svg>',
    bang: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="3" stroke-linecap="round" aria-hidden="true"><path d="M12 6v8M12 18h.01"/></svg>',
    alertR: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#C8281C" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5h.01"/></svg>',
    warnA: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#8F5400" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/></svg>',
    chev: svg('<path d="m9 18 6-6-6-6"/>', 16, 2.4),
    down: svg('<path d="m6 9 6 6 6-6"/>', 16, 2.4),
    shield: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#FFD9D4" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
    bolt: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>',
    boltBig: '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>',
    mail: svg('<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/>'),
    lock: svg('<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>'),
    eye: svg('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'),
    eyeOff: svg('<path d="M3 3l18 18"/><path d="M10.6 5.1A10.9 10.9 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.1M6.6 6.6C3.8 8.4 2 12 2 12s3.5 7 10 7a9.6 9.6 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>'),
    mic: svg('<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v4"/>'),
    refresh: svg('<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/>', 16),
    pin: svg('<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M12 3v18"/>', 14, 2.2),
    coins: svg('<circle cx="8" cy="8" r="6"/><path d="M18.1 10.4A6 6 0 1 1 10.3 18"/><path d="M7 6h1v4"/>', 16, 1.9)
  };
  // The I&E's own icons, the same paths the classic column draws (main.py _IE_ICONS),
  // keyed by the names the server sends.
  var IE_ICON = {
    home: '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    bolt: '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
    drop: '<path d="M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5C6 11.1 5 13 5 15a7 7 0 0 0 7 7z"/>',
    phone: '<rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/>',
    car: '<path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.4 2.9A3.7 3.7 0 0 0 2 12v4c0 .6.4 1 1 1h2"/><circle cx="7" cy="17" r="2"/><path d="M9 17h6"/><circle cx="17" cy="17" r="2"/>',
    cart: '<circle cx="8" cy="21" r="1"/><circle cx="19" cy="21" r="1"/><path d="M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0 0 0 1.95-1.57l1.65-7.43H5.12"/>',
    umbrella: '<path d="M22 12a10.06 10.06 1 0 0-20 0Z"/><path d="M12 12v8a2 2 0 0 0 4 0"/><path d="M12 2v1"/>',
    shirt: '<path d="M20.38 3.46 16 2a4 4 0 0 1-8 0L3.62 3.46a2 2 0 0 0-1.34 2.23l.58 3.47a1 1 0 0 0 .99.84H6v10c0 1.1.9 2 2 2h8a2 2 0 0 0 2-2V10h2.15a1 1 0 0 0 .99-.84l.58-3.47a2 2 0 0 0-1.34-2.23z"/>',
    heart: '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/><path d="M3.22 12H9.5l.5-1 2 4.5 2-7 1.5 3.5h5.27"/>',
    cap: '<path d="M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0 1.66 0z"/><path d="M22 10v6"/><path d="M6 12.5V16a6 3 0 0 0 12 0v-3.5"/>',
    award: '<circle cx="12" cy="8" r="6"/><path d="M15.477 12.89 17 22l-5-3-5 3 1.523-9.11"/>',
    piggy: '<path d="M19 5c-1.5 0-2.8 1.4-3 2-3.5-1.5-11-.3-11 5 0 1.8 0 3 2 4.5V20h4v-2h3v2h4v-4c1-.5 1.7-1 2-2h2v-4h-2c0-1-.5-1.5-1-2V5z"/><path d="M2 9v1c0 1.1.9 2 2 2h1"/><path d="M16 11h.01"/>',
    box: '<path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z"/><path d="M12 22V12"/><path d="m3.3 7 7.703 4.734a2 2 0 0 0 1.994 0L20.7 7"/><path d="m7.5 4.27 9 5.15"/>',
    briefcase: '<path d="M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/><rect width="20" height="14" x="2" y="6" rx="2"/>',
    hand: '<path d="M11 15h2a2 2 0 1 0 0-4h-3c-.6 0-1.1.2-1.4.6L3 17"/><path d="m7 21 1.6-1.4c.3-.4.8-.6 1.4-.6h4c1.1 0 2.1-.4 2.8-1.2l4.6-4.4a2 2 0 0 0-2.75-2.91l-4.2 3.9"/><path d="m2 16 6 6"/><circle cx="16" cy="9" r="2.9"/><circle cx="6" cy="5" r="3"/>',
    coins: '<circle cx="8" cy="8" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18"/><path d="M7 6h1v4"/><path d="m16.71 13.88.7.71-2.82 2.82"/>'
  };
  function ieIcon(name) { return svg(IE_ICON[name] || IE_ICON.box, 16, 1.8); }

  // Where the page's own images are; the dev harness lives in another folder.
  var ASSET = window.FOCUS_ASSETS || '';
  var EQ = '<span class="eq"><i></i><i></i><i></i><i></i></span>';
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /* ---------- state ---------- */
  var bridge = null;
  var host = { phase: 'boot', login: {}, user: {}, shift: {}, mics: [], spks: [], dock: 'right',
               elapsed: 0, callSeq: 0, livePipeline: true, version: '' };
  var call = M.newCall();
  var callSeq = null;
  var summary = null;
  var ui = {
    sheet: null, collapsed: false, pinIE: false, focusKey: null, alt: {}, open: {}, parts: {},
    manual: false, settings: false, peekKey: null, peekUntil: 0, newKey: null, newUntil: 0,
    flash: null, flashUntil: 0, lastFocusKey: null, ieSeen: 0, showPw: false, gateIndex: null,
    summaryAll: false, layoutKey: null
  };
  var regions = {};
  var shape = null;

  function send(action, payload) {
    if (bridge && bridge.call) bridge.call(action, JSON.stringify(payload || {}));
  }

  /* ---------- incoming ---------- */
  function onPush(text) {
    var p;
    try { p = typeof text === 'string' ? JSON.parse(text) : text; } catch (e) { return; }
    if (!p) return;
    if (p.kind === 'state') applyState(p.data || {});
    else if (p.kind === 'msg') applyServer(p.data);
    else if (p.kind === 'summary') { summary = p.data; }
    else if (p.kind === 'batch') { (p.items || []).forEach(onPush); return; }
    schedule();
  }

  function applyState(s) {
    var was = host;
    host = s;
    if (host.callSeq !== callSeq) {
      // A new call: a clean slate, as the classic panels clear on connect.
      callSeq = host.callSeq;
      call = M.newCall();
      ui.sheet = null; ui.focusKey = null; ui.alt = {}; ui.peekKey = null; ui.flash = null;
      ui.newKey = null; ui.pinIE = false; ui.lastFocusKey = null; ui.ieSeen = 0;
    }
    if (was.phase !== host.phase) {
      note('phase:' + was.phase + '>' + host.phase);
      ui.settings = false;
      if (host.phase !== 'live') { ui.sheet = null; ui.collapsed = false; ui.pinIE = false; }
      if (host.phase === 'idle') { ui.manual = false; }
      if (host.phase === 'summary') { ui.summaryAll = false; }
    }
    if (host.micGate && ui.gateIndex == null) ui.gateIndex = host.micIndex || 0;
    if (!host.micGate) ui.gateIndex = null;
  }

  function applyServer(msg) {
    var crisisBefore = !!call.crisis;
    var r = M.applyMessage(call, msg, Date.now(), host.elapsed || 0);
    if (!r.changed) return;
    var now = Date.now();
    // No "Put right" flash when a card leaves. The server takes a card off for
    // more than one reason - the advisor repaired it, OR a manager marked it a
    // false positive on the live dashboard (15 Oct) - and the message does not
    // say which. Telling the advisor they put right a breach that was never one
    // would be untrue, so a card simply goes, as on the classic screen.
    if (crisisBefore && !call.crisis) { ui.flash = 'Support signposted'; ui.flashUntil = now + 1600; }
    if (r.newCard) {
      var top = M.attention(call)[0];
      if (top && (top.kind === 'safety' || top.kind === 'critical' || top.kind === 'high')) {
        ui.focusKey = null;                  // a new card always comes to the front
        if (top.kind === 'safety') { ui.collapsed = false; ui.sheet = null; }   // safety opens the panel
        else if (ui.collapsed) { ui.peekKey = top.key; ui.peekUntil = now + 8000; }
        else if (ui.sheet) { ui.newKey = top.key; ui.newUntil = now + 6000; }
      }
    }
  }

  /* ---------- regions ---------- */
  function setRegion(name, html) {
    var el = document.querySelector('[data-r="' + name + '"]');
    if (!el) return;
    if (regions[name] === html) return;
    // Keep what the advisor typed, and where the cursor was.
    var keep = {}, active = document.activeElement, activeId = active && active.id;
    el.querySelectorAll('input[id]').forEach(function (i) { keep[i.id] = i.value; });
    var scrollers = {};
    el.querySelectorAll('[data-scroll]').forEach(function (s) { scrollers[s.getAttribute('data-scroll')] = s.scrollTop; });
    if (el.hasAttribute('data-scroll')) scrollers.__self = el.scrollTop;
    // Elements already on screen must not animate in again when their region
    // is redrawn: opening a dropdown redrew the Settings sheet and replayed its
    // slide-up, so the whole sheet looked as if it closed and reopened (Faseeh,
    // 15 Oct). Only something genuinely new - a new data-anim key - animates.
    var shown = {};
    el.querySelectorAll('[data-anim]').forEach(function (a) { shown[a.getAttribute('data-anim')] = 1; });
    el.innerHTML = html;
    el.querySelectorAll('[data-anim]').forEach(function (a) {
      if (shown[a.getAttribute('data-anim')]) a.classList.add('calm');
    });
    regions[name] = html;
    Object.keys(keep).forEach(function (id) { var i = document.getElementById(id); if (i) i.value = keep[id]; });
    el.querySelectorAll('[data-scroll]').forEach(function (s) {
      var k = s.getAttribute('data-scroll'); if (scrollers[k] != null) s.scrollTop = scrollers[k];
    });
    if (scrollers.__self != null) el.scrollTop = scrollers.__self;
    if (activeId) { var a = document.getElementById(activeId); if (a && a !== document.activeElement) a.focus(); }
  }

  function buildShape(name, html) {
    if (shape === name) return;
    shape = name; regions = {};
    document.getElementById('app').innerHTML = html;
  }

  /* ---------- pieces: live call ---------- */
  function stageBar() {
    var s = M.stageInfo(call);
    if (!s.total) return '';
    return '<div class="prog"><b title="' + esc(s.label) + '">' + esc(s.label) + '</b><div class="segs" aria-hidden="true" style="grid-template-columns:repeat(' + s.total + ',minmax(0,1fr))">' +
      s.segments.map(function (x) { return '<i class="' + x + '"></i>'; }).join('') + '</div>' +
      '<span class="of">' + (s.index + 1) + ' of ' + s.total + '</span></div>';
  }

  function headerLive() {
    var p = !!host.paused;
    var sub;
    if (call.conn === 'buffering') sub = '<span class="sub warn">Reconnecting \u2014 still recording</span>';
    else if (call.conn === 'failed') sub = '<span class="sub bad">Saved locally \u2014 will not upload</span>';
    else if (p) sub = '<span class="sub warn">Paused \u2014 not recording</span>';
    else sub = '<span class="sub">' + esc([host.ref, (host.user && host.user.dept) || ''].filter(Boolean).join(' \u00b7 ') || 'Recording') + '</span>';
    var fold = host.dock === 'left' ? I.foldL : I.foldR;
    return '<div class="hd' + (p ? ' paused' : '') + '" data-drag><div class="hd-top"><div class="hd-id"><div class="l1"><span class="rec' + (p ? ' pa' : '') + '"></span><span class="tm" data-t></span></div>' + sub + '</div>' +
      (p ? '<button class="ib resume" data-act="pause" aria-label="Resume recording">' + I.play + '</button>'
         : '<button class="ib pause" data-act="pause" aria-label="Pause for card payment" title="Pause for card payment">' + I.pause + '</button>') +
      '<button class="ib stop" data-act="stop" aria-label="Stop recording" title="Stop recording">' + I.stop + '</button>' +
      '<button class="ib ghost" data-act="collapse" aria-label="Fold to the strip" title="Fold to the strip">' + fold + '</button></div>' +
      (host.livePipeline ? stageBar() : '') + '</div>';
  }

  function stateLine(items) {
    var fixes = M.fixCount(items);
    if (call.crisis) return '<div class="state-line" style="color:var(--redDeep)"><span class="ic" style="background:var(--redDeep)">' + I.bang + '</span>Customer safety \u2014 follow the card</div>';
    if (fixes) return '<div class="state-line" style="color:var(--red)"><span class="ic" style="background:var(--red)">' + I.bang + '</span>' + fixes + ' thing' + (fixes > 1 ? 's' : '') + ' to put right</div>';
    // Never "on track" while something critical is still owed: a disclosure's
    // questions, or a critical check skipped in an earlier stage.
    if (items.some(function (i) { return i.kind === 'urgent'; })) return '<div class="state-line" style="color:var(--red)"><span class="ic" style="background:var(--red)">' + I.bang + '</span>Questions to ask now</div>';
    var missed = items.filter(function (i) { return i.kind === 'missed'; }).length;
    if (missed) return '<div class="state-line" style="color:var(--red)"><span class="ic" style="background:var(--red)">' + I.bang + '</span>' + missed + ' critical check' + (missed > 1 ? 's' : '') + ' missed earlier</div>';
    // With transcription down nothing is being judged, so "on track" would be a guess.
    if (call.transcription === 'failed') return '';
    return '<div class="state-line" style="color:var(--grnInk)"><span class="ic" style="background:var(--grn)">' + I.tick + '</span>On track \u2014 nothing to put right</div>';
  }

  function partsList(row, cls) {
    var parts = M.liveParts(row);
    if (parts.length >= 2) {
      return '<div class="parts">' + parts.map(function (p) {
        var na = p.na && !p.done;
        return '<div class="part' + (p.done ? ' ok' : na ? ' na' : '') + '"><span class="o">' + (p.done ? I.tick : '') + '</span><span>' + esc(p.text) + '</span>' + (na ? '<em class="natag">n/a</em>' : '') + '</div>';
      }).join('') + '</div>';
    }
    var miss = (row.missing_parts || []).filter(Boolean);
    if (miss.length) {
      return '<div class="parts">' + miss.slice(0, 4).map(function (t) { return '<div class="part"><span class="o"></span><span>' + esc(t) + '</span></div>'; }).join('') +
        (miss.length > 4 ? '<div class="part"><span class="o" style="border:none"></span><span>+' + (miss.length - 4) + ' more</span></div>' : '') + '</div>';
    }
    return row.prompt ? '<p class="detail">' + esc(row.prompt) + '</p>' : '';
  }

  function listenLine(text) {
    return '<div class="listen' + (host.paused ? ' paused-eq' : '') + '">' + EQ + esc(text) + '</div>';
  }

  function focusCard(it, enter) {
    var cls = ' enter';
    if (!enter) cls = '';
    if (it.kind === 'safety') {
      var c = it.crisis || {};
      var res = (c.resources || []).map(function (r) { return '<b>' + esc(r.name) + '</b><span>' + esc(r.detail) + '</span>'; }).join('');
      return '<div class="focus safety' + cls + '" role="alert"><div class="f-top">' + I.shield + '<span class="cap" style="color:#FFD9D4">Customer safety</span><span class="when" style="color:#FFC9C2">Stays until signposted</span></div>' +
        (c.escalation ? '<div class="esc">' + esc(c.escalation) + '</div>' : '') +
        '<div class="scr">' + esc(c.line || '') + '</div>' +
        (res ? '<div class="lines">' + res + '</div>' : '') +
        (c.evidence ? '<div class="ev">\u201c' + esc(String(c.evidence).slice(0, 140)) + '\u201d</div>' : '') + '</div>';
    }
    if (it.kind === 'critical' || it.kind === 'high') {
      var r = it.row || {};
      var h = '<div class="focus ' + it.kind + cls + '" role="alert"><div class="f-top"><span class="kind">' + (it.kind === 'critical' ? 'Put right now' : 'Put right') + '</span>' +
        (it.at != null ? '<span class="when" data-ago="' + it.at + '"></span>' : '') + '</div>' +
        (it.forbidden ? '' : '<div class="eyebrow">' + esc(it.label) + '</div>') +
        '<h2>' + esc(it.message) + '</h2>';
      if (it.forbidden) {
        h += '<p class="detail">This phrase must not be used. Carry on, and don\u2019t repeat it.</p>';
      } else if (r.script) {
        h += '<div class="quote"><span class="cap">Say this</span><p>' + esc(r.script) + '</p></div>';
        var alts = (r.alternatives || []).filter(function (a) { return a && String(a).trim() && a !== r.script; });
        if (alts.length) {
          if (ui.alt[it.key]) h += alts.map(function (a) { return '<div class="quote"><span class="cap">Or say this</span><p>' + esc(a) + '</p></div>'; }).join('');
          h += '<button class="alt" data-act="alt" data-k="' + esc(it.key) + '">' + (ui.alt[it.key] ? 'Show one way' : (alts.length === 1 ? 'Show another way to say it' : 'Show ' + alts.length + ' other ways to say it')) + '</button>';
        }
        h += listenLine('Clears itself when you say it');
      } else if (r.coaching_only) {
        h += '<div class="coach">There is nothing to say to undo this. Carry on, and do not repeat it \u2014 it is recorded for coaching.</div>';
      } else if (r.action) {
        h += '<p class="detail">' + esc(r.action) + '</p>' + listenLine('Clears itself when it\u2019s put right');
      }
      if (r.auto_clear_seconds != null) {
        h += '<div class="cd"><span data-cd="' + esc(it.key) + '"></span><div class="trk"><i data-cdb="' + esc(it.key) + '"></i></div></div>';
      }
      return h + '</div>';
    }
    if (it.kind === 'urgent') {
      return '<div class="focus urgent' + cls + '" role="alert"><div class="f-top"><span class="kind">Ask these now</span><span class="when">' + it.rows.length + ' to ask</span></div>' +
        '<div class="eyebrow">' + esc(it.reason) + '</div><div class="parts">' +
        it.rows.map(function (c) { return '<div class="part"><span class="o"></span><span>' + esc(c.label) + '</span></div>'; }).join('') + '</div>' +
        listenLine('Each one ticks itself as you ask it') + '</div>';
    }
    if (it.kind === 'missed') {
      var m = it.row || {};
      return '<div class="focus missed' + cls + '"><div class="f-top"><span class="kind">Missed</span><span class="when">' + esc(m.section_label || '') + '</span></div>' +
        '<div class="eyebrow">A critical check left behind earlier</div><h2>' + esc(m.label) + '</h2>' +
        partsList({ missing_parts: m.missing_parts, prompt: m.prompt, parts: [] }) + listenLine('Ticks itself when you cover it') + '</div>';
    }
    if (it.kind === 'cue') {
      return '<div class="focus cue' + cls + '"><div class="f-top"><span class="kind">Customer said</span></div><h2>' + esc(it.label) + '</h2>' +
        (it.suggestion ? '<p class="detail">' + esc(it.suggestion) + '</p>' : '') + '</div>';
    }
    // next
    var n = it.row || {};
    var stage = M.stageInfo(call).label;
    return '<div class="focus next' + cls + '"><div class="f-top"><span class="kind">Say next</span>' + (stage ? '<span class="when">' + esc(stage) + '</span>' : '') + '</div>' +
      '<h2>' + esc(n.label) + '</h2>' + partsList(n) + listenLine('Listening \u2014 this ticks itself') + '</div>';
  }

  function queueHtml(rest) {
    if (!rest.length) return '';
    var col = { critical: 'var(--red)', high: 'var(--ambDot)', next: 'var(--brand)', urgent: 'var(--red)', missed: 'var(--red)', safety: 'var(--redDeep)', cue: 'var(--ambDot)' };
    var lab = { critical: 'Put right', high: 'Put right', next: 'Say next', urgent: 'Ask now', missed: 'Missed', safety: 'Safety', cue: 'Cue' };
    return '<div class="queue"><div class="q-h"><span class="cap" style="color:var(--mute)">Then</span><span class="cap" style="color:var(--faint)">' + rest.length + '</span></div>' +
      rest.map(function (it) {
        var t = it.kind === 'urgent' ? 'Questions to ask now' : it.kind === 'safety' ? 'Customer safety' : it.label;
        return '<button class="qrow" data-act="focus" data-k="' + esc(it.key) + '"><span class="qdot" style="background:' + col[it.kind] + '"></span><span class="qt">' + esc(t) + '</span><span class="qk" style="color:' + col[it.kind] + '">' + lab[it.kind] + '</span><span style="display:flex;color:var(--faint)">' + I.chev + '</span></button>';
      }).join('') + '</div>';
  }

  function quietCard(title, text, busy) {
    return '<div class="focus quiet"><div class="pulse' + (busy ? ' busy' : '') + '"><i></i></div><h2 style="font-size:16px">' + esc(title) + '</h2><p class="detail" style="color:var(--mute)">' + esc(text) + '</p></div>';
  }

  function bodyLive() {
    var h = '';
    if (call.transcription === 'failed') h += '<div class="banner red">' + I.alertR + '<span>Live checking unavailable \u2014 transcription stopped. Your call is still being recorded.</span></div>';
    else if (call.transcription === 'degraded') h += '<div class="banner amber">' + I.warnA + '<span>Live checking interrupted \u2014 reconnecting\u2026</span></div>';
    if (host.paused) {
      return h + '<div class="focus quiet" style="background:#FFF3DA;border:1.5px solid #F2C46B"><div style="width:56px;height:56px;border-radius:28px;background:#F2B233;display:flex;align-items:center;justify-content:center;color:#3B2F12">' + I.pause + '</div>' +
        '<h2 style="color:var(--ambInk)">Paused for card payment</h2><p class="detail" style="color:#6B4F1C">Nothing is being recorded while the client reads out their card details.</p>' +
        '<button class="cta amber" data-act="pause">' + I.play + 'Resume recording</button></div>';
    }
    if (!host.livePipeline) return h + quietCard('Recording', 'This call is being recorded. Live checking is off for this call.');
    var items = M.attention(call);
    var hasAny = call.hasStage || call.missing.length || items.length;
    if (!hasAny) return h + quietCard('Listening', 'Your checklist appears here as the call gets going.', true);
    var focus = null;
    if (ui.focusKey) focus = items.filter(function (i) { return i.key === ui.focusKey; })[0] || null;
    if (!focus) { ui.focusKey = null; focus = items[0] || null; }
    var rest = items.filter(function (i) { return i !== focus; });
    h += stateLine(items);
    if (ui.flash && Date.now() < ui.flashUntil) {
      h += '<div class="focus clear enter" role="status" style="align-items:center;text-align:center;padding:26px 16px"><div style="width:56px;height:56px;border-radius:28px;background:var(--grn);display:flex;align-items:center;justify-content:center">' + I.bigTick + '</div><h2 style="color:var(--grnInk)">' + esc(ui.flash) + '</h2><span style="font-size:13px;color:var(--grnInk)">Moving to the next thing\u2026</span></div>';
    } else if (focus) {
      var enter = focus.key !== ui.lastFocusKey;
      ui.lastFocusKey = focus.key;
      h += focusCard(focus, enter);
      if (ui.focusKey && items[0] && focus !== items[0]) h += '<button class="back" data-act="focus" data-k="">Back to the most urgent</button>';
    } else {
      h += '<div class="focus clear"><div class="f-top"><span class="kind">All clear</span></div><h2>Everything in ' + esc(M.stageInfo(call).label || 'this stage') + ' is done</h2>' + listenLine('Listening') + '</div>';
    }
    h += queueHtml(rest);
    if (call.warnings.length) {
      h += '<button class="dont" data-act="sheet" data-v="dont">' + I.xr + '<span style="flex:1">' + call.warnings.length + ' thing' + (call.warnings.length > 1 ? 's' : '') + ' not to say' + (M.stageInfo(call).label ? ' in ' + esc(M.stageInfo(call).label) : '') + '</span><span style="display:flex">' + I.chev + '</span></button>';
    }
    return h;
  }

  function dockLive() {
    if (!host.livePipeline || host.paused) return '';
    var c = M.checklist(call);
    var total = c.total || c.legacy.length;
    var done = c.total ? c.done : 0;
    var pct = total ? Math.round(done / total * 100) : 0;
    var ie = call.ie && call.ie.visible ? call.ie : null;
    var di = ie ? ((ie.di && ie.di.shown && ie.di.value != null) ? ie.di.text : 'Pending') : 'Not yet';
    var diOk = ie && ie.di && ie.di.shown && ie.di.value != null;
    var fresh = ie && call.ieVersion > ui.ieSeen && ui.sheet !== 'ie' && !ui.pinIE;
    return '<div class="dock">' +
      '<button class="dk" data-act="sheet" data-v="list" aria-label="Open the checklist"><span class="ringm" style="background:conic-gradient(var(--brand) 0 ' + pct + '%,#E3DFF3 ' + pct + '% 100%)"><i></i></span><span class="dt"><span>Checklist</span><span>' + (c.total ? done + ' of ' + total : (total ? total + ' to do' : '\u2014')) + '</span></span>' +
      (c.earlierCount ? '<span class="early" title="' + c.earlierCount + ' still to do from earlier stages">+' + c.earlierCount + '</span>' : '') + '</button>' +
      '<button class="dk" data-act="sheet" data-v="ie" aria-label="Open the income and expenditure"><span class="tile" style="background:#E9F7EF;color:var(--grnInk)">' + I.coins + '</span><span class="dt"><span>I&amp;E \u00b7 DI</span><span class="' + (diOk ? 'mono' : '') + '" style="font-size:14px;' + (diOk ? '' : 'color:var(--amb)') + '">' + esc(di) + '</span></span>' + (fresh ? '<span class="new" aria-label="New figures"></span>' : '') + '</button></div>';
  }

  function footLive() {
    if (call.conn === 'buffering') return '<div class="ft warn"><span class="dotc" style="background:var(--ambDot)"></span>Reconnecting \u2014 audio is saved on this PC</div>';
    if (call.conn === 'failed') return '<div class="ft bad"><span class="dotc" style="background:var(--red)"></span>Saved on this PC \u2014 will not upload</div>';
    if (host.paused) return '<div class="ft warn"><span class="dotc" style="background:var(--ambDot)"></span>Paused \u2014 nothing is being recorded</div>';
    if (!host.livePipeline) return '<div class="ft"><span class="dotc" style="background:var(--grn)"></span>Recording</div>';
    if (call.transcription === 'failed') return '<div class="ft bad"><span class="dotc" style="background:var(--red)"></span>Live checking stopped \u2014 still recording</div>';
    if (call.transcription === 'degraded') return '<div class="ft warn"><span class="dotc" style="background:var(--ambDot)"></span>Live checking reconnecting</div>';
    return '<div class="ft"><span class="dotc" style="background:var(--grn)"></span>Listening \u00b7 live checking on</div>';
  }

  function checklistSheet() {
    var c = M.checklist(call);
    var h = '';
    if (c.total) {
      h += '<div class="st-h">' + esc(c.stage || 'This stage') + '<span style="margin-left:auto;color:var(--brand)">' + c.done + ' / ' + c.total + '</span></div>';
      c.rows.forEach(function (x) {
        var r = x.row, ok = !!r.done, urg = !!r.urgent && !ok;
        var cls = ok ? ' ok' : urg ? ' urg' : x.now ? ' now' : '';
        // The tag sits BESIDE the label, top-aligned on the right - under it, it
        // read as a second, squashed line (Faseeh, 15 Oct).
        var tag = urg ? '<span class="tagurg">Ask now</span>' : (x.now ? '<span class="tagnow">Say next</span>' : '');
        var tx = '<span class="line"><span class="lb">' + esc(r.label) + '</span>' + tag + '</span>';
        if (ok && r.evidence) tx += '<span class="q">\u201c' + esc(String(r.evidence).slice(0, 110)) + '\u201d</span>';
        if (!ok) {
          var parts = M.liveParts(r);
          if (parts.length >= 2) {
            var d = parts.filter(function (p) { return p.done; }).length;
            tx += '<span class="miss">' + d + ' of ' + parts.length + ' parts done</span>';
          }
        }
        h += '<div class="ck' + cls + '"><span class="o">' + (ok ? I.tick : '') + '</span><span class="tx">' + tx + '</span></div>';
      });
    } else if (c.legacy.length) {
      h += '<div class="st-h">Still to cover</div>' + c.legacy.map(function (i) {
        return '<div class="ck"><span class="o" style="border-color:' + (String(i.level).toLowerCase() === 'red' ? 'var(--red)' : 'var(--ambDot)') + '"></span><span class="tx"><span>' + esc(i.label) + '</span>' + (i.suggestion_text ? '<span class="miss">' + esc(i.suggestion_text) + '</span>' : '') + '</span></div>';
      }).join('');
    } else {
      h += '<div class="msg plain">The checklist appears as the call gets going.</div>';
    }
    if (c.earlierCount) {
      h += '<div class="st-h" style="margin-top:8px;color:var(--amb)">Still to do from earlier \u00b7 ' + c.earlierCount + '</div>';
      c.earlier.forEach(function (g) {
        if (g.section) h += '<span class="sec-name">' + esc(g.section) + '</span>';
        g.rows.forEach(function (r) {
          var miss = (r.missing_parts || []).filter(Boolean);
          h += '<div class="ck"><span class="o"></span><span class="tx"><span>' + esc(r.label) + '</span>' + (miss.length ? '<span class="miss">Missing: ' + esc(miss.slice(0, 4).join(', ')) + (miss.length > 4 ? ' +' + (miss.length - 4) : '') + '</span>' : '') + '</span></div>';
        });
      });
    }
    return h;
  }

  function dontSheet() {
    return '<div class="dlist">' + call.warnings.map(function (w) { return '<div class="d">' + I.xr + '<span>' + esc(w.text) + '</span></div>'; }).join('') +
      '<span style="font-size:12.5px;font-style:italic;color:var(--mute)">Said once, these cannot be undone later in the call.</span></div>';
  }

  function ieBody() {
    var ie = call.ie;
    if (!ie || !ie.visible) return '<div class="msg plain">The income and expenditure builds itself here once the call reaches Income.</div>';
    var view = ie.view === 'expenditure' ? 'expenditure' : 'income';
    var inc = ie.income || {}, exp = ie.expenditure || {}, di = ie.di || {}, hd = ie.header || {};
    var diPending = !(di.shown && di.value != null);
    var h = '<div style="display:flex;align-items:center;gap:8px"><span class="cap" style="color:var(--mute)">' + (ie.solutions ? 'Solutions' : view === 'expenditure' ? 'Expenditure' : 'Income') + '</span></div>';
    h += '<div class="ie-sum"><div><span class="cap">Income</span><span class="mono' + (inc.amber ? ' amb' : '') + '">' + esc(inc.text || '\u00a30') + '</span></div>' +
      '<div><span class="cap">Outgoings</span><span class="mono' + (exp.amber ? ' amb' : '') + '">' + (view === 'expenditure' ? esc(exp.text || '\u00a30') : '\u2014') + '</span></div>' +
      '<div><span class="cap">DI</span><span class="mono' + (diPending ? ' amb' : '') + '">' + (di.shown ? esc(diPending ? 'Pending' : di.text) : '\u2014') + '</span></div></div>';
    if (di.shown && diPending && di.note) h += '<div class="ie-note">' + esc(di.note) + '</div>';
    function fact(label, v) { v = v || 'Pending'; return '<div class="kv"><span>' + label + '</span>' + (v === 'Pending' ? '<span class="pd">Pending</span>' : '<span>' + esc(v) + '</span>') + '</div>'; }
    h += '<div class="facts">' + fact('Household', hd.household) + fact('Vehicles', hd.vehicles) + fact('Client affordability', hd.affordability) + '</div>';
    if (view === 'income') {
      h += '<div class="st-h">Income</div>';
      var groups = inc.groups || [];
      if (!groups.length) h += '<div class="msg plain">Income sources appear here as the client gives them.</div>';
      groups.forEach(function (g) { h += groupHtml('income.' + g.key, g, true); });
    } else {
      var items = [];
      (inc.groups || []).forEach(function (g) { (g.items || []).forEach(function (it) { items.push(it); }); });
      h += '<div class="st-h">Income</div>' + groupHtml('income.all', { label: 'Income', icon: 'coins', text: inc.text || '\u00a30', amber: inc.amber, items: items }, false);
      h += '<div class="st-h">Outgoings</div>';
      (exp.groups || []).forEach(function (g) { h += groupHtml('exp.' + g.key, g, false); });
    }
    return h;
  }

  function groupHtml(key, g, openByDefault) {
    var open = (key in ui.open) ? ui.open[key] : openByDefault;
    var text = g.text || 'Pending';
    var pending = text === 'Pending';
    var dotCol = { green: 'var(--grn)', red: 'var(--red)', grey: '#B4B4C6' }[g.dot];
    var h = '<div class="grp' + (g.unresolved ? ' un' : '') + '"><button data-act="grp" data-k="' + esc(key) + '" aria-expanded="' + open + '">' +
      '<span class="tile">' + ieIcon(g.icon) + '</span><span class="gl">' + esc(g.label) + '</span>' +
      (g.unresolved && text !== 'Unresolved' ? '<span class="tg">UNRESOLVED</span>' : '') +
      (pending ? '<span class="gv pd">Pending</span>'
               : text === 'Unresolved' ? '<span class="gv word">Unresolved</span>'
               : '<span class="gv' + (g.amber ? ' amb' : '') + '">' + esc(text) + '</span>') +
      (dotCol ? '<span class="gdot" style="background:' + dotCol + '" aria-label="' + esc(g.dot) + '"></span>' : '') +
      '<span style="display:flex;color:var(--faint)">' + (open ? I.down : I.chev) + '</span></button>';
    if (open) {
      var items = g.items || [];
      h += '<div class="its">';
      if (!items.length) h += '<div class="it pending"><div class="r1"><span class="il">Nothing given yet.</span></div></div>';
      items.forEach(function (it) {
        var pk = key + '/' + (it.key || it.label);
        var parts = it.parts || [];
        var showParts = parts.length > 1 && ui.parts[pk];
        h += '<div class="it' + (it.state === 'pending' ? ' pending' : '') + '"><div class="r1"><span class="il">' + esc(it.label) + '</span><span class="iv">' + esc(it.text || '\u2014') + '</span></div>';
        if (it.flag) h += '<div class="fl"><span class="dotc" style="width:6px;height:6px;flex:0 0 6px;background:var(--ambDot)"></span>' + esc(it.flag) + '</div>';
        if (showParts) {
          h += parts.map(function (p) { return '<div class="pt' + (p.flag ? ' amb' : '') + '"><span>' + esc(p.label) + '</span><span>' + esc(p.text || '\u2014') + '</span></div>' + (p.flag ? '<div class="fl" style="padding-left:12px"><span class="dotc" style="width:6px;height:6px;flex:0 0 6px;background:var(--ambDot)"></span>' + esc(p.flag) + '</div>' : ''); }).join('');
        } else if (it.note) {
          h += '<div class="nt">' + esc(it.note) + '</div>';
        }
        if (parts.length > 1) h += '<button class="pbtn" data-act="parts" data-k="' + esc(pk) + '">' + (showParts ? 'Hide the parts' : 'Show the ' + parts.length + ' parts') + '</button>';
        h += '</div>';
      });
      h += '</div>';
    }
    return h + '</div>';
  }

  function sheetLive() {
    if (!ui.sheet) return '';
    var titles = { list: 'Checklist', ie: 'Income & expenditure', dont: 'Not to say' + (M.stageInfo(call).label ? ' in ' + M.stageInfo(call).label : '') };
    var body = ui.sheet === 'list' ? checklistSheet() : ui.sheet === 'ie' ? ieBody() : dontSheet();
    var nb = '';
    if (ui.newKey && Date.now() < ui.newUntil) {
      var it = M.attention(call).filter(function (i) { return i.key === ui.newKey; })[0];
      if (it) nb = '<div class="newbar" role="alert" data-anim="newbar-' + esc(it.key) + '"><span class="qdot" style="background:var(--red)"></span><span class="t">New: ' + esc(it.label || 'card') + '</span><button data-act="closeSheet">View</button></div>';
    }
    return '<div class="scrim" data-anim="scrim-live" data-act="closeSheet"></div><div class="sheet" data-anim="sheet-' + ui.sheet + '" role="dialog" aria-label="' + esc(titles[ui.sheet]) + '"><div class="grab"></div><div class="sh-h"><h3>' + esc(titles[ui.sheet]) + '</h3>' +
      (ui.sheet === 'ie' && call.ie && call.ie.visible ? '<button class="pinbtn" data-act="pin" title="Keep the I&amp;E open beside the panel">' + I.pin + 'Pin</button>' : '') +
      '<button class="sh-x" data-act="closeSheet" aria-label="Close">' + I.x + '</button></div>' + nb +
      '<div class="sh-b" data-scroll="sheet">' + body + '</div></div>';
  }

  function pinHtml() {
    if (!(ui.pinIE && host.phase === 'live' && !ui.collapsed)) return '';
    return '<div class="pin" data-anim="pin"><div class="sh-h" style="padding-top:12px" data-drag><h3>Income &amp; expenditure</h3><button class="sh-x" data-act="unpin" aria-label="Unpin">' + I.x + '</button></div><div class="sh-b" data-scroll="pin">' + ieBody() + '</div></div>';
  }

  /* ---------- strip ---------- */
  function stripHtml() {
    var items = M.attention(call);
    var fixes = M.fixCount(items);
    var hasNext = items.some(function (i) { return i.kind === 'next' || i.kind === 'urgent' || i.kind === 'missed'; });
    var ie = call.ie && call.ie.visible ? call.ie : null;
    var di = ie && ie.di && ie.di.shown && ie.di.value != null ? ie.di.text : '\u2026';
    var open = host.dock === 'left' ? I.openL : I.openR;
    return '<div class="strip" data-drag><span class="rec' + (host.paused ? ' pa' : '') + '"></span><span class="tm mono" data-t></span><div class="sep"></div>' +
      (fixes ? '<button class="sb r" data-act="expand" aria-label="' + fixes + ' to put right"><span class="mono">' + fixes + '</span><span class="cap">Fix</span></button>'
             : '<button class="sb ' + (hasNext ? 'v' : 'z') + '" data-act="expand" aria-label="Open the panel"><span class="mono">' + (hasNext ? '1' : '0') + '</span><span class="cap">Next</span></button>') +
      (host.livePipeline ? '<button class="sb g" data-act="openSheet" data-v="ie" aria-label="Disposable income"><span class="mono">' + esc(di) + '</span><span class="cap">DI</span></button>' : '') +
      '<div class="grow"></div>' +
      (host.paused ? '<button class="ib resume" data-act="pause" aria-label="Resume recording">' + I.play + '</button>' : '<button class="ib pause" data-act="pause" aria-label="Pause for card payment">' + I.pause + '</button>') +
      '<button class="ib stop" data-act="stop" aria-label="Stop recording">' + I.stop + '</button>' +
      '<button class="ib ghost" data-act="expand" aria-label="Open the panel">' + open + '</button></div>';
  }

  function peekHtml() {
    if (!(ui.peekKey && Date.now() < ui.peekUntil)) return '';
    var it = M.attention(call).filter(function (i) { return i.key === ui.peekKey; })[0];
    if (!it) return '';
    var r = it.row || {};
    return '<div class="peekwrap"><div data-anim="peek-' + esc(it.key) + '" class="peek ' + it.kind + '" role="alert"><div class="focus ' + it.kind + '"><div class="f-top"><span class="kind">New \u00b7 put right</span><span class="when">just now</span></div>' +
      '<div class="eyebrow">' + esc(it.label) + '</div><h2>' + esc(it.message || '') + '</h2>' +
      (r.script ? '<div class="quote"><span class="cap">Say this</span><p>' + esc(r.script) + '</p></div>' : '') +
      '<div class="pa"><button class="go" data-act="expand">Open the panel</button><button class="kp" data-act="keep">Keep as count</button></div></div><div class="pb"><i></i></div></div></div>';
  }

  /* ---------- pages ---------- */
  function loginHtml() {
    var L = host.login || {};
    var out = host.signedOut;
    var h = '';
    if (out) h += '<div class="out" role="alert"><span class="cap" style="color:#FFD9D4">Signed out</span><span class="big">Calls are NOT being recorded</span><span class="sm">Sign in to start recording again. This window stays on screen until you do.</span></div>';
    h += '<div class="hero" data-drag' + (out ? ' style="padding:22px 28px"' : '') + '><img class="bigLogo" src="' + ASSET + 'logo.png" alt="Spark Flow"><h2>Spark Flow</h2><p>Sign in to record and coach your calls</p></div>';
    h += '<div class="pad">';
    if (L.error) h += '<div class="msg red" role="alert">' + I.alertR + '<span>' + esc(L.error) + '</span></div>';
    if (L.info) h += '<div class="msg green" role="status">' + I.tickG + '<span>' + esc(L.info) + '</span></div>';
    h += '<div class="fld"><label for="f-email">Work email</label><div class="inp">' + I.mail + '<input id="f-email" type="email" autocomplete="username" placeholder="name@theinsolvencygroup.co.uk"' + (L.busy ? ' disabled' : '') + '></div></div>';
    h += '<div class="fld"><label for="f-pw">Password</label><div class="inp' + (L.error ? ' err' : '') + '">' + I.lock + '<input id="f-pw" type="' + (ui.showPw ? 'text' : 'password') + '" autocomplete="current-password" placeholder="Your password"' + (L.busy ? ' disabled' : '') + '>' +
      '<button class="eye" data-act="eye" aria-label="' + (ui.showPw ? 'Hide password' : 'Show password') + '">' + (ui.showPw ? I.eyeOff : I.eye) + '</button></div></div>';
    h += '<button class="cta" data-act="login"' + (L.busy ? ' disabled' : '') + '>' + (L.busy ? '<span class="spin"></span>Signing in\u2026' : 'Sign in') + '</button>';
    h += '<button class="linkb" data-act="forgot"' + (L.busy || L.forgotBusy ? ' disabled' : '') + '>' + (L.forgotBusy ? 'Sending\u2026' : 'Forgot password?') + '</button>';
    h += '<div style="margin-top:auto;text-align:center;font-size:11px;color:var(--faint)">Spark Flow ' + esc(host.version || '') + '</div></div>';
    return h;
  }

  function idleHeader() {
    var u = host.user || {};
    return '<div class="hd row" data-drag><img class="logo" src="' + ASSET + 'logo.png" alt=""><div class="hd-id"><span class="name">' + esc(host.company || 'Spark Flow') + '</span><span class="sub">' + esc([u.name || u.email || '', u.dept || ''].filter(Boolean).join(' \u00b7 ')) + '</span></div>' +
      '<button class="ib ghost" data-act="settings" aria-label="Settings" title="Settings">' + I.gear + '</button>' +
      '<button class="ib ghost" data-act="hide" aria-label="Hide to the tray" title="Hide to the tray">' + I.minus + '</button></div>';
  }

  function idleBody() {
    var s = host.shift || {};
    var h = '';
    if (host.phase === 'starting') {
      h += '<div class="wait"><div class="pulse busy"><i></i></div><h2>Connecting\u2026</h2><p>Starting the recording. This takes a second or two.</p></div>';
    } else {
      h += '<div class="wait"><div class="pulse"><i></i></div><h2>Ready for your next call</h2><p>Recording starts by itself when the dialer connects. Nothing to do here.</p></div>';
      if (ui.manual) {
        if (!host.hideFields) {
          h += '<div class="fld"><label for="f-name">Customer name</label><div class="inp"><input id="f-name" placeholder="e.g. John Smith"></div></div>';
          h += '<div class="fld"><label for="f-ref">Reference ID</label><div class="inp"><input id="f-ref" placeholder="e.g. REF-12345"></div></div>';
          h += '<button class="cta" data-act="start">Start recording</button><button class="linkb" data-act="manual">Cancel</button>';
        } else {
          h += '<div class="msg plain">Customer details are managed by the dialer for your team. Start the call in the dialer and recording starts by itself.</div><button class="linkb" data-act="manual">OK</button>';
        }
      } else {
        h += '<button class="linkb" data-act="manual">Start a call manually</button>';
      }
    }
    h += '<div class="hr"></div><span class="cap" style="color:var(--mute)">This shift</span>' +
      '<div class="tiles"><div><span class="mono">' + esc(s.calls != null && s.calls !== '' ? s.calls : '\u2014') + '</span><span>Calls</span></div>' +
      '<div><span class="mono" style="color:var(--grnInk)">' + esc(s.avg || '\u2014') + '</span><span>Average</span></div>' +
      '<div><span class="mono" style="color:var(--amb)">' + esc(s.flags != null && s.flags !== '' ? s.flags : '\u2014') + '</span><span>Flags</span></div></div>';
    h += '<div style="margin-top:auto;text-align:center;font-size:11px;color:var(--faint)">Spark Flow ' + esc(host.version || '') + ' \u00b7 Focus layout</div>';
    return h;
  }

  function overlayIdle() {
    if (host.micGate) {
      var mics = host.mics || [];
      var sel = ui.gateIndex == null ? 0 : ui.gateIndex;
      return '<div class="overlay" data-anim="gate"><div class="card" role="dialog" aria-label="Choose your microphone"><span class="cap" style="color:var(--brand)">One-time setup</span><span style="font-size:20px;font-weight:800">Choose your microphone</span>' +
        '<span style="font-size:13px;color:var(--mute);line-height:1.45">Pick your headset so we record your voice clearly. You only do this once on this PC.</span>' +
        '<div role="radiogroup" aria-label="Microphone" style="display:flex;flex-direction:column;gap:8px">' +
        (mics.length ? mics.map(function (n, i) { return '<button class="opt' + (i === sel ? ' on' : '') + '" role="radio" aria-checked="' + (i === sel) + '" data-act="gatePick" data-v="' + i + '"><span class="radio"></span><span>' + esc(n) + '</span></button>'; }).join('')
          : '<div class="msg amber">No microphone found. Plug in your headset, then rescan.</div>') + '</div>' +
        '<button class="cta" data-act="gateConfirm"' + (mics.length ? '' : ' disabled') + '>Use this microphone</button>' +
        '<button class="linkb" data-act="rescan">Don\u2019t see your headset? Rescan</button></div></div>';
    }
    if (!ui.settings) return '';
    var mi = host.micIndex, si = host.spkIndex;
    // Our own dropdown, not a <select>. Windows draws a native select's list as
    // a separate popup: outside the panel, in another font, cut-off device
    // names on one line (Faseeh, 15 Oct). This one opens inside the panel,
    // wraps long names, ticks the current device and closes on Esc or a click away.
    function dropdown(name, label, list, cur, empty) {
      list = list || [];
      var open = ui.dd === name;
      var current = list[cur] != null ? list[cur] : (list.length ? list[0] : empty);
      var h = '<div class="fld"><span class="lbl" id="dd-' + name + '-l">' + label + '</span>' +
        '<div class="dd' + (open ? ' open' : '') + (ui.ddShut === name ? ' shut' : '') + '" data-anim="ddw-' + name + (open ? '-o' : '-c') + '"><button class="dd-btn" data-act="dd" data-v="' + name + '" aria-haspopup="listbox" aria-expanded="' + open + '" aria-labelledby="dd-' + name + '-l"' + (list.length ? '' : ' disabled') + '>' +
        '<span class="v" title="' + esc(current) + '">' + esc(current) + '</span><span class="chev">' + I.down + '</span></button>';
      if (open) {
        h += '<div class="dd-list" data-anim="dd-' + name + '" role="listbox" aria-labelledby="dd-' + name + '-l">' + list.map(function (n, i) {
          return '<button class="dd-opt' + (i === cur ? ' on' : '') + '" role="option" aria-selected="' + (i === cur) + '" data-act="ddPick" data-v="' + name + '" data-k="' + i + '">' +
            '<span class="tk">' + (i === cur ? I.tickB : '') + '</span><span class="t">' + esc(n) + '</span></button>';
        }).join('') + '</div>';
      }
      return h + '</div></div>';
    }
    return '<div class="scrim" data-anim="scrim-settings" data-act="settings"></div><div class="sheet" data-anim="sheet-settings" role="dialog" aria-label="Settings"><div class="grab"></div><div class="sh-h"><h3>Settings</h3><button class="sh-x" data-act="settings" aria-label="Close">' + I.x + '</button></div>' +
      '<div class="sh-b" data-scroll="settings"><span class="cap" style="color:var(--mute)">Audio</span>' +
      dropdown('mic', 'Your voice', host.mics, mi, 'No microphone found') +
      dropdown('spk', 'Customer voice', host.spks, si, 'No speaker found') +
      '<button class="linkb" style="align-self:flex-start;display:flex;align-items:center;gap:6px" data-act="rescan">' + I.refresh + 'Rescan devices</button>' +
      '<div class="hr"></div><span class="cap" style="color:var(--mute)">Servers</span>' +
      '<div class="fld"><label for="s-api">API base URL</label><div class="inp"><input id="s-api" value="' + esc(host.apiBase || '') + '"></div></div>' +
      '<div class="fld"><label for="s-ws">Recording server URL</label><div class="inp"><input id="s-ws" value="' + esc(host.wsUrl || '') + '"></div></div>' +
      '<button class="cta" data-act="saveServers">Save settings</button>' +
      '<div class="hr"></div><button class="cta danger" data-act="logout">Log out</button></div></div>';
  }

  function summaryHeader() {
    return '<div class="hd row" data-drag><span class="name" style="flex:1">Call ended</span><span class="mono" style="font-size:15px;font-weight:700;color:var(--nightMute)">' + M.mmss((summary && summary.duration) || 0) + '</span></div>';
  }

  function summaryBody() {
    var s = summary || { mode: 'pending' };
    var h = '';
    if (s.mode === 'pending') {
      h += '<div class="wait"><div class="pulse busy"><i></i></div><h2>Working out your score\u2026</h2><p>This takes a moment after the call ends.</p></div>';
    } else if (s.mode === 'score' && s.score != null) {
      var pct = Math.round(s.score * 100);
      var col = pct >= 90 ? 'var(--grn)' : pct >= 70 ? 'var(--ambDot)' : 'var(--red)';
      var ink = pct >= 90 ? 'var(--grnInk)' : pct >= 70 ? 'var(--amb)' : 'var(--red)';
      var cov = s.covered || [], mis = s.missed || [];
      h += '<div class="bigscore"><div class="rc" style="background:conic-gradient(' + col + ' 0 ' + pct + '%,var(--line) ' + pct + '% 100%)"><div style="color:' + ink + '">' + pct + '%</div></div><div style="display:flex;flex-direction:column;gap:4px"><span style="font-size:16px;font-weight:800">' + cov.length + ' covered \u00b7 ' + mis.length + ' missed</span><span style="font-size:13px;color:var(--mute)">Missed checks are grouped by stage below.</span></div></div>';
      if (mis.length) {
        var shown = ui.summaryAll ? mis : mis.slice(0, 3);
        h += '<div class="box"><span class="cap" style="color:var(--red)">' + (ui.summaryAll ? 'Missed \u00b7 ' + mis.length : 'Worth working on') + '</span>';
        var last = null;
        shown.forEach(function (x) {
          var sec = x.section || '';
          if (ui.summaryAll && sec && sec !== last) { last = sec; h += '<span class="sec-name">' + esc(sec) + '</span>'; }
          h += '<div class="ck"><span class="o" style="border-color:#E2A6A0"></span><span class="tx"><span>' + esc(x.label) + '</span>' + (!ui.summaryAll && sec ? '<span class="miss">' + esc(sec) + '</span>' : '') + '</span></div>';
        });
        if (mis.length > 3) h += '<button class="linkb" style="align-self:flex-start;padding-left:0" data-act="sumAll">' + (ui.summaryAll ? 'Show the top three' : 'Show all ' + mis.length) + '</button>';
        h += '</div>';
      }
    } else {
      h += '<div class="wait"><div class="pulse"><i></i></div><h2>Call saved</h2><p>Your recording is safe. There is no score for this call.</p></div>';
    }
    if (s.mode !== 'pending') {
      h += s.saved ? '<div class="msg green">' + I.tickG + '<span><b>Recording saved</b></span></div>'
                   : '<div class="msg plain"><span class="spin" style="border-color:#D6D3E3;border-top-color:var(--brand)"></span><span>Saving the recording\u2026</span></div>';
    }
    return h;
  }

  /* ---------- layout ---------- */
  function wantLayout() {
    var live = host.phase === 'live';
    var strip = live && ui.collapsed;
    var peek = strip && !!ui.peekKey && Date.now() < ui.peekUntil;
    var pin = live && !strip && ui.pinIE;
    return { mode: strip ? 'strip' : 'panel', pin: !!pin, peek: !!peek };
  }

  function render() {
    var app = document.getElementById('app');
    app.className = host.dock === 'left' ? 'dock-left' : 'dock-right';
    var lay = wantLayout();
    var lk = JSON.stringify(lay);
    if (lk !== ui.layoutKey) { ui.layoutKey = lk; send('layout', lay); }
    var ph = host.phase;
    if (ph === 'boot') { buildShape('boot', '<div class="panel"></div>'); return; }
    if (ph === 'login') {
      buildShape('login', '<div class="panel' + '" data-r-panel><div data-r="login" style="display:flex;flex-direction:column;height:100%"></div></div>');
      document.querySelector('[data-r-panel]').classList.toggle('alarm', !!host.signedOut);
      setRegion('login', loginHtml());
    } else if (ph === 'idle' || ph === 'starting') {
      buildShape('idle', '<div class="panel"><div data-r="idleHd"></div><div class="pad" data-r="idleBody" data-scroll="idle"></div><div data-r="overlay"></div></div>');
      setRegion('idleHd', idleHeader());
      setRegion('idleBody', idleBody());
      setRegion('overlay', overlayIdle());
    } else if (ph === 'summary') {
      // The button sits outside the scroller: a long list of missed checks
      // must never push "Ready for the next call" off the bottom.
      buildShape('summary', '<div class="panel"><div data-r="sumHd"></div><div class="pad" data-r="sumBody" data-scroll="sum"></div>' +
        '<div style="padding:12px 20px 20px;background:var(--surf);border-top:1px solid var(--line)"><button class="cta" data-act="newcall">Ready for the next call</button></div></div>');
      setRegion('sumHd', summaryHeader());
      setRegion('sumBody', summaryBody());
    } else if (ph === 'live' && lay.mode === 'strip') {
      buildShape('strip', '<div data-r="peek" style="display:contents"></div><div data-r="strip" style="display:contents"></div>');
      setRegion('peek', peekHtml());
      setRegion('strip', stripHtml());
    } else if (ph === 'live') {
      buildShape('live', '<div data-r="pin" style="display:contents"></div><div class="panel"><div data-r="hd"></div><div class="body" data-r="body" data-scroll="body"></div><div data-r="dock"></div><div data-r="ft"></div><div data-r="sheet"></div><div data-r="toast"></div></div>');
      setRegion('hd', headerLive());
      setRegion('body', bodyLive());
      setRegion('dock', dockLive());
      setRegion('ft', footLive());
      setRegion('sheet', sheetLive());
      setRegion('pin', pinHtml());
    }
    dynamic();
    // Tell the widget once the first real screen is in the page, so it can
    // show the window then - already docked - instead of an empty frame.
    // A timer, not requestAnimationFrame: rAF does not run while the window is
    // minimised to the tray, and then the window would never be shown.
    if (!drawnSent && ph !== 'boot') {
      drawnSent = true;
      setTimeout(function () { send('drawn'); }, 50);
    }
  }
  var drawnSent = false;

  /* Text that changes every second, updated in place - never by rebuilding. */
  function dynamic() {
    var t = M.mmss(host.elapsed || 0);
    document.querySelectorAll('[data-t]').forEach(function (e) { if (e.textContent !== t) e.textContent = t; });
    document.querySelectorAll('[data-ago]').forEach(function (e) {
      var v = M.ago((host.elapsed || 0) - Number(e.getAttribute('data-ago')));
      if (e.textContent !== v) e.textContent = v;
    });
    var now = Date.now();
    call.actions.forEach(function (r) {
      var left = M.secondsLeft(call, r, now);
      if (left == null) return;
      var key = 'card:' + M.cardKey(r);
      var e = document.querySelector('[data-cd="' + cssq(key) + '"]');
      if (e) e.textContent = 'Leaves the screen in ' + M.mmss(left);
      var b = document.querySelector('[data-cdb="' + cssq(key) + '"]');
      if (b) b.style.width = Math.max(0, Math.min(100, left / Number(r.auto_clear_seconds || 1) * 100)) + '%';
    });
  }
  function cssq(s) { return String(s).replace(/(["\\])/g, '\\$1'); }

  var queued = false;
  function schedule() {
    if (queued) return;
    queued = true;
    // A timer, not requestAnimationFrame: rAF does not run in a hidden or
    // minimised window, and the panel must be current the instant it is shown.
    setTimeout(function () { queued = false; render(); }, 16);
  }

  /* ---------- events ---------- */
  function val(id) { var e = document.getElementById(id); return e ? e.value : ''; }

  // The last few things the advisor pressed and phase changes, for support and
  // the end-to-end test (FocusApp.debug). Names only - never what was typed.
  var trail = [];
  function note(what) { trail.push(what); if (trail.length > 20) trail.shift(); }

  function act(a, v, k) {
    note('act:' + a);
    switch (a) {
      case 'login': {
        var em = val('f-email').trim(), pw = val('f-pw');
        if (!em || !pw) { host.login = Object.assign({}, host.login, { error: 'Enter your email and password.', info: '' }); break; }
        send('login', { email: em, password: pw });
        break;
      }
      case 'forgot': send('forgot', { email: val('f-email').trim() }); break;
      case 'eye': ui.showPw = !ui.showPw; break;
      case 'manual': ui.manual = !ui.manual; break;
      case 'start': send('start', { name: val('f-name').trim(), ref: val('f-ref').trim() }); break;
      case 'settings': ui.settings = !ui.settings; ui.dd = null; ui.ddShut = null; if (ui.settings) send('rescan'); break;
      case 'hide': send('hide'); break;
      case 'rescan': send('rescan'); break;
      case 'saveServers': send('saveServers', { api: val('s-api').trim(), ws: val('s-ws').trim() }); ui.settings = false; break;
      case 'logout': ui.settings = false; send('logout'); break;
      case 'gatePick': ui.gateIndex = Number(v); break;
      case 'gateConfirm': send('gateMic', { index: ui.gateIndex == null ? 0 : ui.gateIndex }); break;
      case 'pause': send('pause'); break;
      case 'stop': send('stop'); break;
      case 'collapse': ui.collapsed = true; ui.sheet = null; ui.pinIE = false; break;
      case 'expand': ui.collapsed = false; ui.peekKey = null; break;
      case 'keep': ui.peekKey = null; break;
      case 'sheet': ui.sheet = v; if (v === 'ie') ui.ieSeen = call.ieVersion; break;
      case 'openSheet': ui.collapsed = false; ui.peekKey = null; ui.sheet = v; if (v === 'ie') ui.ieSeen = call.ieVersion; break;
      case 'closeSheet': ui.sheet = null; ui.newKey = null; break;
      case 'pin': ui.pinIE = true; ui.sheet = null; ui.ieSeen = call.ieVersion; break;
      case 'unpin': ui.pinIE = false; break;
      case 'focus': ui.focusKey = k || null; break;
      case 'alt': ui.alt[k] = !ui.alt[k]; break;
      case 'grp': ui.open[k] = !((k in ui.open) ? ui.open[k] : k.indexOf('income.') === 0 && k !== 'income.all' && (call.ie && call.ie.view !== 'expenditure')); break;
      case 'parts': ui.parts[k] = !ui.parts[k]; break;
      case 'newcall': summary = null; send('newcall'); break;
      case 'sumAll': ui.summaryAll = !ui.summaryAll; break;
      case 'dd': ui.ddShut = ui.dd === v ? v : (ui.dd || null); ui.dd = ui.dd === v ? null : v; break;
      case 'ddPick': {
        var i = Number(k);
        // Shown at once; the widget confirms it on its next state.
        if (v === 'mic') host.micIndex = i; else host.spkIndex = i;
        ui.ddShut = v;
        ui.dd = null;
        send(v, { index: i });
        break;
      }
      default: return;
    }
    schedule();
  }

  document.addEventListener('click', function (ev) {
    // A click anywhere outside an open dropdown closes it.
    if (ui.dd && !ev.target.closest('.dd')) { ui.ddShut = ui.dd; ui.dd = null; schedule(); }
    var b = ev.target.closest('[data-act]');
    if (!b || b.disabled) return;
    act(b.getAttribute('data-act'), b.getAttribute('data-v'), b.getAttribute('data-k'));
  });
  document.addEventListener('change', function (ev) {
    var t = ev.target;
    var c = t && t.getAttribute && t.getAttribute('data-change');
    if (c) send(c, { index: Number(t.value) });
  });
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape') {
      if (ui.dd) { ui.ddShut = ui.dd; ui.dd = null; schedule(); }
      else if (ui.sheet) { ui.sheet = null; schedule(); } else if (ui.settings) { ui.settings = false; schedule(); }
    } else if (ev.key === 'Enter') {
      var id = ev.target && ev.target.id;
      if (id === 'f-pw' || id === 'f-email') act('login');
      else if (id === 'f-ref' || id === 'f-name') act('start');
    }
  });
  // Drag the window by its header. The OS does the moving (startSystemMove),
  // so it behaves like any other window and snaps to an edge when let go.
  document.addEventListener('mousedown', function (ev) {
    if (ev.button !== 0) return;
    if (ev.target.closest('button,input,select,a,[data-act]')) return;
    if (ev.target.closest('[data-drag]')) { send('move'); }
  });

  /* ---------- clock ---------- */
  setInterval(function () {
    var now = Date.now(), again = false;
    if (M.expire(call, now)) again = true;
    if (ui.flash && now >= ui.flashUntil) { ui.flash = null; again = true; }
    if (ui.peekKey && now >= ui.peekUntil) { ui.peekKey = null; again = true; }
    if (ui.newKey && now >= ui.newUntil) { ui.newKey = null; again = true; }
    if (again) schedule(); else dynamic();
  }, 500);

  /* ---------- connect ---------- */
  window.FocusApp = {
    connect: function (b) {
      bridge = b;
      if (b.push && b.push.connect) b.push.connect(onPush);
      if (b.ready) b.ready();
    },
    push: onPush,          // the dev harness feeds messages through here
    debug: function () { return { host: host, call: call, ui: ui, summary: summary, trail: trail.slice() }; }
  };
  schedule();
}());
