"use strict";

// ---- persistent settings (native bridge in-app, localStorage in a browser) ----
const store = {
  get(k, d = "") {
    try { return window.Android ? Android.getPref(k, d) : (localStorage.getItem(k) ?? d); }
    catch (e) { return d; }
  },
  set(k, v) {
    try { window.Android ? Android.setPref(k, v) : localStorage.setItem(k, v); }
    catch (e) {}
  }
};
const hasNative = !!window.Android;
function toast(m) { try { if (window.Android) Android.toast(m); else console.log(m); } catch (e) {} }

// species cache keyed by event id, so the gallery can show known IDs
const speciesCache = JSON.parse(store.get("speciesCache", "{}") || "{}");
function rememberSpecies(id, name) {
  speciesCache[id] = name;
  store.set("speciesCache", JSON.stringify(speciesCache));
}

const $ = sel => document.querySelector(sel);
const el = (tag, props = {}, kids = []) => {
  const n = document.createElement(tag);
  Object.assign(n, props);
  for (const k of [].concat(kids)) n.append(k);
  return n;
};
const captureBase = () => {
  const o = store.get("captureUrl", "").trim().replace(/\/$/, "");
  if (o) return o;
  // Served from the sidecar in a desktop/phone browser: use same origin, so the
  // same PWA works everywhere with no configuration. (The Android APK runs from
  // file:// and must set the URL in Settings.)
  if (location.protocol === "http:" || location.protocol === "https:") return location.origin;
  return "";
};
const mediaUrl = (date, file) => `${captureBase()}/api/media/${date}/${encodeURIComponent(file)}`;

// ---- view switching ----
function show(view) {
  for (const v of ["gallery", "detail", "settings"]) $("#" + v).hidden = (v !== view);
}
document.querySelectorAll("[data-back]").forEach(b => b.onclick = () => { show("gallery"); loadGallery(); });
$("#settingsBtn").onclick = () => show("settings");
$("#refreshBtn").onclick = () => loadGallery();

// ---- gallery ----
async function loadGallery() {
  show("gallery");
  const base = captureBase();
  const status = $("#status"), days = $("#days");
  days.innerHTML = "";
  if (!base) { status.textContent = "Set your capture server URL in Settings."; return; }
  status.textContent = "Loading…";
  try {
    const dayList = await fetchJson(`${base}/api/days`);
    if (!dayList.length) { status.textContent = ""; days.append(el("div", { className: "empty", textContent: "No events yet. Wave at the feeder." })); return; }
    status.textContent = "";
    for (const date of dayList.sort().reverse()) {
      const events = await fetchJson(`${base}/api/events/${date}`).catch(() => []);
      if (!events.length) continue;
      const grid = el("div", { className: "grid" });
      // newest event first within each day (reverse-chronological scroll)
      for (const ev of events.slice().reverse()) grid.append(eventCard(date, ev));
      days.append(el("div", { className: "day" }, [el("h2", { textContent: prettyDay(date) }), grid]));
    }
    if (!days.children.length) days.append(el("div", { className: "empty", textContent: "No events yet." }));
  } catch (e) {
    status.textContent = "Can't reach the capture server. Check the URL and that you're on the LAN.";
  }
}

function eventCard(date, ev) {
  // Design B: prefer the species the backend already resolved for this event
  // (from nvts /event/list, keyed by event id); fall back to local cache.
  const sp = ev.species || speciesCache[ev.event_id];
  const img = el("img", { loading: "lazy", src: ev.thumbnail ? mediaUrl(date, ev.thumbnail) : "" });
  img.onerror = () => { img.style.visibility = "hidden"; };
  const cap = el("div", { className: "cap" }, [
    el("span", { className: "sp", textContent: sp || "—" }),
    el("span", { className: "tm", textContent: hhmm(ev.time) })
  ]);
  const card = el("div", { className: "card" }, [img, cap]);
  card.onclick = () => openDetail(date, ev);
  return card;
}

// Event ids come from the feeder's upload path and species names from a remote
// recogniser, so these build text nodes rather than assigning innerHTML.
function showSpecies(elm, name, confidence) {
  elm.textContent = "";
  elm.append(document.createTextNode("Species: "), el("b", { textContent: name }));
  if (confidence != null) {
    elm.append(document.createTextNode(" "),
               el("span", { className: "muted", textContent: `(${confidence}%)` }));
  }
}

function showStatus(elm, text) {
  elm.textContent = "";
  elm.append(el("span", { className: "muted", textContent: text }));
}

