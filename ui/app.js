"use strict";

// Renders the state the local server pushes over /ws. No framework: a dozen DOM nodes.

const $ = (id) => document.getElementById(id);
const el = {
  meter: $("meter"), wave: $("wave"), target: $("target"), clock: $("clock"), dps: $("dps"),
  unit: $("unit"),
  totals: $("totals"), channels: $("channels"), boss: $("boss"), bossHp: $("boss-hp"),
  bossRate: $("boss-rate"), bossEta: $("boss-eta"), bossFill: $("boss-fill"), status: $("status"),
  details: $("details"), skills: $("skills"), history: $("history"), health: $("health"),
  reset: $("reset"), keys: $("keys"), viewing: $("viewing"), back: $("back"),
  copy: $("copy"), sessions: $("sessions"), historyTitle: $("history-title"),
};

const params = new URLSearchParams(location.search);
const wide = params.get("view") === "full" || (params.get("view") !== "overlay" && window.innerHeight > 620);
document.body.classList.toggle("wide", wide);
el.details.hidden = !wide;

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
// For settings.js, the dashboard's settings panel: what to do with an answer of each kind, and
// what to call with every state the meter pushes.
const replyHandlers = {};
const stateWatchers = [];
const ELEMENTS = ["glacio", "fusion", "electro", "aero", "spectro", "havoc"];
const SOURCES = {
  log: "enemy HP in the game log (exact)",
  numbers: "damage numbers on screen (rough: reads about half)",
  bar: "the HP bar on screen (percent only)",
};

// A boss-bar fight is in damage when the boss's full HP is known: from the game's tables, or
// (where they give none) worked out from the pool of one of its parts.
function sourceLabel(enc) {
  if (enc.source === "bar" && enc.hp_from === "tables") {
    return "the HP bar on screen, times the boss's HP from the game's data";
  }
  if (enc.source === "bar" && enc.hp_from === "parts") {
    return "the HP bar on screen, times the boss's HP worked out from one of its parts (derived)";
  }
  return SOURCES[enc.source] || enc.source;
}

// ---- formatting -----------------------------------------------------------------------------

const whole = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

