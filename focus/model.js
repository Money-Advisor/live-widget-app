/* Spark Flow Focus - the model.
 *
 * Pure functions, no DOM. Turns the recording server's messages into what the
 * Focus panel shows. Loaded by the panel (window.FocusModel) and by the Node
 * tests (module.exports), so every rule below is tested without a browser.
 *
 * The rules are the classic widget's rules, ported - not reinvented. Each one
 * names the classic code it mirrors, because the classic widget learned them
 * from real calls (see main.py), and a second copy that drifts would show an
 * advisor something different from what the classic screen would have shown.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.FocusModel = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  function newCall() {
    return {
      stage: '', sections: [], checks: [], still: [], openCrit: [], warnings: [],
      actions: [], cards: {}, batch: 0, expired: {},
      crisis: null, crisisShown: false,
      forbidden: [], cues: [], missing: [],
      ie: null, ieVersion: 0,
      conn: 'ok', transcription: 'ok',
      hasStage: false
    };
  }

  // A card is one trigger AND one occurrence. On the id alone, an advisor who
  // made the same mistake twice would see the warning once: the first card
  // times out, its id is remembered as expired, and the second finding is
  // filtered straight back out (AdvisorAlertsPanel._card_key).
  function cardKey(row) {
    return String(row.id || row.message || '') + '#' + (row.occurrence == null ? '' : row.occurrence);
  }

  function setActions(m, rows, nowMs, elapsed) {
    var items = (rows || []).filter(function (r) {
      return r && typeof r === 'object' && String(r.message || '').trim() && !m.expired[cardKey(r)];
    });
    var fresh = items.filter(function (r) { return !m.cards[cardKey(r)]; });
    if (fresh.length) {
      m.batch += 1;
      fresh.forEach(function (r) {
        m.cards[cardKey(r)] = { batch: m.batch, bornMs: nowMs, at: elapsed };
      });
    }
    // NEWEST FIRST. Bilal, 1 Oct (ref444): "the latest card should always
    // appear at the top". Cards that arrived together keep the server's order
    // (AdvisorAlertsPanel.set_trigger_actions).
    var sent = {};
    items.forEach(function (r, i) { sent[cardKey(r)] = i; });
    items.sort(function (a, b) {
      var A = m.cards[cardKey(a)], B = m.cards[cardKey(b)];
      return (B.batch - A.batch) || (sent[cardKey(a)] - sent[cardKey(b)]);
    });
    m.actions = items;
    return fresh.length > 0;
  }

  /* Apply one server message. Returns what changed, so the panel can react
   * (a NEW card, for instance, is the only thing allowed to move the view). */
  function applyMessage(m, msg, nowMs, elapsed) {
    var out = { changed: false, newCard: false };
    if (!msg || typeof msg !== 'object') return out;
    var t = msg.type;
    if (t === 'crisis_alert') {
      // Shown once and latched for the call (show_crisis). A second alert
      // for the same disclosure must not raise it again.
      if (!m.crisisShown) { m.crisis = msg; m.crisisShown = true; out.changed = true; out.newCard = true; }
      return out;
    }
    if (t === 'compliance_alert') {
      var forb = msg.forbidden_hits || [];
      if (forb.length) {
        forb.forEach(function (f) {
          if (!m.forbidden.some(function (x) { return x.id === f.id; })) {
            m.forbidden.unshift({ id: f.id, label: f.label || 'Forbidden phrase used', at: elapsed });
            out.newCard = true;
          }
        });
        out.changed = true;
        return out;            // a forbidden-only message never touches the checklist
      }
      var cues = msg.cue_hits || [];
      if (cues.length) {
        cues.forEach(function (c) {
          if (!m.cues.some(function (x) { return x.id === c.id; })) {
            m.cues.unshift({ id: c.id, label: c.label || 'Customer cue', suggestion: c.suggestion_text || '' });
          }
        });
        out.changed = true;
        return out;
      }
      m.missing = msg.missing_items || [];
      // Only a message that CARRIES stage fields may change the stage, the
      // warnings or the cards. The server's "good job" message has none of
      // them, and passing it through blanked the panel every time a check
      // went green (_handle_server_message).
      var hasStage = !!(msg.sections || msg.section_checks || msg.stage);
      if (hasStage) {
        m.hasStage = true;
        m.stage = msg.stage || '';
        m.sections = msg.sections || [];
        m.checks = msg.section_checks || [];
        m.still = (msg.still_to_do || []).filter(function (r) { return r && String(r.label || '').trim(); });
        m.openCrit = (msg.open_criticals || []).filter(function (r) { return r && String(r.label || '').trim(); });
        m.warnings = (msg.warnings || []).filter(function (w) { return w && String(w.text || '').trim(); });
        out.newCard = setActions(m, msg.trigger_actions, nowMs, elapsed) || out.newCard;
        if (msg.crisis_resolved && m.crisis) m.crisis = null;   // latch stays: never re-raised
      }
      out.changed = true;
      return out;
    }
    if (t === 'ie_panel') {
      m.ie = msg; m.ieVersion += 1; out.changed = true;
      return out;
    }
    if (t === 'transcription_status') {
      m.transcription = msg.state === 'recovered' ? 'ok' : (msg.state || 'ok');
      out.changed = true;
      return out;
    }
    if (t === 'connection_status') {
      m.conn = msg.state === 'resumed' ? 'ok' : (msg.state || 'ok');
      out.changed = true;
      return out;
    }
    return out;
  }

  /* Cards that clear themselves (auto_clear_seconds) - off the screen when
   * their time is up, and never back: the server keeps sending the row
   * (_expire_action). `is null` and not a truth test - 0 means immediately. */
  function expire(m, nowMs) {
    var changed = false;
    m.actions = m.actions.filter(function (r) {
      var secs = r.auto_clear_seconds;
      if (secs === null || secs === undefined) return true;
      var info = m.cards[cardKey(r)];
      if (info && nowMs - info.bornMs >= Number(secs) * 1000) {
        m.expired[cardKey(r)] = true; changed = true; return false;
      }
      return true;
    });
    return changed;
  }

  function secondsLeft(m, row, nowMs) {
    var info = m.cards[cardKey(row)];
    if (!info || row.auto_clear_seconds == null) return null;
    return Math.max(0, Number(row.auto_clear_seconds) - (nowMs - info.bornMs) / 1000);
  }

  function isCritical(sev) { return sev === 'critical'; }

  /* Everything that needs the advisor, most urgent first. The panel shows the
   * first in full and queues the rest. Order:
   *   1 customer safety - nothing outranks it
   *   2 corrections (put right), newest first, as Bilal ruled
   *   3 questions a vulnerability disclosure made due now
   *   4 critical checks left behind in an earlier stage
   *   5 the next thing to say in this stage
   *   6 customer cues (old matcher only)
   */
  function attention(m) {
    var items = [];
    if (m.crisis) items.push({ key: 'crisis', kind: 'safety', crisis: m.crisis });
    m.forbidden.forEach(function (f) {
      items.push({ key: 'forbidden:' + f.id, kind: 'critical', forbidden: true,
                   label: 'Forbidden phrase', message: 'You said: ' + f.label, at: f.at });
    });
    m.actions.forEach(function (r) {
      var info = m.cards[cardKey(r)] || {};
      items.push({ key: 'card:' + cardKey(r), kind: isCritical(r.severity) ? 'critical' : 'high',
                   row: r, label: r.label || r.message, message: r.message, at: info.at });
    });
    var urgent = m.checks.filter(function (c) { return c && c.urgent && !c.done; });
    if (urgent.length) {
      items.push({ key: 'urgent', kind: 'urgent', rows: urgent,
                   reason: urgent[0].urgent_reason || 'Ask these now' });
    }
    m.openCrit.forEach(function (r) {
      items.push({ key: 'missed:' + (r.id || r.label), kind: 'missed', row: r, label: r.label });
    });
    var next = m.checks.filter(function (c) { return c && !c.done && !c.urgent; })[0];
    if (next) {
      items.push({ key: 'next:' + next.id, kind: 'next', row: next, label: next.label });
    } else if (!m.checks.length && m.missing.length) {
      // The old matcher sends no stages - only a list of what is missing.
      var red = m.missing.filter(function (i) { return String(i.level || '').toLowerCase() === 'red'; })[0];
      var first = red || m.missing[0];
      items.push({ key: 'next:' + first.id, kind: 'next', legacy: true,
                   row: { id: first.id, label: first.label, prompt: first.suggestion_text, parts: [] },
                   label: first.label });
    }
    m.cues.forEach(function (c) {
      items.push({ key: 'cue:' + c.id, kind: 'cue', label: c.label, suggestion: c.suggestion });
    });
    return items;
  }

  function fixCount(items) {
    return items.filter(function (i) { return i.kind === 'critical' || i.kind === 'high' || i.kind === 'safety'; }).length;
  }

  function titleCase(s) {
    return String(s || '').replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }

  /* Where the call has got to. The rulebook sends every section with one
   * marked current (StageTracker.update_stage). */
  function stageInfo(m) {
    var secs = m.sections || [];
    var idx = -1;
    for (var i = 0; i < secs.length; i++) { if (secs[i] && secs[i].current) { idx = i; break; } }
    var label = idx >= 0 ? (secs[idx].label || secs[idx].key || '') : titleCase(m.stage);
    return {
      label: label, index: idx, total: secs.length,
      segments: secs.map(function (s, i) {
        if (idx >= 0 && i === idx) return 'here';
        if (idx >= 0 && i < idx) return 'done';
        if (s && s.total && s.done === s.total) return 'done';
        return 'todo';
      })
    };
  }

  /* A check's parts, minus the ones the customer's answer ruled out - "no
   * partner" retires four questions about a partner, and counting them made
   * a check the advisor could never finish (SectionAccordion._caret). */
  function liveParts(row) {
    return (row && row.parts || []).filter(function (p) { return !p.na || p.done; });
  }

  function checklist(m) {
    var rows = m.checks.slice();
    var next = rows.filter(function (c) { return !c.done && !c.urgent; })[0];
    var groups = [];
    m.still.forEach(function (r) {
      var sec = r.section_label || '';
      var g = groups.filter(function (x) { return x.section === sec; })[0];
      if (!g) { g = { section: sec, rows: [] }; groups.push(g); }
      g.rows.push(r);
    });
    return {
      stage: stageInfo(m).label,
      done: rows.filter(function (c) { return c.done; }).length,
      total: rows.length,
      rows: rows.map(function (c) { return { row: c, now: c === next }; }),
      earlier: groups,
      earlierCount: m.still.length,
      legacy: !rows.length ? m.missing : []
    };
  }

  function mmss(t) {
    t = Math.max(0, Math.floor(Number(t) || 0));
    var mm = Math.floor(t / 60), ss = t % 60;
    return (mm < 10 ? '0' : '') + mm + ':' + (ss < 10 ? '0' : '') + ss;
  }

  function ago(sec) {
    if (sec == null || isNaN(sec)) return '';
    sec = Math.max(0, Math.floor(sec));
    return sec < 60 ? 'just now' : Math.floor(sec / 60) + ' min ago';
  }

  return {
    newCall: newCall, applyMessage: applyMessage, expire: expire, secondsLeft: secondsLeft,
    attention: attention, fixCount: fixCount, stageInfo: stageInfo, checklist: checklist,
    liveParts: liveParts, cardKey: cardKey, mmss: mmss, ago: ago, titleCase: titleCase
  };
}));
