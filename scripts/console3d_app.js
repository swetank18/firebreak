/* Firebreak — Chennai flood, in three dimensions.
 *
 * The renderer computes nothing. The water level, every asset's elevation, and
 * every failure time are fields in the exported scenario: `flood.level` is the
 * hazard field the engine actually used, in the same normalised-elevation units
 * as each asset's `e`, so an asset is under water here exactly when it was
 * under water in the simulation.
 *
 * Terrain is the model's elevation proxy — latitude — and nothing more. It is a
 * ramp because the model says it is a ramp; inventing relief would be inventing
 * data. See docs/LIMITATIONS.md.
 */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var css = getComputedStyle(document.documentElement);
  var col = function (k) { return css.getPropertyValue('--' + k).trim(); };
  var fmt = function (n) { return n.toLocaleString(); };

  if (!window.THREE) { $('nogl').style.display = 'grid'; return; }
  var gl = null;
  try { gl = $('view').getContext('webgl2') || $('view').getContext('webgl'); } catch (e) {}
  if (!gl) { $('nogl').style.display = 'grid'; return; }

  // ---------------------------------------------------------------- data
  var RUNS = DATA.runs, ORDER = ['do_nothing', 'firebreak', 'human'];
  var META = {
    do_nothing: { label: 'Do nothing', dot: 'alarm', targets: [] },
    firebreak: { label: "Firebreak's action", dot: 'safe',
                 targets: (DATA.intervention || {}).targets || [] },
    human: { label: 'Harden the hospitals', dot: 'accent',
             targets: (DATA.human_action || {}).targets || [] }
  };
  var T_END = DATA.horizon_s, T_DEC = DATA.t_decide_s || 0;
  var nodes = DATA.nodes, N = nodes.length, byId = {}, index = {};
  nodes.forEach(function (n, i) { byId[n.id] = n; index[n.id] = i; });
  var LAYERS = ['power', 'water', 'transport', 'telecom', 'health'];
  var hidden = {};
  var FLOOD = DATA.flood || { level: [0], dt_s: T_END, peak: 0 };

  var runKey = 'do_nothing', clock = 0, playing = false, cursor = 0;
  var state = {}, baseline = {}, picked = null;
  RUNS.do_nothing.timeline.forEach(function (r) { baseline[r.n] = r.t; });

  // ------------------------------------------------------------- geometry
  var SIZE = 200, ELEV = 30;
  var lats = nodes.map(function (n) { return n.lat; });
  var lons = nodes.map(function (n) { return n.lon; });
  var la0 = Math.min.apply(null, lats), la1 = Math.max.apply(null, lats);
  var lo0 = Math.min.apply(null, lons), lo1 = Math.max.apply(null, lons);
  var px = function (n) { return ((n.lon - lo0) / (lo1 - lo0) - 0.5) * SIZE; };
  var pz = function (n) { return -(((n.lat - la0) / (la1 - la0)) - 0.5) * SIZE; };
  var elevOf = function (n) { return n.e !== undefined ? n.e : (n.lat - la0) / (la1 - la0); };

  // How tall each kind of asset stands, and how wide. A hospital reads as a
  // block, a tower as a mast, a road as a strip of ground.
  var SHAPE = {
    hospital: [2.2, 7.0], backup_generator: [1.4, 3.0], primary_care: [1.6, 3.6],
    intertie: [2.4, 9.0], substation: [2.0, 6.5], feeder: [1.0, 3.0],
    tower: [0.7, 8.0], backhaul: [1.6, 6.0], scada_link: [0.7, 4.0],
    treatment: [2.4, 4.0], reservoir: [2.8, 2.6], pumping_station: [1.6, 4.2],
    trunk_main: [1.0, 1.6], road_segment: [2.6, 0.35]
  };
  var shapeOf = function (n) { return SHAPE[n.k] || [1.2, 3.0]; };

  // ---------------------------------------------------------------- scene
  var scene = new THREE.Scene();
  var dark = matchMedia('(prefers-color-scheme: dark)').matches;
  scene.background = new THREE.Color(dark ? 0x0b1016 : 0xdfe6ee);
  scene.fog = new THREE.Fog(scene.background.getHex(), SIZE * 1.1, SIZE * 2.6);

  var camera = new THREE.PerspectiveCamera(42, 1, 1, 2000);
  var renderer = new THREE.WebGLRenderer({ canvas: $('view'), antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));

  scene.add(new THREE.HemisphereLight(dark ? 0x8fa8c8 : 0xffffff, dark ? 0x0a0f14 : 0x9aa7b4, dark ? 0.75 : 0.95));
  var sun = new THREE.DirectionalLight(0xffffff, dark ? 0.55 : 0.7);
  sun.position.set(-90, 130, 70);
  scene.add(sun);

  // ---- terrain: the elevation proxy, and nothing invented on top of it
  // The ground must use EXACTLY the mapping the assets use, or the city floats
  // above the terrain and the waterline stops agreeing with which assets are
  // actually submerged. An asset at latitude L sits at z = -(L' - 0.5) * SIZE
  // with elevation L', so the ground at z has elevation 0.5 - z / SIZE.
  var groundElev = function (z) { return Math.max(0, Math.min(1, 0.5 - z / SIZE)); };
  var SEG = 96;
  var tGeo = new THREE.PlaneGeometry(SIZE * 1.25, SIZE * 1.25, SEG, SEG);
  tGeo.rotateX(-Math.PI / 2);
  var tPos = tGeo.attributes.position, tCol = [];
  var lowCol = new THREE.Color(dark ? 0x223026 : 0xc7cfbe);
  var highCol = new THREE.Color(dark ? 0x33404b : 0xe6e2d6);
  for (var i = 0; i < tPos.count; i++) {
    var t = groundElev(tPos.getZ(i));
    tPos.setY(i, t * ELEV);
    var c = lowCol.clone().lerp(highCol, t);
    tCol.push(c.r, c.g, c.b);
  }
  tGeo.setAttribute('color', new THREE.Float32BufferAttribute(tCol, 3));
  tGeo.computeVertexNormals();
  scene.add(new THREE.Mesh(tGeo, new THREE.MeshLambertMaterial({ vertexColors: true })));

  // ---- water: the hazard field itself, raised to the exported level
  var wGeo = new THREE.PlaneGeometry(SIZE * 1.45, SIZE * 1.45, 60, 60);
  wGeo.rotateX(-Math.PI / 2);
  var wBase = wGeo.attributes.position.array.slice();
  var water = new THREE.Mesh(wGeo, new THREE.MeshPhongMaterial({
    color: new THREE.Color(dark ? 0x1d5f8f : 0x2f7fbf),
    transparent: true, opacity: 0.72, shininess: 90,
    specular: new THREE.Color(0x9fd0ff), side: THREE.DoubleSide,
    depthWrite: false
  }));
  water.renderOrder = 2;
  scene.add(water);

  // ---- assets, one instanced draw call
  var aGeo = new THREE.BoxGeometry(1, 1, 1);
  aGeo.translate(0, 0.5, 0);                          // grow upward from the ground
  var assets = new THREE.InstancedMesh(
    aGeo, new THREE.MeshLambertMaterial({}), N);
  assets.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  scene.add(assets);
  var dummy = new THREE.Object3D();
  var COLOR = {}, FAILED = new THREE.Color(dark ? 0xff5a45 : 0xb02a1a);
  var SAVED = new THREE.Color(dark ? 0x51c495 : 0x2e7d5b);
  var SUBMERGED = new THREE.Color(dark ? 0x2a6d9c : 0x24618f);
  LAYERS.forEach(function (l) { COLOR[l] = new THREE.Color(col(l)); });
  var tmpColor = new THREE.Color();

  function layout() {
    for (var i = 0; i < N; i++) {
      var n = nodes[i], sh = shapeOf(n), h = sh[1], w = sh[0];
      var vis = !hidden[n.l];
      dummy.position.set(px(n), elevOf(n) * ELEV, pz(n));
      dummy.scale.set(vis ? w : 0.0001, vis ? h : 0.0001, vis ? w : 0.0001);
      dummy.rotation.set(0, 0, 0);
      dummy.updateMatrix();
      assets.setMatrixAt(i, dummy.matrix);
    }
    assets.instanceMatrix.needsUpdate = true;
  }

  function paintAssets() {
    var lvl = waterLevel();
    var acted = META[runKey].targets, actedSet = {};
    acted.forEach(function (id) { actedSet[id] = 1; });
    var showActed = clock >= T_DEC;
    for (var i = 0; i < N; i++) {
      var n = nodes[i], st = state[n.id];
      if (st) tmpColor.copy(FAILED);
      else if (runKey !== 'do_nothing' && baseline[n.id] !== undefined && baseline[n.id] <= clock)
        tmpColor.copy(SAVED);                          // still standing; would be down
      else if (elevOf(n) < lvl) tmpColor.copy(SUBMERGED).lerp(COLOR[n.l], 0.35);
      else tmpColor.copy(COLOR[n.l]);
      if (showActed && actedSet[n.id]) tmpColor.lerp(new THREE.Color(0xffffff), 0.45);
      if (picked && picked.id === n.id) tmpColor.lerp(new THREE.Color(0xffffff), 0.6);
      assets.setColorAt(i, tmpColor);
    }
    if (assets.instanceColor) assets.instanceColor.needsUpdate = true;
  }

  // ---- dependency edges: the couplings failure actually travels along
  var lg = new THREE.BufferGeometry(), lpts = [];
  (DATA.deps || []).forEach(function (e) {
    var a = byId[e.s], b = byId[e.d];
    if (!a || !b) return;
    var ax = px(a), ay = elevOf(a) * ELEV + shapeOf(a)[1] * 0.6, az = pz(a);
    var bx = px(b), by = elevOf(b) * ELEV + shapeOf(b)[1] * 0.6, bz = pz(b);
    var lift = 6 + Math.hypot(bx - ax, bz - az) * 0.16;
    var prev = null;
    for (var s = 0; s <= 8; s++) {
      var t = s / 8;
      var p = [ax + (bx - ax) * t, ay + (by - ay) * t + Math.sin(Math.PI * t) * lift,
               az + (bz - az) * t];
      if (prev) lpts.push(prev[0], prev[1], prev[2], p[0], p[1], p[2]);
      prev = p;
    }
  });
  lg.setAttribute('position', new THREE.Float32BufferAttribute(lpts, 3));
  scene.add(new THREE.LineSegments(lg, new THREE.LineBasicMaterial({
    color: new THREE.Color(dark ? 0x4a5b6e : 0x9fb0c0), transparent: true, opacity: 0.3
  })));

  // ---------------------------------------------------------------- camera
  var orbit = { az: -0.52, el: 0.46, r: SIZE * 1.12, tx: 0, ty: ELEV * 0.45, tz: 0 };
  var HOME = JSON.parse(JSON.stringify(orbit));
  function applyCam() {
    orbit.el = Math.max(0.10, Math.min(1.45, orbit.el));
    orbit.r = Math.max(SIZE * 0.30, Math.min(SIZE * 3.0, orbit.r));
    camera.position.set(
      orbit.tx + orbit.r * Math.cos(orbit.el) * Math.sin(orbit.az),
      orbit.ty + orbit.r * Math.sin(orbit.el),
      orbit.tz + orbit.r * Math.cos(orbit.el) * Math.cos(orbit.az));
    camera.lookAt(orbit.tx, orbit.ty, orbit.tz);
  }
  var drag = null;
  $('view').addEventListener('pointerdown', function (e) {
    drag = { x: e.clientX, y: e.clientY, moved: 0 };
    $('view').setPointerCapture(e.pointerId);
  });
  $('view').addEventListener('pointermove', function (e) {
    if (!drag) return;
    var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    drag.moved += Math.abs(dx) + Math.abs(dy);
    orbit.az -= dx * 0.006; orbit.el += dy * 0.005;
    drag.x = e.clientX; drag.y = e.clientY; applyCam();
  });
  $('view').addEventListener('pointerup', function (e) {
    if (drag && drag.moved < 5) pick(e);
    drag = null;
    try { $('view').releasePointerCapture(e.pointerId); } catch (err) {}
  });
  $('view').addEventListener('wheel', function (e) {
    e.preventDefault(); orbit.r *= (1 + Math.sign(e.deltaY) * 0.09); applyCam();
  }, { passive: false });
  $('resetCam').addEventListener('click', function () {
    orbit = JSON.parse(JSON.stringify(HOME)); applyCam();
  });

  var ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  function pick(e) {
    var r = $('view').getBoundingClientRect();
    ndc.x = ((e.clientX - r.left) / r.width) * 2 - 1;
    ndc.y = -((e.clientY - r.top) / r.height) * 2 + 1;
    ray.setFromCamera(ndc, camera);
    var hit = ray.intersectObject(assets);
    picked = (hit.length && hit[0].instanceId !== undefined) ? nodes[hit[0].instanceId] : null;
    paintInspect(picked); paintAssets();
  }

  // ------------------------------------------------------------- the flood
  function waterLevel() {
    var i = Math.min(FLOOD.level.length - 1, Math.floor(clock / (FLOOD.dt_s || T_END)));
    return FLOOD.level[Math.max(0, i)] || 0;
  }
  function submergedPct() {
    var lvl = waterLevel(), c = 0;
    for (var i = 0; i < N; i++) if (elevOf(nodes[i]) < lvl) c++;
    return c / N;
  }

  // ---------------------------------------------------------------- clock
  function seekTo(t) {
    t = Math.max(0, Math.min(T_END, t));
    var tl = RUNS[runKey].timeline;
    if (t < clock) { state = {}; cursor = 0; }
    clock = t;
    while (cursor < tl.length && tl[cursor].t <= clock) {
      var e = tl[cursor++];
      if (byId[e.n]) state[e.n] = e;
    }
    refresh();
  }
  function counters() {
    var f = 0, hosp = 0, people = 0, dang = 0;
    for (var k in state) {
      var n = byId[k]; if (!n) continue;
      f++; people += n.pop || 0;
      if (n.k === 'hospital') hosp++;
      if (state[k].br > 1) dang++;
    }
    $('cFail').textContent = fmt(f); $('cHosp').textContent = hosp;
    $('cPeople').textContent = fmt(people); $('cDanger').textContent = dang;
  }
  function savedCount() {
    var c = 0;
    for (var id in baseline) if (baseline[id] <= clock && !state[id]) c++;
    return c;
  }
  function refresh() {
    var h = Math.floor(clock / 3600), m = Math.floor((clock % 3600) / 60);
    var txt = 'T+' + String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');
    $('clock').textContent = txt;
    $('track').setAttribute('aria-valuenow', Math.round(clock));
    $('track').setAttribute('aria-valuetext', txt);
    var lvl = waterLevel();
    // Reported on the model's own scale, which is a fraction of the city's
    // elevation range — not metres, because the model has no metres.
    $('waterLvl').textContent = lvl.toFixed(3);
    $('waterPct').textContent = Math.round(submergedPct() * 100) + '%';
    counters(); paintAssets(); drawTrack();
    var note = $('viewnote');
    if (runKey === 'do_nothing') note.hidden = true;
    else {
      var s = savedCount(); note.hidden = false;
      note.innerHTML = s
        ? '<b>' + fmt(s) + ' assets still standing</b> that had already failed by now if nobody acted — shown in green.'
        : 'No divergence from the do-nothing run yet.';
    }
    var btns = document.querySelectorAll('#runs button');
    for (var i = 0; i < btns.length; i++)
      btns[i].setAttribute('aria-pressed', String(btns[i].dataset.run === runKey));
  }

  // ------------------------------------------------------------- timeline
  var tl = $('tl'), tctx = tl.getContext('2d'), TW = 0, TH = 0, BINS = [];
  function bins() {
    var out = new Array(120).fill(0);
    RUNS[runKey].timeline.forEach(function (r) {
      out[Math.min(119, Math.floor(r.t / T_END * 120))]++;
    });
    return out;
  }
  function sizeTrack() {
    var r = $('track').getBoundingClientRect(), dpr = Math.min(devicePixelRatio || 1, 2);
    TW = Math.max(200, r.width); TH = Math.max(30, r.height - 15);
    tl.width = TW * dpr; tl.height = TH * dpr; tctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  function drawTrack() {
    tctx.clearRect(0, 0, TW, TH);
    // the flood, behind the failures it caused
    var fl = FLOOD.level, fmax = Math.max.apply(null, fl) || 1;
    tctx.beginPath(); tctx.moveTo(0, TH);
    for (var i = 0; i < fl.length; i++)
      tctx.lineTo(i / (fl.length - 1) * TW, TH - (fl[i] / fmax) * (TH - 4));
    tctx.lineTo(TW, TH); tctx.closePath();
    tctx.fillStyle = col('water'); tctx.globalAlpha = 0.22; tctx.fill(); tctx.globalAlpha = 1;
    var max = Math.max.apply(null, BINS) || 1, bw = TW / BINS.length;
    BINS.forEach(function (v, i) {
      var h = (v / max) * (TH - 6), past = (i + 1) / BINS.length * T_END <= clock;
      tctx.fillStyle = past ? col(runKey === 'firebreak' ? 'safe' : 'alarm') : col('rule');
      tctx.globalAlpha = past ? 0.85 : 1;
      tctx.fillRect(i * bw, TH - h, Math.max(1, bw - 0.6), h);
    });
    tctx.globalAlpha = 1;
    var dx = T_DEC / T_END * TW;
    tctx.strokeStyle = col('accent'); tctx.lineWidth = 1; tctx.setLineDash([3, 3]);
    tctx.beginPath(); tctx.moveTo(dx, 0); tctx.lineTo(dx, TH); tctx.stroke(); tctx.setLineDash([]);
    var cx = clock / T_END * TW;
    tctx.strokeStyle = col('ink'); tctx.lineWidth = 2;
    tctx.beginPath(); tctx.moveTo(cx, 0); tctx.lineTo(cx, TH); tctx.stroke();
    tctx.fillStyle = col('ink');
    tctx.beginPath(); tctx.moveTo(cx - 4, 0); tctx.lineTo(cx + 4, 0); tctx.lineTo(cx, 6); tctx.fill();
  }
  function drawAxis() {
    var a = $('axis'); a.innerHTML = '';
    for (var h = 0; h <= 72; h += 12) {
      var s = document.createElement('span');
      s.style.left = (h * 3600 / T_END * 100) + '%'; s.textContent = h + 'h'; a.appendChild(s);
    }
    var d = document.createElement('span');
    d.style.left = (T_DEC / T_END * 100) + '%'; d.style.color = col('accent');
    d.textContent = 'decide'; a.appendChild(d);
  }

  // ---------------------------------------------------------------- panels
  function paintRuns() {
    $('runs').innerHTML = ORDER.filter(function (k) { return RUNS[k]; }).map(function (k) {
      var s = RUNS[k].summary, m = META[k];
      return '<button data-run="' + k + '" aria-pressed="' + (k === runKey) + '">' +
        '<span class="dot" style="background:var(--' + m.dot + ')"></span>' +
        '<span>' + m.label + '</span>' +
        '<span class="val">' + fmt(Math.round(s.person_hours)) + '</span></button>';
    }).join('');
    Array.prototype.forEach.call($('runs').querySelectorAll('button'), function (b) {
      b.addEventListener('click', function () { selectRun(b.dataset.run); });
    });
  }
  function paintAction() {
    var iv = DATA.intervention || {};
    if (runKey === 'human') {
      var t = (DATA.human_action || {}).targets || [];
      $('actBlk').querySelector('h2').textContent = 'The human instinct';
      $('act').style.borderLeftColor = col('accent');
      $('act').innerHTML = '<div class="kind">harden &times; ' + t.length + '</div>' +
        '<ul><li>Protect the most critical assets on the map — same budget, and what an ' +
        'experienced operator reaches for.</li><li>It does not stop the cascade: ' +
        fmt(Math.round(RUNS.human.summary.person_hours)) + ' person-hours lost against ' +
        fmt(Math.round(RUNS.firebreak.summary.person_hours)) + '.</li></ul>' +
        '<div class="tgt">' + t.join('<br>') + '</div>';
      return;
    }
    $('actBlk').querySelector('h2').textContent = "Firebreak's action";
    $('act').style.borderLeftColor = col('safe');
    var mins = Math.round((iv.deadline_s || 0) / 60);
    $('act').innerHTML = '<div class="kind">' + (iv.kind || 'n/a') + ' &times; ' +
      ((iv.targets || []).length) + ' <span style="color:var(--ink-3);font-weight:400">· cost ' +
      (iv.cost || 0) + '</span></div><ul>' +
      (iv.rationale || []).map(function (r) { return '<li>' + r + '</li>'; }).join('') +
      '</ul><div class="tgt">' + (iv.targets || []).join('<br>') + '</div>' +
      '<div class="deadline"><span class="t">' + mins + '</span><span class="u">minutes before ' +
      'this option is worth less than 90% of acting now</span></div>';
  }
  function paintPair() {
    var p = DATA.pair;
    if (!p) { $('pair').innerHTML = '<div>No pair in this run.</div>'; return; }
    $('pair').innerHTML =
      '<div class="hot"><div class="id">' + p.danger.id + '</div><div class="n">' +
        p.danger.br.toFixed(2) + '</div><div class="cap">n · score ' + p.danger.score.toFixed(2) + '</div></div>' +
      '<div class="cool"><div class="id">' + p.decoy.id + '</div><div class="n">' +
        p.decoy.br.toFixed(2) + '</div><div class="cap">n · score ' + p.decoy.score.toFixed(2) + '</div></div>';
  }
  function paintStats() {
    var s = DATA.stats;
    $('cityStats').innerHTML = [
      ['Assets', fmt(s.nodes)], ['Dependencies', fmt(s.deps)], ['Diesel edges', s.diesel],
      ['Kernel edges', fmt(s.kernel_edges)], ['Spectral radius', s.rho],
      ['Flood peak', (DATA.flood || {}).peak]
    ].map(function (r) { return '<dt>' + r[0] + '</dt><dd>' + r[1] + '</dd>'; }).join('');
    $('where').textContent = DATA.city + ' · monsoon_flood · seed ' + DATA.seed;
  }
  function paintLegend() {
    $('legend3').innerHTML = LAYERS.map(function (l) {
      return '<button data-layer="' + l + '" aria-pressed="' + (!hidden[l]) + '">' +
        '<i style="background:var(--' + l + ')"></i>' + l + '</button>';
    }).join('');
    Array.prototype.forEach.call($('legend3').querySelectorAll('button'), function (b) {
      b.addEventListener('click', function () {
        var l = b.dataset.layer; hidden[l] = !hidden[l];
        b.setAttribute('aria-pressed', String(!hidden[l]));
        layout(); paintAssets();
      });
    });
  }
  function paintInspect(n) {
    if (!n) { $('inspect').innerHTML = '<dt>Click an asset</dt><dd>—</dd>'; return; }
    var st = state[n.id], rows = [['Asset', n.id], ['Layer', n.l], ['Kind', n.k],
      ['People served', fmt(n.pop)], ['Elevation', elevOf(n).toFixed(3)],
      ['Under water', elevOf(n) < waterLevel() ? 'yes' : 'no']];
    if (st) {
      rows.push(['Failed at', 'T+' + String(Math.floor(st.t / 3600)).padStart(2, '0') + ':' +
        String(Math.floor((st.t % 3600) / 60)).padStart(2, '0')]);
      rows.push(['Anomaly score', st.s.toFixed(3)]);
      rows.push(['Branching ratio', st.br.toFixed(2)]);
      rows.push(['Downstream reach', st.r]);
      rows.push(['Reached health', st.h ? 'yes' : 'no']);
    } else if (baseline[n.id] !== undefined && baseline[n.id] <= clock) {
      rows.push(['Status', 'saved by this action']);
    } else { rows.push(['Status', 'standing']); }
    $('inspect').innerHTML = rows.map(function (r) {
      return '<dt>' + r[0] + '</dt><dd>' + r[1] + '</dd>';
    }).join('');
  }

  // ------------------------------------------------------------- playback
  var raf = null;
  function stop() { playing = false; $('play').textContent = 'Play'; }
  function play() {
    if (clock >= T_END) seekTo(0);
    playing = true; $('play').textContent = 'Pause';
  }
  function selectRun(k) {
    if (!RUNS[k]) return;
    stop(); runKey = k; BINS = bins(); state = {}; cursor = 0;
    var at = clock; clock = 0; seekTo(at); paintAction();
  }

  var BEATS = [['City', 'five layers'], ['Alarms', 'identical scores'], ['Do nothing', 'the cascade'],
               ['Firebreak', 'the action'], ['Human instinct', 'still cascades'], ['Evidence', 'the numbers']];
  function paintBeats() {
    $('beats').innerHTML = BEATS.map(function (b, i) {
      return '<button data-beat="' + (i + 1) + '" aria-pressed="false"><b>' + (i + 1) + '</b>' +
        b[0] + ' <span style="opacity:.6">' + b[1] + '</span></button>';
    }).join('');
    Array.prototype.forEach.call($('beats').querySelectorAll('button'), function (b) {
      b.addEventListener('click', function () { beat(Number(b.dataset.beat)); });
    });
  }
  function beat(n) {
    Array.prototype.forEach.call($('beats').querySelectorAll('button'), function (b) {
      b.setAttribute('aria-pressed', String(Number(b.dataset.beat) === n));
    });
    if (n === 1) { selectRun('do_nothing'); seekTo(0); orbit = JSON.parse(JSON.stringify(HOME)); applyCam(); }
    else if (n === 2) {
      selectRun('do_nothing'); seekTo(T_DEC);
      var d = byId[(DATA.pair || {}).danger && DATA.pair.danger.id];
      if (d) { orbit.tx = px(d); orbit.tz = pz(d); orbit.r = SIZE * 0.75; orbit.el = 0.42; applyCam(); }
    } else if (n === 3) { selectRun('do_nothing'); seekTo(0); play(); }
    else if (n === 4) { selectRun('firebreak'); seekTo(0); play(); }
    else if (n === 5) { selectRun('human'); seekTo(0); play(); }
    else if (n === 6) { stop(); seekTo(T_END); orbit = JSON.parse(JSON.stringify(HOME)); applyCam(); }
  }

  // ---------------------------------------------------------------- input
  var track = $('track'), dragging = false;
  function seekFromX(ev) {
    var r = track.getBoundingClientRect();
    var x = (ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left;
    seekTo(Math.max(0, Math.min(1, x / r.width)) * T_END);
  }
  track.addEventListener('pointerdown', function (e) {
    dragging = true; stop(); track.setPointerCapture(e.pointerId); seekFromX(e);
  });
  track.addEventListener('pointermove', function (e) { if (dragging) seekFromX(e); });
  track.addEventListener('pointerup', function (e) {
    dragging = false; try { track.releasePointerCapture(e.pointerId); } catch (err) {}
  });
  track.addEventListener('keydown', function (e) {
    var step = T_END / 72;
    if (e.key === 'ArrowLeft') { stop(); seekTo(clock - step); e.preventDefault(); }
    if (e.key === 'ArrowRight') { stop(); seekTo(clock + step); e.preventDefault(); }
  });
  $('play').addEventListener('click', function () { playing ? stop() : play(); });
  $('reset').addEventListener('click', function () { stop(); seekTo(0); });
  document.addEventListener('keydown', function (e) {
    var t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.isContentEditable)) return;
    if (e.key >= '1' && e.key <= '6') { e.preventDefault(); beat(Number(e.key)); }
    else if (e.key === ' ') { e.preventDefault(); playing ? stop() : play(); }
    else if (e.key.toLowerCase() === 'r') { stop(); seekTo(0); }
  });

  function resize() {
    var r = $('view').parentElement.getBoundingClientRect();
    var w = Math.max(320, r.width), h = Math.max(240, r.height);
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
    sizeTrack(); drawTrack();
  }
  addEventListener('resize', resize);

  // ---------------------------------------------------------------- loop
  var last = performance.now();
  function frame(now) {
    var dt = Math.min(0.1, (now - last) / 1000); last = now;
    if (playing) {
      var step = T_END / Number($('speed').value) * (dt * 60);
      if (clock + step >= T_END) { seekTo(T_END); stop(); $('play').textContent = 'Replay'; }
      else seekTo(clock + step);
    }
    // water: level from the scenario, ripple from the clock
    var lvl = waterLevel();
    water.position.y = lvl * ELEV;
    water.visible = lvl > 0.001;
    var pos = wGeo.attributes.position, tsec = now / 1000;
    for (var i = 0; i < pos.count; i++) {
      var x = wBase[i * 3], z = wBase[i * 3 + 2];
      pos.array[i * 3 + 1] = Math.sin(x * 0.09 + tsec * 1.1) * 0.30 +
                             Math.cos(z * 0.11 - tsec * 0.8) * 0.24;
    }
    pos.needsUpdate = true;
    renderer.render(scene, camera);
    raf = requestAnimationFrame(frame);
  }

  // ---------------------------------------------------------------- boot
  layout(); applyCam(); resize();
  BINS = bins(); drawAxis();
  paintRuns(); paintPair(); paintAction(); paintStats(); paintLegend(); paintBeats();
  paintInspect(null);
  // Deep link: ?run=firebreak&t=0.5 opens on that run at that fraction of the
  // horizon. Useful for pointing someone at a moment, and for rendering one.
  var q = new URLSearchParams(location.search);
  var qr = q.get('run'), qt = parseFloat(q.get('t'));
  if (qr && RUNS[qr]) selectRun(qr);
  if (isFinite(qt)) seekTo(Math.max(0, Math.min(1, qt)) * T_END);
  else seekTo(T_DEC);
  if (!qr && !isFinite(qt))
    $('beats').querySelector('[data-beat="2"]').setAttribute('aria-pressed', 'true');
  if (q.get('play') === '1') play();
  raf = requestAnimationFrame(frame);
  window.__fb = { seekTo: seekTo, beat: beat, selectRun: selectRun,
                  get clock() { return clock; }, waterLevel: waterLevel };
})();
