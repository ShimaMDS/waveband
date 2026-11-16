//--- start
JSON.stringify([document.getElementById("details").dataset.view, document.getElementById("set-title").textContent,
 [...document.querySelectorAll(".set-page")].filter((p) => !p.hidden).map((p) => p.dataset.page).join()])
//--- wait_key
document.querySelector('[data-action="toggle"]').focus();
document.querySelector('[data-action="toggle"]').click();
document.querySelector('[data-action="toggle"]').textContent
//--- plain_key shot
document.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyM", key: "m", bubbles: true }));
document.getElementById("set-said").textContent
//--- take_key
document.dispatchEvent(new KeyboardEvent("keydown", { code: "F12", key: "F12", ctrlKey: true, bubbles: true }));
"sent"
//--- key_taken
JSON.stringify([document.querySelector('[data-action="toggle"]').textContent, document.getElementById("set-said").textContent,
 document.getElementById("set-said").hidden])
//--- remove_key
document.querySelector('[data-clear="toggle"]').click(); "sent"
//--- key_removed
JSON.stringify([document.querySelector('[data-action="toggle"]').textContent,
 getComputedStyle(document.querySelector('[data-clear="toggle"]')).visibility])
//--- usual_keys
document.getElementById("set-keys-usual").click(); "sent"
//--- keys_back
document.querySelector('[data-action="toggle"]').textContent
//--- to_meter
location.hash = "#settings-meter"; "sent"
//--- switch_on
document.getElementById("set-compact").click();
JSON.stringify([document.getElementById("set-title").textContent, document.getElementById("set-compact").checked])
//--- switch_state
JSON.stringify([document.getElementById("set-compact").checked, document.body.classList.contains("compact")])
//--- switch_off
document.getElementById("set-compact").click(); "sent"
//--- to_rows
location.hash = "#settings-rows"; "sent"
//--- add_figure
document.querySelector('input[data-figure="damage"]').click(); "sent"
//--- figure_added
JSON.stringify([...document.querySelectorAll("#set-figures .set-figure")].map((r) =>
  r.querySelector("input").dataset.figure + (r.querySelector("input").checked ? "+" : "-")).join(" "))
//--- move_up
document.querySelector('button[data-figure="damage"][data-step="-1"]').click(); "sent"
//--- moved shot
JSON.stringify([[...document.querySelectorAll("#set-figures .set-figure")].map((r) =>
  r.querySelector("input").dataset.figure + (r.querySelector("input").checked ? "+" : "-")).join(" "),
 document.activeElement.dataset.figure + "/" + document.activeElement.dataset.step,
 getComputedStyle(document.querySelector(".channel")).gridTemplateColumns])
//--- remove_figure
document.querySelector('input[data-figure="damage"]').click(); "sent"
//--- to_colours
location.hash = "#settings-colours"; "sent"
//--- pick_colour
(() => {
  const pick = document.querySelector('[data-element="glacio"]');
  pick.value = "#ff0000";
  pick.dispatchEvent(new Event("input", { bubbles: true }));
  const shown = document.querySelector('[data-code="glacio"]').textContent;
  pick.dispatchEvent(new Event("change", { bubbles: true }));
  return shown;
})()
//--- colour_set
JSON.stringify([document.querySelector('[data-code="glacio"]').textContent,
 getComputedStyle(document.querySelector('[data-reset="glacio"]')).visibility,
 getComputedStyle(document.documentElement).getPropertyValue("--glacio")])
//--- colour_reset
document.querySelector('[data-reset="glacio"]').click(); "sent"
//--- colour_back
JSON.stringify([document.querySelector('[data-code="glacio"]').textContent,
 getComputedStyle(document.querySelector('[data-reset="glacio"]')).visibility])
//--- to_transfer
location.hash = "#settings-transfer"; "sent"
//--- import_bad
document.getElementById("set-import").value = "not a line";
document.getElementById("set-import-use").click(); "sent"
//--- import_bad_said shot
document.getElementById("set-said").textContent
//--- import_good
document.getElementById("set-import").value = document.getElementById("set-export").value;
document.getElementById("set-import-use").click(); "sent"
//--- import_good_said
JSON.stringify([document.getElementById("set-said").textContent, document.getElementById("set-import").value])
//--- plain_settings
location.hash = "#settings"; "sent"
//--- stays_on_page
document.getElementById("set-title").textContent
//--- to_fights
location.hash = "#fights"; "sent"
//--- fights shot
JSON.stringify([document.getElementById("details").dataset.view,
 getComputedStyle(document.getElementById("settings")).display,
 document.querySelector('.views [aria-current]').textContent])
//--- to_changes
location.hash = "#changes"; "sent"
//--- changes shot
JSON.stringify([document.getElementById("details").dataset.view, document.querySelectorAll("#changes-list h3").length,
 [...document.querySelectorAll(".details > .panel")].filter((p) => getComputedStyle(p).display !== "none").length])