function compact(n) {
  if (!isFinite(n)) return "0";
  const a = Math.abs(n);
  if (a >= 1e9) return (n / 1e9).toFixed(2) + "B";
  if (a >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (a >= 1e4) return (n / 1e3).toFixed(1) + "k";
  return whole.format(n);
}

// How finely figures are written: decimals of a short figure and of a share. Settings.
let figureDecimals = 2;
let shareDecimals = 0;

// A per-second figure, written short the way the game writes big numbers: 15,380 is "15.38k".
// Two decimals unless the settings say fewer, so a thousand's worth is still told apart from
// the next. Under 1,000 it is written out. Totals keep compact() above; the copied summary
// keeps every digit.
function short(n) {
  if (!isFinite(n)) return "0";
  const a = Math.abs(n);
  if (a >= 1e9) return (n / 1e9).toFixed(figureDecimals) + "B";
  if (a >= 1e6) return (n / 1e6).toFixed(figureDecimals) + "M";
  if (a >= 1e3) return (n / 1e3).toFixed(figureDecimals) + "k";
  return whole.format(Math.round(n));
}

// Damage per second, or percent of HP per second when only the HP bar could be read.
function rate(n, unit) {
  return unit === "percent" ? amount(n, unit) : short(n);
}

// Amounts are damage, or percent of the target's HP when only the HP bar could be read.
function amount(n, unit) {
  if (unit === "percent") return (n >= 10 ? n.toFixed(1) : n.toFixed(2)) + "%";
  return compact(n);
}

function clock(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
}

function setText(node, text) {
  if (node.textContent !== text) node.textContent = text;
}

// ---- motion: the bars and the headline figure, at the meter's own frame rate ----------------

// Between the pushes (four a second) the bars slide and the headline figure counts, drawn at 60
// frames a second, or 120 if chosen in Settings (the server sends ``ui.fps``). Left to the browser
// (CSS transitions, a step every frame) they ran at the monitor's rate, 144 Hz and up, and each
// frame was a new picture of the page to make: about half a CPU core through a fight. When
// nothing moves, nothing is drawn.
let frameMs = 1000 / 60;
const slides = new Map(); // bar -> {from, to, start, ms, linear}
const scales = new WeakMap(); // bar -> the share of its length it shows
let ticking = false;
let lastTick = 0;

function setFrameRate(fps) {
  if (fps === 60 || fps === 120) frameMs = 1000 / fps;
}

function valueAt(slide, now) {
  const k = Math.min(1, (now - slide.start) / slide.ms);
  const eased = slide.linear ? k : 1 - (1 - k) ** 3; // ease-out, as the transition was
  return slide.from + (slide.to - slide.from) * eased;
}

function paintScale(bar, value) {
  scales.set(bar, value);
  bar.style.transform = `scaleX(${value.toFixed(4)})`;
}

// A bar is a full-width element scaled down to its share (the themes start a row's at 0): a
// scale is put on screen by the GPU alone, a width would lay the page out again.
function slideBar(bar, to, ms, linear = false) {
  to = Math.max(0, Math.min(1, to));
  const now = performance.now();
  const sliding = slides.get(bar);
  const from = sliding ? valueAt(sliding, now) : scales.get(bar) ?? (bar === el.bossFill ? 1 : 0);
  if (Math.abs(to - from) < 0.0005) {
    if (sliding) {
      slides.delete(bar);
      paintScale(bar, to);
    }
    return;
  }
  if (reducedMotion) {
    paintScale(bar, to);
    return;
  }
  slides.set(bar, { from, to, start: now, ms, linear });
  wake();
}

// The headline figure closes 22% of the gap every 1/60 s, as it has since it was first eased:
// timed, not counted in frames, so 120 frames are smoother and no faster.
const DPS_TAU_MS = 1000 / 60 / -Math.log(1 - 0.22);
let shownDps = 0;
let targetDps = 0;
let dpsUnit = "damage";
let dpsSubject = "";

function showDps() {
  setText(el.dps, dpsUnit === "percent" ? shownDps.toFixed(2) : short(shownDps));
}

function stepDps(elapsed) {
  const gap = targetDps - shownDps;
  if (Math.abs(gap) < (dpsUnit === "percent" ? 0.005 : 1)) {
    if (shownDps !== targetDps) {
      shownDps = targetDps;
      showDps();
    }
    return false;
  }
  shownDps += gap * (1 - Math.exp(-elapsed / DPS_TAU_MS));
  showDps();
  return true;
}

function tick() {
  const now = performance.now();
  const counting = stepDps(now - lastTick);
  lastTick = now;
  for (const [bar, slide] of slides) {
    paintScale(bar, valueAt(slide, now));
    if (now - slide.start >= slide.ms) slides.delete(bar);
  }
  if (counting || slides.size) setTimeout(tick, frameMs);
  else ticking = false;
}

function wake() {
  if (ticking) return;
  ticking = true;
  lastTick = performance.now();
  setTimeout(tick, frameMs);
}

// ``subject`` names what the figure is about (a fight, an earlier fight on show, no fight). Only
// changes within one subject are eased; on a new one the figure jumps, or going back from an
// earlier fight would count down through made-up values under "No fight yet".
function setDps(value, unit = "damage", subject = "") {
  if (unit !== dpsUnit || subject !== dpsSubject || reducedMotion) {
    dpsUnit = unit;
    dpsSubject = subject;
    shownDps = value;
    showDps();
  }
  targetDps = value;
  if (shownDps !== targetDps) wake();
}

// ---- tape: damage per second, mirrored like an audio clip -----------------------------------

// ---- colours of the user's own for the elements, laid over the theme's -----------------------

// The themes draw each element from a variable (--glacio, ...). A colour chosen on the settings
// page is that variable set on the page itself, which wins over the theme's stylesheet.
let coloursShown = "{}";
const themeColours = {}; // element -> the theme's own colour, for the settings page to show

function paintColours(colours) {
  const root = document.documentElement.style;
  for (const name of ELEMENTS) {
    const value = colours[name];
    if (typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value)) root.setProperty("--" + name, value);
    else root.removeProperty("--" + name);
  }
}

function setColours(colours) {
  const wanted = JSON.stringify(colours || {});
  if (wanted === coloursShown) return;
  coloursShown = wanted;
  paintColours(colours || {});
}

