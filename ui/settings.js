"use strict";

// The settings panel on the dashboard. It asks the meter for the settings over the same socket
// the figures come in on, shows them, and sends back each change as it is made; the meter
// checks the change, saves it, and answers with the settings as they now are. Nothing is kept
// here: the meter's answer is what is shown. Loaded after app.js, whose send(), replyHandlers,
// stateWatchers, themeColours and ELEMENTS it uses.

(() => {
  if (!wide) return; // the overlay never shows settings

  const part = {
    panel: $("settings"), said: $("set-said"), keys: $("set-keys"), usualKeys: $("set-keys-usual"),
    keysAdmin: $("set-keys-admin"),
    colours: $("set-colours"), language: $("set-language"), theme: $("set-theme"),
    unit: $("set-unit"), zoom: $("set-zoom"), zoomShown: $("set-zoom-shown"), log: $("set-log"),
    logState: $("set-log-state"), logUse: $("set-log-use"), logFind: $("set-log-find"),
    exported: $("set-export"), exportCopy: $("set-export-copy"), imported: $("set-import"),
    importUse: $("set-import-use"), figures: $("set-figures"),
    tablesState: $("set-tables-state"), tablesUpdate: $("set-tables-update"),
    appState: $("set-app-state"), appCheck: $("set-app-check"), appInstall: $("set-app-install"),
    channel: $("set-update_channel"), engine: $("set-overlay_engine"),
    figureDecimals: $("set-figure_decimals"), shareDecimals: $("set-share_decimals"),
  };
  const FLAGS = ["compact", "show_keys", "hide_between_fights", "only_over_game", "hide_from_capture",
    "check_updates", "auto_update"];
  // event.code of the keys the meter can take besides F1-F24, letters and digits
  const NAMED_KEYS = ["Insert", "Delete", "Home", "End", "PageUp", "PageDown", "Pause",
    "ScrollLock", "NumLock", "Tab", "Space"];

  let current = null; // the settings as the meter last gave them
  let mark = null; // the meter's stamp for those settings; another stamp means they changed
  let waiting = null; // the action whose key is being chosen
  let importing = false;
  let saidTimer = 0;

  const change = (changes) => send({ cmd: "set", changes });
  const busy = (node) => document.activeElement === node;

  // A line of the settings: what it is on the left, its controls on the right.
  function row(name, ...controls) {
    const line = document.createElement("div");
    line.className = "set-row";
    const side = document.createElement("span");
    side.className = "set-ctl";
    side.append(...controls);
    line.append(name, side);
    return line;
  }

  // A checkbox drawn as a switch: the box itself stays, unseen, over the drawing.
  function toggle(box) {
    const frame = document.createElement("span");
    frame.className = "switch";
    frame.append(box, document.createElement("i"));
    return frame;
  }

  // ---- one page of settings at a time, picked on the rail ------------------------------------

  const rail = $("set-rail");
  const title = $("set-title");
  const pages = [...part.panel.querySelectorAll(".set-page")];
  let page = pages[0].dataset.page;

  // "#settings-colours" opens that page; plain "#settings" the one last looked at.
  function showPage() {
    const asked = /^#settings-(\w+)$/.exec(location.hash);
    if (asked && pages.some((one) => one.dataset.page === asked[1])) page = asked[1];
    for (const one of pages) {
      one.hidden = one.dataset.page !== page;
      if (!one.hidden) setText(title, one.dataset.title);
    }
    for (const link of rail.querySelectorAll("a")) {
      if (link.dataset.page === page) link.setAttribute("aria-current", "true");
      else link.removeAttribute("aria-current");
    }
    stopWaiting();
  }
  window.addEventListener("hashchange", showPage);

  // ---- what the meter has to say about a change ---------------------------------------------

  function say(said, problems) {
    problems = problems || [];
    if (!said && !problems.length) return;
    part.said.replaceChildren();
    for (const text of problems) {
      const line = document.createElement("span");
      line.className = "bad";
      line.textContent = text;
      part.said.appendChild(line);
    }
    if (said) {
      const line = document.createElement("span");
      line.textContent = said;
      part.said.appendChild(line);
    }
    part.said.hidden = false;
    clearTimeout(saidTimer);
    // something that went wrong stays up until the next thing said
    if (!problems.length) saidTimer = setTimeout(() => { part.said.hidden = true; }, 6000);
  }

  // ---- keys ---------------------------------------------------------------------------------

  function drawKeys(s) {
    if (part.keys.children.length !== s.hotkeys.length) {
      part.keys.replaceChildren();
      for (const item of s.hotkeys) {
        const label = document.createElement("span");
        label.className = "set-name";
        label.textContent = item.label;
        // said under a key that won't reach Waveband while the game runs as administrator
        const blocked = document.createElement("span");
        blocked.className = "set-note bad";
        blocked.dataset.blocked = item.action;
        blocked.textContent = "Won't work while you play: the game runs as administrator. Hold Ctrl or Alt with this key.";
        blocked.hidden = true;
        label.append(blocked);
        const key = document.createElement("button");
        key.type = "button";
        key.className = "key";
        key.dataset.action = item.action;
        const none = document.createElement("button");
        none.type = "button";
        none.className = "plain";
        none.dataset.clear = item.action;
        none.textContent = "remove";
        none.setAttribute("aria-label", `${item.label}: use no key`);
        part.keys.append(row(label, none, key));
      }
    }
    for (const item of s.hotkeys) {
      if (waiting === item.action) continue;
      const key = part.keys.querySelector(`[data-action="${item.action}"]`);
      key.textContent = item.key || "none";
      key.classList.toggle("none", !item.key);
      key.classList.remove("waiting");
      key.setAttribute("aria-label", `${item.label}: ${item.key || "no key"}. Press to change it.`);
      part.keys.querySelector(`[data-clear="${item.action}"]`).hidden = !item.key;
      part.keys.querySelector(`[data-blocked="${item.action}"]`).hidden = !item.blocked;
    }
    part.keysAdmin.hidden = !s.keys_need_ctrl_or_alt;
  }

  function stopWaiting() {
    if (!waiting) return;
    waiting = null;
    if (current) drawKeys(current);
  }

  function startWaiting(button) {
    stopWaiting();
    waiting = button.dataset.action;
    button.classList.remove("none");
    button.classList.add("waiting");
    button.textContent = "press a key";
  }

  // "Ctrl+Alt+M" for a key press, the way the meter writes keys. null for a key it cannot take.
  function keyName(event) {
    const code = event.code;
    let key = null;
    if (/^F([1-9]|1\d|2[0-4])$/.test(code)) key = code;
    else if (/^Key[A-Z]$/.test(code)) key = code.slice(3);
    else if (/^Digit\d$/.test(code)) key = code.slice(5);
    else if (NAMED_KEYS.includes(code)) key = code;
    if (!key) return null;
    const held = [];
    if (event.ctrlKey) held.push("Ctrl");
    if (event.altKey) held.push("Alt");
    if (event.shiftKey) held.push("Shift");
    if (event.metaKey) held.push("Win");
    // a letter, a digit, Space or Tab is the game's own while it is in front
    const typed = key.length === 1 || key === "Space" || key === "Tab";
    return { name: [...held, key].join("+"), key, plain: typed && !event.ctrlKey && !event.altKey };
  }

  part.keys.addEventListener("click", (event) => {
    const clear = event.target.closest("[data-clear]");
    if (clear) {
      stopWaiting();
      change({ hotkeys: { [clear.dataset.clear]: "" } });
      return;
    }
    const key = event.target.closest("[data-action]");
    if (!key) return;
    if (waiting === key.dataset.action) stopWaiting();
    else startWaiting(key);
  });

  part.keys.addEventListener("focusout", (event) => {
    if (waiting && event.target.dataset && event.target.dataset.action === waiting) stopWaiting();
  });

  document.addEventListener("keydown", (event) => {
    if (!waiting || ["Control", "Shift", "Alt", "Meta"].includes(event.key)) return;
    event.preventDefault(); // F5 would reload the page, Space would press the button again
    event.stopPropagation();
    if (event.key === "Escape") {
      stopWaiting();
      return;
    }
    const pressed = keyName(event);
    if (!pressed) {
      say("", ["That key can't be used. Function keys, letters, digits, Insert, Delete, Home, " +
        "End, Page Up and Page Down can, alone or with Ctrl, Alt or Shift."]);
      return;
    }
    if (pressed.plain) {
      say("", [`The game uses ${pressed.key} itself. Hold Ctrl or Alt with it.`]);
      return;
    }
    const action = waiting;
    stopWaiting();
    change({ hotkeys: { [action]: pressed.name } });
  }, true);

  part.usualKeys.addEventListener("click", () => {
    if (!current) return;
    stopWaiting();
    change({ hotkeys: Object.fromEntries(current.hotkeys.map((item) => [item.action, item.default])) });
  });

  // ---- colours ------------------------------------------------------------------------------

  const ink = document.createElement("canvas").getContext("2d");

  // Any colour a stylesheet can write, as the #rrggbb a colour picker wants.
  function hex(colour) {
    ink.fillStyle = "#000000";
    ink.fillStyle = colour || "#000000";
    return /^#[0-9a-f]{6}$/.test(ink.fillStyle) ? ink.fillStyle : "#000000";
  }

  function drawColours(s) {
    if (part.colours.children.length !== s.elements.length) {
      part.colours.replaceChildren();
      for (const name of s.elements) {
        const pick = document.createElement("input");
        pick.type = "color";
        pick.dataset.element = name;
        pick.setAttribute("aria-label", `Colour for ${name}`);
        const label = document.createElement("span");
        label.className = "set-name";
        // the diamond that marks a character's row on the meter, in this element's colour
        const gem = document.createElement("i");
        gem.className = "set-gem";
        gem.style.setProperty("--hue", `var(--${name})`);
        label.append(gem, name[0].toUpperCase() + name.slice(1));
        const code = document.createElement("span");
        code.className = "set-code";
        code.dataset.code = name;
        const reset = document.createElement("button");
        reset.type = "button";
        reset.className = "plain";
        reset.dataset.reset = name;
        reset.textContent = "the theme's colour";
        reset.setAttribute("aria-label", `${name}: back to the theme's colour`);
        part.colours.append(row(label, reset, code, pick));
      }
    }
    for (const name of s.elements) {
      const pick = part.colours.querySelector(`[data-element="${name}"]`);
      const own = s.colours[name];
      if (!busy(pick)) pick.value = own || hex(themeColours[name]);
      setText(part.colours.querySelector(`[data-code="${name}"]`), pick.value);
      part.colours.querySelector(`[data-reset="${name}"]`).hidden = !own;
    }
  }

  // while the picker is open the meter beside it shows the colour being tried
  part.colours.addEventListener("input", (event) => {
    const name = event.target.dataset.element;
    if (!name) return;
    document.documentElement.style.setProperty("--" + name, event.target.value);
    setText(part.colours.querySelector(`[data-code="${name}"]`), event.target.value);
  });
  part.colours.addEventListener("change", (event) => {
    const name = event.target.dataset.element;
    if (name) change({ colours: { [name]: event.target.value } });
  });
  part.colours.addEventListener("click", (event) => {
    const reset = event.target.closest("[data-reset]");
    if (reset) change({ colours: { [reset.dataset.reset]: "" } });
  });
  // another theme has other colours for the elements left at the theme's
  window.addEventListener("themecolours", () => { if (current) drawColours(current); });

  // ---- the rest -----------------------------------------------------------------------------

  // ---- what a character's row shows ---------------------------------------------------------

  let refocus = null; // the control of the list to give the keyboard back to once it is redrawn

  // The chosen figures first, in their order on the row; then the ones left out.
  function drawFigures(s) {
    const chosen = s.row_figures;
    const order = [...chosen, ...s.figures.map((f) => f.name).filter((name) => !chosen.includes(name))];
    const wanted = JSON.stringify(order) + chosen.length;
    if (part.figures.dataset.shown === wanted) return;
    part.figures.dataset.shown = wanted;
    part.figures.replaceChildren();
    for (const name of order) {
      const figure = s.figures.find((f) => f.name === name);
      const place = chosen.indexOf(name);
      const label = document.createElement("label");
      label.className = "set-pick";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = place >= 0;
      box.dataset.figure = name;
      const text = document.createElement("span");
      text.className = "set-name";
      text.textContent = figure.label;
      if (figure.note) {
        const note = document.createElement("small");
        note.className = "set-note";
        note.textContent = figure.note;
        text.append(note);
      }
      label.append(toggle(box), text);
      const steps = [];
      for (const [step, sign, word] of [[-1, "↑", "earlier"], [1, "↓", "later"]]) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "step";
        button.textContent = sign;
        button.dataset.figure = name;
        button.dataset.step = step;
        button.setAttribute("aria-label", `${figure.label}: ${word} on the row`);
        button.disabled = place < 0 || place + step < 0 || place + step >= chosen.length;
        steps.push(button);
      }
      const line = document.createElement("div");
      line.className = "set-row set-figure";
      line.classList.toggle("off", place < 0);
      const controls = document.createElement("span");
      controls.className = "set-ctl";
      controls.append(...steps);
      line.append(label, controls);
      part.figures.append(line);
    }
    if (refocus) {
      const again = part.figures.querySelector(`button[data-figure="${refocus.figure}"][data-step="${refocus.step}"]`);
      const box = part.figures.querySelector(`input[data-figure="${refocus.figure}"]`);
      const target = again && !again.disabled ? again : box;
      if (target) target.focus();
      refocus = null;
    }
  }

  function changeFigures(figures, from) {
    refocus = from;
    part.figures.dataset.shown = ""; // drawn again from the meter's answer, taken or refused
    change({ row_figures: figures });
  }

  part.figures.addEventListener("change", (event) => {
    const name = event.target.dataset.figure;
    if (!name || !current) return;
    const chosen = current.row_figures.filter((other) => other !== name);
    if (event.target.checked) chosen.push(name);
    changeFigures(chosen, { figure: name, step: 0 });
  });

  part.figures.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-step]");
    if (!button || !current) return;
    const chosen = [...current.row_figures];
    const from = chosen.indexOf(button.dataset.figure);
    const to = from + Number(button.dataset.step);
    if (from < 0 || to < 0 || to >= chosen.length) return;
    [chosen[from], chosen[to]] = [chosen[to], chosen[from]];
    changeFigures(chosen, { figure: button.dataset.figure, step: button.dataset.step });
  });

  for (const [select, setting] of [[part.figureDecimals, "figure_decimals"], [part.shareDecimals, "share_decimals"]]) {
    select.addEventListener("change", () => change({ [setting]: Number(select.value) }));
  }

  function options(select, items, chosen) {
    if (busy(select)) return;
    const wanted = JSON.stringify(items);
    if (select.dataset.items !== wanted) {
      select.dataset.items = wanted;
      select.replaceChildren();
      for (const [value, label] of items) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        select.appendChild(option);
      }
    }
    select.value = chosen;
  }

  function draw(s) {
    drawKeys(s);
    drawColours(s);
    drawFigures(s);
    if (!busy(part.figureDecimals)) part.figureDecimals.value = String(s.figure_decimals);
    if (!busy(part.shareDecimals)) part.shareDecimals.value = String(s.share_decimals);
    options(part.theme, s.themes.map((t) => [t.name, t.label]), s.theme);
    if (!busy(part.unit)) part.unit.value = s.display_unit;
    const game = s.game_language ? `The game's language (now ${s.game_language})` : "The game's language";
    options(part.language, [["", game], ...s.languages.map((l) => [l.code, l.label])], s.language);
    if (!busy(part.zoom)) {
      part.zoom.min = Math.round(s.zoom_range[0] * 100);
      part.zoom.max = Math.round(s.zoom_range[1] * 100);
      part.zoom.value = Math.round(s.overlay_zoom * 100);
      setText(part.zoomShown, Math.round(s.overlay_zoom * 100) + "%");
    }
    for (const flag of FLAGS) $("set-" + flag).checked = Boolean(s[flag]);
    if (!busy(part.log)) part.log.value = s.log_dir;
    if (!busy(part.channel)) part.channel.value = s.update_channel || "stable";
    if (!busy(part.engine)) part.engine.value = s.overlay_engine || "webview2";
    $("set-engine-row").hidden = !s.qt_available;
    setText(part.logState, s.log_found
      ? "The meter is reading Client.log in this folder."
      : "There is no Client.log in this folder. The game writes one when it starts.");
    part.logState.classList.toggle("bad", !s.log_found);
    if (!busy(part.exported)) part.exported.value = s.line;
  }

  part.theme.addEventListener("change", () => change({ theme: part.theme.value }));
  part.unit.addEventListener("change", () => change({ display_unit: part.unit.value }));
  part.language.addEventListener("change", () => change({ language: part.language.value }));
  part.zoom.addEventListener("input", () => setText(part.zoomShown, part.zoom.value + "%"));
  part.zoom.addEventListener("change", () => change({ overlay_zoom: Number(part.zoom.value) / 100 }));
  for (const flag of FLAGS) {
    const box = $("set-" + flag);
    box.addEventListener("change", () => change({ [flag]: box.checked }));
  }

  function useLog() {
    if (part.log.value.trim()) change({ log_dir: part.log.value });
    part.log.blur(); // so the answer, the folder as the meter understood it, is shown
  }
  part.logUse.addEventListener("click", useLog);
  part.log.addEventListener("keydown", (event) => { if (event.key === "Enter") useLog(); });
  part.logFind.addEventListener("click", () => send({ cmd: "find_log" }));

  // The boss HP tables: which game they are for, and an update once the game is patched. Drawn
  // from every state the meter pushes, since an update runs for a minute or more.
  let tablesShown = "";
  function drawTables(t) {
    if (!t) return;
    const built = t.built ? `, built ${t.built}` : "";
    const game = t.game ? ` The installed game is ${t.game}.` : "";
    const text = t.running ? (t.line || "Updating the boss HP tables.")
      : t.version ? `The tables are for game ${t.version}${built}.${game}` +
        (t.stale ? " They are out of date: update them." : "")
      : "There are no boss HP tables yet. Bosses whose HP the log does not give show percent.";
    const shown = text + (t.running ? "1" : "0") + (t.stale ? "1" : "0");
    if (shown === tablesShown) return;
    tablesShown = shown;
    setText(part.tablesState, text);
    part.tablesState.classList.toggle("bad", Boolean(t.stale) && !t.running);
    part.tablesUpdate.disabled = Boolean(t.running);
    part.tablesUpdate.classList.toggle("main", Boolean(t.stale) || !t.version);
  }
  part.tablesUpdate.addEventListener("click", () => send({ cmd: "update_tables" }));

  // Waveband's own updates: the version running, the newest one, and installing it.
  let appShown = "";
  function drawApp(u) {
    if (!u) return;
    let text;
    if (!u.set_up) text = `This is Waveband ${u.current}. This build does not look for updates.`;
    else if (u.status === "available" || u.status === "downloading" || u.status === "error") text = u.line;
    else if (u.status === "checking") text = "Looking for a newer version.";
    else if (u.status === "latest") text = `Waveband ${u.current} is the newest version.`;
    else text = `This is Waveband ${u.current}.`;
    const shown = text + u.status + u.installs;
    if (shown === appShown) return;
    appShown = shown;
    setText(part.appState, text);
    part.appState.classList.toggle("bad", u.status === "error");
    part.appCheck.disabled = !u.set_up || u.status === "checking" || u.status === "downloading";
    part.appInstall.hidden = u.status !== "available" && u.status !== "downloading";
    part.appInstall.disabled = u.status === "downloading";
    setText(part.appInstall, u.installs ? `Install ${u.latest}` : `Download ${u.latest}`);
  }
  part.appCheck.addEventListener("click", () => send({ cmd: "check_app" }));
  part.channel.addEventListener("change", () => change({ update_channel: part.channel.value }));
  part.engine.addEventListener("change", () => change({ overlay_engine: part.engine.value }));
  part.appInstall.addEventListener("click", () => send({ cmd: "install_app" }));
  stateWatchers.push((state) => drawApp((state.ui || {}).app));
  stateWatchers.push((state) => drawTables((state.ui || {}).tables));

  part.exported.addEventListener("focus", () => part.exported.select());
  part.exportCopy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(part.exported.value);
    } catch (error) {
      part.exported.select();
      if (!document.execCommand("copy")) {
        say("", ["Couldn't get at the clipboard. The line is selected: press Ctrl+C."]);
        return;
      }
    }
    say("Line copied. Paste it into the meter's settings on the other PC.");
  });

  function useImport() {
    if (!part.imported.value.trim()) return;
    importing = true;
    send({ cmd: "import", line: part.imported.value });
  }
  part.importUse.addEventListener("click", useImport);
  part.imported.addEventListener("keydown", (event) => { if (event.key === "Enter") useImport(); });

  // ---- talking to the meter -----------------------------------------------------------------

  replyHandlers.settings = (reply) => {
    current = reply.settings;
    draw(current);
    say(reply.said, reply.problems);
    if (importing) {
      importing = false;
      if (!(reply.problems || []).length) part.imported.value = "";
    }
  };

  // Settings change in other places too: the tray menu, a hotkey, another tab. The meter stamps
  // every state it pushes with a number that changes when a setting does.
  showPage();

  stateWatchers.push((state) => {
    const stamp = state.ui ? state.ui.settings : undefined;
    if (stamp === undefined || stamp === mark) return;
    mark = stamp;
    send({ cmd: "settings" });
  });
})();
