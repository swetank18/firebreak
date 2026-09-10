/* Firebreak — operator dashboard.
 *
 * This page CONTROLS a scenario rather than replaying a frozen one. Pick the
 * hazard, the seed, how late the call is made and how big the budget is, and
 * press Run.
 *
 * Two engines behind it:
 *   live   `python -m service.api` runs the real cascade engine and the real
 *          decision layer on demand. Detected via GET /api/health.
 *   static a precomputed matrix in ./data/, so the same page works on a host
 *          that cannot run Python. Same code path, same fields.
 *
 * Nothing here computes a simulation result. Ranking, counting and sorting are
 * reading the file; the branching ratios, damages and deadlines are the
 * engine's.
 */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var fmt = function (n) { return Number(n || 0).toLocaleString(); };
  var MATRIX = window.MATRIX || { scenarios: [] };

  var CITY = null, SC = null;              // city topology, current scenario
  var live = false;
  var runKey = 'do_nothing', clock = 0, playing = false, raf = null;
  var sortBy = 'br', hindsight = false, selected = null;
  var decided = [];                        // the operator's own decisions

  function hhmm(t) {
    return 'T+' + String(Math.floor(t / 3600)).padStart(2, '0') + ':' +
           String(Math.floor((t % 3600) / 60)).padStart(2, '0');
  }
  function mmss(s) {
    s = Math.max(0, Math.round(s));
    return String(Math.floor(s / 60)).padStart(2, '0') + ':' +
           String(s % 60).padStart(2, '0');
  }

  // ------------------------------------------------------------ engine mode
  function setMode(isLive, text) {
    live = isLive;
    $('mode').className = 'mode' + (isLive ? ' live' : '');
    $('modeText').textContent = text;
  }
  fetch('/api/health').then(function (r) { return r.ok ? r.json() : null; })
    .then(function (j) {
      if (j && j.ok) setMode(true, 'live engine · runs on demand');
      else setMode(false, 'precomputed scenarios');
    })
    .catch(function () { setMode(false, 'precomputed scenarios'); })
    .finally(fillControls);

  // ------------------------------------------------------------- controls
  function fillControls() {
    var hazards = live
      ? ['monsoon_flood', 'heatwave', 'cyber', 'equipment_age', 'none']
      : uniq(MATRIX.scenarios.map(function (s) { return s.hazard; }));
    // Monsoon first and selected: it is the anchored hazard and the one with a
    // live cascade at the decision point. Opening on cyber showed an empty
    // queue, because its onset is at 25% of the horizon and nothing has failed
    // yet — true, and a terrible first screen.
    hazards.sort(function (a, b) {
      return (a === 'monsoon_flood' ? -1 : 0) - (b === 'monsoon_flood' ? -1 : 0);
    });
    fill($('fHazard'), hazards, hazards[0]);
    syncSeeds();
    var whens = live ? [[0.1, 'early · 10%'], [0.25, 'standard · 25%'],
                        [0.4, 'late · 40%'], [0.6, 'very late · 60%']]
                     : uniq(MATRIX.scenarios.map(function (s) { return s.decide_frac; }))
                         .map(function (f) { return [f, Math.round(f * 100) + '% of horizon']; });
    fillPairs($('fWhen'), whens);
    var budgets = live ? [[1, '1'], [3, '3'], [5, '5'], [10, '10']]
                       : [[MATRIX.budget || 5, String(MATRIX.budget || 5) + ' (fixed)']];
    fillPairs($('fBudget'), budgets);
    $('fBudget').disabled = !live;
    if (Q.get('hazard')) $('fHazard').value = Q.get('hazard');
    syncSeeds();
    if (Q.get('seed')) $('fSeed').value = Q.get('seed');
    if (Q.get('sort')) setSort(Q.get('sort'));
    if (Q.get('hindsight') === '1') { hindsight = true; $('hindsight').checked = true; }
    $('fHazard').addEventListener('change', syncSeeds);
    $('ctlNote').textContent = live
      ? 'The engine runs when you press Run. Expect a few seconds — it simulates 72 hours, decides, then re-runs the counterfactuals.'
      : 'Served without a Python process, so these are precomputed combinations. Run `python -m service.api` to drive the engine live and unlock every hazard, budget and decision time.';
    run();
  }
  function syncSeeds() {
    var h = $('fHazard').value;
    var seeds = live ? [90105, 90210, 90311, 90412, 90513]
      : uniq(MATRIX.scenarios.filter(function (s) { return s.hazard === h; })
             .map(function (s) { return s.seed; }));
    fill($('fSeed'), seeds, seeds[0]);
  }
  // Deep link: ?hazard=&seed=&sort=s|br&hindsight=1 — so a moment can be shared,
  // and so this screen can be rendered for review.
  var Q = new URLSearchParams(location.search);
  function uniq(a) { return a.filter(function (v, i) { return a.indexOf(v) === i; }); }
  function fill(sel, vals, cur) {
    sel.innerHTML = vals.map(function (v) {
      return '<option value="' + v + '"' + (v === cur ? ' selected' : '') + '>' + v + '</option>';
    }).join('');
  }
  function fillPairs(sel, pairs) {
    sel.innerHTML = pairs.map(function (p) {
      return '<option value="' + p[0] + '">' + p[1] + '</option>';
    }).join('');
  }

  // ------------------------------------------------------------------ run
  function run() {
    var hazard = $('fHazard').value, seed = Number($('fSeed').value);
    var frac = Number($('fWhen').value), budget = Number($('fBudget').value);
    $('runBtn').disabled = true;
    $('runBtn').textContent = live ? 'Simulating…' : 'Loading…';
    var p = live
      ? fetch('/api/simulate', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ hazard: hazard, seed: seed, decide_frac: frac,
                                 budget: budget, protect: 0.9 })
        }).then(function (r) { return r.json(); })
      : loadStatic(hazard, seed, frac);
    p.then(function (sc) {
      if (!sc || sc.error) throw new Error((sc && sc.error) || 'no scenario');
      SC = sc; decided = []; selected = null; runKey = 'do_nothing';
      clock = sc.t_decide_s;                 // open at the moment of the call
      paintRuns(); paintLog(); refresh();
    }).catch(function (e) {
      $('queue').innerHTML = '<p class="qempty"><b>Could not load that scenario.</b><br>' +
        String(e.message || e) + '</p>';
    }).finally(function () {
      $('runBtn').disabled = false; $('runBtn').textContent = 'Run scenario';
    });
  }
  function loadStatic(hazard, seed, frac) {
    var key = hazard + '-s' + seed + '-d' + Math.round(frac * 100);
    return fetch('data/' + key + '.json').then(function (r) {
      if (!r.ok) throw new Error('combination not precomputed: ' + key);
      return r.json();
    });
  }
  $('runBtn').addEventListener('click', run);

  // ---------------------------------------------------------------- city
  fetch('data/city.json').then(function (r) { return r.json(); })
    .then(function (c) { CITY = c; buildIndex(); refresh(); })
    .catch(function () {});
  var byId = {};
  function buildIndex() { CITY.nodes.forEach(function (n) { byId[n.id] = n; }); }

  // -------------------------------------------------------------- queue
  function alerts() {
    if (!SC) return [];
    var tl = SC.runs[runKey] ? SC.runs[runKey].timeline : [];
    return tl.filter(function (r) { return r.t <= clock; });
  }
  // Ground truth, exported per alert: did a chain from this failure go on to
  // reach the health layer? An operator does not have this at the time. It is
  // here so the ranking can be judged after the fact, and it is labelled.
  function outcomeHit(r) { return !!(r && r.h); }
  function paintQueue() {
    var a = alerts().slice();
    a.sort(function (x, y) { return sortBy === 'br' ? y.br - x.br : y.s - x.s; });
    $('qCount').textContent = a.length;
    if (!a.length) {
      $('queue').innerHTML = '<p class="qempty">No alarms yet at this hour. ' +
        'Move the clock forward, or jump to the decision point.</p>';
      $('precision').textContent = '';
      return;
    }
    // The payoff goes ABOVE the list. Under a sixty-row queue nobody sees it.
    var n = Math.min(10, a.length), c = 0;
    for (var i = 0; i < n; i++) if (outcomeHit(a[i])) c++;
    var base = 0;
    for (var j = 0; j < a.length; j++) if (outcomeHit(a[j])) base++;
    var pct = Math.round(base / a.length * 100);
    $('precision').innerHTML =
      '<div class="big">' + c + ' <em>of ' + n + '</em></div>' +
      '<p>of the top ' + n + ' alarms under this ranking went on to reach a hospital, ' +
      'against a base rate of <b>' + pct + '%</b> across all ' + a.length +
      ' alarms. Switch the ranking and watch it move.</p>';

    var top = a.slice(0, 60);
    // FIXED domain, not scaled to whatever is on screen. n = 1 is the criterion
    // the whole project rests on, so the threshold has to sit in the same place
    // under both rankings — otherwise the bars are only comparable to each
    // other and "above one" stops being readable at a glance.
    var DOMAIN = 3.0;
    $('queue').innerHTML = top.map(function (r) {
      var hit = hindsight && outcomeHit(r);
      var w = Math.max(1.5, Math.min(100, r.br / DOMAIN * 100));
      var mark = 1 / DOMAIN * 100;
      return '<button class="qrow" data-id="' + r.n + '" aria-selected="' +
        (selected === r.n) + '">' +
        '<span class="qid">' + r.n + '</span>' +
        '<span class="qs">' + r.s.toFixed(2) + '</span>' +
        '<span class="qbar"><span class="' + (r.br > 1 ? 'hot' : '') +
          '" style="width:' + w.toFixed(1) + '%"></span>' +
          '<i style="left:' + mark.toFixed(1) + '%"></i></span>' +
        '<span class="qval' + (r.br > 1 ? ' hot' : '') + '">' + r.br.toFixed(2) + '</span>' +
        '<span class="qout' + (hit ? ' hit' : '') + '"></span></button>';
    }).join('');
    Array.prototype.forEach.call($('queue').querySelectorAll('.qrow'), function (b) {
      b.addEventListener('click', function () { select(b.dataset.id); });
    });
  }
  $('sortLoud').addEventListener('click', function () { setSort('s'); });
  $('sortDanger').addEventListener('click', function () { setSort('br'); });
  function setSort(k) {
    sortBy = k;
    $('sortLoud').setAttribute('aria-pressed', String(k === 's'));
    $('sortDanger').setAttribute('aria-pressed', String(k === 'br'));
    paintQueue();
  }
  $('hindsight').addEventListener('change', function (e) {
    hindsight = e.target.checked; paintQueue();
  });

  function select(id) {
    selected = id;
    var r = alerts().filter(function (x) { return x.n === id; })[0];
    var n = byId[id] || {};
    if (!r) { $('detail').innerHTML = '<dt>Nothing selected</dt><dd>—</dd>'; return; }
    var rows = [['Asset', id], ['Layer', n.l || '?'], ['Kind', n.k || '?'],
                ['People served', fmt(n.pop)], ['Alarm raised', hhmm(r.t)],
                ['Anomaly score', r.s.toFixed(3)],
                ['Branching ratio', r.br.toFixed(2) + (r.br > 1 ? '  (supercritical)' : '')]];
    if (hindsight) rows.push(['Reached a hospital', outcomeHit(r) ? 'yes' : 'no']);
    if (hindsight) rows.push(['Downstream reach', r.r === undefined ? '—' : r.r]);
    $('detail').innerHTML = rows.map(function (x) {
      return '<dt>' + x[0] + '</dt><dd>' + x[1] + '</dd>';
    }).join('');
    paintQueue();
  }

  // ------------------------------------------------------------- action
  function paintAction() {
    if (!SC) { $('action').innerHTML = ''; return; }
    var iv = SC.intervention || {};
    if (!iv.targets || !iv.targets.length) {
      $('action').innerHTML = '<p class="empty">No action recommended for this scenario. ' +
        'Nothing had failed by the decision time, so the search had no live cascade to ' +
        'reason about.</p>';
      return;
    }
    // A deadline of zero is NOT an expiry. It means the solver could not
    // establish one: the top action's estimated benefit was not positive under
    // its own rollout, so there is no point at which it decays past 90%. Saying
    // EXPIRED there would be the system claiming certainty it does not have.
    var hasDeadline = (iv.deadline_s || 0) > 0;
    var expiresAt = SC.t_decide_s + (iv.deadline_s || 0);
    var left = expiresAt - clock;
    var acted = decided.filter(function (d) { return d.what === 'dispatch'; }).length > 0;
    var cls = !hasDeadline ? 'warn' : (left <= 0 ? 'gone'
              : (left < (iv.deadline_s || 1) * 0.35 ? 'warn' : ''));
    $('action').innerHTML =
      '<div class="act' + (hasDeadline && left <= 0 ? ' expired' : '') + '">' +
      '<div class="kind">' + (iv.kind || 'n/a') + ' &times; ' + iv.targets.length +
        ' <span style="color:var(--ink-3);font-weight:400">· cost ' + (iv.cost || 0) + '</span></div>' +
      '<ul>' + (iv.rationale || []).map(function (t) { return '<li>' + t + '</li>'; }).join('') +
        (iv.compute_ms ? '<li>decided in ' + fmt(Math.round(iv.compute_ms)) + ' ms</li>' : '') +
      '</ul><div class="tgt">' + iv.targets.join('<br>') + '</div>' +
      '<div class="count"><span class="t ' + cls + '">' +
        (!hasDeadline ? 'NONE' : (left <= 0 ? 'EXPIRED' : mmss(left))) + '</span>' +
        '<span class="u">' + (!hasDeadline
          ? 'no deadline established &mdash; the search could not demonstrate a positive ' +
            'benefit for this action under its own rollout, so treat it as a suggestion ' +
            'rather than an instruction'
          : (left <= 0
             ? 'the option is past the point where it retains 90% of its value'
             : 'until this option is worth less than 90% of acting now')) +
        '</span></div>' +
      '<div class="btns">' +
        '<button class="go" id="doGo"' + (acted ? ' disabled' : '') + '>' +
          (acted ? 'Dispatched' : 'Dispatch') + '</button>' +
        '<button class="no" id="doNo"' + (acted ? ' disabled' : '') + '>Dismiss</button>' +
      '</div></div>';
    if ($('doGo')) $('doGo').addEventListener('click', function () { decide('dispatch'); });
    if ($('doNo')) $('doNo').addEventListener('click', function () { decide('dismiss'); });
  }
  function decide(what) {
    var iv = SC.intervention || {};
    var expiresAt = SC.t_decide_s + (iv.deadline_s || 0);
    var late = clock > expiresAt;
    decided.push({ t: clock, what: what, late: late });
    if (what === 'dispatch') { runKey = 'firebreak'; }
    paintRuns(); paintLog(); refresh();
  }
  function paintLog() {
    if (!decided.length) {
      $('log').innerHTML = '<p class="empty">Nothing dispatched yet. Anything you do here is ' +
        'recorded with the scenario clock, because a recommendation nobody can audit ' +
        'afterwards is not a decision.</p>';
      return;
    }
    var s0 = SC.runs.do_nothing.summary;
    $('log').innerHTML = decided.map(function (d) {
      if (d.what === 'dispatch') {
        var sf = SC.runs.firebreak ? SC.runs.firebreak.summary : s0;
        return '<div class="logrow good"><span class="t">' + hhmm(d.t) + '</span>' +
          '<span class="w"><b>Dispatched</b> ' + (SC.intervention.targets || []).length +
          ' assets' + (d.late ? ' — after the deadline' : '') + '. Outcome: ' +
          fmt(Math.round(sf.person_hours)) + ' person-hours lost against ' +
          fmt(Math.round(s0.person_hours)) + ' for doing nothing.</span></div>';
      }
      return '<div class="logrow bad"><span class="t">' + hhmm(d.t) + '</span>' +
        '<span class="w"><b>Dismissed</b> the recommendation. Outcome stands at ' +
        fmt(Math.round(s0.person_hours)) + ' person-hours lost.</span></div>';
    }).join('');
  }

  // ------------------------------------------------------------ runs/ticker
  var META = { do_nothing: ['Do nothing', 'alarm'], firebreak: ["Firebreak's action", 'safe'],
               human: ['Harden the hospitals', 'accent'] };
  function paintRuns() {
    if (!SC) return;
    $('runsel').innerHTML = ['do_nothing', 'firebreak', 'human']
      .filter(function (k) { return SC.runs[k]; })
      .map(function (k) {
        return '<button data-run="' + k + '" aria-pressed="' + (k === runKey) + '">' +
          '<span class="dot" style="background:var(--' + META[k][1] + ')"></span>' +
          '<span>' + META[k][0] + '</span><span class="v">' +
          fmt(Math.round(SC.runs[k].summary.person_hours)) + '</span></button>';
      }).join('');
    Array.prototype.forEach.call($('runsel').querySelectorAll('button'), function (b) {
      b.addEventListener('click', function () { runKey = b.dataset.run; paintRuns(); refresh(); });
    });
  }

  // ---------------------------------------------------------------- map
  var cv = $('mini'), ctx = cv.getContext('2d');
  function drawMap() {
    var W = cv.width, H = cv.height;
    ctx.clearRect(0, 0, W, H);
    if (!CITY) return;
    var css = getComputedStyle(document.documentElement);
    var col = function (k) { return css.getPropertyValue('--' + k).trim(); };
    var lats = CITY.nodes.map(function (n) { return n.lat; });
    var lons = CITY.nodes.map(function (n) { return n.lon; });
    var la0 = Math.min.apply(null, lats), la1 = Math.max.apply(null, lats);
    var lo0 = Math.min.apply(null, lons), lo1 = Math.max.apply(null, lons);
    var pad = 14;
    var X = function (n) { return pad + (n.lon - lo0) / (lo1 - lo0) * (W - 2 * pad); };
    var Y = function (n) { return H - pad - (n.lat - la0) / (la1 - la0) * (H - 2 * pad); };
    // flood line: everything below the current water level
    if (SC && SC.flood) {
      var i = Math.min(SC.flood.level.length - 1, Math.floor(clock / SC.flood.dt_s));
      var lvl = SC.flood.level[Math.max(0, i)] || 0;
      if (lvl > 0.001) {
        var y = H - pad - lvl * (H - 2 * pad);
        ctx.fillStyle = col('water'); ctx.globalAlpha = .22;
        ctx.fillRect(0, y, W, H - y); ctx.globalAlpha = 1;
        ctx.strokeStyle = col('water'); ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
      }
    }
    ctx.strokeStyle = col('transport'); ctx.globalAlpha = .34; ctx.lineWidth = .7;
    ctx.beginPath();
    (CITY.flow || []).forEach(function (e) {
      var a = CITY.nodes[e[0]], b = CITY.nodes[e[1]];
      if (!a || !b || a.l !== 'transport' || b.l !== 'transport') return;
      ctx.moveTo(X(a), Y(a)); ctx.lineTo(X(b), Y(b));
    });
    ctx.stroke(); ctx.globalAlpha = 1;
    var down = {};
    alerts().forEach(function (r) { down[r.n] = r; });
    CITY.nodes.forEach(function (n) {
      var st = down[n.id];
      var r = n.k === 'hospital' ? 5 : (n.l === 'transport' ? 1.5 : 3);
      ctx.beginPath(); ctx.arc(X(n), Y(n), st ? r * 1.25 : r, 0, 6.2832);
      ctx.fillStyle = st ? col('crisis') : col(n.l);
      ctx.globalAlpha = st ? 1 : (n.l === 'transport' ? .3 : .7);
      ctx.fill(); ctx.globalAlpha = 1;
      if (st && n.k === 'hospital') {                 // a hospital going dark is the headline
        ctx.beginPath(); ctx.arc(X(n), Y(n), 13, 0, 6.2832);
        ctx.strokeStyle = col('crisis'); ctx.lineWidth = 2; ctx.stroke();
        ctx.globalAlpha = .18; ctx.fillStyle = col('crisis'); ctx.fill(); ctx.globalAlpha = 1;
      }
      if (selected === n.id) {
        ctx.beginPath(); ctx.arc(X(n), Y(n), 11, 0, 6.2832);
        ctx.strokeStyle = col('ink'); ctx.lineWidth = 1.2; ctx.stroke();
      }
    });
  }

  // ------------------------------------------------------------- refresh
  function refresh() {
    if (!SC) return;
    $('clock').textContent = hhmm(clock);
    $('runLabel').textContent = SC.hazard + ' · seed ' + SC.seed;
    var a = alerts(), hosp = 0, people = 0, dang = 0;
    a.forEach(function (r) {
      var n = byId[r.n]; if (!n) return;
      people += n.pop || 0;
      if (n.k === 'hospital') hosp++;
      if (r.br > 1) dang++;
    });
    $('cFail').textContent = fmt(a.length);
    $('cHosp').textContent = hosp;
    $('cPeople').textContent = fmt(people);
    $('cDanger').textContent = dang;
    $('scrub').value = String(Math.round(clock / SC.horizon_s * 1000));
    paintQueue(); paintAction(); drawMap();
  }

  $('scrub').addEventListener('input', function (e) {
    if (!SC) return;
    stop(); clock = Number(e.target.value) / 1000 * SC.horizon_s; refresh();
  });
  $('reset').addEventListener('click', function () { stop(); clock = 0; refresh(); });
  $('toDecide').addEventListener('click', function () {
    if (SC) { stop(); clock = SC.t_decide_s; refresh(); }
  });
  function stop() { playing = false; if (raf) cancelAnimationFrame(raf); $('play').textContent = 'Play'; }
  $('play').addEventListener('click', function () {
    if (!SC) return;
    if (playing) return stop();
    playing = true; $('play').textContent = 'Pause';
    var last = performance.now();
    (function step(now) {
      if (!playing) return;
      var dt = Math.min(0.1, (now - last) / 1000); last = now;
      clock += SC.horizon_s / 45 * dt;
      if (clock >= SC.horizon_s) { clock = SC.horizon_s; refresh(); return stop(); }
      refresh(); raf = requestAnimationFrame(step);
    })(last);
  });
  document.addEventListener('keydown', function (e) {
    var t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'SELECT')) return;
    if (e.key === ' ') { e.preventDefault(); $('play').click(); }
    if (e.key.toLowerCase() === 'd') $('toDecide').click();
    if (e.key.toLowerCase() === 'r') $('reset').click();
  });
})();