// ---- theme: a stylesheet in themes/, chosen in the tray menu ---------------------------------

const themeLink = document.getElementById("theme");
let theme = params.get("theme") || "";
let waveRgb = "244, 246, 248";

function readThemeColours() {
  paintColours({}); // the user's colours off for a moment, to see the theme's
  const style = getComputedStyle(document.documentElement);
  waveRgb = style.getPropertyValue("--wave-rgb").trim() || waveRgb;
  for (const name of ELEMENTS) themeColours[name] = style.getPropertyValue("--" + name).trim();
  paintColours(JSON.parse(coloursShown));
  window.dispatchEvent(new Event("themecolours"));
}

function setTheme(name) {
  if (!name || name === theme || params.get("theme")) return;
  theme = name;
  themeLink.href = `themes/${encodeURIComponent(name)}.css`;
}

themeLink.addEventListener("load", readThemeColours);
if (theme) themeLink.href = `themes/${encodeURIComponent(theme)}.css`;
readThemeColours();

function drawWave(samples, live) {
  const canvas = el.wave;
  const ratio = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (canvas.width !== Math.round(w * ratio) || canvas.height !== Math.round(h * ratio)) {
    canvas.width = Math.round(w * ratio);
    canvas.height = Math.round(h * ratio);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (!samples || !samples.length) return;

  const step = 3; // 2px bar + 1px gap, one bar per second
  const visible = Math.min(samples.length, Math.floor(w / step));
  const slice = samples.slice(samples.length - visible);
  const peak = Math.max(1, ...slice);
  const mid = h / 2;
  for (let i = 0; i < slice.length; i++) {
    // sqrt keeps quiet seconds visible next to bursts; a second can be below nothing when
    // "Over time" is taken back in it, and is drawn as a quiet one
    const level = Math.sqrt(Math.max(0, slice[i]) / peak);
    const half = Math.max(0.5, level * (mid - 3));
    const x = w - (slice.length - i) * step;
    ctx.fillStyle = `rgba(${waveRgb}, ${live ? 0.1 + 0.3 * level : 0.12})`;
    ctx.fillRect(x, mid - half, 2, half * 2);
  }
}

// ---- keys -----------------------------------------------------------------------------------

// The line along the top saying which key does what. The server sends the keys in use, or an
// empty list when the line is switched off (tray menu).
let keysShown = "";

function renderKeys(keys) {
  const wanted = JSON.stringify(keys || []);
  if (wanted === keysShown) return;
  keysShown = wanted;
  el.keys.replaceChildren();
  for (const item of keys || []) {
    const hint = document.createElement("span");
    const key = document.createElement("b");
    key.textContent = item.key;
    hint.append(key, " " + item.label);
    el.keys.appendChild(hint);
  }
  el.keys.hidden = !(keys && keys.length);
}

// ---- channels -------------------------------------------------------------------------------

// A character is drawn in its element's colour. Characters that share an element get shades of
// it ("twin-1", "twin-2"), handed out in party order so a row keeps its shade as the ranking
// changes. A character whose element is not known gets a grey.
function hueClasses(players) {
  const seen = {};
  const classes = new Map();
  const inPartyOrder = players.map((p, i) => [p, p.slot ?? i]).sort((a, b) => a[1] - b[1]);
  for (const [p, slot] of inPartyOrder) {
    if (p.other) {
      classes.set(p.key, "other");
    } else if (ELEMENTS.includes(p.element)) {
      const twin = seen[p.element] || 0;
      seen[p.element] = twin + 1;
      classes.set(p.key, "elem el-" + p.element + (twin ? " twin-" + (((twin - 1) % 2) + 1) : ""));
    } else {
      classes.set(p.key, "slot-" + ((slot % 3) + 1));
    }
  }
  return classes;
}

// The figures a row can show: the heading over its column, the column's width in pixels, and
// the figure as text. Which of them are shown, and in what order, is a setting. A fight saved
// by an earlier version has no time on field, and the "over time" row never has: a dash.
const FIGURES = {
  dps: { head: "DPS", width: () => 54, text: (p, unit) => rate(p.dps, unit) },
  damage: {
    head: "Total",
    width: () => 54,
    text: (p, unit) => (unit === "percent" ? amount(p.damage, unit) : short(p.damage)),
  },
  share: {
    head: "Share",
    width: () => 36 + 9 * shareDecimals,
    text: (p) => (p.share * 100).toFixed(shareDecimals) + "%",
  },
  field_time: {
    head: "Field",
    width: () => 38,
    text: (p) => (p.field_time == null ? "–" : clock(p.field_time)),
  },
  field_dps: {
    head: "Field DPS",
    width: () => 62,
    text: (p, unit) => (p.field_dps == null ? "–" : rate(p.field_dps, unit)),
  },
};
const USUAL_FIGURES = "dps share";
let rowFigures = USUAL_FIGURES.split(" ");

function setFigures(ui) {
  if (Array.isArray(ui.figures)) rowFigures = ui.figures.filter((name) => FIGURES[name]);
  if (Array.isArray(ui.decimals)) [figureDecimals, shareDecimals] = ui.decimals;
}

function renderChannels(players, unit) {
  const box = el.channels;
  const shown = rowFigures.join(" ");
  const laidOut = shown + "/" + shareDecimals;
  if (box.dataset.figures !== laidOut) {
    // other figures: other columns, so the rows are made again
    box.dataset.figures = laidOut;
    box.replaceChildren();
    box.style.setProperty("--row-figures", rowFigures.map((name) => FIGURES[name].width() + "px").join(" "));
  }
  // The usual two figures explain themselves. Any other choice gets a line of headings.
  let heads = box.firstElementChild;
  if (heads && !heads.classList.contains("heads")) heads = null;
  const wanted = players.length > 0 && shown !== USUAL_FIGURES;
  if (heads && !wanted) {
    heads.remove();
    heads = null;
  } else if (!heads && wanted) {
    heads = document.createElement("div");
    heads.className = "channel heads";
    heads.append(...["", "", "", ...rowFigures.map((name) => FIGURES[name].head)].map((text) => {
      const cell = document.createElement("span");
      cell.textContent = text;
      return cell;
    }));
    box.prepend(heads);
  }
  const before = heads ? 1 : 0;
  while (box.children.length - before > players.length) box.removeChild(box.lastChild);
  while (box.children.length - before < players.length) {
    const row = document.createElement("div");
    row.innerHTML = '<span class="lamp"></span><span class="name"></span><span class="level"><i></i></span>' +
      rowFigures.map((name) => `<span class="${name === "share" ? "share" : "rate"}"></span>`).join("");
    box.appendChild(row);
  }
  const hues = hueClasses(players);
  const top = Math.max(1, ...players.map((p) => p.damage));
  players.forEach((p, i) => {
    const row = box.children[i + before];
    const cls = "channel " + hues.get(p.key) + (p.on_field ? " on-field" : "");
    if (row.className !== cls) row.className = cls;
    setText(row.children[1], p.name);
    slideBar(row.children[2].firstChild, p.damage / top, 350);
    rowFigures.forEach((name, n) => setText(row.children[3 + n], FIGURES[name].text(p, unit)));
  });
}

// ---- dashboard panels -----------------------------------------------------------------------

// Each list is drawn again only when what it shows has changed: the meter pushes its state many
// times a second, and a row that is replaced under the pointer loses its click and its focus.

function note(text) {
  const empty = document.createElement("div");
  empty.className = "empty";
  empty.textContent = text;
  return empty;
}

// The fights of the session on show: name, length, damage per second. The one on the meter is marked.
function renderFights(state) {
  const fights = state.history || [];
  const drawn = JSON.stringify(fights.map((h) => [h.id, h.title, h.duration, h.dps, h.unit]));
  if (el.history.drawn !== drawn) {
    el.history.drawn = drawn;
    el.history.replaceChildren(...fights.map((h) => {
      const row = document.createElement("button");
      row.type = "button";
      row.dataset.id = h.id;
      for (const cell of [h.title, clock(h.duration), rate(h.dps, h.unit) + "/s"]) {
        const span = document.createElement("span");
        span.textContent = cell;
        row.append(span);
      }
      return row;
    }));
    if (!fights.length) el.history.append(note("Finished fights are listed here."));
  }
  fights.forEach((h, i) => {
    const shown = Boolean(state.view) && state.view.id === h.id;
    const row = el.history.children[i];
    row.className = shown ? "row shown" : "row";
    if (shown) row.setAttribute("aria-current", "true");
    else row.removeAttribute("aria-current");
  });
  el.back.hidden = !state.view;
  // the list is this session's, unless an earlier session has been opened
  const opened = state.view && state.view.session;
  setText(el.historyTitle, opened ? `Fights of the session of ${opened}` : "Fights this session");
}

// The rail of the fights page: this session, then the earlier ones, newest first.
function renderSessions(state) {
  const fights = (n) => (n === 1 ? "1 fight" : n ? n + " fights" : "no fights yet");
  const opened = state.view ? state.view.session : "";
  const earlier = state.sessions || [];
  const items = [{ file: "", label: "This session", said: fights(state.fights_this_session || 0) }];
  for (const s of earlier) items.push({ file: s.file, label: s.label, said: `${fights(s.fights)} · ${s.last}` });
  const drawn = JSON.stringify(items);
  if (el.sessions.drawn !== drawn) {
    el.sessions.drawn = drawn;
    el.sessions.replaceChildren(...items.map((item) => {
      const pick = document.createElement("button");
      pick.type = "button";
      pick.className = "sess";
      pick.dataset.file = item.file;
      pick.dataset.label = item.label;
      pick.title = item.said;
      const text = document.createElement("span");
      const label = document.createElement("b");
      label.textContent = item.label;
      const said = document.createElement("small");
      said.textContent = item.said;
      text.append(label, said);
      pick.append(text);
      return pick;
    }));
    if (!earlier.length) {
      const none = document.createElement("p");
      none.textContent = "Earlier sessions are listed here.";
      el.sessions.append(none);
    }
  }
  let marked = false;
  for (const pick of el.sessions.querySelectorAll(".sess")) {
    const current = !marked && (opened ? pick.dataset.label === opened && pick.dataset.file !== "" : pick.dataset.file === "");
    if (current) pick.setAttribute("aria-current", "true");
    else pick.removeAttribute("aria-current");
    marked = marked || current;
  }
}

// The skills of the fight on show, a block to a character, under the diamond of its row.
function renderSkills(enc) {
  const sets = [];
  if (enc) {
    const hues = hueClasses(enc.players);
    for (const p of enc.players) {
      if (p.skills && p.skills.length) {
        sets.push({ name: p.name, cls: hues.get(p.key) || "", skills: p.skills.map((s) => [s.name, s.casts]) });
      }
    }
  }
  const drawn = JSON.stringify(sets);
  if (el.skills.drawn === drawn) return;
  el.skills.drawn = drawn;
  el.skills.replaceChildren(...sets.map((set) => {
    const block = document.createElement("div");
    block.className = "skill-set " + set.cls;
    const name = document.createElement("h5");
    const gem = document.createElement("i");
    gem.className = "set-gem";
    name.append(gem, set.name);
    block.append(name);
    for (const [skill, casts] of set.skills) {
      const line = document.createElement("div");
      const what = document.createElement("span");
      what.textContent = skill;
      const times = document.createElement("span");
      times.textContent = "×" + casts;
      line.append(what, times);
      block.append(line);
    }
    return block;
  }));
  if (!sets.length) el.skills.append(note("Skill names appear here once a fight is under way."));
}

function renderDetails(state) {
  const enc = state.encounter;
  renderFights(state);
  renderSessions(state);
  renderSkills(enc);

  const s = state.status;
  const health = [
    ["Game", s.game ? (s.focused ? "running, focused" : "running, not focused") : "not running", s.game],
    ["Log", s.log ? `reading, ${whole.format(s.log_lines || 0)} lines` : "not found", s.log],
    ["Screen", s.screen ? `${s.backend}, ${(s.fps || 0).toFixed(0)} frames/s` : "not capturing", s.screen],
    ["Damage from", enc ? sourceLabel(enc) : "nothing yet", true],
  ];
  health.forEach(([name, value, ok], i) => {
    let fact = el.health.children[i];
    if (!fact) {
      fact = document.createElement("div");
      fact.append(document.createElement("dt"), document.createElement("dd"));
      el.health.append(fact);
    }
    fact.className = ok ? "fact" : "fact bad";
    setText(fact.firstChild, name);
    setText(fact.lastChild, value);
  });
}

// ---- main render ----------------------------------------------------------------------------

// "F9", "F9 and F10", "F8, F9 and F10"
function listed(names) {
  if (names.length < 2) return names.join("");
  return names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
}

function statusLine(s, state) {
  const ui = state.ui || {};
  if (ui.said) return ui.said; // the answer to something just asked for, shown for a few seconds
  if (s.note) return s.note;
  const enc = state.encounter;
  if (enc && enc.unit === "percent" && ui.unit === "damage") {
    return "This enemy's HP isn't known, so damage can only be shown as percent of its HP.";
  }
  if (!s.game) return "Game is not running.";
  if (!s.log) {
    return "Can't find the game's log file. Tell the meter where it is: tray menu, Settings.";
  }
  if (!s.screen) return "Screen capture isn't working, so only log data is shown.";
  const taken = ui.keys_taken || [];
  if (taken.length) {
    // a key Windows gave to another program does nothing here, and would do so silently
    return `${listed(taken)} ${taken.length > 1 ? "are" : "is"} in use by another program, so ` +
      `${taken.length > 1 ? "they do" : "it does"} nothing here. Pick ` +
      `${taken.length > 1 ? "other keys" : "another key"}: tray menu, Settings.`;
  }
  if (ui.news) return ui.news; // a newer version of the meter has just started for the first time
  if (ui.stale) return ui.stale; // the game was patched and the boss HP tables were not
  if (ui.app_line) return ui.app_line; // a newer Waveband is out
  if (!s.focused) return "Game isn't focused. Screen reading is paused.";
  return "";
}

// Something is wrong with what the meter reads from. It has to stay on screen to say so.
function signalTrouble(s) {
  return Boolean(s.note) || !s.game || !s.log || !s.screen;
}

// ---- an earlier fight on show ---------------------------------------------------------------

function timeOfDay(epoch) {
  const d = new Date(epoch * 1000);
  return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
}

// The line that says the figures are an earlier fight's, and how to get back. The meter goes on
// measuring behind it, so a running fight is mentioned.
function renderViewing(view, enc, ui) {
  el.viewing.hidden = !view;
  if (!view) return;
  let extra = enc && enc.ended_at ? "ended " + timeOfDay(enc.ended_at) : "";
  if (view.running) extra += (extra ? " · " : "") + "a fight is running now";
  if (!wide && ui.newer_key) extra += (extra ? " · " : "") + ui.newer_key + " goes forward";
  // an earlier session opened for reading names itself; its label is a date the meter made
  // fights are counted in the order they were fought: "fight 1" is the session's first
  const number = view.count - view.place + 1;
  const what = view.session
    ? `Session of ${view.session}, fight ${number} of ${view.count}`
    : `Fight ${number} of ${view.count}, earlier this session`;
  const html = what + (extra ? ` <span>· ${extra}</span>` : "");
  if (el.viewing.innerHTML !== html) el.viewing.innerHTML = html;
}

// Seconds a finished fight stays up before the meter hides between fights. Long enough to read
// the result; 20 felt long (owner, 2026-11-17).
const REST_AFTER = 12;

// The tray toggle asks for damage or percent of HP. Damage becomes percent when the enemy's full
// HP is known. A fight read off the HP bar arrives as damage if the game's tables gave the boss's
// HP, and as percent (which is all that can be shown) if they did not.
function inUnit(enc, want) {
  if (!enc || want !== "percent" || enc.unit !== "damage" || !enc.max_hp_total) return enc;
  const k = 100 / enc.max_hp_total;
  return {
    ...enc,
    unit: "percent",
    damage: enc.damage * k,
    dps: enc.dps * k,
    max_hit: enc.max_hit * k,
    players: enc.players.map((p) => ({
      ...p,
      damage: p.damage * k,
      dps: p.dps * k,
      max_hit: p.max_hit * k,
      field_dps: p.field_dps == null ? p.field_dps : p.field_dps * k,
    })),
  };
}

function unitLabel(enc) {
  if (!enc) return "damage / s";
  if (enc.unit === "percent") return "% of HP / s";
  return enc.source === "numbers" ? "damage / s, rough" : "damage / s";
}

function render(state) {
  const ui = state.ui || {};
  const view = state.view || null;
  const oneLine = !wide && Boolean(ui.compact);
  const enc = inUnit(state.encounter, ui.unit);
  if (state.ui) setTheme(ui.theme);
  if (state.ui) setFrameRate(ui.fps);
  if (state.ui) setColours(ui.colours);
  if (state.ui) setFigures(ui);
  for (const watch of stateWatchers) watch(state);
  document.body.classList.toggle("compact", oneLine);
  renderKeys(ui.keys);
  renderViewing(view, enc, ui);
  setText(el.unit, unitLabel(enc));
  const mode = !enc ? "idle" : enc.live ? "live" : "ended";
  if (el.meter.dataset.state !== mode) el.meter.dataset.state = mode;

  // an earlier fight on show stays on show, whatever is being fought meanwhile
  const unmeasured = view ? "" : state.status.unmeasured;
  let notice = ""; // said in the totals line, which the one-line meter does not have
  if (unmeasured && (!enc || !enc.live)) {
    // a fight is going on, but these enemies give the meter nothing to read
    el.meter.dataset.state = "idle";
    notice = `${unmeasured} doesn't report its HP, so there's no damage to show.`;
    setText(el.target, unmeasured);
    setText(el.clock, "0:00");
    setDps(0, "damage", "unmeasured");
    setText(el.totals, "This enemy doesn't report its HP, so there's no damage to show.");
    renderChannels([], "damage");
    drawWave([], false);
    el.boss.hidden = true;
  } else if (!enc) {
    setText(el.target, "No fight yet");
    setText(el.clock, "0:00");
    setDps(0, "damage", "none");
    setText(el.totals, "Damage shows up here when you land a hit.");
    renderChannels([], "damage");
    drawWave([], false);
    el.boss.hidden = true;
  } else {
    setText(el.target, enc.title || "Fight");
    setText(el.clock, clock(enc.duration));
    setDps(enc.dps, enc.unit, `${view ? `view ${view.id}` : "live"} ${enc.id}`);
    const parts = enc.unit === "percent"
      ? [enc.damage > 100.5
        ? `<b>${(enc.damage / 100).toFixed(2)}</b> HP bars dealt`
        : `<b>${amount(enc.damage, enc.unit)}</b> of the target's HP dealt`]
      : [`<b>${compact(enc.damage)}</b> total`];
    if (enc.unit !== "percent" && enc.max_hit) parts.push(`biggest hit <b>${compact(enc.max_hit)}</b>`);
    const html = parts.join(" · ");
    if (el.totals.innerHTML !== html) el.totals.innerHTML = html;
    renderChannels(enc.players || [], enc.unit);
    drawWave(enc.wave || [], enc.live);

    const boss = enc.boss;
    el.boss.hidden = !boss;
    if (boss) {
      const left = boss.life > 0 ? `${compact(boss.life)} left` : "";
      if (boss.hp === null) {
        // only logged HP to go by: no bar to draw
        setText(el.bossHp, left ? `Target HP ${left}` : enc.live ? "Target HP" : "Target defeated");
        setText(el.bossRate, "");
        setText(el.bossEta, "");
        slideBar(el.bossFill, 0, 300, true);
      } else if (boss.hp <= 0) {
        // Dead. Nothing more is said: the rate the bar was falling at used to follow here with
        // a minus sign in front, and next to "0.0%" that read as HP below zero.
        setText(el.bossHp, "Target defeated");
        setText(el.bossRate, "");
        setText(el.bossEta, "");
        slideBar(el.bossFill, 0, 300, true);
      } else {
        setText(el.bossHp, `Target HP ${(boss.hp * 100).toFixed(1)}%`);
        setText(el.bossRate, left || (boss.rate > 0 ? `falling ${(boss.rate * 100).toFixed(2)}%/s` : ""));
        setText(el.bossEta, boss.eta > 0 && enc.live ? `about ${clock(boss.eta)} to go` : "");
        slideBar(el.bossFill, boss.hp, 300, true);
      }
    }
  }

  const note = statusLine(state.status, state) || (oneLine ? notice : "");
  el.status.hidden = !note;
  setText(el.status, note);

  // Hidden between fights, if asked for: not while a fight runs or one has just ended, not
  // while an earlier fight is on show, and not while there is something the user has to be told.
  const quiet = !enc || (!enc.live && enc.ended_at != null && state.now - enc.ended_at > REST_AFTER);
  const resting = !wide && Boolean(ui.hide_between_fights) && quiet && !view && !unmeasured &&
    !ui.said && !ui.news && !signalTrouble(state.status);
  document.body.classList.toggle("resting", resting);

  if (wide) renderDetails(state);
}

// ---- what changed (dashboard only) ----------------------------------------------------------

// The meter's changelog, with the versions that are new since the one last run here marked.
// Asked for once per connection; opened from the tray menu it is scrolled to, and the meter
// then stops saying it was updated.
const changes = { panel: $("changes"), list: $("changes-list"), asked: false };

replyHandlers.changes = (reply) => {
  const fresh = new Set(reply.new || []);
  const nodes = [];
  for (const version of reply.versions || []) {
    const title = document.createElement("h3");
    title.textContent = version.version;
    if (version.when) {
      const when = document.createElement("span");
      when.textContent = ` (${version.when})`;
      title.append(when);
    }
    if (fresh.has(version.version)) {
      const mark = document.createElement("span");
      mark.className = "new";
      mark.textContent = `new since ${reply.before}, the version last run here`;
      title.append(mark);
    }
    const list = document.createElement("ul");
    for (const note of version.notes || []) {
      const item = document.createElement("li");
      item.textContent = note;
      list.append(item);
    }
    nodes.push(title, list);
  }
  if (!nodes.length) {
    const none = document.createElement("p");
    none.textContent = "The list of changes (CHANGELOG.md) is missing from the meter's folder.";
    nodes.push(none);
  }
  changes.list.replaceChildren(...nodes);
};

stateWatchers.push(() => {
  if (!wide || !changes.panel || changes.asked) return;
  changes.asked = true;
  send({ cmd: "changes", read: location.hash === "#changes" });
});

// ---- the dashboard's pages: fights, settings, what changed ----------------------------------
// The address says which is open ("#settings", "#changes"; anything else is the fights), so the
// tray menu can open one and the browser's back button goes through them.

const views = $("views");

function showView() {
  if (!wide) return;
  const hash = location.hash.slice(1);
  const view = /^settings(-|$)/.test(hash) ? "settings" : hash === "changes" ? "changes" : "fight";
  const opened = el.details.dataset.view !== view;
  el.details.dataset.view = view;
  for (const link of views.querySelectorAll("a")) {
    if (link.dataset.view === view) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  // the notes are now in front of the user: the meter can stop saying it was updated
  if (opened && view === "changes" && changes.asked) send({ cmd: "changes", read: true });
}

window.addEventListener("hashchange", showView);
showView();

// ---- connection -----------------------------------------------------------------------------

let socket = null;

function connect() {
  socket = new WebSocket(`ws://${location.host}/ws`);
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    // an answer to something this page asked says so; everything else is the meter's state
    if (!message.reply) render(message);
    else if (replyHandlers[message.reply]) replyHandlers[message.reply](message);
  };
  socket.onclose = () => {
    changes.asked = false; // the meter that answers next may be a newer one
    el.status.hidden = false;
    setText(el.status, "Lost the connection to the meter. Retrying.");
    setTimeout(connect, 1500);
  };
}

function send(command) {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(command));
}

el.reset.addEventListener("click", () => send({ cmd: "reset" }));
el.back.addEventListener("click", () => send({ cmd: "view", id: null }));
el.copy.addEventListener("click", () => send({ cmd: "copy" }));
// "This session" has no file: asking for none goes back to the session that is running.
el.sessions.addEventListener("click", (event) => {
  const pick = event.target.closest("[data-file]");
  if (pick) send({ cmd: "session", file: pick.dataset.file || null });
});
el.history.addEventListener("click", (event) => {
  const row = event.target.closest("[data-id]");
  if (row) send({ cmd: "view", id: Number(row.dataset.id) });
});

connect();
