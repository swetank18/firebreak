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
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  // Sky. A monsoon sky is not a gradient for decoration — the storm darkens as
  // the water rises, which is the one non-user-triggered motion in the scene
  // and it is driven by the exported flood level.
  var CLEAR = new THREE.Color(dark ? 0x101a24 : 0xb9c6d2);
  var STORM = new THREE.Color(dark ? 0x070c12 : 0x5d6b78);
  var skyGeo = new THREE.SphereGeometry(900, 24, 16);
  var skyMat = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false,
    uniforms: { top: { value: STORM.clone() }, bot: { value: CLEAR.clone() } },
    vertexShader: 'varying float h; void main(){ h = normalize(position).y;' +
      ' gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
    fragmentShader: 'uniform vec3 top; uniform vec3 bot; varying float h;' +
      ' void main(){ gl_FragColor = vec4(mix(bot, top, clamp(h*1.3+0.25,0.0,1.0)), 1.0); }'
  });
  scene.add(new THREE.Mesh(skyGeo, skyMat));

  var hemi = new THREE.HemisphereLight(dark ? 0x8fa8c8 : 0xffffff, dark ? 0x0a0f14 : 0x8f9daa, dark ? 0.62 : 0.85);
  scene.add(hemi);
  var sun = new THREE.DirectionalLight(0xffffff, dark ? 0.85 : 1.0);
  sun.position.set(-110, 150, 80);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  var sc = sun.shadow.camera;
  sc.left = -SIZE * 0.8; sc.right = SIZE * 0.8;
  sc.top = SIZE * 0.8; sc.bottom = -SIZE * 0.8;
  sc.near = 1; sc.far = 500; sc.updateProjectionMatrix();
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
  var terrain = new THREE.Mesh(tGeo, new THREE.MeshLambertMaterial({ vertexColors: true }));
  terrain.receiveShadow = true;
  scene.add(terrain);

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
  assets.castShadow = true;
  assets.receiveShadow = true;
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

  // ---- the networks the city is actually made of.
  // 1,400 road-to-road links, 312 in the grid, the mains and the backhaul. This
  // is the difference between a city and a scatter of markers, and it was in the
  // topology all along — it just was not being drawn.
  function networkLayer(pairs, colour, opacity, lift) {
    var g = new THREE.BufferGeometry(), pts = [];
    pairs.forEach(function (e) {
      var a = nodes[e[0]], b = nodes[e[1]];
      if (!a || !b) return;
      pts.push(px(a), elevOf(a) * ELEV + lift, pz(a),
               px(b), elevOf(b) * ELEV + lift, pz(b));
    });
    g.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
    var m = new THREE.LineSegments(g, new THREE.LineBasicMaterial({
      color: new THREE.Color(colour), transparent: true, opacity: opacity }));
    scene.add(m);
    return m;
  }
  var flowPairs = DATA.flow || [];
  var roadNet = flowPairs.filter(function (e) {
    return nodes[e[0]].l === 'transport' && nodes[e[1]].l === 'transport'; });
  var gridNet = flowPairs.filter(function (e) {
    return nodes[e[0]].l === 'power' && nodes[e[1]].l === 'power'; });
  var otherNet = flowPairs.filter(function (e) {
    var la = nodes[e[0]].l; return la !== 'transport' && la !== 'power'; });
  // The roads carry the city's shape, so they are the network that shows. The
  // grid crosses the whole map in long spans and at any real opacity it becomes
  // a spiderweb over everything else — it is drawn faintly, as context.
  networkLayer(roadNet, dark ? 0x8d9aa6 : 0x74818d, dark ? 0.9 : 0.75, 0.16);
  networkLayer(gridNet, col('power'), 0.16, 0.9);
  networkLayer(otherNet, dark ? 0x5c7f9e : 0x6d90ad, 0.18, 0.7);

  // ---- dependency edges: the couplings failure travels along.
  // Held as per-edge segment ranges so one can be lit up when failure crosses it.
  var depPairs = DATA.depix || [];
  var SEGS = 10;
  var dg = new THREE.BufferGeometry(), dpts = [], dcols = [];
  var restCol = new THREE.Color(dark ? 0x44566a : 0x9fb0c0);
  depPairs.forEach(function (e) {
    var a = nodes[e[0]], b = nodes[e[1]];
    var ax = px(a), ay = elevOf(a) * ELEV + shapeOf(a)[1] * 0.6, az = pz(a);
    var bx = px(b), by = elevOf(b) * ELEV + shapeOf(b)[1] * 0.6, bz = pz(b);
    var lift = 5 + Math.hypot(bx - ax, bz - az) * 0.18;
    var prev = null;
    for (var k = 0; k <= SEGS; k++) {
      var t = k / SEGS;
      var pnt = [ax + (bx - ax) * t, ay + (by - ay) * t + Math.sin(Math.PI * t) * lift,
                 az + (bz - az) * t];
      if (prev) {
        dpts.push(prev[0], prev[1], prev[2], pnt[0], pnt[1], pnt[2]);
        dcols.push(restCol.r, restCol.g, restCol.b, restCol.r, restCol.g, restCol.b);
      }
      prev = pnt;
    }
  });
  dg.setAttribute('position', new THREE.Float32BufferAttribute(dpts, 3));
  dg.setAttribute('color', new THREE.Float32BufferAttribute(dcols, 3));
  var depLines = new THREE.LineSegments(dg, new THREE.LineBasicMaterial({
    vertexColors: true, transparent: true, opacity: 0.55 }));
  scene.add(depLines);
  var depColAttr = dg.attributes.color;

  // ---- rain. It is a monsoon; the intensity follows the exported flood level,
  // so the sky is doing the thing that is filling the streets rather than an
  // effect running beside it.
  // Each drop is a short falling STREAK. Rendered as points they read as a
  // starfield, which is what the first pass looked like.
  var RAIN = 5200, RAIN_H = 95, RAIN_LEN = 3.2;
  var rainGeo = new THREE.BufferGeometry();
  var rainPos = new Float32Array(RAIN * 6);            // two vertices per drop
  var rainVel = new Float32Array(RAIN);
  function seedDrop(i, y) {
    var x = (Math.random() - 0.5) * SIZE * 1.25;
    var z = (Math.random() - 0.5) * SIZE * 1.25;
    var len = RAIN_LEN * (0.7 + Math.random() * 0.9);
    rainPos[i * 6] = x; rainPos[i * 6 + 1] = y; rainPos[i * 6 + 2] = z;
    rainPos[i * 6 + 3] = x + 0.6; rainPos[i * 6 + 4] = y + len; rainPos[i * 6 + 5] = z;
    rainVel[i] = 85 + Math.random() * 95;
  }
  for (var r = 0; r < RAIN; r++) seedDrop(r, Math.random() * RAIN_H);
  rainGeo.setAttribute('position', new THREE.BufferAttribute(rainPos, 3));
  var rain = new THREE.LineSegments(rainGeo, new THREE.LineBasicMaterial({
    color: new THREE.Color(dark ? 0xa8cbe6 : 0x7796b2),
    transparent: true, opacity: 0.0, depthWrite: false
  }));
  scene.add(rain);

  // ---- hospital beacons.
  // The pitch is "four hospitals go dark", and a hospital that has failed was
  // previously a red box among nine hundred other boxes. A failed health asset
  // raises a column of light, so the count on the panel has something on the
  // map to point at from any camera angle.
  // Hospitals only. Lighting all 62 health assets put a dozen columns on the map
  // beside a counter reading 5, and a map that disagrees with its own number is
  // worse than no map.
  var healthIx = [];
  nodes.forEach(function (n, i) { if (n.k === 'hospital') healthIx.push(i); });
  var beamGeo = new THREE.CylinderGeometry(0.55, 0.55, 1, 8, 1, true);
  beamGeo.translate(0, 0.5, 0);
  var beams = new THREE.InstancedMesh(beamGeo, new THREE.MeshBasicMaterial({
    color: new THREE.Color(dark ? 0xff7a5e : 0xc0392b), transparent: true,
    opacity: 0.30, depthWrite: false, side: THREE.DoubleSide
  }), healthIx.length);
  beams.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  beams.renderOrder = 3;
  scene.add(beams);
  var beamDummy = new THREE.Object3D();
  function paintBeams() {
    for (var b = 0; b < healthIx.length; b++) {
      var n = nodes[healthIx[b]];
      var lit = !!state[n.id] && !hidden[n.l];
      beamDummy.position.set(px(n), elevOf(n) * ELEV, pz(n));
      beamDummy.scale.set(lit ? 1.7 : 0.0001, lit ? 80 : 0.0001, lit ? 1.7 : 0.0001);
      beamDummy.updateMatrix();
      beams.setMatrixAt(b, beamDummy.matrix);
    }
    beams.instanceMatrix.needsUpdate = true;
  }

  // ---- cascade rings: a failure is an event, and the eye should catch it.
  var RINGS = 26, ringPool = [], ringAge = [];
  var ringGeo = new THREE.RingGeometry(0.6, 1.0, 40);
  ringGeo.rotateX(-Math.PI / 2);
  for (var q = 0; q < RINGS; q++) {
    var m = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({
      color: new THREE.Color(dark ? 0xff6a52 : 0xb02a1a), transparent: true,
      opacity: 0, side: THREE.DoubleSide, depthWrite: false }));
    m.visible = false; scene.add(m); ringPool.push(m); ringAge.push(0);
  }
  var ringNext = 0;
  function ringAt(n) {
    var m = ringPool[ringNext], i = ringNext;
    ringNext = (ringNext + 1) % RINGS;
    m.position.set(px(n), elevOf(n) * ELEV + 0.4, pz(n));
    m.visible = true; ringAge[i] = 0;
  }

  // ---- which dependency edge did failure just cross?
  // Not a simulation: both endpoints' failure times are fields in the file, and
  // an edge is lit when the parent fell first and the child has just followed.
  var depFlash = [];                                   // {edge index, age}
  function flashDep(childIdx) {
    for (var k = 0; k < depPairs.length; k++) {
      if (depPairs[k][0] !== childIdx) continue;
      var parent = nodes[depPairs[k][1]];
      if (state[parent.id]) depFlash.push({ e: k, age: 0 });
    }
  }
  var flashCol = new THREE.Color(dark ? 0xffb057 : 0xc47f10);

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
    var fresh = [];
    while (cursor < tl.length && tl[cursor].t <= clock) {
      var e = tl[cursor++];
      if (byId[e.n]) { state[e.n] = e; fresh.push(e.n); }
    }
    // Only mark what just happened, and only when the clock is moving forward
    // in normal-sized steps — scrubbing across three hours should not fire two
    // hundred rings at once.
    if (fresh.length && fresh.length < 40) {
      for (var f = 0; f < fresh.length; f++) {
        var nn = byId[fresh[f]];
        if (nn) { ringAt(nn); flashDep(index[fresh[f]]); }
      }
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
    counters(); paintAssets(); paintBeams(); drawTrack();
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
        layout(); paintAssets(); paintBeams();
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
    var lvl = waterLevel();
    var storm = Math.min(1, lvl / (FLOOD.peak || 1));

    // rain follows the flood
    rain.material.opacity = 0.06 + storm * 0.34;
    var rp = rainGeo.attributes.position.array;
    var fall = dt * (0.85 + storm * 1.2);
    for (var i = 0; i < RAIN; i++) {
      var dy = rainVel[i] * fall, dx = 13 * fall;
      rp[i * 6 + 1] -= dy; rp[i * 6 + 4] -= dy;
      rp[i * 6] -= dx; rp[i * 6 + 3] -= dx;
      if (rp[i * 6 + 1] < 0) seedDrop(i, RAIN_H + Math.random() * 25);
    }
    rainGeo.attributes.position.needsUpdate = true;

    // the storm closes in as the water rises
    skyMat.uniforms.top.value.copy(CLEAR).lerp(STORM, storm * 0.85);
    skyMat.uniforms.bot.value.copy(CLEAR).lerp(STORM, storm * 0.4);
    scene.fog.color.copy(CLEAR).lerp(STORM, storm * 0.5);
    scene.background.copy(scene.fog.color);
    sun.intensity = (dark ? 0.9 : 1.05) * (1 - storm * 0.28);
    hemi.intensity = (dark ? 0.72 : 0.9) * (1 - storm * 0.12);

    // cascade rings expand and fade
    for (var g2 = 0; g2 < RINGS; g2++) {
      var m2 = ringPool[g2];
      if (!m2.visible) continue;
      ringAge[g2] += dt;
      var a2 = ringAge[g2];
      if (a2 > 1.6) { m2.visible = false; continue; }
      var sc2 = 2 + a2 * 26;
      m2.scale.set(sc2, 1, sc2);
      m2.material.opacity = 0.75 * (1 - a2 / 1.6);
    }

    // dependency edges light up where failure just crossed them
    if (depFlash.length) {
      var keep = [];
      for (var d2 = 0; d2 < depFlash.length; d2++) {
        var fl2 = depFlash[d2]; fl2.age += dt;
        var k2 = Math.max(0, 1 - fl2.age / 1.1);
        var base = fl2.e * SEGS * 2;
        for (var v2 = 0; v2 < SEGS * 2; v2++) {
          var o2 = (base + v2) * 3;
          depColAttr.array[o2] = restCol.r + (flashCol.r - restCol.r) * k2;
          depColAttr.array[o2 + 1] = restCol.g + (flashCol.g - restCol.g) * k2;
          depColAttr.array[o2 + 2] = restCol.b + (flashCol.b - restCol.b) * k2;
        }
        if (fl2.age < 1.1) keep.push(fl2);
      }
      depColAttr.needsUpdate = true;
      depFlash = keep;
    }

    // gentle drift while playing, so the city reads as a place, not a diagram
    if (playing && !drag) { orbit.az += dt * 0.018; applyCam(); }

    // water: level from the scenario, ripple from the clock
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