// ---- detail ----
function openDetail(date, ev) {
  show("detail");
  const body = $("#detailBody");
  body.innerHTML = "";
  const base = captureBase();

  const poster = ev.thumbnail ? mediaUrl(date, ev.thumbnail) : "";
  const videoUrl = `${base}/api/event/${date}/${encodeURIComponent(ev.event_id)}/video.mp4`;
  const video = el("video", { controls: true, playsInline: true, preload: "metadata", hidden: true });
  video.poster = poster;
  const hero = el("img", { className: "hero", src: poster }); // shown until we know video exists
  // Cheap HEAD probe: show the player only if the server can produce an MP4.
  fetch(videoUrl, { method: "HEAD" }).then(r => {
    if (r.ok) { video.src = videoUrl; video.hidden = false; hero.hidden = true; }
  }).catch(() => {});

  const meta = el("div", { className: "meta" });
  meta.append(document.createTextNode(fmtTime(ev.time)), el("br"),
              document.createTextNode("event "),
              el("code", { textContent: ev.event_id || "" }));
  if (ev.segments) {
    meta.append(el("br"), document.createTextNode(`${ev.segments.length} segment(s)`));
  }

  const species = el("div", { className: "species" });
  const known = ev.species || speciesCache[ev.event_id];
  if (known) showSpecies(species, known);
  else showStatus(species, "Not identified yet.");

  const idBtn = el("button", { className: "primary", textContent: "Identify species" });
  idBtn.onclick = () => identify(date, ev, species, idBtn);

  body.append(video, hero, meta, species, el("div", { className: "row" }, [idBtn]));
}

// ---- species recognition (config-driven; contract filled once captured) ----
// On demand: the sidecar sends this one thumbnail to the recogniser and caches
// the result. Nothing leaves the LAN unless you tap this.
async function identify(date, ev, speciesEl, btn) {
  btn.disabled = true; btn.textContent = "Identifying…";
  try {
    const r = await fetch(`${captureBase()}/api/identify/${date}/${encodeURIComponent(ev.event_id)}`,
                          { method: "POST" });
    const data = await r.json();
    if (r.ok && data.species) {
      showSpecies(speciesEl, data.species, data.confidence);
      rememberSpecies(ev.event_id, data.species);
    } else {
      showStatus(speciesEl, data.error || "No bird detected");
    }
  } catch (e) {
    showStatus(speciesEl, `Couldn't reach the recogniser: ${e.message}`);
  } finally {
    btn.disabled = false; btn.textContent = "Identify species";
  }
}

// ---- settings ----
const SETTING_KEYS = ["captureUrl", "ntfyUrl", "ntfyTopic", "ntfyToken"];
function loadSettings() {
  const f = $("#settingsForm");
  for (const k of SETTING_KEYS) if (f[k]) f[k].value = store.get(k, "");
}
$("#settingsForm").onsubmit = e => {
  e.preventDefault();
  const f = e.target;
  for (const k of SETTING_KEYS) if (f[k]) store.set(k, f[k].value.trim());
  toast("Saved");
  show("gallery"); loadGallery();
};

// ---- watch toggle (native ntfy service) ----
function syncWatchBtn() {
  const on = hasNative && (() => { try { return Android.isWatching(); } catch (e) { return false; } })();
  const b = $("#watchBtn");
  b.textContent = "Watch: " + (on ? "on" : "off");
  b.classList.toggle("on", !!on);
}
$("#watchBtn").onclick = () => {
  if (!hasNative) { toast("Background watch needs the installed app"); return; }
  const on = (() => { try { return Android.isWatching(); } catch (e) { return false; } })();
  if (on) Android.stopWatch(); else {
    if (!store.get("ntfyUrl") || !store.get("ntfyTopic")) { show("settings"); toast("Set ntfy server + topic first"); return; }
    Android.startWatch();
  }
  setTimeout(syncWatchBtn, 300);
};

// ---- notification deep-link: body is "date/eventId" ----
window.openEvent = async function (combined) {
  try {
    const [date, ...rest] = combined.split("/");
    const eventId = rest.join("/");
    const events = await fetchJson(`${captureBase()}/api/events/${date}`);
    const ev = events.find(e => e.event_id === eventId);
    if (ev) openDetail(date, ev); else { show("gallery"); loadGallery(); }
  } catch (e) { show("gallery"); loadGallery(); }
};

// ---- helpers ----
async function fetchJson(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}
function prettyDay(d) {
  try {
    const dt = new Date(d + "T00:00:00");
    return dt.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
  } catch (e) { return d; }
}
function hhmm(t) { try { return new Date(t).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }); } catch (e) { return ""; } }
function fmtTime(t) { try { return new Date(t).toLocaleString(); } catch (e) { return t || ""; } }

// ---- boot ----
loadSettings();
syncWatchBtn();
const pending = hasNative ? (() => { try { return Android.takePendingEvent(); } catch (e) { return ""; } })() : "";
if (pending) window.openEvent(pending); else loadGallery();
