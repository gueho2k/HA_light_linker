/*
 * Light Linker panel – plain web component, no build step.
 * Talks only to the light_linker/* WebSocket commands and uses HA theme variables,
 * no internal ha-* elements (they change between releases).
 *
 * Views: "Taster" (device picture, every button event a slot), "Räume & Geräte"
 * (who operates a lamp), "Übersicht" (table per room). Links (Verknüpfungen) are the
 * containers for name, "aktiv" switch and dashboard button; motion links keep their
 * own editor.
 */

const PROFILES = [
  { id: "toggle", label: "Taster", hint: "Klick schaltet um, Halten dimmt" },
  { id: "rocker", label: "Wippe", hint: "oben an, unten aus, Halten dimmt" },
  { id: "switch", label: "Schalter", hint: "jede Schaltstellung schaltet um" },
  { id: "gate", label: "Tor", hint: "nur Einzelklick, kein Wiederholen" },
  { id: "motion", label: "Bewegung", hint: "Melder schalten ein, nach dem Nachlauf aus; von Hand hat Vorrang" },
];
const PROFILE_LABEL = { ...Object.fromEntries(PROFILES.map((p) => [p.id, p.label])), custom: "Eigene Belegung" };

const MOTION_STATE_TEXT = {
  off: "aus, wartet auf Bewegung",
  auto: "automatisch an",
  runout: "Nachlauf läuft",
  manual: "von Hand an",
  blocked: "von Hand aus, Automatik ruht",
  inactive: "inaktiv",
};

const DEVICE_CLASS_TEXT = { motion: "Bewegung", occupancy: "Belegung", presence: "Präsenz" };

// What a binding can do: [id, label, hint, group]
const ACTIONS = [
  ["toggle", "Umschalten", "an ↔ aus", "light"],
  ["on", "Einschalten", "optional mit Helligkeit", "light"],
  ["off", "Ausschalten", "", "light"],
  ["ramp_up", "Rampe hoch", "heller, solange gehalten", "ramp"],
  ["ramp_down", "Rampe runter", "dunkler, solange gehalten", "ramp"],
  ["ramp_alt", "Rampe wechselnd", "abwechselnd hoch und runter", "ramp"],
  ["brightness", "Helligkeit setzen", "fester Wert", "light"],
  ["cycle_color_temp", "Farbtemperatur durchschalten", "Liste mit Reglern", "light"],
  ["cycle_color", "Farbe durchschalten", "Liste mit Farbwähler", "light"],
  ["scene", "Szene", "scene.…", "other"],
  ["cover_toggle", "Tor / Rollladen", "Impuls, nie wiederholt", "cover"],
  ["cover_open", "Öffnen", "", "cover"],
  ["cover_close", "Schließen", "", "cover"],
  ["cover_stop", "Stopp", "", "cover"],
  ["none", "Nichts", "Platz bleibt frei", "other"],
];
const ACTION_LABEL = Object.fromEntries(ACTIONS.map(([id, label]) => [id, label]));
const RAMP_ACTIONS = new Set(["ramp_up", "ramp_down", "ramp_alt"]);
const HOLD_EVENTS = new Set(["hold", "hold_up", "hold_down"]);

const RAMP_DEFAULTS = {
  mode: "auto",
  duration_s: 4,
  min_pct: 3,
  max_pct: 100,
  when_off: "on_min",
  end: "auto",
  no_release: "step",
  step_pct: 25,
  max_s: 8,
  interval_ms: 400,
};

const BUTTON_NAMES = {
  left: "Links",
  right: "Rechts",
  both: "Beide zusammen",
  main: "Taste",
  on: "Taste I (an)",
  off: "Taste O (aus)",
  up: "Taste + (heller)",
  down: "Taste − (dunkler)",
  toggle: "Mitte",
  arrow_left: "Pfeil links",
  arrow_right: "Pfeil rechts",
  brightness_up: "Heller",
  brightness_down: "Dunkler",
};

const RAW_HINT = { hold_up: "brightness_move_up", hold_down: "brightness_move_down", on: "on", off: "off" };

const KIND_TEXT = {
  press: "kurz",
  double: "doppelt",
  triple: "dreifach",
  hold: "gehalten",
  hold_up: "gehalten (hoch)",
  hold_down: "gehalten (runter)",
  on: "an",
  off: "aus",
  rise: "eingeschaltet",
  fall: "ausgeschaltet",
  motion_on: "Bewegung, Licht an",
  motion_off: "Nachlauf vorbei, aus",
  manual_on: "von Hand an",
  manual_off: "von Hand aus",
};

const ORIGIN_TEXT = { test: " (Test)", dashboard: " (Dashboard)", service: " (Aktion)", motion: "" };

const DOMAIN_LABEL = { light: "Lampe", switch: "Steckdose/Schalter", cover: "Tor/Rollladen" };

const DEFAULT_OPTIONS = {
  on_brightness_pct: null,
  on_color_temp_kelvin: null,
  transition: 0.4,
  toggle_mode: "any_on",
  dim_step_pct: 10,
  dim_interval_ms: 400,
  min_brightness_pct: 3,
  dim_timeout_s: 8,
  hold_without_release: "step",
  hold_step_pct: 25,
  events: ["click", "double", "triple", "hold"],
  double: { type: "none" },
  triple: { type: "none" },
  verify: { enabled: true, timeout_s: 1.5, retries: 1, notify: true },
  motion: {
    lux_entity: null,
    lux_threshold: 36,
    off_delay_s: 30,
    manual_off_delay_s: 600,
    manual_off_block: "until_empty",
    manual_off_block_s: 600,
    block_entity: null,
    only_off: false,
  },
};

const fmtDuration = (sec) => {
  sec = Math.max(0, Math.round(sec));
  if (sec < 60) return `${sec} s`;
  const m = Math.floor(sec / 60);
  const r = sec % 60;
  return r ? `${m}:${String(r).padStart(2, "0")} min` : `${m} min`;
};

const COMBO_LIMIT = 60;

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const clone = (obj) => JSON.parse(JSON.stringify(obj));

const toHex = (rgb) => "#" + rgb.map((v) => Math.max(0, Math.min(255, v)).toString(16).padStart(2, "0")).join("");
const fromHex = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));

// Approximate colour of a white light at a given colour temperature (Tanner Helland).
const kelvinRgb = (k) => {
  const t = k / 100;
  const r = t <= 66 ? 255 : 329.7 * (t - 60) ** -0.1332;
  const g = t <= 66 ? 99.47 * Math.log(t) - 161.12 : 288.12 * (t - 60) ** -0.0755;
  const b = t >= 66 ? 255 : t <= 19 ? 0 : 138.52 * Math.log(t - 10) - 305.04;
  return [r, g, b].map((v) => Math.round(Math.max(0, Math.min(255, v))));
};

const COLOR_PRESETS = [
  [255, 147, 41], [255, 0, 0], [255, 120, 0], [255, 220, 0], [0, 200, 60],
  [0, 180, 255], [0, 60, 255], [140, 0, 255], [255, 0, 150], [255, 255, 255],
];
const KELVIN_PRESETS = [[2200, "Kerze"], [2700, "Warmweiß"], [3500, "Gemütlich"], [4000, "Neutral"], [5000, "Hell"], [6500, "Tageslicht"]];
const LIST_DEFAULTS = {
  cycle_color_temp: { key: "kelvin_list", value: [2700, 4000, 6500] },
  cycle_color: { key: "color_list", value: [{ rgb: [255, 147, 41], name: "" }, { rgb: [0, 180, 255], name: "" }] },
};

const fold = (text) =>
  String(text ?? "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/ß/g, "ss");

const timeAgo = (iso) => {
  if (!iso) return "noch nie ausgelöst";
  const sec = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (sec < 60) return "gerade eben";
  if (sec < 3600) return `vor ${Math.round(sec / 60)} min`;
  if (sec < 86400) return `vor ${Math.round(sec / 3600)} h`;
  return new Date(iso).toLocaleDateString("de-DE");
};

const keyOf = (src) => `${src.adapter}:${src.adapter === "zha" ? src.device_ieee : src.entity_id}`;
const EMPTY_TARGETS = () => ({ entity_id: [], area_id: [], group_id: [] });
const hasTargets = (t) => Boolean(t && ((t.entity_id || []).length || (t.area_id || []).length || (t.group_id || []).length));
const sameTargets = (a, b) => {
  const norm = (t) => JSON.stringify([[...(t?.entity_id || [])].sort(), [...(t?.area_id || [])].sort(), [...(t?.group_id || [])].sort()]);
  return norm(a) === norm(b);
};

class LightLinkerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._state = {
      loaded: false,
      error: null,
      view: "taster", // taster | geraete | netz
      links: [],
      sources: [],
      targets: [],
      areas: [],
      selSource: null, // source key shown in the Taster view
      selTarget: null, // entity id shown in Räume & Geräte
      netzArea: null,
      focusButton: null,
      selected: null, // link id or "new" (link editor)
      draft: null,
      dlg: null, // binding dialog
      setup: null, // quick setup of an unbound device
      learning: false,
      learnFor: null, // "source" (link editor) | "find" | "assign"
      candidates: [],
      activity: [],
      pressed: null, // {source, button, event, until}
      notice: null,
    };
    this._combo = null; // {id, query, active, items}
    this._unsubs = [];
    // One set of delegated listeners for the lifetime of the element.
    const root = this.shadowRoot;
    root.addEventListener("click", (e) => this._onClick(e));
    // Remember which <details> are open so a re-render does not collapse them.
    root.addEventListener("toggle", (e) => {
      const key = e.target.dataset?.keep;
      if (key) this._open = { ...(this._open || {}), [key]: e.target.open };
    }, true);
    root.addEventListener("dragstart", (e) => this._onDrag(e, "start"));
    root.addEventListener("dragover", (e) => this._onDrag(e, "over"));
    root.addEventListener("drop", (e) => this._onDrag(e, "drop"));
    root.addEventListener("dragend", (e) => this._onDrag(e, "end"));
    root.addEventListener("change", (e) => this._onChange(e));
    root.addEventListener("input", (e) => this._onInputEvent(e));
    root.addEventListener("keydown", (e) => this._onKeydown(e));
    root.addEventListener("focusin", (e) => this._onFocusIn(e));
    root.addEventListener("focusout", (e) => this._onFocusOut(e));
    root.addEventListener("mousedown", (e) => this._onMousedown(e));
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._init();
    else this._paintMotion();
  }

  get hass() {
    return this._hass;
  }

  set narrow(value) {
    this._haNarrow = Boolean(value);
    this._updateNarrow();
  }

  /** One column when HA says so or when the panel itself is small (tablet, split screen). */
  _updateNarrow() {
    const width = this.getBoundingClientRect().width || window.innerWidth;
    const narrow = Boolean(this._haNarrow) || width < 760;
    if (narrow === this._narrow) return;
    this._narrow = narrow;
    if (this._state.loaded) this._render();
  }

  connectedCallback() {
    if (!this._resizeObs && window.ResizeObserver) {
      this._resizeObs = new ResizeObserver(() => this._updateNarrow());
    }
    this._resizeObs?.observe(this);
    this._updateNarrow();
  }

  disconnectedCallback() {
    this._resizeObs?.disconnect();
    this._stopLearn();
    this._watchSource(null);
    this._unsubs.forEach((u) => u());
    this._unsubs = [];
  }

  // Motion status comes live from the state sensor; only the status line is
  // repainted, so typing in the editor is never disturbed.
  _motionLive(link) {
    const entity = link?.status?.sensor_entity;
    const st = entity && this._hass.states[entity];
    if (!st) return link?.status?.motion || null;
    return { state: st.state, timer_end: st.attributes.timer_end, occupied: st.attributes.occupied };
  }

  _motionText(m) {
    if (!m) return "";
    let text = MOTION_STATE_TEXT[m.state] || m.state;
    if (m.timer_end) {
      const left = (new Date(m.timer_end).getTime() - Date.now()) / 1000;
      if (left > 0) text += m.state === "blocked" ? `, frei in ${fmtDuration(left)}` : `, aus in ${fmtDuration(left)}`;
    }
    if (m.occupied === true) text += ", Raum belegt";
    return text;
  }

  _paintMotion() {
    const root = this.shadowRoot;
    let ticking = false;
    for (const el of root.querySelectorAll("[data-motion]")) {
      const link = this._state.links.find((l) => l.id === el.dataset.motion);
      const m = this._motionLive(link);
      el.textContent = (el.dataset.prefix || "") + this._motionText(m);
      if (m?.timer_end) ticking = true;
    }
    clearTimeout(this._tick);
    if (ticking) this._tick = setTimeout(() => this._paintMotion(), 1000);
  }

  // ------------------------------------------------------------- data

  _ws(type, data = {}) {
    return this._hass.connection.sendMessagePromise({ type: `light_linker/${type}`, ...data });
  }

  async _init() {
    this._render();
    try {
      await this._reload();
      const unsub = await this._hass.connection.subscribeMessage(
        (msg) => {
          if (!msg.activity) return;
          this._state.activity = [msg.activity, ...this._state.activity].slice(0, 20);
          const link = this._state.links.find((l) => l.id === msg.activity.link_id);
          if (link) link.status.last_triggered = msg.activity.time;
          this._softRender();
        },
        { type: "light_linker/activity/subscribe" }
      );
      this._unsubs.push(unsub);
    } catch (err) {
      this._state.error = err?.message || err?.code || String(err);
    }
    this._state.loaded = true;
    const used = this._usedSourceKeys();
    if (!this._narrow && !this._state.selSource && used.length) this._state.selSource = used[0];
    this._watchSource(this._state.selSource);
    this._render();
  }

  async _reload() {
    // Links are essential; the catalogs only feed the pickers. A failing
    // catalog must not hide the links.
    const [links, sources, targets, migrations, groups] = await Promise.allSettled([
      this._ws("links/list"),
      this._ws("sources/list"),
      this._ws("targets/list"),
      this._ws("migrations/list"),
      this._ws("groups/list"),
    ]);
    this._state.groups = groups.status === "fulfilled" ? groups.value.groups : [];
    if (links.status === "rejected") throw links.reason;
    this._state.links = links.value.links;
    this._state.migrations = migrations.status === "fulfilled" ? migrations.value.migrations : {};
    if (sources.status === "fulfilled") {
      this._state.sources = sources.value.sources;
      this._state.illuminance = sources.value.illuminance || [];
    }
    if (targets.status === "fulfilled") {
      this._state.targets = targets.value.targets;
      this._state.areas = targets.value.areas;
    }
    const failed = [sources, targets].find((r) => r.status === "rejected");
    if (failed) {
      this._state.notice = {
        text: `Auswahllisten konnten nicht geladen werden (${failed.reason?.message || failed.reason}). Details im Protokoll.`,
        isError: true,
      };
    }
  }

  // Re-render unless the user is typing in a search field or a dialog field.
  _softRender() {
    if (this._combo) return;
    const active = this.shadowRoot.activeElement;
    if (active && active.matches?.("input:not([type=checkbox]):not([type=range]):not([type=color]), select")) return;
    this._render();
  }

  _areaName(areaId) {
    return this._state.areas.find((a) => a.area_id === areaId)?.name || "Ohne Raum";
  }

  _targetInfo(entityId) {
    return this._state.targets.find((t) => t.entity_id === entityId);
  }

  _ident(src) {
    return src.adapter === "zha" ? src.device_ieee : src.entity_id;
  }

  _sourceInfo(src) {
    const ident = this._ident(src);
    return this._state.sources.find((s) => s.adapter === src.adapter && this._ident(s) === ident);
  }

  _catalog(key) {
    return this._state.sources.find((s) => s.key === key || keyOf(s) === key);
  }

  _sourceName(src) {
    if (src.adapter === "zha") return this._sourceInfo(src)?.name || src.device_ieee;
    return this._entityName(src.entity_id).replace(/ Action$/, "");
  }

  _keyName(key) {
    const info = this._catalog(key);
    if (info?.alias) return info.alias;
    return this._deviceName(key);
  }

  /** The name Home Assistant knows the device by (also searchable when an alias is set). */
  _deviceName(key) {
    const info = this._catalog(key);
    if (info) return (info.device || info.name || key).replace(/ Action$/, "");
    const [adapter, ident] = [key.split(":")[0], key.slice(key.indexOf(":") + 1)];
    return adapter === "zha" ? ident : this._entityName(ident).replace(/ Action$/, "");
  }

  _keyArea(key) {
    const info = this._catalog(key);
    if (info?.area_id) return info.area_id;
    const ident = key.slice(key.indexOf(":") + 1);
    return this._targetInfo(ident)?.area_id || null;
  }

  _sourceArea(src) {
    if (!src) return null;
    if (src.adapter === "state_input") return this._targetInfo(src.entity_id)?.area_id || null;
    return this._sourceInfo(src)?.area_id || null;
  }

  _entityName(entityId) {
    return this._hass.states[entityId]?.attributes?.friendly_name || entityId;
  }

  _linkArea(link) {
    const first = link.status?.resolved_targets?.[0] || link.targets.entity_id?.[0];
    if (first) return this._targetInfo(first)?.area_id || null;
    return link.targets.area_id?.[0] || null;
  }

  _layout(key) {
    const info = this._catalog(key);
    if (info?.layout) return info.layout;
    const adapter = key.split(":")[0];
    const events = adapter === "state_input" ? ["rise", "fall"] : ["press", "double", "triple", "hold"];
    return {
      library: null,
      model_name: null,
      frame: { w: 64, h: 96, r: 12 },
      buttons: [{ id: "_any", label: "", x: 0, y: 0, w: 64, h: 96, slots: events.map((e) => ({ button: null, event: e })) }],
      hold_end: "release",
      native_multi: adapter === "state_input",
    };
  }

  /** Source keys used by button links (not motion sensors), sorted by area and name. */
  _usedSourceKeys() {
    const keys = new Set();
    for (const link of this._state.links) {
      for (const src of link.sources) if (src.adapter !== "occupancy") keys.add(keyOf(src));
    }
    return [...keys].sort(
      (a, b) =>
        this._areaName(this._keyArea(a)).localeCompare(this._areaName(this._keyArea(b)), "de") ||
        this._keyName(a).localeCompare(this._keyName(b), "de")
    );
  }

  /** Every binding of a source: [{link, binding, button, event}] (button = effective button). */
  _deviceBindings(key) {
    const result = [];
    for (const link of this._state.links) {
      const srcs = link.sources.filter((s) => keyOf(s) === key);
      if (!srcs.length) continue;
      for (const binding of link.bindings || []) {
        if (binding.source !== null && binding.source !== undefined && binding.source !== key) continue;
        for (const src of srcs) {
          const button = binding.button ?? src.button ?? null;
          result.push({ link, binding, button, event: binding.event });
          break;
        }
      }
    }
    return result;
  }

  /** Whether this device can produce the event (templates also cover events other remotes send). */
  _reachable(key, button, event) {
    const info = this._catalog(key);
    if (!info?.layout || (!info.layout.library && !(info.event_types || []).length)) return true;
    const slots = info.layout.buttons.flatMap((b) => b.slots);
    if (button === null || button === undefined) return slots.some((x) => x.event === event);
    return slots.some((x) => x.event === event && ((x.button ?? null) === button || x.button === null));
  }

  _slotBindings(key, slot) {
    const all = this._deviceBindings(key).filter((x) => x.event === slot.event);
    const own = all.filter((x) => (x.button ?? null) === (slot.button ?? null));
    if (own.length || slot.button == null) return own;
    // a binding for "all buttons" acts here too as long as the button has none of its own
    return all.filter((x) => (x.button ?? null) === null).map((x) => ({ ...x, inherited: true }));
  }

  _slotText(layout, slot) {
    const lib = Boolean(layout?.library);
    const e = slot.event;
    if (e === "rise") return "eingeschaltet";
    if (e === "fall") return "ausgeschaltet";
    if (e === "double") return "doppelt drücken";
    if (e === "triple") return "dreifach drücken";
    if (lib) return HOLD_EVENTS.has(e) ? "halten" : "kurz drücken";
    return { press: "kurz drücken", on: "„an“ drücken", off: "„aus“ drücken", hold: "halten", hold_up: "halten (heller)", hold_down: "halten (dunkler)" }[e] || e;
  }

  _slotRaw(layout, slot) {
    if ((slot.event === "double" || slot.event === "triple") && !layout.native_multi) return "von Light Linker erkannt";
    return RAW_HINT[slot.event] || slot.event;
  }

  /** Id of the picture button that holds a slot. */
  _buttonOf(layout, slot) {
    return layout.buttons.find((b) => b.slots.some((x) => (x.button ?? null) === (slot.button ?? null) && x.event === slot.event))?.id ?? slot.button;
  }

  _buttonLabel(layout, buttonId) {
    const btn = layout.buttons.find((b) => b.id === buttonId);
    if (buttonId === "_any" || buttonId == null) return layout.buttons.length > 1 ? "Alle Tasten" : "Taster";
    if (buttonId === "_extra") return "Weitere Tasten";
    if (BUTTON_NAMES[buttonId]) return BUTTON_NAMES[buttonId];
    const label = btn?.label || buttonId;
    return /^(I|O|[0-9]+|•+)$/.test(label) || label.length <= 2 ? `Taste ${label}` : label.charAt(0).toUpperCase() + label.slice(1);
  }

  /** Short "I kurz" / "Links doppelt" label for chips. */
  _chipLabel(layout, button, event) {
    const btn = layout.buttons.find((b) => b.slots.some((x) => (x.button ?? null) === (button ?? null) && x.event === event));
    let name = "";
    if (btn && btn.id !== "_any") name = btn.label && btn.label.length <= 2 ? btn.label : this._buttonLabel(layout, btn.id).replace(/^Taste /, "");
    else if (button) name = BUTTON_NAMES[button] || button;
    const ev = layout.library || btn
      ? { press: "kurz", on: "kurz", off: "kurz", hold: "halten", hold_up: "halten", hold_down: "halten" }[event] || KIND_TEXT[event] || event
      : KIND_TEXT[event] || event;
    return `${name ? `${name} ` : ""}${ev}`;
  }

  _targetsText(targets) {
    const names = [
      ...(targets?.entity_id || []).map((e) => this._entityName(e)),
      ...(targets?.area_id || []).map((a) => `Bereich ${this._areaName(a)}`),
      ...(targets?.group_id || []).map((g) => this._group(g)?.name || "Gruppe ?"),
    ];
    if (!names.length) return "kein Ziel";
    return names.length > 3 ? `${names.slice(0, 3).join(", ")} +${names.length - 3}` : names.join(", ");
  }

  _group(id) {
    return (this._state.groups || []).find((g) => g.id === id);
  }

  /** Entity ids a target spec switches (groups and areas expanded). */
  _expandTargets(t) {
    const out = new Set(t?.entity_id || []);
    for (const g of t?.group_id || []) for (const e of this._group(g)?.entities || []) out.add(e);
    for (const a of t?.area_id || []) for (const x of this._state.targets) if (x.area_id === a) out.add(x.entity_id);
    return out;
  }

  _assignTargets() {
    const t = this._state.selTarget || "";
    if (t.startsWith("grp:")) return { ...EMPTY_TARGETS(), group_id: [t.slice(4)] };
    return { ...EMPTY_TARGETS(), entity_id: this._selEntities() };
  }

  _groupArea(g) {
    return g.area_id || this._targetInfo(g.entities?.[0])?.area_id || null;
  }

  /** The group whose members are exactly these entities, if any. */
  _groupFor(entities) {
    const set = new Set(entities);
    return (this._state.groups || []).find((g) => g.entities.length === set.size && g.entities.every((e) => set.has(e)));
  }

  _chips(targets, scope) {
    const chip = (kind, value, label, cls = "") =>
      `<span class="chip ${cls}">${label}<button class="x" data-action="chip-remove" data-scope="${scope}" data-kind="${kind}" data-value="${esc(value)}" aria-label="entfernen">×</button></span>`;
    return [
      ...(targets.group_id || []).map((g) => chip("group", g, `<span class="gico" aria-hidden="true">▦</span>${esc(this._group(g)?.name || "Gruppe ?")}`, "grp")),
      ...(targets.entity_id || []).map((e) => chip("entity", e, esc(this._entityName(e)))),
      ...(targets.area_id || []).map((a) => chip("area", a, `Bereich ${esc(this._areaName(a))}`, "area")),
    ].join("");
  }

  _bindingTargets(link, binding) {
    return binding.targets || link.targets;
  }

  // ---------------------------------------------------------- navigation

  _go(view) {
    this._stopLearn();
    this._combo = null;
    this._state.view = view;
    this._state.selected = null;
    this._state.draft = null;
    this._state.setup = null;
    if (view === "netz" && !this._state.netzArea) this._state.netzArea = this._netzAreas()[0]?.area_id ?? "_all";
    this._render();
  }

  _openSource(key) {
    this._stopLearn();
    this._combo = null;
    this._state.view = "taster";
    this._state.selSource = key;
    this._state.selected = null;
    this._state.draft = null;
    this._state.focusButton = null;
    this._state.setup = this._deviceBindings(key).length ? null : this._newSetup(key);
    this._watchSource(key);
    this._render();
  }

  _selEntities() {
    const t = this._state.selTarget || "";
    return t.startsWith("=") ? [t.slice(1)] : t.split("|").filter(Boolean);
  }

  _openTarget(entityId) {
    this._stopLearn();
    this._combo = null;
    this._state.view = "geraete";
    // a device that is part of a group opens the group
    this._state.selTarget =
      entityId.includes("|") || entityId.startsWith("=") ? entityId : this._targetGroups().find((g) => g.entities.includes(entityId))?.id || entityId;
    this._state.selected = null;
    this._state.draft = null;
    this._render();
  }

  async _watchSource(key) {
    if (this._pressUnsub) {
      try {
        this._pressUnsub();
      } catch (_err) {
        /* already closed */
      }
      this._pressUnsub = null;
    }
    if (!key || !this._hass) return;
    try {
      this._pressUnsub = await this._hass.connection.subscribeMessage(
        (msg) => {
          if (!msg.press) return;
          const p = msg.press;
          if (p.event === "release" || p.event === "repeat") return;
          this._state.pressed = { ...p, until: Date.now() + 1500 };
          this._paintPressed();
          clearTimeout(this._pressTimer);
          this._pressTimer = setTimeout(() => {
            this._state.pressed = null;
            this._paintPressed();
          }, 1600);
        },
        { type: "light_linker/presses/subscribe", source: key }
      );
    } catch (_err) {
      /* the highlight is a convenience */
    }
  }

  // Highlight without a full render: mark the button in the picture and its slot rows.
  _paintPressed() {
    const p = this._state.pressed;
    const root = this.shadowRoot;
    root.querySelectorAll(".pressed").forEach((el) => el.classList.remove("pressed"));
    if (!p) return;
    const layout = this._layout(p.source);
    const btn = layout.buttons.find((b) => b.slots.some((s) => (s.button ?? null) === (p.button ?? null) && s.event === p.event))
      || layout.buttons.find((b) => b.id === p.button);
    // only this remote's big picture and its rows – the small pictures of other
    // remotes in the list have keys with the same names ("1", "left")
    if (this._state.selSource !== p.source) return;
    const pic = [...root.querySelectorAll("svg.device[data-key]")].find((el) => el.dataset.key === p.source);
    if (btn && pic) pic.querySelectorAll(`[data-btn="${CSS.escape(btn.id)}"]`).forEach((el) => el.classList.add("pressed"));
    const pane = root.querySelector(".pane");
    if (pane) pane.querySelectorAll(`[data-slot="${CSS.escape(`${p.button ?? ""}:${p.event}`)}"]`).forEach((el) => el.classList.add("pressed"));
  }

  // ---------------------------------------------------------- link editor

  _select(id, preset = {}) {
    this._stopLearn();
    this._combo = null;
    this._state.notice = null;
    if (id === "new") {
      this._state.draft = {
        name: "",
        enabled: true,
        dashboard_button: false,
        profile: preset.profile || "toggle",
        sources: preset.sources || [],
        targets: { ...EMPTY_TARGETS(), ...(preset.targets || {}) },
        options: clone(DEFAULT_OPTIONS),
      };
      this._state.selected = "new";
      this._origSources = null;
      this._render();
      if (!preset.sources?.length) this._startLearn("source");
      return;
    }
    const link = this._state.links.find((l) => l.id === id);
    this._state.selected = id;
    this._state.draft = this._toDraft(link);
    this._origSources = JSON.stringify(link.sources.map(keyOf).sort());
    this._origProfile = link.profile;
    this._render();
  }

  _toDraft(link) {
    const options = { ...clone(DEFAULT_OPTIONS), ...link.options };
    options.motion = { ...clone(DEFAULT_OPTIONS.motion), ...(link.options.motion || {}) };
    return clone({ dashboard_button: false, ...link, targets: { ...EMPTY_TARGETS(), ...link.targets }, options });
  }

  _closeEditor() {
    this._stopLearn();
    this._state.selected = null;
    this._state.draft = null;
    this._render();
  }

  async _startLearn(purpose) {
    this._stopLearn();
    this._state.learning = true;
    this._state.learnFor = purpose;
    this._state.candidates = [];
    this._render();
    try {
      this._learnUnsub = await this._hass.connection.subscribeMessage(
        (msg) => {
          if (msg.done) {
            this._state.learning = false;
            this._learnUnsub = null;
            this._render();
            return;
          }
          const c = msg.candidate;
          if (this._state.learnFor === "assign" && c.kind && c.kind !== "hold_end" && c.adapter !== "occupancy") {
            this._assignFromCandidate(c);
            return;
          }
          if (this._state.learnFor === "find" && c.adapter !== "occupancy") {
            // any message of a device identifies it, also "pressed down" without a meaning of its own
            this._stopLearn();
            this._openSource(c.adapter === "zha" ? `zha:${c.device_ieee}` : `${c.adapter}:${c.entity_id}`);
            return;
          }
          const key = `${c.adapter}|${this._ident(c)}|${c.button ?? ""}`;
          if (!this._state.candidates.some((x) => `${x.adapter}|${this._ident(x)}|${x.button ?? ""}` === key)) {
            this._state.candidates = [c, ...this._state.candidates].slice(0, 8);
            this._softRender();
          }
        },
        { type: "light_linker/learn/subscribe" }
      );
    } catch (err) {
      this._state.learning = false;
      this._flash(`Anlernen nicht möglich: ${err.message}`, true);
    }
  }

  _stopLearn() {
    if (this._learnUnsub) {
      this._learnUnsub();
      this._learnUnsub = null;
    }
    this._state.learning = false;
    this._state.learnFor = null;
  }

  _addSource(src, suggestedProfile, areaName) {
    const d = this._state.draft;
    const ident = this._ident(src);
    if (d.sources.some((s) => s.adapter === src.adapter && this._ident(s) === ident && (s.button ?? null) === (src.button ?? null))) return;
    d.sources.push({
      adapter: src.adapter,
      entity_id: src.adapter === "zha" ? null : src.entity_id,
      device_ieee: src.adapter === "zha" ? src.device_ieee : null,
      button: src.button ?? null,
      mode: src.adapter === "state_input" && d.profile === "switch" ? "switch" : "button",
      role: null,
    });
    if (src.adapter === "occupancy") {
      // A sensor turns the link into a motion link and brings its light sensor along.
      const info = this._sourceInfo(src) || {};
      const isNew = this._state.selected === "new";
      d.profile = "motion";
      d.options.motion = { ...clone(DEFAULT_OPTIONS.motion), ...(d.options.motion || {}) };
      if (!d.options.motion.lux_entity && info.lux_entity) d.options.motion.lux_entity = info.lux_entity;
      if (isNew && d.sources.filter((x) => x.adapter === "occupancy").length === 1 && info.default_off_delay_s)
        d.options.motion.off_delay_s = info.default_off_delay_s;
    } else if (d.sources.length === 1 && suggestedProfile && this._state.selected === "new" && d.profile !== "motion") d.profile = suggestedProfile;
    if (!d.name && areaName && areaName !== "Ohne Raum") d.name = areaName;
  }

  _payload() {
    const d = clone(this._state.draft);
    ["status", "id", "created_at", "updated_at"].forEach((k) => delete d[k]);
    const sourcesNow = JSON.stringify(d.sources.map(keyOf).sort());
    if (d.profile === "custom") {
      // keep the single bindings; drop those of removed sources
      const keys = new Set(d.sources.map(keyOf));
      d.bindings = (d.bindings || []).filter((b) => b.source === null || b.source === undefined || keys.has(b.source));
    } else if (this._state.selected === "new" || d.profile !== this._origProfile || sourcesNow !== this._origSources) {
      // template changed (or new link): the server builds the bindings from it
      delete d.bindings;
    }
    return d;
  }

  async _save() {
    const d = this._state.draft;
    if (!d.name.trim()) return this._flash("Gib der Verknüpfung einen Namen.", true);
    if (!d.sources.length) return this._flash("Füge mindestens eine Quelle hinzu.", true);
    if (!hasTargets(d.targets) && !(d.bindings || []).some((b) => hasTargets(b.targets)))
      return this._flash("Wähle mindestens ein Ziel.", true);
    if (this._state.selected !== "new" && d.profile !== this._origProfile && this._origProfile === "custom" && d.profile !== "motion") {
      if (!confirm("Die Vorlage ersetzt alle einzeln eingestellten Belegungen dieser Verknüpfung. Fortfahren?")) return;
    }
    try {
      let result;
      if (this._state.selected === "new") {
        result = await this._ws("links/create", { link: this._payload() });
      } else {
        result = await this._ws("links/update", {
          link_id: this._state.selected,
          link: this._payload(),
          updated_at: d.updated_at,
        });
      }
      this._stopLearn();
      await this._reload();
      const saved = this._state.links.find((l) => l.id === result.link.id) || result.link;
      this._state.selected = saved.id;
      this._state.draft = this._toDraft(saved);
      this._origSources = JSON.stringify(saved.sources.map(keyOf).sort());
      this._origProfile = saved.profile;
      this._flash(saved.status?.conflicts?.length ? "Gespeichert, aber eine andere Verknüpfung belegt dieselbe Taste." : "Gespeichert.", Boolean(saved.status?.conflicts?.length));
    } catch (err) {
      this._flash(
        err.code === "conflict" ? "Die Verknüpfung wurde zwischenzeitlich geändert. Lade das Panel neu." : `Speichern fehlgeschlagen: ${err.message}`,
        true
      );
    }
  }

  async _delete() {
    if (!confirm(`„${this._state.draft.name}“ löschen?`)) return;
    try {
      await this._ws("links/delete", { link_id: this._state.selected });
      await this._reload();
      this._state.selected = null;
      this._state.draft = null;
      this._flash("Gelöscht.");
    } catch (err) {
      this._flash(`Löschen fehlgeschlagen: ${err.message}`, true);
    }
  }

  async _migrate() {
    if (!confirm("Quellen und Ziele auf die Zigbee2MQTT-Geräte umstellen? Die Verknüpfungen bleiben sonst unverändert.")) return;
    try {
      const result = await this._ws("migrations/apply");
      await this._reload();
      if (this._state.selected && this._state.selected !== "new") this._select(this._state.selected);
      this._flash(`${result.applied} umgestellt.`);
    } catch (err) {
      this._flash(`Umstellen fehlgeschlagen: ${err.message}`, true);
    }
  }

  async _setExternal(key, note) {
    if (note === "?") {
      note = prompt("Wer nutzt diesen Taster außerdem? (z. B. Node-RED Terrarium)");
      if (!note) return;
    }
    try {
      await this._ws("external/set", { key, note: note || null });
      await this._reload();
      if (this._state.draft && this._state.selected !== "new")
        this._state.draft.status = this._state.links.find((l) => l.id === this._state.selected)?.status || this._state.draft.status;
      this._render();
    } catch (err) {
      this._flash(`Speichern fehlgeschlagen: ${err.message}`, true);
    }
  }

  async _testLink(kind) {
    if (this._state.selected === "new") return this._flash("Speichere die Verknüpfung, bevor du sie testest.", true);
    try {
      await this._ws("links/test", { link_id: this._state.selected, kind, confirm: false });
      this._flash("Test gesendet.");
    } catch (err) {
      if (err.code === "confirm_required" && confirm("Das Tor wird jetzt wirklich bewegt. Fortfahren?")) {
        await this._ws("links/test", { link_id: this._state.selected, kind, confirm: true });
        this._flash("Test gesendet.");
        return;
      }
      this._flash(`Test fehlgeschlagen: ${err.message}`, true);
    }
  }

  async _testBinding(linkId, bindingId) {
    const link = this._state.links.find((l) => l.id === linkId);
    const binding = link?.bindings.find((b) => b.id === bindingId);
    let confirmGate = false;
    if (binding?.action === "cover_toggle") {
      if (!confirm("Das Tor wird jetzt wirklich bewegt. Fortfahren?")) return;
      confirmGate = true;
    }
    try {
      await this._ws("bindings/test", { link_id: linkId, binding_id: bindingId, confirm: confirmGate });
      this._flash(`Test: ${ACTION_LABEL[binding?.action] || "gesendet"}${HOLD_EVENTS.has(binding?.event) ? " (2 s gehalten)" : ""}.`);
    } catch (err) {
      this._flash(`Test fehlgeschlagen: ${err.message}`, true);
    }
  }

  async _toggleEnabled(link) {
    try {
      const copy = clone(link);
      ["status", "id", "created_at", "updated_at"].forEach((k) => delete copy[k]);
      await this._ws("links/update", {
        link_id: link.id,
        link: { ...copy, enabled: !link.enabled },
        updated_at: link.updated_at,
      });
      await this._reload();
      if (this._state.selected === link.id) this._select(link.id);
      else this._render();
    } catch (err) {
      this._flash(`Umschalten fehlgeschlagen: ${err.message}`, true);
    }
  }

  _flash(text, isError = false) {
    this._state.notice = { text, isError };
    // a message follows an action: always show its result (a search list closes)
    this._combo = null;
    this._render();
    const live = this.shadowRoot.querySelector(".notice-slot");
    if (live) live.innerHTML = `<p class="notice ${isError ? "err" : ""}" role="status">${esc(text)}</p>`;
    clearTimeout(this._noticeTimer);
    this._noticeTimer = setTimeout(() => {
      this._state.notice = null;
      const slot = this.shadowRoot.querySelector(".notice-slot");
      if (slot) slot.innerHTML = "";
    }, isError ? 6000 : 2500);
  }

  // ---------------------------------------------------------- groups

  _groupSummary(g) {
    const subs = g.members.filter((m) => m.startsWith("group:")).map((m) => this._group(m.slice(6))?.name).filter(Boolean);
    const direct = g.members.filter((m) => !m.startsWith("group:")).length;
    const parts = [...subs];
    if (direct) parts.push(direct === 1 ? "1 Gerät" : `${direct} Geräte`);
    return `Lichtgruppe · ${parts.join(" + ")}${g.on ? ` · ${g.on} an` : ""}`;
  }

  _groupEditing() {
    const t = this._state.selTarget || "";
    if (t === "grp:new") return this._state.groupDraft;
    return this._group(t.slice(4));
  }

  _groupAncestors(id) {
    const out = new Set();
    const walk = (gid) => {
      for (const g of this._state.groups || []) {
        if (g.members.includes(`group:${gid}`) && !out.has(g.id)) {
          out.add(g.id);
          walk(g.id);
        }
      }
    };
    if (id) walk(id);
    return [...out];
  }

  _newGroup(entities) {
    const link = entities.length ? this._groupLink(entities) : null;
    this._state.groupDraft = { id: null, name: link?.name || "", area_id: this._targetInfo(entities[0])?.area_id || null, members: [...entities] };
    this._openTarget("grp:new");
  }

  async _saveGroup(group, message) {
    try {
      const r = await this._ws("groups/save", { group: { id: group.id || undefined, name: group.name, area_id: group.area_id || null, members: group.members } });
      await this._reload();
      this._state.selTarget = `grp:${r.group.id}`;
      this._state.groupDraft = null;
      if (r.group.adopted?.length) {
        const other = r.group.adopted.filter((n) => n !== r.group.name);
        message = `${message || "Gespeichert."} Taster, die genau diese Geräte geschaltet haben, schalten jetzt die Gruppe${other.length ? ` (${other.map((n) => `„${n}“`).join(", ")})` : ""}.`;
      }
      if (message) this._flash(message);
      else this._render();
    } catch (err) {
      this._flash(`Speichern fehlgeschlagen: ${err.message}`, true);
    }
  }

  _groupAddMember(member) {
    const g = this._groupEditing();
    if (g.members.includes(member)) return this._render();
    if (!g.id) {
      g.members.push(member);
      if (!g.area_id && !member.startsWith("group:")) g.area_id = this._targetInfo(member)?.area_id || null;
      this._render();
      return;
    }
    this._saveGroup({ ...g, members: [...g.members, member] });
  }

  _groupRemoveMember(member) {
    const g = this._groupEditing();
    if (!g.id) {
      g.members = g.members.filter((m) => m !== member);
      this._render();
      return;
    }
    if (g.members.length === 1) return this._flash("Eine Gruppe braucht mindestens ein Gerät. Lösche sie stattdessen.", true);
    this._saveGroup({ ...g, members: g.members.filter((m) => m !== member) });
  }

  _createGroup() {
    const g = this._state.groupDraft;
    if (!g.name.trim()) return this._flash("Gib der Gruppe einen Namen.", true);
    if (!g.members.length) return this._flash("Füge mindestens ein Gerät hinzu.", true);
    this._saveGroup(g, `Lichtgruppe „${g.name}“ angelegt.`);
  }

  _renameGroup(id) {
    const g = this._group(id);
    const name = prompt("Neuer Name der Lichtgruppe:", g.name);
    if (!name || !name.trim() || name.trim() === g.name) return;
    this._saveGroup({ ...g, name: name.trim().slice(0, 80) }, "Umbenannt.");
  }

  async _deleteGroup(id) {
    const g = this._group(id);
    let text = `Lichtgruppe „${g.name}“ löschen? Die Lampen selbst bleiben unverändert.`;
    if (g.used_by.length) text += `\n\nSie wird benutzt von: ${g.used_by.join(", ")}. Dort fällt sie als Ziel weg.`;
    if (g.parents.length) text += `\n\nSie steckt in: ${g.parents.join(", ")}.`;
    if (!confirm(text)) return;
    try {
      await this._ws("groups/delete", { group_id: id });
      await this._reload();
      this._state.selTarget = null;
      this._flash("Gruppe gelöscht.");
    } catch (err) {
      this._flash(`Löschen fehlgeschlagen: ${err.message}`, true);
    }
  }

  _renderGroup(id) {
    const s = this._state;
    const isNew = id === "new";
    const g = isNew ? s.groupDraft : this._group(id);
    if (!g) return this._renderTargetIntro();
    const members = g.members;
    const entities = isNew ? members.flatMap((m) => (m.startsWith("group:") ? this._group(m.slice(6))?.entities || [] : [m])) : g.entities;
    const area = g.area_id || this._targetInfo(entities[0])?.area_id || null;
    const memberChips = members
      .map((m) => {
        const isGrp = m.startsWith("group:");
        const label = isGrp ? `<span class="gico" aria-hidden="true">▦</span>${esc(this._group(m.slice(6))?.name || "?")}` : `${esc(this._entityName(m))} <b>${esc(this._stateText(m))}</b>`;
        const open = isGrp ? `data-action="open-group" data-value="${esc(m.slice(6))}"` : `data-action="open-target" data-value="=${esc(m)}"`;
        return `<span class="evx"><button class="ev ${isGrp ? "grp" : ""}" ${open}>${label}</button><button class="x" data-action="chip-remove" data-scope="group" data-kind="member" data-value="${esc(m)}" aria-label="aus der Gruppe nehmen" title="aus der Gruppe nehmen">×</button></span>`;
      })
      .join("");
    const head = isNew
      ? `<label class="title-wrap"><span class="lbl">Name der Lichtgruppe</span><input class="title" data-scope="groupdraft" data-bind="name" value="${esc(g.name)}" placeholder="z. B. Kellerlicht 1"></label>`
      : `<div class="pane-title"><h2><span class="gico big" aria-hidden="true">▦</span>${esc(g.name)}<button class="icon" data-action="group-rename" data-value="${esc(id)}" aria-label="Gruppe umbenennen" title="Umbenennen">✎</button></h2>
          <p class="sub">${esc(`Lichtgruppe · ${entities.length} Geräte · ${g.on ? `${g.on} an` : "alle aus"} · ${this._areaName(area)}`)}</p></div>`;
    let rest = "";
    if (!isNew) {
      const ancestors = this._groupAncestors(id);
      const bySource = new Map();
      for (const link of s.links) {
        for (const binding of link.bindings || []) {
          const gids = this._bindingTargets(link, binding).group_id || [];
          const via = gids.includes(id) ? null : ancestors.find((a) => gids.includes(a));
          if (!gids.includes(id) && !via) continue;
          for (const src of link.sources) {
            if (src.adapter === "occupancy") continue;
            const key = keyOf(src);
            if (binding.source && binding.source !== key) continue;
            if (!this._reachable(key, binding.button ?? src.button ?? null, binding.event)) continue;
            if (!bySource.has(key)) bySource.set(key, []);
            const sig = `${binding.button ?? src.button ?? ""}|${binding.event}|${this._bindingSig(link, binding)}`;
            if (bySource.get(key).some((x) => x.sig === sig)) continue;
            bySource.get(key).push({ link, binding, button: binding.button ?? src.button ?? null, via, sig });
          }
        }
      }
      const who = [...bySource.entries()]
        .map(([key, items]) => {
          const layout = this._layout(key);
          return `<div class="who">${this._deviceSvg(layout, { size: 44, interactive: false })}<div class="who-text">
            <button class="link strong" data-action="open-source" data-value="${esc(key)}">${esc(this._keyName(key))}</button>
            <div class="evs">${items
              .map(
                ({ link, binding, button, via }) =>
                  `<button class="ev" data-action="slot-edit" data-value="${esc(link.id)}" data-binding="${esc(binding.id)}" data-key="${esc(key)}">${esc(this._chipLabel(layout, button, binding.event))} <b>${esc(ACTION_LABEL[binding.action])}</b>${via ? ` <small>über ${esc(this._group(via)?.name || "")}</small>` : ""}</button>`
              )
              .join("")}</div></div></div>`;
        })
        .join("");
      const motion = s.links.filter((l) => l.profile === "motion" && (l.targets.group_id || []).includes(id));
      rest = `
        ${g.parents.length ? `<p class="hint">Steckt in: ${ancestors.filter((a) => this._group(a)?.members.includes(`group:${id}`)).map((a) => `<button class="link" data-action="open-group" data-value="${esc(a)}">${esc(this._group(a).name)}</button>`).join(", ")}</p>` : ""}
        <h3 class="sec">Wird bedient von</h3>
        ${who || `<p class="hint">Noch kein Taster. Weise unten einen zu.</p>`}
        ${this._renderAssign(area)}
        <h3 class="sec">Automatik</h3>
        ${motion.map((link) => `<div class="who motion-card"><span class="bulb" aria-hidden="true">◎</span><div class="who-text"><b>${esc(link.name)}${this._renameBtn(link, true)}</b><span class="sub" data-motion="${esc(link.id)}">${esc(this._motionText(this._motionLive(link)))}</span></div><button class="ghost" data-action="select" data-value="${esc(link.id)}">Bearbeiten</button></div>`).join("")}
        <button class="add" data-action="new-motion" data-value="grp:${esc(id)}">+ Bewegungs- oder Präsenzmelder verknüpfen</button>
        <div class="row-end"><button class="ghost danger" data-action="group-delete" data-value="${esc(id)}">Gruppe löschen</button></div>`;
    }
    return `<section class="pane" aria-label="Lichtgruppe">
      <div class="pane-head">${this._narrow ? `<button class="icon" data-action="back" aria-label="Zurück">‹</button>` : ""}${head}</div>
      <h3 class="sec">Gehört dazu</h3>
      <div class="evs members-edit">${memberChips || `<span class="hint">Noch leer.</span>`}</div>
      ${this._comboHtml("grp-member", "Lampe, Steckdose oder Lichtgruppe hinzufügen …")}
      <p class="hint">Eine Lichtgruppe darf andere Gruppen enthalten (z. B. „Kellerlicht gesamt“ = Kellerlicht 1 + 2). Änderst du die Mitglieder, gilt das sofort für alle Taster, die die Gruppe schalten.</p>
      ${isNew ? `<div class="row-end"><button class="ghost" data-action="view" data-value="geraete">Abbrechen</button><button class="primary" data-action="group-create">Anlegen</button></div>` : rest}
    </section>`;
  }

  // ---------------------------------------------------------- tidy up

  /** What a binding does – equal signatures are shown once. */
  _bindingSig(link, binding) {
    const t = this._bindingTargets(link, binding);
    const extra = {};
    for (const k of ["brightness_pct", "color_temp_kelvin", "kelvin_list", "color_list", "scene"]) if (binding[k] != null) extra[k] = binding[k];
    if (RAMP_ACTIONS.has(binding.action)) extra.ramp = binding.ramp;
    return JSON.stringify([binding.action, [...(t.entity_id || [])].sort(), [...(t.area_id || [])].sort(), extra]);
  }

  _dupCount() {
    // number of bindings "Bereinigen" removes: of n identical ones, n - 1
    const total = this._state.links.reduce((n, l) => n + Object.values(l.status?.duplicates || {}).reduce((m, c) => m + (c - 1) / c, 0), 0);
    return Math.round(total);
  }

  async _dedupe() {
    try {
      const r = await this._ws("links/dedupe");
      await this._reload();
      this._flash(`${r.removed} doppelte Belegungen entfernt${r.deleted.length ? `, ${r.deleted.length} leere Verknüpfungen gelöscht` : ""}.`);
    } catch (err) {
      this._flash(`Bereinigen fehlgeschlagen: ${err.message}`, true);
    }
  }

  async _unbindTarget(linkId, bindingId, entityId) {
    const link = this._state.links.find((l) => l.id === linkId);
    const binding = link?.bindings.find((b) => b.id === bindingId);
    if (!binding) return;
    if (!confirm(`${this._entityName(entityId)} aus dieser Belegung von „${link.name}“ lösen? Die anderen Geräte bleiben belegt.`)) return;
    try {
      const payload = this._linkPayload(link);
      const b = payload.bindings.find((x) => x.id === bindingId);
      const t = clone(this._bindingTargets(link, binding));
      t.entity_id = t.entity_id.filter((e) => e !== entityId);
      b.targets = t;
      if (payload.profile !== "motion") payload.profile = "custom";
      await this._ws("links/update", { link_id: link.id, link: payload, updated_at: link.updated_at });
      await this._reload();
      this._flash(`${this._entityName(entityId)} gelöst.`);
    } catch (err) {
      this._flash(`Lösen fehlgeschlagen: ${err.message}`, true);
    }
  }

  async _renameSource(key) {
    const info = this._catalog(key);
    const name = prompt(`Lesbarer Name für diesen Taster (leer lassen = „${this._deviceName(key)}“):`, info?.alias || "");
    if (name === null) return;
    try {
      await this._ws("sources/alias", { source: key, name: name.trim() || null });
      await this._reload();
      this._flash(name.trim() ? "Taster umbenannt. Der Gerätename in Home Assistant bleibt unverändert." : "Name zurückgesetzt.");
    } catch (err) {
      this._flash(`Umbenennen fehlgeschlagen: ${err.message}`, true);
    }
  }

  _newSource() {
    this._combo = null;
    this._state.view = "taster";
    this._state.selected = null;
    this._state.draft = null;
    this._state.setup = null;
    this._state.selSource = "_new";
    this._watchSource(null);
    this._render();
    this._startLearn("find");
  }

  _renderNewSource() {
    const s = this._state;
    return `<section class="pane" aria-label="Neuen Taster einrichten">
      <div class="pane-head">${this._narrow ? `<button class="icon" data-action="back" aria-label="Zurück">‹</button>` : ""}
        <div class="pane-title"><h2>Neuen Taster einrichten</h2><p class="sub">Schritt 1 von 2: Taster finden</p></div></div>
      <div class="findbox">
        <div class="learn big ${s.learning && s.learnFor === "find" ? "live" : ""}" aria-live="polite">
          ${
            s.learning && s.learnFor === "find"
              ? `<p><span class="pulse" aria-hidden="true"></span><b>Drück jetzt eine Taste am Taster.</b></p><p class="hint">Light Linker erkennt ihn und öffnet ihn direkt. Hört 30 s lang zu.</p>`
              : `<p><b>Taste drücken</b></p><button class="learnbtn" data-action="learn" data-value="find">Zuhören starten</button>`
          }
        </div>
        <div class="or">oder</div>
        <div>
          <p><b>Taster suchen</b></p>
          ${this._comboHtml("find-source", "Name, Raum oder Modell …")}
          <p class="hint">Findet Ereignis-Entitäten (Zigbee2MQTT, Hue, Matter, Homematic), ZHA-Fernbedienungen und Eingänge.</p>
        </div>
      </div>
      <p class="hint">Danach wählst du, was der Taster schalten soll, und eine Vorlage – oder belegst einzelne Tasten.</p>
    </section>`;
  }

  async _renameLink(linkId) {
    const link = this._state.links.find((l) => l.id === linkId);
    const name = prompt("Neuer Name der Verknüpfung:", link.name);
    if (!name || !name.trim() || name.trim() === link.name) return;
    try {
      const payload = this._linkPayload(link);
      payload.name = name.trim().slice(0, 80);
      await this._ws("links/update", { link_id: link.id, link: payload, updated_at: link.updated_at });
      await this._reload();
      if (this._state.draft && this._state.selected === link.id) this._select(link.id);
      this._flash("Umbenannt. Der Schalter behält seine Entitäts-ID.");
    } catch (err) {
      this._flash(`Umbenennen fehlgeschlagen: ${err.message}`, true);
    }
  }

  async _removeSource(key) {
    const links = this._state.links.filter((l) => l.sources.some((s) => keyOf(s) === key));
    const gone = links.filter((l) => l.sources.every((s) => keyOf(s) === key) || l.bindings.every((b) => b.source === key || (b.source == null && l.sources.length === 1)));
    const kept = links.filter((l) => !gone.includes(l));
    let text = `„${this._keyName(key)}“ aus Light Linker entfernen?`;
    if (gone.length) text += `\n\nDiese Verknüpfungen werden gelöscht (mit ihrem Schalter „aktiv“):\n– ${gone.map((l) => l.name).join("\n– ")}`;
    if (kept.length) text += `\n\nIn diesen bleibt nur der Taster weg:\n– ${kept.map((l) => l.name).join("\n– ")}`;
    text += "\n\nAlte Automationen, die diese Schalter als Bedingung nutzen, laufen danach wieder selbst.";
    if (!confirm(text)) return;
    try {
      await this._ws("sources/remove", { source: key });
      await this._reload();
      this._state.selSource = null;
      this._watchSource(null);
      this._flash("Taster entfernt.");
    } catch (err) {
      this._flash(`Entfernen fehlgeschlagen: ${err.message}`, true);
    }
  }

  // ---------------------------------------------------------- quick setup

  _newSetup(key) {
    const info = this._catalog(key);
    const lib = info?.layout;
    const onOff = lib?.buttons?.some((b) => b.slots.some((s) => s.event === "on"));
    // remotes with several keys: the template goes to one key, the first one still free
    const keys = this._setupKeys(key);
    const free = keys.find((k) => !this._deviceBindings(key).some((x) => x.button === k.button));
    return {
      key,
      profile: key.startsWith("state_input:") ? "switch" : onOff ? "rocker" : "toggle",
      targets: EMPTY_TARGETS(),
      name: "",
      button: keys.length > 1 ? (free || keys[0]).button : null,
    };
  }

  /** Keys of a remote a template can be put on alone ([] = the remote counts as one). */
  _setupKeys(key) {
    const layout = this._catalog(key)?.layout;
    if (!layout) return [];
    const keys = [];
    for (const b of layout.buttons) {
      if (!b.w || !b.h) continue; // "both", "weitere"
      const press = b.slots.find((x) => x.button != null && x.event === "press");
      if (press) keys.push({ id: b.id, button: press.button, label: this._buttonLabel(layout, b.id) });
    }
    return keys;
  }

  async _runSetup() {
    const st = this._state.setup;
    if (!hasTargets(st.targets)) return this._flash("Wähle zuerst, was geschaltet werden soll.", true);
    const [adapter, ident] = [st.key.split(":")[0], st.key.slice(st.key.indexOf(":") + 1)];
    const name = st.name.trim() || this._targetsText(st.targets).slice(0, 80);
    try {
      await this._ws("links/create", {
        link: {
          name,
          profile: st.profile,
          sources: [{ adapter, entity_id: adapter === "zha" ? null : ident, device_ieee: adapter === "zha" ? ident : null, button: st.button ?? null, mode: st.profile === "switch" ? "switch" : "button" }],
          targets: st.targets,
          options: {},
        },
      });
      await this._reload();
      this._state.setup = null;
      this._flash("Eingerichtet. Jede Zeile lässt sich jetzt einzeln ändern.");
    } catch (err) {
      this._flash(`Einrichten fehlgeschlagen: ${err.message}`, true);
    }
  }

  // ---------------------------------------------------------- binding dialog

  /** Open the dialog: existing binding, free slot of a device, or (slot=null) choose a slot. */
  _openDialog({ key, slot = null, linkId = null, bindingId = null, targets = null, inheritFrom = null }) {
    this._stopLearn();
    this._combo = null;
    const layout = this._layout(key);
    let b;
    let belong;
    if (inheritFrom) {
      // a row that only shows the "all buttons" binding: changes apply to this button alone
      const link = this._state.links.find((l) => l.id === inheritFrom.linkId);
      const binding = link.bindings.find((x) => x.id === inheritFrom.bindingId);
      b = clone(binding);
      b.id = null;
      b.button = slot.button;
      b.targets = { ...EMPTY_TARGETS(), ...clone(this._bindingTargets(link, binding)) };
      b.ramp = { ...RAMP_DEFAULTS, ...(b.ramp || {}) };
      belong = link.id;
    } else if (linkId && bindingId) {
      const link = this._state.links.find((l) => l.id === linkId);
      const binding = link.bindings.find((x) => x.id === bindingId);
      b = clone(binding);
      b.targets = { ...EMPTY_TARGETS(), ...clone(this._bindingTargets(link, binding)) };
      b.ramp = { ...RAMP_DEFAULTS, ...(b.ramp || {}) };
      slot = { button: binding.button ?? link.sources.find((s) => keyOf(s) === key)?.button ?? null, event: binding.event };
      belong = linkId;
    } else {
      const event = slot?.event || "press";
      b = {
        id: null,
        source: key,
        button: slot?.button ?? null,
        event,
        action: HOLD_EVENTS.has(event) ? (event === "hold_down" ? "ramp_down" : event === "hold_up" ? "ramp_up" : "ramp_alt") : event === "off" ? "off" : event === "on" ? "on" : "toggle",
        targets: { ...EMPTY_TARGETS(), ...(targets ? clone(targets) : {}) },
        ramp: { ...RAMP_DEFAULTS },
      };
      if (layout.hold_end === "none") b.ramp.no_release = "step";
      belong = null;
    }
    const ownLinks = this._state.links.filter((l) => l.profile !== "motion" && l.sources.some((s) => keyOf(s) === key));
    if (!belong) {
      // same targets, else the link that already uses this button, else the only one
      const sameButton = this._deviceBindings(key).find((x) => (x.button ?? null) === (slot?.button ?? null) && x.link.profile !== "motion");
      const match =
        (hasTargets(b.targets) ? ownLinks.find((l) => sameTargets(l.targets, b.targets)) : null) ||
        sameButton?.link ||
        (ownLinks.length === 1 ? ownLinks[0] : null);
      belong = match ? match.id : "new";
      if (match && !hasTargets(b.targets)) b.targets = { ...EMPTY_TARGETS(), ...clone(match.targets) };
    }
    this._state.dlg = {
      key,
      slot,
      slotFixed: Boolean(slot),
      origLink: linkId,
      origBinding: bindingId,
      inherited: Boolean(inheritFrom),
      belong,
      newName: "",
      b,
    };
    this._render();
    this.shadowRoot.querySelector(".dialog [data-focus]")?.focus();
  }

  _closeDialog() {
    this._state.dlg = null;
    this._combo = null;
    this._render();
  }

  _freeSlots(key) {
    const layout = this._layout(key);
    const result = [];
    for (const btn of layout.buttons) {
      for (const slot of btn.slots) {
        if (!this._slotBindings(key, slot).length) result.push({ ...slot, label: `${this._buttonLabel(layout, btn.id)}: ${this._slotText(layout, slot)}` });
      }
    }
    return result;
  }

  _dlgBindingPayload(dlg, link) {
    const b = clone(dlg.b);
    const out = {
      source: dlg.key,
      button: dlg.slot.button ?? null,
      event: dlg.slot.event,
      action: b.action,
      targets: link && sameTargets(link.targets, b.targets) ? null : b.targets,
      ramp: b.ramp,
    };
    if (b.id) out.id = b.id;
    if (b.action === "on" || b.action === "brightness") {
      if (b.brightness_pct) out.brightness_pct = Number(b.brightness_pct);
      if (b.action === "on" && b.color_temp_kelvin) out.color_temp_kelvin = Number(b.color_temp_kelvin);
    }
    if (b.action === "cycle_color_temp") out.kelvin_list = b.kelvin_list || LIST_DEFAULTS.cycle_color_temp.value;
    if (b.action === "cycle_color") out.color_list = b.color_list || LIST_DEFAULTS.cycle_color.value;
    if (b.action === "scene") out.scene = b.scene || null;
    return out;
  }

  _linkPayload(link) {
    const copy = clone(link);
    ["status", "id", "created_at", "updated_at"].forEach((k) => delete copy[k]);
    return copy;
  }

  async _saveDialog() {
    const dlg = this._state.dlg;
    if (!dlg.slot) return this._flash("Wähle eine Taste und ein Ereignis.", true);
    const t = dlg.b.targets;
    if (dlg.b.action !== "none" && dlg.b.action !== "scene" && !hasTargets(t))
      return this._flash("Wähle, was geschaltet werden soll.", true);
    if (dlg.b.action === "scene" && !dlg.b.scene) return this._flash("Gib eine Szene an.", true);
    const [adapter, ident] = [dlg.key.split(":")[0], dlg.key.slice(dlg.key.indexOf(":") + 1)];
    const source = { adapter, entity_id: adapter === "zha" ? null : ident, device_ieee: adapter === "zha" ? ident : null, button: null, mode: "button" };
    try {
      // moved to another link: remove it from the old one first
      if (dlg.origLink && dlg.belong !== dlg.origLink) await this._removeBinding(dlg.origLink, dlg.origBinding, false);
      if (dlg.belong === "new") {
        const name = (dlg.newName || "").trim() || `${this._targetsText(t)}`.slice(0, 80);
        const binding = this._dlgBindingPayload(dlg, null);
        binding.targets = null;
        delete binding.id;
        await this._ws("links/create", {
          link: { name, profile: "custom", sources: [source], targets: t, options: {}, bindings: [binding] },
        });
      } else {
        const link = this._state.links.find((l) => l.id === dlg.belong);
        const payload = this._linkPayload(link);
        if (!payload.sources.some((s) => keyOf(s) === dlg.key)) payload.sources.push(source);
        // a source limited to one button would hide the new slot: bindings carry their button
        for (const src of payload.sources) {
          if (keyOf(src) === dlg.key && src.button && src.button !== (dlg.slot.button ?? null)) {
            for (const x of payload.bindings || []) if ((x.source ?? dlg.key) === dlg.key && x.button == null) x.button = src.button;
            src.button = null;
          }
        }
        const binding = this._dlgBindingPayload(dlg, link);
        if (dlg.origLink !== dlg.belong) delete binding.id;
        const sameSlot = (x) =>
          (x.source ?? dlg.key) === dlg.key && (x.button ?? null) === binding.button && x.event === binding.event;
        payload.bindings = (payload.bindings || []).filter((x) => (binding.id ? x.id !== binding.id : true) && !sameSlot(x));
        // "Nichts" on a single button keeps an "all buttons" binding away from it
        if (binding.action !== "none" || dlg.inherited) payload.bindings.push(binding);
        if (payload.profile !== "motion") payload.profile = "custom";
        await this._ws("links/update", { link_id: link.id, link: payload, updated_at: link.updated_at });
      }
      await this._reload();
      this._state.dlg = null;
      this._flash("Belegung gespeichert.");
    } catch (err) {
      this._flash(err.code === "conflict" ? "Die Verknüpfung wurde zwischenzeitlich geändert. Lade das Panel neu." : `Speichern fehlgeschlagen: ${err.message}`, true);
    }
  }

  async _removeBinding(linkId, bindingId, ask = true) {
    const link = this._state.links.find((l) => l.id === linkId);
    if (!link) return;
    if (ask && !confirm("Diese Belegung entfernen? Die Taste ist danach frei.")) return;
    const payload = this._linkPayload(link);
    payload.bindings = payload.bindings.filter((b) => b.id !== bindingId);
    if (payload.profile !== "motion") payload.profile = "custom";
    await this._ws("links/update", { link_id: link.id, link: payload, updated_at: link.updated_at });
    if (ask) {
      await this._reload();
      this._state.dlg = null;
      this._flash("Belegung entfernt.");
    }
  }

  _assignFromCandidate(c) {
    // "+ Taster zuweisen" in Räume & Geräte: the pressed key opens the dialog for its slot
    const key = c.adapter === "zha" ? `zha:${c.device_ieee}` : `${c.adapter}:${c.entity_id}`;
    const kindToEvent = { press: "press", toggle: "press", double: "double", triple: "triple", hold_start: "hold", on: "on", off: "off", rising: "rise", falling: "fall" };
    let event = kindToEvent[c.kind] || "press";
    if (event === "hold" && c.raw_type === "brightness_move_up") event = "hold_up";
    if (event === "hold" && c.raw_type === "brightness_move_down") event = "hold_down";
    this._stopLearn();
    this._openDialog({ key, slot: { button: c.button ?? null, event }, targets: this._assignTargets() });
  }

  // ---------------------------------------------------------- combobox

  _comboOptions(id) {
    const s = this._state;
    if (["target", "dlg-target", "setup-target", "find-target", "grp-member"].includes(id)) {
      let chosen = EMPTY_TARGETS();
      let allowed = ["light", "switch", "cover"];
      let near = null;
      if (id === "target") {
        chosen = s.draft.targets;
        allowed = s.draft.profile === "gate" ? ["cover", "switch"] : ["light", "switch", "cover"];
        near = this._sourceArea(s.draft.sources[0]);
      } else if (id === "dlg-target") {
        chosen = s.dlg.b.targets;
        near = this._keyArea(s.dlg.key);
      } else if (id === "setup-target") {
        chosen = s.setup.targets;
        allowed = s.setup.profile === "gate" ? ["cover", "switch"] : ["light", "switch", "cover"];
        near = this._keyArea(s.setup.key);
      } else if (id === "grp-member") {
        const g = this._groupEditing();
        chosen = { entity_id: g.members.filter((m) => !m.startsWith("group:")), area_id: [], group_id: g.members.filter((m) => m.startsWith("group:")).map((m) => m.slice(6)) };
        near = g.area_id || this._targetInfo(chosen.entity_id[0])?.area_id || null;
        // a group may not contain itself or a group that contains it
        const forbidden = new Set([g.id, ...this._groupAncestors(g.id)]);
        chosen.group_id = [...chosen.group_id, ...forbidden];
      }
      const items = s.targets
        .filter((t) => allowed.includes(t.domain) && !chosen.entity_id.includes(t.entity_id))
        .map((t) => ({
          value: `entity:${t.entity_id}`,
          label: t.name,
          sub: `${t.entity_id}${t.model ? ` · ${t.model}` : ""}, ${this._areaName(t.area_id)}`,
          area: this._areaName(t.area_id),
          near: Boolean(near) && t.area_id === near,
          kind: DOMAIN_LABEL[t.domain],
        }));
      if (id !== "find-target") {
        for (const g of s.groups || []) {
          if ((chosen.group_id || []).includes(g.id)) continue;
          const area = this._areaName(this._groupArea(g));
          items.push({ value: `group:${g.id}`, label: g.name, sub: `Lichtgruppe: ${g.entities.map((e) => this._entityName(e)).join(", ")}`, area, near: Boolean(near) && this._groupArea(g) === near, kind: "Lichtgruppe", isArea: true });
        }
      }
      if (id !== "find-target" && id !== "grp-member" && !(id === "target" && s.draft.profile === "gate")) {
        for (const a of s.areas) {
          if (chosen.area_id.includes(a.area_id)) continue;
          items.push({ value: `area:${a.area_id}`, label: `Ganzer Bereich ${a.name}`, sub: "alle Lampen und Schalter im Raum", area: a.name, near: a.area_id === near, kind: "Bereich", isArea: true });
        }
      }
      return items;
    }
    // sources: devices (find-source) or buttons (link editor)
    const items = [];
    const perButton = id === "source";
    for (const src of s.sources) {
      if (!perButton && src.adapter === "occupancy") continue;
      const original = (src.device || src.name).replace(/ Action$/, "");
      const name = src.alias || original;
      const area = this._areaName(src.area_id);
      const ident = this._ident(src);
      let sub = src.adapter === "zha" ? `ZHA ${ident}, ${area}` : `${src.entity_id}, ${area}`;
      if (src.layout?.model_name) sub = `${src.layout.model_name}, ${sub}`;
      if (src.alias) sub = `${original}, ${sub}`;
      if (src.external) sub += `, auch genutzt von ${src.external}`;
      const kind = src.adapter === "zha" ? "ZHA" : src.adapter === "occupancy" ? DEVICE_CLASS_TEXT[src.device_class] || "Melder" : src.adapter === "state_input" ? "Eingang" : "Taster";
      const buttons = perButton && src.buttons.length ? src.buttons : [null];
      for (const b of buttons) {
        items.push({ value: `${src.adapter}|${ident}|${b ?? ""}`, label: b ? `${name}, Taste ${b}` : name, sub, area, kind, external: src.external });
      }
    }
    const occupancyIds = new Set(s.sources.filter((x) => x.adapter === "occupancy").map((x) => x.entity_id));
    const known = new Set(s.sources.map((x) => x.entity_id));
    for (const t of Object.keys(this._hass.states).filter((e) => (e.startsWith("binary_sensor.") || e.startsWith("input_boolean.")) && !occupancyIds.has(e) && !known.has(e))) {
      const area = this._areaName(this._targetInfo(t)?.area_id);
      items.push({ value: `state_input|${t}|`, label: this._entityName(t), sub: t, area, kind: "Eingang", late: true });
    }
    return items;
  }

  _filterCombo(id, query) {
    const tokens = fold(query).split(/\s+/).filter(Boolean);
    let items = this._comboOptions(id);
    if (!tokens.length) {
      // Without a query: everything grouped by room – the room of the button
      // first, "Ohne Raum" last, inside a room the whole-area entry first, then
      // by name. Binary inputs only appear when searched for.
      items = items.filter((i) => !i.late);
      items.sort(
        (a, b) =>
          (b.near === true) - (a.near === true) ||
          (a.area === "Ohne Raum") - (b.area === "Ohne Raum") ||
          a.area.localeCompare(b.area, "de") ||
          (b.isArea === true) - (a.isArea === true) ||
          a.label.localeCompare(b.label, "de")
      );
      return items;
    }
    const scored = [];
    for (const item of items) {
      const hay = fold(`${item.label} ${item.sub} ${item.area}`);
      if (!tokens.every((t) => hay.includes(t))) continue;
      const label = fold(item.label);
      let score = 0;
      if (label.startsWith(tokens[0])) score -= 3;
      else if (label.includes(tokens[0])) score -= 2;
      if (item.near) score -= 1;
      if (item.late) score += 2;
      scored.push([score, item]);
    }
    scored.sort((a, b) => a[0] - b[0] || a[1].label.localeCompare(b[1].label, "de"));
    return scored.slice(0, COMBO_LIMIT).map(([, item]) => item);
  }

  _comboListHtml() {
    const c = this._combo;
    if (!c.items.length) return `<li class="combo-empty">Nichts gefunden für „${esc(c.query)}“</li>`;
    const grouped = !fold(c.query).trim();
    let lastArea = null;
    return c.items
      .map((item, i) => {
        let header = "";
        if (grouped && item.area !== lastArea) {
          lastArea = item.area;
          const hint = item.near ? " (Raum des Tasters)" : "";
          header = `<li role="presentation" class="combo-group">${esc(item.area)}${hint}</li>`;
        }
        // In the grouped view the room is in the heading, the sub line keeps the entity id only.
        const sub = grouped ? item.sub.replace(`, ${item.area}`, "") : item.sub;
        return `${header}<li role="option" id="cb-${c.id}-${i}" data-combo-index="${i}" aria-selected="${i === c.active}" class="${i === c.active ? "active" : ""}${grouped ? " in-group" : ""}">
          <span class="opt-label">${esc(item.label)}</span><span class="opt-kind">${esc(item.kind)}</span>
          <span class="opt-sub">${esc(sub)}</span></li>`;
      })
      .join("");
  }

  _openCombo(id, query) {
    // Only one list at a time: moving from one search field to the other closes the first.
    if (this._combo && this._combo.id !== id) this._closeCombo();
    this._combo = { id, query, active: 0, items: this._filterCombo(id, query) };
    this._paintCombo();
  }

  _paintCombo() {
    const c = this._combo;
    if (!c) return;
    const list = this.shadowRoot.querySelector(`#cb-list-${c.id}`);
    const input = this.shadowRoot.querySelector(`[data-combo-input="${c.id}"]`);
    if (!list || !input) return;
    list.innerHTML = this._comboListHtml();
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    input.setAttribute("aria-activedescendant", c.items.length ? `cb-${c.id}-${c.active}` : "");
    list.querySelector("li.active")?.scrollIntoView({ block: "nearest" });
  }

  _closeCombo() {
    const c = this._combo;
    if (!c) return;
    const list = this.shadowRoot.querySelector(`#cb-list-${c.id}`);
    const input = this.shadowRoot.querySelector(`[data-combo-input="${c.id}"]`);
    if (list) list.hidden = true;
    input?.setAttribute("aria-expanded", "false");
    this._combo = null;
  }

  _pickCombo(item) {
    const id = this._combo.id;
    const s = this._state;
    const addTarget = (targets) => {
      if (item.value.startsWith("group:")) {
        targets.group_id = targets.group_id || [];
        if (!targets.group_id.includes(item.value.slice(6))) targets.group_id.push(item.value.slice(6));
      } else if (item.value.startsWith("area:")) {
        const areaId = item.value.slice(5);
        if (!targets.area_id.includes(areaId)) targets.area_id.push(areaId);
      } else {
        const entityId = item.value.slice(7);
        if (!targets.entity_id.includes(entityId)) targets.entity_id.push(entityId);
      }
    };
    let keepOpen = true;
    if (id === "target") addTarget(s.draft.targets);
    else if (id === "dlg-target") addTarget(s.dlg.b.targets);
    else if (id === "setup-target") addTarget(s.setup.targets);
    else if (id === "grp-member") {
      this._combo = null;
      this._groupAddMember(item.value.startsWith("group:") ? item.value : item.value.slice(7));
      return;
    }
    else if (id === "find-target") {
      this._combo = null;
      this._openTarget(item.value.slice(7));
      return;
    } else if (id === "assign-source") {
      const [adapter, ident] = item.value.split("|");
      this._combo = null;
      this._openDialog({ key: adapter === "zha" ? `zha:${ident}` : `${adapter}:${ident}`, slot: null, targets: this._assignTargets() });
      return;
    } else if (id === "find-source") {
      if (item.external && !confirm(`Dieser Taster wird auch von „${item.external}“ genutzt. Trotzdem öffnen?`)) return;
      const [adapter, ident] = item.value.split("|");
      this._combo = null;
      this._openSource(adapter === "zha" ? `zha:${ident}` : `${adapter}:${ident}`);
      return;
    } else {
      if (item.external && !confirm(`Diese Taste wird auch von „${item.external}“ genutzt. Trotzdem verknüpfen?`)) return;
      const [adapter, ident, button] = item.value.split("|");
      this._addSource(
        { adapter, entity_id: adapter === "zha" ? null : ident, device_ieee: adapter === "zha" ? ident : null, button: button || null },
        adapter === "state_input" ? "switch" : null,
        item.area
      );
      keepOpen = false;
    }
    this._combo = null;
    this._render();
    // Keep the field ready for the next pick.
    const input = this.shadowRoot.querySelector(`[data-combo-input="${id}"]`);
    if (input && keepOpen) {
      input.focus();
      this._openCombo(id, "");
    }
  }

  _onFocusIn(ev) {
    const id = ev.target.dataset?.comboInput;
    if (id && (!this._combo || this._combo.id !== id)) this._openCombo(id, ev.target.value);
  }

  _onFocusOut(ev) {
    const id = ev.target.dataset?.comboInput;
    if (!id) return;
    // Let a click on an option land first.
    setTimeout(() => {
      // The panel may have re-rendered meanwhile: compare with the live input.
      const live = this.shadowRoot.querySelector(`[data-combo-input="${id}"]`);
      if (this._combo?.id === id && this.shadowRoot.activeElement !== live) this._closeCombo();
    }, 150);
  }

  _onMousedown(ev) {
    const li = ev.target.closest("[data-combo-index]");
    if (!li || !this._combo) return;
    ev.preventDefault(); // keep focus in the input
    this._pickCombo(this._combo.items[Number(li.dataset.comboIndex)]);
  }

  _onKeydown(ev) {
    if (ev.key === "Escape" && this._state.dlg && !this._combo) {
      ev.preventDefault();
      this._closeDialog();
      return;
    }
    const btn = ev.target.closest?.("[data-btn-key]");
    if (btn && (ev.key === "Enter" || ev.key === " ")) {
      ev.preventDefault();
      btn.dispatchEvent(new MouseEvent("click", { bubbles: true, composed: true }));
      return;
    }
    const id = ev.target.dataset?.comboInput;
    if (!id) return;
    if (!this._combo) {
      if (ev.key === "ArrowDown") this._openCombo(id, ev.target.value);
      return;
    }
    const c = this._combo;
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      if (!c.items.length) return;
      c.active = (c.active + (ev.key === "ArrowDown" ? 1 : -1) + c.items.length) % c.items.length;
      this._paintCombo();
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      if (c.items[c.active]) this._pickCombo(c.items[c.active]);
    } else if (ev.key === "Escape") {
      ev.preventDefault();
      ev.stopPropagation();
      ev.target.value = "";
      this._closeCombo();
    }
  }

  _comboHtml(id, placeholder) {
    return `<div class="combo">
      <input type="text" role="combobox" autocomplete="off" spellcheck="false"
        aria-autocomplete="list" aria-expanded="false" aria-controls="cb-list-${id}"
        aria-label="${esc(placeholder)}" placeholder="${esc(placeholder)}" data-combo-input="${id}">
      <ul role="listbox" id="cb-list-${id}" class="combo-list" hidden></ul>
    </div>`;
  }

  // ------------------------------------------------------ input binding

  _scope(el) {
    const scope = el.dataset.scope;
    if (scope === "dlg") return this._state.dlg;
    if (scope === "setup") return this._state.setup;
    if (scope === "groupdraft") return this._state.groupDraft;
    return this._state.draft;
  }

  _onInputEvent(ev) {
    const el = ev.target;
    if (el.dataset.comboInput) {
      this._openCombo(el.dataset.comboInput, el.value);
      return;
    }
    if (el.dataset.cycle) {
      const list = this._cycleList();
      const i = Number(el.dataset.index);
      if (el.type === "color") list[i] = { rgb: fromHex(el.value), name: "" };
      else {
        list[i] = Number(el.value);
        const label = this.shadowRoot.querySelector(`[data-cval="${i}"]`);
        if (label) label.textContent = `${el.value} K`;
        const sw = el.previousElementSibling;
        if (sw) sw.style.background = toHex(kelvinRgb(Number(el.value)));
      }
      return;
    }
    if (el.dataset.bind && el.dataset.rerender === undefined) this._onInput(ev);
  }

  _onInput(ev) {
    const el = ev.target;
    const path = el.dataset.bind;
    const base = this._scope(el);
    if (!path || !base) return;
    let value = el.type === "checkbox" ? el.checked : el.value;
    if (el.dataset.type === "number") value = value === "" ? null : Number(value);
    if (el.dataset.type === "nullable") value = value === "" ? null : value;
    if (el.dataset.type === "minutes") value = value === "" ? null : Math.round(Number(value) * 60);
    const keys = path.split(".");
    let obj = base;
    keys.slice(0, -1).forEach((k) => {
      obj = obj[k];
    });
    obj[keys.at(-1)] = value;
    if (el.dataset.rerender !== undefined) this._render();
  }

  _onClick(ev) {
    const el = ev.target.closest("[data-action]");
    if (!el) return;
    const { action, value, index } = el.dataset;
    const s = this._state;
    const d = s.draft;
    switch (action) {
      case "menu":
        this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
        break;
      case "view":
        this._go(value);
        break;
      case "open-source":
        this._openSource(value);
        break;
      case "open-target":
        this._openTarget(value);
        break;
      case "netz-area":
        s.netzArea = value;
        this._render();
        break;
      case "pick-button":
        s.focusButton = s.focusButton === value ? null : value;
        this._render();
        break;
      case "back":
        this._stopLearn();
        if (s.draft) {
          s.selected = null;
          s.draft = null;
        } else if (s.view === "taster") s.selSource = null;
        else if (s.view === "geraete") s.selTarget = null;
        this._render();
        break;
      case "select":
        this._select(value);
        break;
      case "new-motion":
        this._select("new", {
          profile: "motion",
          targets: value?.startsWith("grp:") ? { ...EMPTY_TARGETS(), group_id: [value.slice(4)] } : { ...EMPTY_TARGETS(), entity_id: value ? value.split("|") : [] },
        });
        break;
      case "close-editor":
        this._closeEditor();
        break;
      case "enable":
        this._toggleEnabled(s.links.find((l) => l.id === value));
        break;
      case "learn":
        s.learning ? (this._stopLearn(), this._render()) : this._startLearn(value || "source");
        break;
      case "candidate": {
        const c = s.candidates[Number(index)];
        if (s.learnFor === "find") {
          this._stopLearn();
          this._openSource(c.adapter === "zha" ? `zha:${c.device_ieee}` : `${c.adapter}:${c.entity_id}`);
        } else {
          this._addSource(c, c.suggested_profile, c.area);
          this._render();
        }
        break;
      }
      case "remove-source":
        d.sources.splice(Number(index), 1);
        this._render();
        break;
      case "remove-target":
        d.targets.entity_id = d.targets.entity_id.filter((e) => e !== value);
        this._render();
        break;
      case "remove-area":
        d.targets.area_id = d.targets.area_id.filter((a) => a !== value);
        this._render();
        break;
      case "profile":
        d.profile = value;
        this._render();
        break;
      case "save":
        this._save();
        break;
      case "delete":
        this._delete();
        break;
      case "test":
        this._testLink(value);
        break;
      // ---- device page and dialog
      case "slot-new": {
        const [button, event] = [el.dataset.button || null, el.dataset.event];
        this._openDialog({ key: value, slot: { button, event } });
        break;
      }
      case "slot-edit":
        this._openDialog({ key: el.dataset.key, linkId: value, bindingId: el.dataset.binding });
        break;
      case "slot-override":
        this._openDialog({
          key: value,
          slot: { button: el.dataset.button || null, event: el.dataset.event },
          inheritFrom: { linkId: el.dataset.link, bindingId: el.dataset.binding },
        });
        break;
      case "slot-test":
        this._testBinding(value, el.dataset.binding);
        break;
      case "assign":
        this._openDialog({ key: value, slot: el.dataset.event ? { button: el.dataset.button || null, event: el.dataset.event } : null, targets: this._assignTargets() });
        break;
      case "assign-learn":
        s.learning ? (this._stopLearn(), this._render()) : this._startLearn("assign");
        break;
      case "netz-add":
        this._openDialog({
          key: value,
          slot: null,
          targets: el.dataset.target.startsWith("grp:") ? { ...EMPTY_TARGETS(), group_id: [el.dataset.target.slice(4)] } : { ...EMPTY_TARGETS(), entity_id: el.dataset.target.split("|") },
        });
        break;
      case "dlg-close":
        this._closeDialog();
        break;
      case "dlg-save":
        this._saveDialog();
        break;
      case "dlg-remove":
        this._removeBinding(s.dlg.origLink, s.dlg.origBinding).catch((err) => this._flash(`Entfernen fehlgeschlagen: ${err.message}`, true));
        break;
      case "dlg-test":
        this._testBinding(s.dlg.origLink, s.dlg.origBinding);
        break;
      case "dlg-action":
        s.dlg.b.action = value;
        this._render();
        break;
      case "dlg-slot": {
        const [button, event] = value.split("|");
        s.dlg.slot = { button: button || null, event };
        if (HOLD_EVENTS.has(event) && !RAMP_ACTIONS.has(s.dlg.b.action)) s.dlg.b.action = event === "hold_down" ? "ramp_down" : event === "hold_up" ? "ramp_up" : "ramp_alt";
        this._render();
        break;
      }
      case "dlg-remove-target":
        s.dlg.b.targets.entity_id = s.dlg.b.targets.entity_id.filter((e) => e !== value);
        this._render();
        break;
      case "dlg-remove-area":
        s.dlg.b.targets.area_id = s.dlg.b.targets.area_id.filter((a) => a !== value);
        this._render();
        break;
      case "setup-profile":
        s.setup.profile = value;
        this._render();
        break;
      case "chip-remove": {
        const base = el.dataset.scope === "dlg" ? s.dlg.b.targets : el.dataset.scope === "setup" ? s.setup.targets : el.dataset.scope === "group" ? null : d.targets;
        if (el.dataset.scope === "group") {
          this._groupRemoveMember(value);
          break;
        }
        const field = { entity: "entity_id", area: "area_id", group: "group_id" }[el.dataset.kind];
        base[field] = (base[field] || []).filter((x) => x !== value);
        this._render();
        break;
      }
      case "open-group":
        this._openTarget(`grp:${value}`);
        break;
      case "group-new":
        this._newGroup(value ? value.split("|") : []);
        break;
      case "group-create":
        this._createGroup();
        break;
      case "group-rename":
        this._renameGroup(value);
        break;
      case "group-delete":
        this._deleteGroup(value);
        break;
      case "setup-remove":
        s.setup.targets.entity_id = s.setup.targets.entity_id.filter((e) => e !== value);
        s.setup.targets.area_id = s.setup.targets.area_id.filter((a) => a !== value);
        this._render();
        break;
      case "setup-button":
        s.setup.button = value || null;
        this._render();
        break;
      case "setup-run":
        this._runSetup();
        break;
      case "setup-open":
        s.setup = this._newSetup(value);
        this._render();
        break;
      case "setup-cancel":
        s.setup = null;
        this._render();
        break;
      case "cycle-move": {
        const list = this._cycleList();
        const i = Number(index);
        const j = i + Number(el.dataset.dir);
        [list[i], list[j]] = [list[j], list[i]];
        this._render();
        break;
      }
      case "cycle-remove":
        this._cycleList().splice(Number(index), 1);
        this._render();
        break;
      case "cycle-add": {
        const raw = el.dataset.add;
        this._cycleList().push(raw.includes(",") ? { rgb: raw.split(",").map(Number), name: "" } : Number(raw));
        this._render();
        break;
      }
      case "migrate":
        this._migrate();
        break;
      case "dedupe":
        this._dedupe();
        break;
      case "unbind-target":
        this._unbindTarget(value, el.dataset.binding, el.dataset.entity);
        break;
      case "alias":
        this._renameSource(value);
        break;
      case "new-source":
        this._newSource();
        break;
      case "rename":
        this._renameLink(value);
        break;
      case "remove-source-all":
        this._removeSource(value);
        break;
      case "external":
        this._setExternal(value, el.dataset.note);
        break;
      default:
        break;
    }
  }

  _onDrag(ev, phase) {
    const chip = ev.target.closest?.("[data-drag]");
    if (phase === "start") {
      if (!chip || ev.target.matches("input")) return;
      this._dragging = { index: Number(chip.dataset.index) };
      ev.dataTransfer.effectAllowed = "move";
      ev.dataTransfer.setData("text/plain", "");
      chip.classList.add("dragging");
    } else if (phase === "over") {
      if (chip && this._dragging) ev.preventDefault();
    } else if (phase === "drop") {
      if (!chip || !this._dragging) return;
      ev.preventDefault();
      const list = this._cycleList();
      const [item] = list.splice(this._dragging.index, 1);
      list.splice(Number(chip.dataset.index), 0, item);
      this._dragging = null;
      this._render();
    } else {
      this._dragging = null;
      chip?.classList.remove("dragging");
    }
  }

  _onChange(ev) {
    if (ev.target.dataset.comboInput || ev.target.dataset.cycle) return;
    if (ev.target.dataset.cycleAdd !== undefined) {
      this._cycleList().push({ rgb: fromHex(ev.target.value), name: "" });
      this._render();
      return;
    }
    this._onInput(ev);
  }

  // ----------------------------------------------------------- render

  _render() {
    const s = this._state;
    const views = [
      ["taster", "Taster"],
      ["geraete", "Räume & Geräte"],
      ["netz", "Übersicht"],
    ];
    let body;
    if (!s.loaded) body = `<p class="empty">Lade Verknüpfungen …</p>`;
    else if (s.error) body = `<p class="empty err">Light Linker antwortet nicht: ${esc(s.error)}. Ist die Integration eingerichtet?</p>`;
    else if (s.view === "netz") body = `<main class="full">${s.draft ? this._renderEditor() : this._renderNetz()}</main>`;
    else {
      const detail = s.draft
        ? this._renderEditor()
        : s.view === "taster"
          ? s.selSource === "_new"
            ? this._renderNewSource()
            : s.selSource
            ? this._renderDevice(s.selSource)
            : this._renderIntro()
          : s.selTarget
            ? this._renderTarget(s.selTarget)
            : this._renderTargetIntro();
      const hasDetail = Boolean(s.draft || (s.view === "taster" ? s.selSource : s.selTarget));
      const showList = !this._narrow || !hasDetail;
      body = `<main class="${this._narrow ? "narrow" : ""}">
        ${showList ? (s.view === "taster" ? this._renderTasterList() : this._renderTargetList()) : ""}
        ${!this._narrow || hasDetail ? detail : ""}
      </main>`;
    }
    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <header>
        <div class="bar">
          ${this._narrow ? `<button class="icon menu" data-action="menu" aria-label="Menü">☰</button>` : ""}
          <h1>Light Linker</h1>
        </div>
        <nav class="tabs" aria-label="Ansicht">
          ${views.map(([id, label]) => `<button class="tab ${s.view === id ? "on" : ""}" aria-current="${s.view === id ? "page" : "false"}" data-action="view" data-value="${id}">${label}</button>`).join("")}
        </nav>
        <span class="notice-slot">${s.notice ? `<p class="notice ${s.notice.isError ? "err" : ""}" role="status">${esc(s.notice.text)}</p>` : ""}</span>
      </header>
      ${body}
      ${s.dlg ? this._renderDialog() : ""}`;
    this._paintMotion();
    this._paintPressed();
  }

  _renderIntro() {
    return `<section class="pane intro">
      <h2>Taster mit Licht verbinden</h2>
      <p>${this._state.links.length ? "Wähle links einen Taster" : "Richte deinen ersten Taster ein"}: Taste drücken oder suchen, Lampe wählen, Vorlage wählen – fertig. Danach siehst du ein Bild des Tasters und jede Taste mit allem, was sie kann (kurz, doppelt, halten), und kannst jede Zeile einzeln ändern.</p>
      <div class="row-start"><button class="primary" data-action="new-source">+ Taster einrichten</button><button class="ghost" data-action="new-motion" data-value="">+ Bewegungsmelder verknüpfen</button></div>
      <p class="hint"><b>Räume &amp; Geräte</b> zeigt dieselben Verknüpfungen von der Lampe aus; dort legst du auch Lichtgruppen an. <b>Übersicht</b> zeigt alles als Tabelle Raum für Raum.</p>
    </section>`;
  }

  _renderBanner() {
    const s = this._state;
    const moves = Object.entries(s.migrations || {});
    const count = moves.reduce((n, [, m]) => n + m.length, 0);
    if (!count) return "";
    return `<div class="banner">
      <p><b>Zigbee2MQTT:</b> ${count === 1 ? "1 Gerät ist" : `${count} Geräte sind`} jetzt in Zigbee2MQTT gekoppelt und kann umgestellt werden.</p>
      <ul>${moves
        .flatMap(([linkId, list]) => {
          const name = s.links.find((l) => l.id === linkId)?.name || linkId;
          return list.map((m) => `<li>${esc(name)}: ${esc(m.kind === "source" ? `ZHA ${m.old}` : this._entityName(m.old))} → ${esc(this._entityName(m.new))}</li>`);
        })
        .join("")}</ul>
      <button class="primary" data-action="migrate">Umstellen</button>
    </div>`;
  }

  // ---- device drawing

  _deviceSvg(layout, { size = 160, focus = null, interactive = true, key = "" } = {}) {
    const f = layout.frame || { w: 64, h: 96, r: 12 };
    const pad = 4;
    const scale = size / Math.max(f.w, f.h);
    const w = Math.round((f.w + pad * 2) * scale);
    const h = Math.round((f.h + pad * 2) * scale);
    const visible = layout.buttons.filter((b) => b.w > 0 && b.h > 0);
    const wall = f.style === "wall";
    const buttons = visible
      .map((b) => {
        const inset = wall ? 6 : 2;
        const x = pad + b.x + inset;
        const y = pad + b.y + inset;
        const bw = Math.max(1, b.w - inset * 2);
        const bh = Math.max(1, b.h - inset * 2);
        const r = b.r ?? Math.min(8, f.r);
        const on = focus === b.id;
        const fontSize = Math.min(16, bh * 0.38, bw * 0.4);
        const attrs = interactive
          ? `role="button" tabindex="0" data-action="pick-button" data-value="${esc(b.id)}" data-btn-key="${esc(key)}" aria-pressed="${on}" aria-label="${esc(this._buttonLabel(layout, b.id))}"`
          : `aria-hidden="true"`;
        return `<g class="btn ${on ? "on" : ""}" data-btn="${esc(b.id)}" ${attrs}>
          <rect x="${x}" y="${y}" width="${bw}" height="${bh}" rx="${r}" ry="${r}"></rect>
          ${b.label ? `<text x="${x + bw / 2}" y="${y + bh / 2}" font-size="${fontSize}" text-anchor="middle" dominant-baseline="central">${esc(b.label)}</text>` : ""}
        </g>`;
      })
      .join("");
    return `<svg class="device ${wall ? "wall" : ""}" ${key ? `data-key="${esc(key)}"` : ""} viewBox="0 0 ${f.w + pad * 2} ${f.h + pad * 2}" width="${w}" height="${h}" ${interactive ? `role="group" aria-label="Bild des Tasters"` : `aria-hidden="true"`}>
      <rect class="frame" x="${pad}" y="${pad}" width="${f.w}" height="${f.h}" rx="${f.r}" ry="${f.r}"></rect>
      ${buttons}
    </svg>`;
  }

  // ---- Taster view

  _renderTasterList() {
    const s = this._state;
    const keys = this._usedSourceKeys();
    const groups = new Map();
    for (const key of keys) {
      const area = this._areaName(this._keyArea(key));
      if (!groups.has(area)) groups.set(area, []);
      groups.get(area).push(key);
    }
    // lamps nobody operates yet: listed too, so every light can be found by room
    const bound = new Set([...this._boundTargets().keys()]);
    for (const g of s.groups || []) for (const e of g.entities || []) bound.add(e);
    const idle = new Map();
    for (const t of s.targets || []) {
      if (t.domain !== "light" || bound.has(t.entity_id)) continue;
      const area = this._areaName(t.area_id);
      if (!groups.has(area)) groups.set(area, []);
      if (!idle.has(area)) idle.set(area, []);
      idle.get(area).push(t.entity_id);
    }
    const sorted = [...groups.entries()].sort(([a], [b]) => (a === "Ohne Raum") - (b === "Ohne Raum") || a.localeCompare(b, "de"));
    const motion = s.links.filter((l) => l.profile === "motion");
    const learn = `<button class="add" data-action="new-source">+ Taster einrichten</button>`;
    const dups = this._dupCount();
    return `<nav class="list" aria-label="Taster">
      ${this._renderBanner()}
      ${dups ? `<div class="banner warnb"><p><b>${dups === 1 ? "1 Belegung ist" : `${dups} Belegungen sind`} doppelt angelegt.</b> Die Taste schaltet dann mehrfach.</p><button class="primary" data-action="dedupe">Bereinigen</button></div>` : ""}
      ${this._comboHtml("find-source", "Taster suchen …")}
      ${
        keys.length
          ? sorted
              .map(
                ([area, ks]) => `<h3>${esc(area)}</h3>${ks.map((k) => this._renderDeviceCard(k)).join("")}`
              )
              .join("")
          : `<p class="empty">Noch kein Taster eingerichtet.</p>`
      }
      ${learn}
      <h3>Bewegungs- und Präsenzmelder</h3>
      ${motion.map((link) => this._renderCard(link)).join("")}
      <button class="add" data-action="new-motion" data-value="">+ Bewegungsmelder verknüpfen</button>
      ${this._renderActivity()}
    </nav>`;
  }

  _renderDeviceCard(key) {
    const s = this._state;
    const layout = this._layout(key);
    const total = layout.buttons.reduce((n, b) => n + b.slots.length, 0);
    const bound = layout.buttons.reduce((n, b) => n + b.slots.filter((slot) => this._slotBindings(key, slot).length).length, 0);
    const all = this._deviceBindings(key);
    const links = [...new Set(all.map((x) => x.link))];
    const off = links.length && links.every((l) => !l.enabled);
    const bad = links.some((l) => l.status.broken || l.status.last_error);
    const warn = links.some((l) => l.status.conflicts?.length);
    const stateClass = bad ? "bad" : warn ? "warn" : off ? "off" : "ok";
    const info = this._catalog(key);
    const sel = s.selSource === key && !s.draft;
    return `<button class="dev ${sel ? "sel" : ""}" data-action="open-source" data-value="${esc(key)}">
      ${this._deviceSvg(layout, { size: 40, interactive: false })}
      <span class="dev-text">
        <span class="dev-name">${esc(this._keyName(key))}</span>
        <span class="dev-meta"><span class="dot ${stateClass}"></span>${esc(layout.model_name || (info?.adapter === "zha" ? "ZHA" : info?.adapter === "state_input" ? "Eingang" : "Taster"))} · ${total ? `${bound} von ${total} belegt` : `${all.length} Belegungen`}${off ? " · aus, Automation übernimmt" : ""}</span>
      </span>
    </button>`;
  }

  _renderDevice(key) {
    const s = this._state;
    const layout = this._layout(key);
    const info = this._catalog(key);
    const all = this._deviceBindings(key);
    const shown = new Set();
    const focus = s.focusButton;
    const links = [...new Map(all.map((x) => [x.link.id, x.link])).values()];
    for (const link of s.links) if (link.profile !== "motion" && link.sources.some((src) => keyOf(src) === key) && !links.includes(link)) links.push(link);
    const groups = layout.buttons
      .filter((btn) => btn.slots.length)
      .map((btn) => {
        const rows = btn.slots
          .map((slot) => {
            const found = this._slotBindings(key, slot);
            found.forEach((x) => shown.add(x.binding.id));
            return this._renderSlotRow(key, layout, slot, found);
          })
          .join("");
        return `<section class="slot-group ${focus && focus !== btn.id ? "dim" : ""} ${focus === btn.id ? "focus" : ""}" data-btn="${esc(btn.id)}">
          <h4>${esc(this._buttonLabel(layout, btn.id))}</h4>
          <div class="slots">${rows}</div>
        </section>`;
      })
      .join("");
    const rest = all.filter((x) => !shown.has(x.binding.id) && this._reachable(key, x.button, x.event));
    const restHtml = rest.length
      ? `<section class="slot-group"><h4>Weitere Belegungen</h4><div class="slots">${rest
          .map((x) => {
            // an "all keys" binding every drawn key has overridden
            const unused = x.button == null && layout.buttons.some((b) => b.slots.some((sl) => sl.event === x.event && sl.button != null));
            return this._renderSlotRow(key, layout, { button: x.button, event: x.event }, [{ ...x, unused }], true);
          })
          .join("")}</div></section>`
      : "";
    const external = info?.external;
    const sub = [
      layout.model_name,
      info?.adapter === "zha" ? "ZHA" : info?.adapter === "event_entity" ? "Ereignis-Entität" : info?.adapter === "state_input" ? "Eingang" : null,
      this._areaName(this._keyArea(key)),
    ].filter(Boolean);
    const holdNote =
      layout.hold_end === "none"
        ? `<p class="hint">Dieser Taster meldet beim Halten kein Loslassen. Eine Rampe macht hier einen Schritt; einstellbar in der Belegung.</p>`
        : "";
    return `<section class="pane device-page" aria-label="${esc(this._keyName(key))}">
      <div class="pane-head">
        ${this._narrow ? `<button class="icon" data-action="back" aria-label="Zurück">‹</button>` : ""}
        <div class="pane-title">
          <h2>${esc(this._keyName(key))}<button class="icon" data-action="alias" data-value="${esc(key)}" aria-label="Taster umbenennen" title="Taster umbenennen">✎</button></h2>
          <p class="sub">${esc([info?.alias ? this._deviceName(key) : null, ...sub].filter(Boolean).join(" · "))}</p>
        </div>
        <div class="head-btns">
          ${all.length ? `<button class="ghost" data-action="setup-open" data-value="${esc(key)}">Vorlage anwenden …</button>` : ""}
          ${links.length ? `<button class="ghost danger" data-action="remove-source-all" data-value="${esc(key)}">Taster entfernen</button>` : ""}
        </div>
      </div>
      ${all.some((x) => x.link.status?.duplicates?.[x.binding.id]) ? `<div class="banner warnb"><p><b>Einige Belegungen dieses Tasters sind mehrfach angelegt.</b> Jede Zeile wird nur einmal gezeigt, schaltet aber mehrfach.</p><button class="primary" data-action="dedupe">Bereinigen</button></div>` : ""}
      ${
        external
          ? `<p class="ext">Auch genutzt von ${esc(external)} <button class="link" data-action="external" data-value="${esc(key)}" data-note="">Markierung entfernen</button></p>`
          : `<button class="link small" data-action="external" data-value="${esc(key)}" data-note="?">Wird auch anderswo genutzt (Node-RED, Automation)?</button>`
      }
      ${s.setup && s.setup.key === key ? this._renderSetup() : ""}
      <div class="device-body">
        <figure class="device-fig">
          ${this._deviceSvg(layout, { size: 190, focus, key })}
          <figcaption>Taste im Bild antippen hebt ihre Zeilen hervor. Drückst du den echten Taster, leuchtet die Zeile kurz auf.</figcaption>
        </figure>
        <div class="slot-list">${groups}${restHtml}${holdNote}</div>
      </div>
      ${
        links.length
          ? `<h3 class="sec">Verknüpfungen dieses Tasters</h3>
             <p class="hint">Eine Verknüpfung fasst Belegungen zusammen: Name, Schalter „aktiv“ (Fallback für alte Automationen) und Dashboard-Taste.</p>
             <div class="link-rows">${links.map((l) => this._renderLinkRow(l, key)).join("")}</div>`
          : ""
      }
    </section>`;
  }

  _renderLinkRow(link, key) {
    const n = (link.bindings || []).filter((b) => (b.source == null || b.source === key) && this._reachable(key, b.button ?? link.sources.find((x) => keyOf(x) === key)?.button ?? null, b.event)).length;
    let stateClass = link.enabled ? "ok" : "off";
    let stateText = link.enabled ? "aktiv" : "aus, Automation übernimmt";
    if (link.status.last_error) [stateClass, stateText] = ["bad", "letzter Befehl fehlgeschlagen"];
    if (link.status.broken) [stateClass, stateText] = ["bad", "Entität fehlt"];
    return `<div class="lrow">
      <div class="lrow-text">
        <span class="lrow-name">${esc(link.name)}${link.dashboard_button ? ` <span class="badge">Dashboard</span>` : ""}</span>
        <span class="dev-meta"><span class="dot ${stateClass}"></span>${n === 1 ? "1 Belegung" : `${n} Belegungen`} · ${esc(stateText)}${link.status.switch_entity ? ` · <code>${esc(link.status.switch_entity)}</code>` : ""}</span>
      </div>
      <button class="icon" data-action="rename" data-value="${esc(link.id)}" aria-label="${esc(link.name)} umbenennen" title="Umbenennen">✎</button>
      <button class="icon" data-action="select" data-value="${esc(link.id)}" aria-label="${esc(link.name)} Einstellungen" title="Einstellungen">⚙</button>
      <label class="switch" title="Verknüpfung aktiv">
        <input type="checkbox" ${link.enabled ? "checked" : ""} data-action="enable" data-value="${esc(link.id)}" aria-label="${esc(link.name)} aktiv">
        <span></span>
      </label>
    </div>`;
  }

  _renderSlotRow(key, layout, slot, found, extra = false) {
    const slotId = `${slot.button ?? ""}:${slot.event}`;
    const label = extra ? `${slot.button ? `Taste ${slot.button}, ` : "alle Tasten, "}${KIND_TEXT[slot.event] || slot.event}` : this._slotText(layout, slot);
    const head = `<div class="slot-ev"><span class="slot-name">${esc(label)}</span><code class="raw">${esc(this._slotRaw(layout, slot))}</code></div>`;
    if (!found.length) {
      return `<button class="slot free" data-slot="${esc(slotId)}" data-action="slot-new" data-value="${esc(key)}" data-button="${esc(slot.button ?? "")}" data-event="${esc(slot.event)}">
        ${head}<span class="slot-arrow" aria-hidden="true">+</span><span class="slot-free">frei – belegen</span>
      </button>`;
    }
    // identical bindings (same action and targets, e.g. created twice) are shown once
    const groups = new Map();
    for (const x of found) {
      const sig = this._bindingSig(x.link, x.binding);
      if (!groups.has(sig)) groups.set(sig, []);
      groups.get(sig).push(x);
    }
    const conflict = groups.size > 1;
    return [...groups.values()]
      .map((same) => {
        const { link, binding } = same[0];
        const names = [...new Set(same.map((x) => x.link.name))];
        const targets = this._bindingTargets(link, binding);
        const extraInfo = this._actionDetail(binding);
        const dup = same.length > 1;
        return `<div class="slot ${link.enabled ? "" : "off"} ${conflict || dup ? "conflict" : ""}" data-slot="${esc(slotId)}">
          ${head}
          <span class="slot-arrow" aria-hidden="true">⟶</span>
          <div class="slot-act">
            <span class="pill">${esc(ACTION_LABEL[binding.action] || binding.action)}</span>
            ${extraInfo}
            <span class="slot-tgt">${esc(this._targetsText(targets))}</span>
            <span class="slot-link">${esc([
              same[0].inherited ? "gilt für alle Tasten" : "",
              same[0].unused ? "jede Taste hat inzwischen eine eigene Belegung – kann entfernt werden" : "",
              names.join(", ") === this._targetsText(targets) ? "" : names.join(", "),
              link.enabled ? "" : "aus",
              dup ? `${same.length}× angelegt` : "",
              conflict ? "Taste schaltet zusätzlich etwas anderes" : "",
            ].filter(Boolean).join(" · "))}</span>
          </div>
          <div class="slot-btns">
            <button class="icon" data-action="slot-test" data-value="${esc(link.id)}" data-binding="${esc(binding.id)}" aria-label="Testen" title="Testen">▶</button>
            ${
              same[0].inherited
                ? `<button class="icon" data-action="slot-override" data-value="${esc(key)}" data-link="${esc(link.id)}" data-binding="${esc(binding.id)}" data-button="${esc(slot.button ?? "")}" data-event="${esc(slot.event)}" aria-label="Nur diese Taste ändern" title="Nur diese Taste ändern">✎</button>`
                : `<button class="icon" data-action="slot-edit" data-value="${esc(link.id)}" data-binding="${esc(binding.id)}" data-key="${esc(key)}" aria-label="Bearbeiten" title="Bearbeiten">✎</button>`
            }
          </div>
        </div>`;
      })
      .join("");
  }

  _actionDetail(binding) {
    if (binding.action === "cycle_color_temp")
      return (binding.kelvin_list || []).map((k) => `<span class="swatch sm" style="background:${toHex(kelvinRgb(k))}" title="${k} K"></span>`).join("");
    if (binding.action === "cycle_color")
      return (binding.color_list || []).map((c) => `<span class="swatch sm" style="background:${toHex(c.rgb)}"></span>`).join("");
    if (RAMP_ACTIONS.has(binding.action)) {
      const r = { ...RAMP_DEFAULTS, ...(binding.ramp || {}) };
      const mode = { auto: "", native: "Zigbee direkt, ", transition: "Übergang, ", steps: "Schritte, " }[r.mode];
      return `<span class="slot-note">${esc(`${mode}${r.duration_s} s, ${r.min_pct}–${r.max_pct} %`)}</span>`;
    }
    if ((binding.action === "on" || binding.action === "brightness") && binding.brightness_pct) return `<span class="slot-note">${binding.brightness_pct} %</span>`;
    if (binding.action === "scene" && binding.scene) return `<span class="slot-note">${esc(this._entityName(binding.scene))}</span>`;
    return "";
  }

  _renderSetup() {
    const st = this._state.setup;
    const chips = this._chips(st.targets, "setup");
    const profiles = PROFILES.filter((p) => p.id !== "motion");
    const hasBindings = this._deviceBindings(st.key).length > 0;
    return `<div class="setup">
      <h3>${hasBindings ? "Vorlage anwenden" : "Was soll dieser Taster schalten?"}</h3>
      <div class="setup-grid">
        <div>
          <span class="lbl">Ziel</span>
          <div class="chips">${chips}</div>
          ${this._comboHtml("setup-target", "Lampe, Steckdose oder Raum suchen …")}
        </div>
        ${(() => {
          const keys = this._setupKeys(st.key);
          if (keys.length < 2) return "";
          const opts = [...keys.map((k) => [k.button, k.label]), [null, "alle Tasten"]];
          return `<div>
          <span class="lbl">Für welche Taste?</span>
          <div class="seg" role="radiogroup" aria-label="Taste">
            ${opts.map(([v, label]) => `<button role="radio" aria-checked="${(st.button ?? null) === v}" class="${(st.button ?? null) === v ? "on" : ""}" data-action="setup-button" data-value="${esc(v ?? "")}">${esc(label)}</button>`).join("")}
          </div>
          <p class="hint">${st.button == null ? "Alle Tasten schalten dasselbe. Einzelne Tasten lassen sich danach trotzdem anders belegen." : "Die anderen Tasten bleiben frei für weitere Ziele."}</p>
        </div>`;
        })()}
        <div>
          <span class="lbl">Vorlage</span>
          <div class="seg" role="radiogroup" aria-label="Vorlage">
            ${profiles.map((p) => `<button role="radio" aria-checked="${st.profile === p.id}" class="${st.profile === p.id ? "on" : ""}" data-action="setup-profile" data-value="${p.id}">${p.label}</button>`).join("")}
          </div>
          <p class="hint">${esc(profiles.find((p) => p.id === st.profile)?.hint || "")}</p>
        </div>
        <label><span class="lbl">Name</span><input data-scope="setup" data-bind="name" value="${esc(st.name)}" placeholder="${esc(this._targetsText(st.targets) === "kein Ziel" ? "z. B. Esstisch" : this._targetsText(st.targets))}"></label>
      </div>
      <p class="hint">${hasBindings ? "Legt eine neue Verknüpfung mit allen Belegungen der Vorlage an. Bestehende Belegungen bleiben; doppelt belegte Tasten zeigt die Liste an." : "Die Vorlage belegt alle passenden Tasten auf einmal. Danach lässt sich jede Zeile einzeln ändern – oder du belegst direkt einzelne Zeilen unten."}</p>
      <div class="row-end">
        ${hasBindings ? `<button class="ghost" data-action="setup-cancel">Abbrechen</button>` : ""}
        <button class="primary" data-action="setup-run">Einrichten</button>
      </div>
    </div>`;
  }

  // ---- Räume & Geräte

  _boundTargets() {
    const map = new Map(); // entity -> [{link, binding|null, key}]
    for (const link of this._state.links) {
      const all = link.status?.resolved_targets || link.targets.entity_id || [];
      for (const e of all) if (!map.has(e)) map.set(e, []);
    }
    return map;
  }

  _whoOperates(entityId) {
    // [{key, items: [{link, binding, button, event}]}], plus motion links
    const bySource = new Map();
    const motion = [];
    for (const link of this._state.links) {
      if (link.profile === "motion") {
        if ((link.status?.resolved_targets || link.targets.entity_id || []).includes(entityId)) motion.push(link);
      }
      for (const binding of link.bindings || []) {
        const t = this._bindingTargets(link, binding);
        if (!this._expandTargets(t).has(entityId)) continue;
        for (const src of link.sources) {
          if (src.adapter === "occupancy") continue;
          const key = keyOf(src);
          if (binding.source && binding.source !== key) continue;
          if (!this._reachable(key, binding.button ?? src.button ?? null, binding.event)) continue;
          if (!bySource.has(key)) bySource.set(key, []);
          bySource.get(key).push({ link, binding, button: binding.button ?? src.button ?? null, event: binding.event });
        }
      }
    }
    // identical bindings (created twice) count once
    const sources = [...bySource.entries()].map(([key, items]) => {
      const seen = new Map();
      for (const x of items) {
        const k = `${x.button ?? ""}|${x.event}|${this._bindingSig(x.link, x.binding)}`;
        if (!seen.has(k)) seen.set(k, x);
      }
      return { key, items: [...seen.values()] };
    });
    return { sources, motion };
  }

  /** Same buttons, same actions, same automatics: such devices are shown as one group. */
  _operationKey(entityId) {
    const who = this._whoOperates(entityId);
    const parts = who.sources.flatMap(({ key, items }) => items.map((x) => `${key}|${x.button ?? ""}|${x.event}|${x.link.id}|${x.binding.id}`));
    parts.push(...who.motion.map((l) => `motion|${l.id}`));
    return parts.sort().join("\n");
  }

  /** Name for a group of devices: the link name if all their buttons come from one link. */
  _groupLink(entities) {
    const who = this._whoOperates(entities[0]);
    const ids = new Set([...who.sources.flatMap((x) => x.items.map((i) => i.link.id)), ...who.motion.map((l) => l.id)]);
    if (ids.size !== 1) return null;
    const link = this._state.links.find((l) => l.id === [...ids][0]);
    // a link named like the device itself adds nothing
    if (!link || (entities.length === 1 && link.name === this._entityName(entities[0]))) return null;
    // only when these devices are exactly what the link switches (else the name would mislead)
    const all = new Set(link.status?.resolved_targets || []);
    if (all.size !== entities.length || !entities.every((e) => all.has(e))) return null;
    return link;
  }

  _groupName(entities) {
    return this._groupLink(entities)?.name || null;
  }

  _renameBtn(link, small = false) {
    return link ? `<button class="icon ${small ? "sm" : ""}" data-action="rename" data-value="${esc(link.id)}" aria-label="${esc(link.name)} umbenennen" title="Verknüpfung umbenennen">✎</button>` : "";
  }

  _targetGroups() {
    const groups = new Map();
    for (const e of this._boundTargets().keys()) {
      const area = this._targetInfo(e)?.area_id ?? null;
      const op = this._operationKey(e);
      const gk = op ? `${area}\n${op}` : `single\n${e}`;
      if (!groups.has(gk)) groups.set(gk, { area, entities: [] });
      groups.get(gk).entities.push(e);
    }
    return [...groups.values()].map((g) => {
      g.entities.sort((a, b) => this._entityName(a).localeCompare(this._entityName(b), "de"));
      g.id = g.entities.join("|");
      return g;
    });
  }

  _renderTargetList() {
    const s = this._state;
    const groups = new Map();
    const explicit = new Map();
    for (const g of s.groups || []) {
      const area = this._areaName(this._groupArea(g));
      if (!explicit.has(area)) explicit.set(area, []);
      explicit.get(area).push(g);
      if (!groups.has(area)) groups.set(area, []);
    }
    for (const g of this._targetGroups()) {
      if (g.entities.length > 1 && this._groupFor(g.entities)) continue; // shown as its Lichtgruppe
      const area = this._areaName(g.area);
      if (!groups.has(area)) groups.set(area, []);
      groups.get(area).push(g);
    }
    // lamps nobody operates yet: listed too, so every light can be found by room
    const bound = new Set([...this._boundTargets().keys()]);
    for (const g of s.groups || []) for (const e of g.entities || []) bound.add(e);
    const idle = new Map();
    for (const t of s.targets || []) {
      if (t.domain !== "light" || bound.has(t.entity_id)) continue;
      const area = this._areaName(t.area_id);
      if (!groups.has(area)) groups.set(area, []);
      if (!idle.has(area)) idle.set(area, []);
      idle.get(area).push(t.entity_id);
    }
    const sorted = [...groups.entries()].sort(([a], [b]) => (a === "Ohne Raum") - (b === "Ohne Raum") || a.localeCompare(b, "de"));
    return `<nav class="list" aria-label="Geräte">
      ${this._comboHtml("find-target", "Lampe, Steckdose oder Tor suchen …")}
      <button class="add" data-action="group-new" data-value="">+ Lichtgruppe anlegen</button>
      ${sorted
        .map(
          ([area, gs]) => `<h3>${esc(area)}</h3>${(explicit.get(area) || [])
            .map(
              (g) => `<button class="dev ${s.selTarget === `grp:${g.id}` && !s.draft ? "sel" : ""}" data-action="open-group" data-value="${esc(g.id)}">
                <span class="bulb ${g.on ? "on" : ""} multi" aria-hidden="true">▦<small>${g.entities.length}</small></span>
                <span class="dev-text"><span class="dev-name">${esc(g.name)}</span>
                <span class="dev-meta">${esc(this._groupSummary(g))}</span></span>
              </button>`
            )
            .join("")}${gs
            .sort((a, b) => this._entityName(a.entities[0]).localeCompare(this._entityName(b.entities[0]), "de"))
            .map((g) => {
              const e = g.entities[0];
              const on = g.entities.some((x) => ["on", "open"].includes(this._hass.states[x]?.state));
              const who = this._whoOperates(e);
              const n = who.sources.length + who.motion.length;
              const domain = e.split(".")[0];
              const multi = g.entities.length > 1;
              const state = multi ? `${g.entities.length} Geräte, gleiche Bedienung` : this._stateText(e);
              const selected = !s.draft && (s.selTarget === g.id || (s.selTarget?.startsWith("=") && g.entities.includes(s.selTarget.slice(1))));
              return `<button class="dev ${selected ? "sel" : ""}" data-action="open-target" data-value="${esc(g.id)}">
                <span class="bulb ${on ? "on" : ""} ${multi ? "multi" : ""}" aria-hidden="true">${domain === "cover" ? "▤" : domain === "switch" ? "⏻" : "💡"}${multi ? `<small>${g.entities.length}</small>` : ""}</span>
                <span class="dev-text"><span class="dev-name">${esc(this._groupName(g.entities) || g.entities.map((x) => this._entityName(x)).join(", "))}</span>
                <span class="dev-meta">${esc(
                  this._groupName(g.entities)
                    ? `${g.entities.map((x) => this._entityName(x)).join(", ")}${multi ? " · gleiche Bedienung" : ` · ${this._stateText(e)}`}`
                    : state
                )} · ${n === 1 ? "1 Taster" : `${n} Bedienungen`}</span></span>
              </button>`;
            })
            .join("")}${(idle.get(area) || [])
            .sort((a, b) => this._entityName(a).localeCompare(this._entityName(b), "de"))
            .map((e) => {
              const selected = !s.draft && s.selTarget === `=${e}`;
              const on = this._hass.states[e]?.state === "on";
              return `<button class="dev idle ${selected ? "sel" : ""}" data-action="open-target" data-value="=${esc(e)}">
                <span class="bulb ${on ? "on" : ""}" aria-hidden="true">💡</span>
                <span class="dev-text"><span class="dev-name">${esc(this._entityName(e))}</span>
                <span class="dev-meta">${esc(this._stateText(e))} · noch kein Taster</span></span>
              </button>`;
            })
            .join("")}`
        )
        .join("")}
    </nav>`;
  }

  _stateText(entityId) {
    const st = this._hass.states[entityId];
    if (!st) return "unbekannt";
    if (st.state === "on" && st.attributes.brightness) return `an, ${Math.round((st.attributes.brightness * 100) / 255)} %`;
    return { on: "an", off: "aus", open: "offen", closed: "zu", opening: "öffnet", closing: "schließt", unavailable: "nicht erreichbar" }[st.state] || st.state;
  }

  _renderTargetIntro() {
    return `<section class="pane intro">
      <h2>Vom Licht aus denken</h2>
      <p>Wähle links eine Lampe, Steckdose oder ein Tor. Du siehst, welche Taster und Melder es bedienen, und kannst mit „+ Taster zuweisen“ eine freie Taste dazunehmen – auch einfach per Tastendruck.</p>
    </section>`;
  }

  _renderAssign(area) {
    const s = this._state;
    // devices with free slots, same room first
    const candidates = this._usedSourceKeys()
      .concat(s.sources.filter((x) => x.adapter !== "occupancy" && x.area_id === area).map((x) => x.key))
      .filter((k, i, arr) => arr.indexOf(k) === i)
      .map((k) => ({ key: k, free: this._freeSlots(k) }))
      .filter((x) => x.free.length)
      .sort((a, b) => (this._keyArea(b.key) === area) - (this._keyArea(a.key) === area) || this._keyName(a.key).localeCompare(this._keyName(b.key), "de"))
      .slice(0, 8);
    return `<div class="assign">
      <div class="assign-head">
        <b>+ Taster zuweisen</b>
        ${
          s.learning && s.learnFor === "assign"
            ? `<span class="live"><span class="pulse" aria-hidden="true"></span>Jetzt die gewünschte Taste drücken (kurz, doppelt oder halten) … <button class="link" data-action="assign-learn">abbrechen</button></span>`
            : `<button class="ghost" data-action="assign-learn">Per Tastendruck wählen</button>`
        }
      </div>
      <div class="assign-search">${this._comboHtml("assign-source", "oder Taster suchen …")}</div>
      <div class="assign-list">${candidates
        .map(({ key, free }) => {
          const layout = this._layout(key);
          const preview = free.slice(0, 4).map((f) => f.label).join(", ") + (free.length > 4 ? ` +${free.length - 4}` : "");
          return `<button class="opt" data-action="assign" data-value="${esc(key)}">
            ${this._deviceSvg(layout, { size: 36, interactive: false })}
            <span><b>${esc(this._keyName(key))}</b><small>frei: ${esc(preview)}</small></span>
            <small class="opt-area">${esc(area && this._keyArea(key) === area ? "gleicher Raum" : this._areaName(this._keyArea(key)))}</small>
          </button>`;
        })
        .join("") || `<p class="hint">Kein Taster mit freien Tasten gefunden. Lerne einen an.</p>`}</div>
    </div>`;
  }

  _renderTarget(groupId) {
    if (groupId.startsWith("grp:")) return this._renderGroup(groupId.slice(4));
    const s = this._state;
    const single = groupId.startsWith("=");
    const entities = single ? [groupId.slice(1)] : groupId.split("|");
    const entityId = entities[0];
    const group = single ? this._targetGroups().find((g) => g.entities.includes(entityId) && g.entities.length > 1) : null;
    const groupLink = this._groupLink(entities);
    const groupName = groupLink?.name || null;
    const info = this._targetInfo(entityId);
    const who = this._whoOperates(entityId);
    const area = info?.area_id || null;
    const sources = who.sources
      .map(({ key, items }) => {
        const layout = this._layout(key);
        return `<div class="who">
          ${this._deviceSvg(layout, { size: 44, interactive: false })}
          <div class="who-text">
            <button class="link strong" data-action="open-source" data-value="${esc(key)}">${esc(this._keyName(key))}</button>
            <div class="evs">${items
              .map(({ link, binding, button }) => {
                const targets = this._bindingTargets(link, binding);
                const shared = single && (targets.entity_id || []).length > 1 && (targets.entity_id || []).includes(entityId);
                return `<span class="evx"><button class="ev" data-action="slot-edit" data-value="${esc(link.id)}" data-binding="${esc(binding.id)}" data-key="${esc(key)}">${esc(this._chipLabel(layout, button, binding.event))} <b>${esc(ACTION_LABEL[binding.action])}</b></button>${
                  shared
                    ? `<button class="x" data-action="unbind-target" data-value="${esc(link.id)}" data-binding="${esc(binding.id)}" data-entity="${esc(entityId)}" aria-label="${esc(this._entityName(entityId))} aus dieser Belegung lösen" title="nur dieses Gerät aus der Belegung lösen">×</button>`
                    : ""
                }</span>`;
              })
              .join("")}</div>
          </div>
        </div>`;
      })
      .join("");
    const assign = this._renderAssign(area);
    const motion = who.motion
      .map(
        (link) => `<div class="who motion-card">
          <span class="bulb" aria-hidden="true">◎</span>
          <div class="who-text"><b>${esc(link.name)}${this._renameBtn(link, true)}</b>
            <span class="sub" data-motion="${esc(link.id)}">${esc(this._motionText(this._motionLive(link)))}</span></div>
          <button class="ghost" data-action="select" data-value="${esc(link.id)}">Bearbeiten</button>
        </div>`
      )
      .join("");
    const domain = entityId.split(".")[0];
    return `<section class="pane" aria-label="${esc(entities.map((e) => this._entityName(e)).join(", "))}">
      <div class="pane-head">
        ${this._narrow ? `<button class="icon" data-action="back" aria-label="Zurück">‹</button>` : ""}
        <div class="pane-title">
          <h2>${esc(groupName || entities.map((e) => this._entityName(e)).join(", "))}${this._renameBtn(groupLink)}</h2>
          <p class="sub">${esc(
            [
              groupName && entities.length === 1 ? this._entityName(entityId) : null,
              entities.length > 1 ? `${entities.length} Geräte mit gleicher Bedienung` : DOMAIN_LABEL[domain],
              this._areaName(area),
              entities.length > 1 ? null : this._stateText(entityId),
            ]
              .filter(Boolean)
              .join(" · ")
          )}${groupName ? ` · Name der Verknüpfung „${esc(groupName)}“` : ""}</p>
        </div>
      </div>
      ${entities.length > 1 && !single ? `<div class="row-start"><button class="ghost" data-action="group-new" data-value="${esc(entities.join("|"))}">▦ Als Lichtgruppe speichern</button></div>` : ""}
      ${
        entities.length > 1
          ? `<div class="members"><span class="lbl">Einzeln ansehen oder anders belegen:</span><div class="evs">${entities
              .map((e) => `<button class="ev" data-action="open-target" data-value="=${esc(e)}">${esc(this._entityName(e))} <b>${esc(this._stateText(e))}</b></button>`)
              .join("")}</div></div>`
          : ""
      }
      ${
        group
          ? `<p class="hint grouped">Gehört zur Gruppe <button class="link" data-action="open-target" data-value="${esc(group.id)}">${esc(this._groupName(group.entities) || group.entities.map((e) => this._entityName(e)).join(", "))}</button>. Belegst du hier einen weiteren Taster oder löst eine Belegung (×), wird das Gerät eigenständig.</p>`
          : ""
      }
      <h3 class="sec">Wird bedient von</h3>
      ${sources || `<p class="hint">Noch kein Taster.</p>`}
      ${assign}
      ${domain === "cover" ? "" : `<h3 class="sec">Automatik</h3>${motion}
        <button class="add" data-action="new-motion" data-value="${esc(entities.join("|"))}">+ Bewegungs- oder Präsenzmelder verknüpfen</button>`}
    </section>`;
  }

  // ---- Übersicht

  _netzAreas() {
    const ids = new Set();
    for (const e of this._boundTargets().keys()) ids.add(this._targetInfo(e)?.area_id ?? null);
    return [...ids]
      .map((id) => ({ area_id: id ?? "_none", name: this._areaName(id) }))
      .sort((a, b) => (a.name === "Ohne Raum") - (b.name === "Ohne Raum") || a.name.localeCompare(b.name, "de"));
  }

  _renderNetz() {
    const s = this._state;
    const areas = this._netzAreas();
    const sel = s.netzArea ?? areas[0]?.area_id ?? "_all";
    const rows = [...this._boundTargets().keys()]
      .filter((e) => sel === "_all" || (this._targetInfo(e)?.area_id ?? "_none") === sel)
      .sort((a, b) => this._entityName(a).localeCompare(this._entityName(b), "de"));
    const cols = [];
    const cell = new Map();
    for (const e of rows) {
      for (const { key, items } of this._whoOperates(e).sources) {
        if (!cols.includes(key)) cols.push(key);
        cell.set(`${e}|${key}`, items);
      }
    }
    // sources of this room without bindings to these rows stay addable
    if (sel !== "_all")
      for (const k of this._usedSourceKeys()) if ((this._keyArea(k) ?? "_none") === sel && !cols.includes(k)) cols.push(k);
    cols.sort((a, b) => this._keyName(a).localeCompare(this._keyName(b), "de"));
    // rows with exactly the same entries in every column become one row
    const rowKey = (e) => cols.map((k) => (cell.get(`${e}|${k}`) || []).map((x) => x.binding.id).sort().join(",")).join(";");
    const merged = [];
    for (const e of rows) {
      const rk = rowKey(e);
      const same = rk.replace(/[;,]/g, "") ? merged.find((m) => m.key === rk) : null;
      if (same) same.entities.push(e);
      else merged.push({ key: rk, entities: [e] });
    }
    const table = rows.length
      ? `<div class="table-wrap"><table>
          <caption>Zeilen: was geschaltet wird. Spalten: womit. „+“ legt eine Belegung an.</caption>
          <thead><tr><th scope="col">Gerät</th>${cols
            .map(
              (k) => `<th scope="col"><button class="link strong" data-action="open-source" data-value="${esc(k)}">${esc(this._keyName(k))}</button>${
                sel !== "_all" && (this._keyArea(k) ?? "_none") !== sel ? `<br><small>${esc(this._areaName(this._keyArea(k)))}</small>` : ""
              }</th>`
            )
            .join("")}</tr></thead>
          <tbody>${merged
            .map(
              ({ entities }) => {
                const e = entities[0];
                const egrp = entities.length > 1 ? this._groupFor(entities) : null;
                const glink = egrp ? null : this._groupLink(entities);
                const gname = glink?.name;
                const head = egrp
                  ? `<span class="rowname"><button class="link strong" data-action="open-group" data-value="${esc(egrp.id)}"><span class="gico" aria-hidden="true">▦</span>${esc(egrp.name)}</button></span><small>${esc(`Lichtgruppe, ${entities.length} Geräte`)}</small>`
                  : `${gname ? `<span class="rowname"><button class="link strong" data-action="open-target" data-value="${esc(entities.join("|"))}">${esc(gname)}</button>${this._renameBtn(glink, true)}</span>` : ""}${entities
                      .map((x) => `<button class="link ${gname ? "" : "strong"}" data-action="open-target" data-value="=${esc(x)}">${esc(this._entityName(x))}</button>`)
                      .join(`<span class="sep">, </span>`)}<br><small>${esc(entities.length > 1 ? `${entities.length} Geräte, gleiche Belegung` : this._stateText(e))}</small>`;
                return `<tr><th scope="row">${head}</th>${cols
                .map((k) => {
                  const items = cell.get(`${e}|${k}`) || [];
                  const layout = this._layout(k);
                  if (!items.length)
                    return `<td><button class="addcell" data-action="netz-add" data-value="${esc(k)}" data-target="${esc(entities.join("|"))}" aria-label="${esc(`${this._keyName(k)} für ${entities.map((x) => this._entityName(x)).join(", ")} belegen`)}">+</button></td>`;
                  return `<td>${items
                    .map(({ link, binding, button }) => `<button class="use" data-action="slot-edit" data-value="${esc(link.id)}" data-binding="${esc(binding.id)}" data-key="${esc(k)}">${esc(`${this._chipLabel(layout, button, binding.event)}: ${ACTION_LABEL[binding.action]}`)}</button>`)
                    .join("")}</td>`;
                })
                .join("")}</tr>`;
              }
            )
            .join("")}</tbody>
        </table></div>`
      : `<p class="empty">In diesem Raum ist noch nichts verknüpft.</p>`;
    return `<section class="netz">
      <div class="pills" role="group" aria-label="Raum">
        ${areas.map((a) => `<button class="pillbtn ${sel === a.area_id ? "on" : ""}" aria-pressed="${sel === a.area_id}" data-action="netz-area" data-value="${esc(a.area_id)}">${esc(a.name)}</button>`).join("")}
        <button class="pillbtn ${sel === "_all" ? "on" : ""}" aria-pressed="${sel === "_all"}" data-action="netz-area" data-value="_all">Alle</button>
      </div>
      ${table}
    </section>`;
  }

  // ---- shared cards

  _renderCard(link) {
    const sel = this._state.selected === link.id;
    const sensors = link.sources.filter((x) => x.adapter === "occupancy").length;
    const src = sensors ? (sensors > 1 ? `${sensors} Melder` : "Melder") : `${(link.bindings || []).length} Belegungen`;
    const tgt = (link.status.resolved_targets || []).map((e) => this._entityName(e));
    const tgtText = tgt.length > 2 ? `${tgt.slice(0, 2).join(", ")} +${tgt.length - 2}` : tgt.join(", ");
    const profile = PROFILE_LABEL[link.profile] || link.profile;
    let stateClass = link.enabled ? "ok" : "off";
    let stateText = link.enabled ? "aktiv" : "aus, Automation übernimmt";
    if (link.status.last_error) [stateClass, stateText] = ["bad", "letzter Befehl fehlgeschlagen"];
    if (link.status.conflicts?.length) [stateClass, stateText] = ["warn", "Taste doppelt belegt"];
    if (link.status.broken) [stateClass, stateText] = ["bad", "Entität fehlt"];
    return `<div class="card ${sel ? "sel" : ""}">
      <button class="card-main" data-action="select" data-value="${esc(link.id)}">
        <span class="card-name">${esc(link.name)}${link.dashboard_button ? ` <span class="badge" title="Hat eine Dashboard-Taste">Dashboard</span>` : ""}</span>
        <span class="card-wire">${esc(src)} <span class="arrow" aria-hidden="true">⟶</span> ${esc(tgtText || "keine Ziele")}</span>
        <span class="card-meta"><span class="dot ${stateClass}"></span>${
          link.profile === "motion" && link.enabled && !link.status.broken
            ? `<span data-motion="${esc(link.id)}" data-prefix="${esc(profile)}, ">${esc(profile)}, ${esc(this._motionText(this._motionLive(link)))}</span>`
            : `${esc(profile)}, ${esc(stateText)}, ${esc(timeAgo(link.status.last_triggered))}`
        }</span>
      </button>
      <label class="switch" title="Verknüpfung aktiv">
        <input type="checkbox" ${link.enabled ? "checked" : ""} data-action="enable" data-value="${esc(link.id)}" aria-label="${esc(link.name)} aktiv">
        <span></span>
      </label>
    </div>`;
  }

  _renderActivity() {
    const items = this._state.activity.slice(0, 6);
    if (!items.length) return "";
    return `<details class="activity" data-keep="activity" ${this._open?.activity ? "open" : ""}><summary>Zuletzt ausgelöst</summary><ul>
      ${items
        .map(
          (a) => `<li><b>${esc(a.link_name)}</b> ${esc(KIND_TEXT[a.kind] || a.kind)}${a.action ? ` → ${esc(ACTION_LABEL[a.action] || a.action)}` : ""}${esc(ORIGIN_TEXT[a.origin] || "")}
            <time>${new Date(a.time).toLocaleTimeString("de-DE")}</time></li>`
        )
        .join("")}
    </ul></details>`;
  }

  // ---- binding dialog

  _renderDialog() {
    const s = this._state;
    const dlg = s.dlg;
    const b = dlg.b;
    const layout = this._layout(dlg.key);
    const slotLabel = dlg.slot
      ? `${this._buttonLabel(layout, (layout.buttons.find((x) => x.slots.some((y) => (y.button ?? null) === (dlg.slot.button ?? null) && y.event === dlg.slot.event)) || {}).id || dlg.slot.button || "_any")}: ${this._slotText(layout, dlg.slot)}`
      : "Taste wählen";
    const slotPicker = dlg.slotFixed
      ? ""
      : `<div class="field"><span class="lbl">Welche Taste?</span><div class="seg wrap">${this._freeSlots(dlg.key)
          .map((f) => {
            const v = `${f.button ?? ""}|${f.event}`;
            const on = dlg.slot && `${dlg.slot.button ?? ""}|${dlg.slot.event}` === v;
            return `<button class="${on ? "on" : ""}" aria-pressed="${on}" data-action="dlg-slot" data-value="${esc(v)}">${esc(f.label)}</button>`;
          })
          .join("") || `<span class="hint">Alle Tasten sind belegt.</span>`}</div></div>`;
    const isHold = dlg.slot && HOLD_EVENTS.has(dlg.slot.event);
    // every action is always offered, whatever template the link came from
    const tile = ([id, label, hint, group]) => {
      let h = hint;
      if (group === "ramp" && dlg.slot && !isHold) h = "auf einem Klick: ein Schritt";
      return `<button class="tile ${b.action === id ? "on" : ""}" aria-pressed="${b.action === id}" data-action="dlg-action" data-value="${id}"><span>${esc(label)}</span><small>${esc(h)}</small></button>`;
    };
    const sections = [
      ["Licht & Steckdose", ["light", "ramp"]],
      ["Tor & Rollladen", ["cover"]],
      ["Sonstiges", ["other"]],
    ];
    const tiles = sections
      .map(([title, groups]) => `<div class="tile-sec">${esc(title)}</div>${ACTIONS.filter((x) => groups.includes(x[3])).map(tile).join("")}`)
      .join("");
    const resolved = this._expandTargets(b.targets);
    const hasCover = [...resolved].some((e) => e.startsWith("cover."));
    const coverWarn = ["cover_open", "cover_close", "cover_stop"].includes(b.action) && resolved.size && !hasCover
      ? `<p class="warn">Öffnen, Schließen und Stopp gehen nur an Tore und Rollläden mit Rückmeldung (cover.…). Für einen Torschalter (Relais, switch.…) nimm „Tor / Rollladen“ – das gibt einen Impuls.</p>`
      : "";
    const chips = this._chips(b.targets, "dlg");
    const ownLinks = s.links.filter((l) => l.profile !== "motion" && l.sources.some((x) => keyOf(x) === dlg.key));
    const belong = `<div class="field belong">
      <label><span class="lbl">Gehört zur Verknüpfung</span>
        <select data-scope="dlg" data-bind="belong" data-rerender>
          ${ownLinks.map((l) => `<option value="${esc(l.id)}" ${dlg.belong === l.id ? "selected" : ""}>${esc(l.name)}</option>`).join("")}
          <option value="new" ${dlg.belong === "new" ? "selected" : ""}>Neue Verknüpfung …</option>
        </select></label>
      ${dlg.belong === "new" ? `<label><span class="lbl">Name</span><input data-scope="dlg" data-bind="newName" value="${esc(dlg.newName)}" placeholder="${esc(hasTargets(b.targets) ? this._targetsText(b.targets) : "Name, z. B. Esstisch")}"></label>` : ""}
      <p class="hint">Die Verknüpfung bringt den Schalter „aktiv“ mit (Fallback für alte Automationen).</p>
    </div>`;
    return `<div class="scrim" data-action="dlg-close"></div>
    <section class="dialog" role="dialog" aria-modal="true" aria-label="Belegung bearbeiten">
      <div class="dlg-head">
        ${this._deviceSvg(layout, { size: 46, interactive: false, focus: null })}
        <div class="pane-title"><h2>${esc(slotLabel)}</h2><p class="sub">${esc(this._keyName(dlg.key))}${dlg.slot ? ` · <code>${esc(this._slotRaw(layout, dlg.slot))}</code>` : ""}</p></div>
        <button class="icon" data-action="dlg-close" aria-label="Schließen" data-focus>×</button>
      </div>
      <div class="dlg-body">
        ${dlg.inherited ? `<p class="hint grouped">Bisher galt hier die Belegung für alle Tasten. Was du jetzt wählst, gilt nur für ${esc(this._buttonLabel(layout, this._buttonOf(layout, dlg.slot)))}; die anderen Tasten bleiben, wie sie sind.</p>` : ""}
        ${slotPicker}
        <div class="field"><span class="lbl">Was soll passieren?</span><div class="tiles">${tiles}</div>${coverWarn}</div>
        ${b.action === "none" || b.action === "scene" ? "" : `<div class="field"><span class="lbl">Ziel</span><div class="chips">${chips}</div>${this._comboHtml("dlg-target", "Lampe, Steckdose, Tor oder Raum suchen …")}</div>`}
        ${this._renderActionSettings()}
        ${belong}
      </div>
      <div class="dlg-foot">
        ${dlg.origBinding ? `<button class="ghost" data-action="dlg-test">Testen</button><button class="ghost danger" data-action="dlg-remove">Entfernen</button>` : ""}
        <span class="grow"></span>
        <button class="ghost" data-action="dlg-close">Abbrechen</button>
        <button class="primary" data-action="dlg-save">Übernehmen</button>
      </div>
    </section>`;
  }

  _renderActionSettings() {
    const dlg = this._state.dlg;
    const b = dlg.b;
    const num = (path, value, attrs) => `<input type="number" data-scope="dlg" data-type="number" data-bind="b.${path}" value="${esc(value ?? "")}" ${attrs}>`;
    if (b.action === "on")
      return `<div class="field grid2">
        <label><span class="lbl">Helligkeit</span><span class="row">${num("brightness_pct", b.brightness_pct, 'min="1" max="100" placeholder="zuletzt"')} %</span></label>
        <label><span class="lbl">Farbtemperatur</span><span class="row">${num("color_temp_kelvin", b.color_temp_kelvin, 'min="1000" max="10000" step="100" placeholder="unverändert"')} K</span></label>
      </div>`;
    if (b.action === "brightness")
      return `<div class="field"><label><span class="lbl">Helligkeit</span><span class="row">${num("brightness_pct", b.brightness_pct ?? 100, 'min="1" max="100"')} %</span></label></div>`;
    if (b.action === "scene")
      return `<div class="field"><label><span class="lbl">Szene</span>
        <input list="scene-list" data-scope="dlg" data-type="nullable" data-bind="b.scene" value="${esc(b.scene || "")}" placeholder="scene.…">
        <datalist id="scene-list">${Object.keys(this._hass.states).filter((e) => e.startsWith("scene.")).map((e) => `<option value="${esc(e)}">${esc(this._entityName(e))}</option>`).join("")}</datalist></label></div>`;
    if (b.action === "cycle_color_temp" || b.action === "cycle_color") return this._renderCycle(b);
    if (RAMP_ACTIONS.has(b.action)) return this._renderRamp(b);
    return "";
  }

  _renderRamp(b) {
    const r = b.ramp;
    const layout = this._layout(this._state.dlg.key);
    const num = (path, value, attrs) => `<input type="number" data-scope="dlg" data-type="number" data-bind="b.ramp.${path}" value="${esc(value ?? "")}" ${attrs}>`;
    const sel = (path, value, options) =>
      `<select data-scope="dlg" data-bind="b.ramp.${path}" data-rerender>${options.map(([v, l]) => `<option value="${v}" ${String(value) === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
    const endHint = { release: "Dieser Taster meldet das Loslassen.", none: "Dieser Taster meldet kein Loslassen.", repeat: "Dieser Taster wiederholt „halten“, solange er gedrückt ist." }[layout.hold_end] || "";
    const isHold = this._state.dlg.slot && HOLD_EVENTS.has(this._state.dlg.slot.event);
    return `<div class="field ramp">
      <span class="lbl">Rampe</span>
      ${isHold ? "" : `<p class="hint">Auf einem Klick macht die Rampe einen Schritt von ${esc(r.step_pct)} %.</p>`}
      <div class="mgrid">
        <label><span class="lbl">Art</span><span class="row">${sel("mode", r.mode, [["auto", "Automatisch"], ["native", "Zigbee direkt"], ["transition", "Übergang"], ["steps", "Schritte"]])}</span>
          <span class="hint">${esc({ auto: "Zigbee direkt, wo die Lampe es kann, sonst Schritte", native: "ein Befehl über Zigbee2MQTT oder ZHA, am flüssigsten", transition: "Zielhelligkeit mit Übergangszeit", steps: "kleine Schritte im Takt, wie Node-RED" }[r.mode])}</span></label>
        <label><span class="lbl">Dauer von unten bis oben</span><span class="row">${num("duration_s", r.duration_s, 'min="0.5" max="30" step="0.5"')} s</span></label>
        <label><span class="lbl">Untergrenze</span><span class="row">${num("min_pct", r.min_pct, 'min="1" max="50"')} %</span></label>
        <label><span class="lbl">Obergrenze</span><span class="row">${num("max_pct", r.max_pct, 'min="10" max="100"')} %</span></label>
        <label><span class="lbl">Ist das Licht aus</span><span class="row">${sel("when_off", r.when_off, [["on_min", "einschalten und hochdimmen"], ["ignore", "nichts tun"]])}</span></label>
        <label><span class="lbl">Ende der Rampe</span><span class="row">${sel("end", r.end, [["auto", "automatisch"], ["release", "beim Loslassen"], ["repeat", "wenn „halten“ aufhört"], ["full", "bis zur Grenze"]])}</span>
          <span class="hint">${esc(endHint)}</span></label>
        ${r.end === "auto" ? `<label><span class="lbl">Meldet der Taster kein Ende</span><span class="row">${sel("no_release", r.no_release, [["step", "ein Schritt"], ["full", "bis zur Grenze"], ["none", "nichts"]])}${r.no_release === "step" ? ` ${num("step_pct", r.step_pct, 'min="1" max="100"')} %` : ""}</span></label>` : ""}
        ${r.mode === "steps" ? `<label><span class="lbl">Schritt alle</span><span class="row">${num("interval_ms", r.interval_ms, 'min="100" max="2000" step="50"')} ms</span></label>` : ""}
        <label><span class="lbl">Sicherheitsstopp nach</span><span class="row">${num("max_s", r.max_s, 'min="1" max="60"')} s</span></label>
      </div>
      <div class="ramp-preview" aria-hidden="true"><span>${esc(r.min_pct)} %</span><div style="--from:${r.min_pct}%;--to:${r.max_pct}%"></div><span>${esc(r.max_pct)} % in ${esc(r.duration_s)} s</span></div>
    </div>`;
  }

  // Colour range the selected lamps support (intersection), fallback 2000-6500 K.
  _kelvinRange() {
    let lo = 2000;
    let hi = 6500;
    let found = false;
    for (const id of this._state.dlg?.b.targets.entity_id || []) {
      const at = this._hass.states[id]?.attributes || {};
      if (at.min_color_temp_kelvin && at.max_color_temp_kelvin) {
        lo = found ? Math.max(lo, at.min_color_temp_kelvin) : at.min_color_temp_kelvin;
        hi = found ? Math.min(hi, at.max_color_temp_kelvin) : at.max_color_temp_kelvin;
        found = true;
      }
    }
    return lo < hi ? [lo, hi] : [2000, 6500];
  }

  _renderCycle(b) {
    const isTemp = b.action === "cycle_color_temp";
    const { key, value } = LIST_DEFAULTS[b.action];
    if (!b[key] || !b[key].length) b[key] = clone(value);
    const list = b[key];
    const [lo, hi] = this._kelvinRange();
    const chips = list
      .map((item, i) => {
        const rgb = isTemp ? kelvinRgb(item) : item.rgb;
        const control = isTemp
          ? `<span class="swatch" style="background:${toHex(rgb)}"></span>
             <input type="range" class="kelvin" style="--k-lo:${toHex(kelvinRgb(lo))};--k-hi:${toHex(kelvinRgb(hi))}" min="${lo}" max="${hi}" step="100" value="${esc(item)}" data-cycle="1" data-index="${i}" aria-label="Farbtemperatur ${i + 1}">
             <span class="cval" data-cval="${i}">${esc(item)} K</span>`
          : `<input type="color" value="${toHex(rgb)}" data-cycle="1" data-index="${i}" aria-label="Farbe ${i + 1}">`;
        return `<li class="cchip" draggable="true" data-drag="1" data-index="${i}">
          <span class="grip" aria-hidden="true">⋮⋮</span>${control}
          <span class="cbtns">
            <button class="icon sm" data-action="cycle-move" data-index="${i}" data-dir="-1" ${i === 0 ? "disabled" : ""} aria-label="nach vorne">‹</button>
            <button class="icon sm" data-action="cycle-move" data-index="${i}" data-dir="1" ${i === list.length - 1 ? "disabled" : ""} aria-label="nach hinten">›</button>
            <button class="icon sm" data-action="cycle-remove" data-index="${i}" ${list.length <= 1 ? "disabled" : ""} aria-label="entfernen">×</button>
          </span>
        </li>`;
      })
      .join("");
    const presets = isTemp
      ? KELVIN_PRESETS.filter(([k]) => k >= lo && k <= hi)
          .map(([k, name]) => `<button class="preset" data-action="cycle-add" data-add="${k}" title="${k} K"><span class="swatch" style="background:${toHex(kelvinRgb(k))}"></span>${name}</button>`)
          .join("")
      : COLOR_PRESETS.map((rgb) => `<button class="preset dot-only" data-action="cycle-add" data-add="${rgb.join(",")}" aria-label="Farbe hinzufügen ${toHex(rgb)}"><span class="swatch" style="background:${toHex(rgb)}"></span></button>`).join("");
    return `<div class="field cycle">
      <span class="lbl">${isTemp ? "Farbtemperaturen" : "Farben"} in dieser Reihenfolge</span>
      <ol class="clist">${chips}</ol>
      <div class="presets"><span class="hint">Hinzufügen:</span>${presets}${
        isTemp ? "" : `<label class="preset custom" title="eigene Farbe"><input type="color" data-cycle-add="1" value="#ff8800"> eigene …</label>`
      }</div>
      <p class="hint">Jedes Auslösen schaltet zum nächsten Wert, nach dem letzten wieder zum ersten. Reihenfolge per Ziehen oder ‹ ›.${
        isTemp ? ` Die gewählten Lampen können ${lo}–${hi} K.` : ""
      }</p>
    </div>`;
  }

  _cycleList() {
    const b = this._state.dlg.b;
    return b[LIST_DEFAULTS[b.action].key];
  }

  // ---- link editor (name, aktiv, template, motion)

  _renderEditor() {
    const s = this._state;
    const d = s.draft;
    const isNew = s.selected === "new";
    const isMotion = d.profile === "motion";
    const profile = PROFILES.find((p) => p.id === d.profile);
    const status = d.status || {};
    const lastError = status.last_error
      ? `<p class="warn err">Letzter Befehl fehlgeschlagen (${esc(new Date(status.last_error.time).toLocaleTimeString("de-DE"))}): ${esc(status.last_error.message)}</p>`
      : "";
    const templates = PROFILES.filter((p) => (isMotion ? p.id === "motion" : p.id !== "motion"));
    return `<section class="pane editor" aria-label="Verknüpfung bearbeiten">
      <div class="editor-head">
        <button class="icon" data-action="close-editor" aria-label="Zurück">‹</button>
        <label class="title-wrap"><span class="lbl">Name der Verknüpfung (zum Ändern hineintippen)</span>
          <input class="title" data-bind="name" value="${esc(d.name)}" placeholder="Name, z. B. Esstisch"></label>
        <label class="inline" title="Legt eine Taste an, die du aufs Dashboard legen kannst. Sie wirkt wie ein kurzer Klick.">
          <input type="checkbox" data-bind="dashboard_button" ${d.dashboard_button ? "checked" : ""}> Dashboard-Taste</label>
        <label class="inline"><input type="checkbox" data-bind="enabled" ${d.enabled ? "checked" : ""}> aktiv</label>
      </div>
      ${status.broken ? `<p class="warn err">Diese Entitäten gibt es nicht mehr: ${esc(status.missing.join(", "))}</p>` : ""}
      ${status.conflicts?.length ? `<p class="warn">Eine Taste ist zusätzlich belegt in: ${esc(status.conflicts.join(", "))}. Beide schalten dann gleichzeitig.</p>` : ""}
      ${lastError}
      ${status.z2m_group ? `<p class="hint">Schaltet über die Zigbee2MQTT-Gruppe „${esc(status.z2m_group)}“: alle Lampen gleichzeitig.</p>` : ""}
      ${isMotion && !isNew ? `<p class="motion-now">Gerade: <span data-motion="${esc(s.selected)}">${esc(this._motionText(this._motionLive(s.links.find((l) => l.id === s.selected))))}</span></p>` : ""}
      ${
        !isNew && (status.switch_entity || status.button_entity)
          ? `<p class="hint entities">${status.switch_entity ? `Fallback-Schalter <code>${esc(status.switch_entity)}</code>` : ""}${
              status.button_entity ? `${status.switch_entity ? ", " : ""}Dashboard-Taste <code>${esc(status.button_entity)}</code>` : ""
            }${status.sensor_entity ? `, Status <code>${esc(status.sensor_entity)}</code>` : ""}</p>`
          : ""
      }

      <div class="wiring">
        <div class="col">
          <h4>Quellen</h4>
          ${this._renderSources()}
        </div>
        <div class="col mid">
          <h4>${isMotion ? "Verhalten" : "Vorlage"}</h4>
          <div class="profiles" role="radiogroup" aria-label="Vorlage">
            ${templates.map(
              (p) => `<button role="radio" aria-checked="${p.id === d.profile}" class="${p.id === d.profile ? "on" : ""}" data-action="profile" data-value="${p.id}">${p.label}</button>`
            ).join("")}
            ${!isMotion && d.profile === "custom" ? `<button role="radio" aria-checked="true" class="on" disabled>Eigene Belegung</button>` : ""}
          </div>
          <p class="hint">${esc(d.profile === "custom" ? "Einzeln belegt. Eine Vorlage zu wählen ersetzt die Belegungen." : profile?.hint || "")}</p>
        </div>
        <div class="col">
          <h4>${isMotion ? "Ziele" : "Standard-Ziele"}</h4>
          ${this._renderTargets()}
        </div>
      </div>

      ${isMotion ? this._renderMotion() : ""}
      ${!isNew && !isMotion ? this._renderBindingSummary(d) : ""}
      ${d.profile === "gate" ? "" : this._renderOptions()}

      <div class="actions">
        <div class="test">
          ${isMotion ? `<button data-action="test" data-value="press" ${isNew ? "disabled" : ""}>Umschalten wie von Hand</button>` : ""}
        </div>
        <div>
          ${isNew ? "" : `<button class="danger" data-action="delete">Löschen</button>`}
          <button class="primary" data-action="save">${isNew ? "Anlegen" : "Speichern"}</button>
        </div>
      </div>
    </section>`;
  }

  _renderBindingSummary(d) {
    const keys = [...new Set(d.sources.map(keyOf))];
    return `<section class="bsum">
      <h4>Belegungen</h4>
      ${keys
        .map((key) => {
          const layout = this._layout(key);
          const btn = d.sources.find((x) => keyOf(x) === key)?.button ?? null;
          const rows = (d.bindings || []).filter((b) => (!b.source || b.source === key) && this._reachable(key, b.button ?? btn, b.event));
          return `<div class="who">
            ${this._deviceSvg(layout, { size: 40, interactive: false })}
            <div class="who-text">
              <button class="link strong" data-action="open-source" data-value="${esc(key)}">${esc(this._keyName(key))} öffnen</button>
              <div class="evs">${rows
                .map((b) => `<span class="ev static">${esc(this._chipLabel(layout, b.button ?? btn, b.event))} <b>${esc(ACTION_LABEL[b.action])}</b></span>`)
                .join("")}</div>
            </div>
          </div>`;
        })
        .join("")}
    </section>`;
  }

  _renderSources() {
    const s = this._state;
    const d = s.draft;
    const chips = d.sources
      .map((src, i) => {
        const info = this._sourceInfo(src);
        const name = this._sourceName(src);
        const typeLabel =
          src.adapter === "zha" ? "ZHA" : src.adapter === "state_input" ? "Eingang" : src.adapter === "occupancy" ? DEVICE_CLASS_TEXT[info?.device_class] || "Melder" : "";
        return `<div class="item">
          <div class="item-top"><span>${esc(name)}${typeLabel ? ` <small class="tag">${typeLabel}</small>` : ""}${src.button ? ` <small class="tag">Taste ${esc(src.button)}</small>` : ""}</span>
            <button class="x" data-action="remove-source" data-index="${i}" aria-label="Quelle entfernen">×</button></div>
          ${
            src.adapter === "state_input" && d.profile !== "custom"
              ? `<div class="item-opts"><label>Art
                  <select data-bind="sources.${i}.mode">
                    ${[["button", "Taster"], ["switch", "Schalter"], ["mirror", "Zustand spiegeln"]]
                      .map(([v, l]) => `<option value="${v}" ${src.mode === v ? "selected" : ""}>${l}</option>`)
                      .join("")}
                  </select></label></div>`
              : ""
          }
          ${
            d.profile === "rocker"
              ? `<div class="item-opts"><label>Rolle <select data-bind="sources.${i}.role" data-type="nullable">
                  <option value="" ${!src.role ? "selected" : ""}>vom Gerät</option>
                  <option value="up" ${src.role === "up" ? "selected" : ""}>oben / an</option>
                  <option value="down" ${src.role === "down" ? "selected" : ""}>unten / aus</option>
                </select></label></div>`
              : ""
          }
        </div>`;
      })
      .join("");

    const learn =
      s.learning && s.learnFor === "source"
        ? `<div class="learn live" aria-live="polite">
            <p><span class="pulse" aria-hidden="true"></span>${d.profile === "motion" ? "Beweg dich jetzt vor dem Melder …" : "Drück jetzt eine Taste am Taster …"}</p>
            ${s.candidates
              .map(
                (c, i) => `<button class="cand" data-action="candidate" data-index="${i}">
                  <b>${esc(c.name.replace(/ Action$/, ""))}${c.button ? `, Taste ${esc(c.button)}` : ""}</b>
                  <small>${esc(c.area || "ohne Raum")}, ${esc(c.raw_type)}</small></button>`
              )
              .join("")}
            <button class="link" data-action="learn">Anlernen beenden</button>
          </div>`
        : `<button class="learnbtn" data-action="learn" data-value="source">Anlernen</button>`;

    return `${chips}${learn}${this._comboHtml("source", d.profile === "motion" ? "oder Melder suchen …" : "oder Taster suchen …")}`;
  }

  _renderTargets() {
    const d = this._state.draft;
    const chips = this._chips(d.targets, "draft");
    const placeholder = d.profile === "gate" ? "Tor suchen …" : "Ziel suchen …";
    return `<div class="chips">${chips || `<p class="hint">Noch kein Ziel.</p>`}</div>${this._comboHtml("target", placeholder)}
      ${d.profile === "custom" ? `<p class="hint">Gilt für Belegungen ohne eigenes Ziel.</p>` : ""}`;
  }

  _renderMotion() {
    const s = this._state;
    const m = this._state.draft.options.motion;
    const luxOptions = (s.illuminance || [])
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name, "de"))
      .map((x) => `<option value="${esc(x.entity_id)}" ${x.entity_id === m.lux_entity ? "selected" : ""}>${esc(x.name)}</option>`)
      .join("");
    const luxNow = m.lux_entity ? this._hass.states[m.lux_entity]?.state : null;
    const minutes = (v) => (v == null ? "" : Math.round(v / 60));
    return `<section class="motion" aria-label="Automatik">
      <h4>Automatik</h4>
      <div class="mgrid">
        <label><span class="lbl">Helligkeit von</span>
          <span class="row"><select data-bind="options.motion.lux_entity" data-type="nullable" data-rerender>
            <option value="" ${!m.lux_entity ? "selected" : ""}>keinem Sensor (immer einschalten)</option>${luxOptions}
          </select></span>${luxNow != null ? `<span class="hint">gerade ${esc(luxNow)} lx</span>` : ""}</label>
        <label><span class="lbl">Einschalten, wenn dunkler als</span>
          <span class="row"><input type="number" min="0" step="1" data-type="number" data-bind="options.motion.lux_threshold" value="${esc(m.lux_threshold)}"> lx</span></label>
        <label><span class="lbl">Ausschalten ohne Bewegung nach</span>
          <span class="row"><input type="number" min="0" step="5" data-type="number" data-bind="options.motion.off_delay_s" value="${esc(m.off_delay_s)}"> s</span></label>
        <label><span class="lbl">Von Hand eingeschaltet: aus ohne Bewegung nach</span>
          <span class="row"><input type="number" min="1" data-type="minutes" data-bind="options.motion.manual_off_delay_s" value="${esc(minutes(m.manual_off_delay_s))}" placeholder="nie"> min</span>
          <span class="hint">leer lassen = bleibt an</span></label>
        <label><span class="lbl">Von Hand ausgeschaltet</span>
          <span class="row"><select data-bind="options.motion.manual_off_block" data-rerender>
            <option value="until_empty" ${m.manual_off_block === "until_empty" ? "selected" : ""}>Automatik ruht, bis der Raum leer ist</option>
            <option value="timed" ${m.manual_off_block === "timed" ? "selected" : ""}>Automatik ruht für feste Zeit</option>
          </select>
          ${m.manual_off_block === "timed" ? `<input type="number" min="1" data-type="minutes" data-bind="options.motion.manual_off_block_s" value="${esc(minutes(m.manual_off_block_s))}"> min` : ""}</span></label>
        <label><span class="lbl">Pausieren, solange eingeschaltet ist</span>
          <span class="row"><input list="block-entities" data-type="nullable" data-bind="options.motion.block_entity" value="${esc(m.block_entity || "")}" placeholder="z. B. input_boolean.film"></span>
          <datalist id="block-entities">${Object.keys(this._hass.states)
            .filter((e) => e.startsWith("input_boolean.") || e.startsWith("switch.light_linker"))
            .map((e) => `<option value="${esc(e)}">`)
            .join("")}</datalist></label>
      </div>
      <label class="inline"><input type="checkbox" data-bind="options.motion.only_off" ${m.only_off ? "checked" : ""}> Nur ausschalten, nie automatisch einschalten</label>
    </section>`;
  }

  _renderOptions() {
    const o = this._state.draft.options;
    const num = (path, value, attrs) => `<input type="number" data-type="number" data-bind="options.${path}" value="${esc(value ?? "")}" ${attrs}>`;
    return `<details class="options" data-keep="options" ${this._open?.options ? "open" : ""}>
      <summary>Feineinstellungen</summary>
      <div class="grid">
        <label>Umschalten
          <select data-bind="options.toggle_mode">
            <option value="any_on" ${o.toggle_mode === "any_on" ? "selected" : ""}>irgendeine an → alle aus</option>
            <option value="all_on" ${o.toggle_mode === "all_on" ? "selected" : ""}>nur wenn alle an → aus</option>
          </select></label>
        <label>Einschalthelligkeit ${num("on_brightness_pct", o.on_brightness_pct, 'min="1" max="100" placeholder="zuletzt"')} %</label>
        <label>Farbtemperatur ${num("on_color_temp_kelvin", o.on_color_temp_kelvin, 'min="1000" max="10000" step="100" placeholder="unverändert"')} K</label>
        <label>Übergang ${num("transition", o.transition, 'min="0" max="10" step="0.1"')} s</label>
        <label class="inline"><input type="checkbox" data-bind="options.verify.enabled" ${o.verify.enabled ? "checked" : ""}>
          Zustand prüfen, ${num("verify.retries", o.verify.retries, 'min="0" max="3"')} Wiederholung(en), dann melden</label>
      </div>
      <p class="hint">Doppelklick, Dreifachklick und Dimmen stellst du jetzt je Taste ein: im Taster-Bild auf die Zeile tippen.</p>
    </details>`;
  }
}

const STYLES = `
  :host {
    display: block;
    min-height: 100vh;
    background: var(--primary-background-color);
    color: var(--primary-text-color);
    font-family: var(--paper-font-body1_-_font-family, var(--ha-font-family-body, inherit));
    --ll-accent: var(--primary-color);
    --ll-line: var(--divider-color);
    --ll-card: var(--card-background-color, var(--ha-card-background));
    --ll-warn: var(--warning-color, #f57c00);
    --ll-soft: color-mix(in srgb, var(--ll-accent) 12%, transparent);
    --ll-radius: 12px;
  }
  * { box-sizing: border-box; }
  button, input, select { font: inherit; color: inherit; }
  :focus-visible { outline: 2px solid var(--ll-accent); outline-offset: 2px; }
  header {
    border-bottom: 1px solid var(--ll-line);
    background: var(--app-header-background-color, var(--primary-background-color));
    color: var(--app-header-text-color, var(--primary-text-color));
    display: flex; flex-wrap: wrap; align-items: center; padding: 0 12px 0 16px; gap: 0 24px;
  }
  .bar { display: flex; align-items: center; gap: 12px; min-height: var(--header-height, 56px); }
  .tabs { display: flex; align-self: stretch; align-items: flex-end; }
  .notice-slot { margin-left: auto; padding: 6px 0; }
  @media (max-width: 700px) { .tabs { order: 3; flex-basis: 100%; } }
  .tab { background: none; border: 0; border-bottom: 2px solid transparent; padding: 0 14px; min-height: 48px; cursor: pointer; font-size: 14px; font-weight: 500; color: inherit; opacity: .8; }
  .tab.on { border-bottom-color: var(--ll-accent); opacity: 1; color: var(--ll-accent); }
  h1 { font-size: 20px; font-weight: 400; margin: 0; }
  .notice { margin: 0; font-size: 14px; padding: 6px 12px; border-radius: 16px; background: var(--ll-card); border: 1px solid var(--ll-line); color: var(--primary-text-color); }
  .notice.err, .err { color: var(--error-color); }
  main { display: grid; grid-template-columns: minmax(280px, 340px) 1fr; gap: 24px; padding: 24px; max-width: 1360px; }
  main.narrow { display: block; padding: 12px 12px 24px; }
  main.full { display: block; padding: 24px; max-width: 1360px; }
  .empty { padding: 24px; color: var(--secondary-text-color); }
  .list h3 { font-size: 13px; font-weight: 500; color: var(--secondary-text-color); margin: 20px 4px 8px; }
  .list > .combo { margin: 0 0 4px; }
  .dev { display: flex; align-items: center; gap: 12px; width: 100%; text-align: left; padding: 10px 12px; margin-bottom: 8px; border: 1px solid var(--ll-line); border-radius: var(--ll-radius); background: var(--ll-card); cursor: pointer; }
  .dev:hover { border-color: color-mix(in srgb, var(--ll-accent) 50%, var(--ll-line)); }
  .dev.sel { border-color: var(--ll-accent); box-shadow: inset 4px 0 0 var(--ll-accent); }
  .dev.idle { border-style: dashed; background: transparent; }
  .dev.idle .dev-name { font-weight: 400; }
  .dev svg { flex: none; }
  .dev-text { display: grid; gap: 2px; min-width: 0; }
  .dev-name { font-size: 15px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dev-meta { font-size: 12px; color: var(--secondary-text-color); line-height: 1.4; }
  .dev-meta .dot { display: inline-block; margin-right: 6px; vertical-align: 1px; }
  .bulb { width: 36px; height: 36px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; flex: none; background: color-mix(in srgb, var(--ll-line) 60%, transparent); font-size: 16px; filter: grayscale(1); }
  .bulb.on { background: color-mix(in srgb, #ffc107 30%, transparent); filter: none; }
  .card {
    display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
    background: var(--ll-card); border: 1px solid var(--ll-line); border-radius: var(--ll-radius);
  }
  .card.sel { border-color: var(--ll-accent); box-shadow: inset 4px 0 0 var(--ll-accent); }
  .card-main { flex: 1; text-align: left; background: none; border: 0; padding: 12px 4px 12px 16px; cursor: pointer; display: grid; gap: 4px; min-width: 0; }
  .card-name { font-size: 15px; font-weight: 500; }
  .badge { font-size: 11px; font-weight: 400; padding: 1px 6px; border-radius: 8px; border: 1px solid var(--ll-line); color: var(--secondary-text-color); vertical-align: 2px; }
  .card-wire { font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .arrow { color: var(--ll-accent); padding: 0 2px; }
  .card-meta { font-size: 12px; color: var(--secondary-text-color); display: flex; align-items: center; gap: 6px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--secondary-text-color); flex: none; }
  .dot.ok { background: var(--success-color, #43a047); }
  .dot.warn { background: var(--ll-warn); }
  .dot.bad { background: var(--error-color); }
  .switch { position: relative; width: 40px; height: 22px; margin-right: 14px; flex: none; }
  .switch input { position: absolute; inset: 0; opacity: 0; margin: 0; cursor: pointer; }
  .switch span { position: absolute; inset: 0; border-radius: 11px; background: var(--ll-line); transition: background .15s; pointer-events: none; }
  .switch span::after { content: ""; position: absolute; top: 3px; left: 3px; width: 16px; height: 16px; border-radius: 50%; background: var(--ll-card); transition: transform .15s; }
  .switch input:checked + span { background: var(--ll-accent); }
  .switch input:checked + span::after { transform: translateX(18px); }
  .switch input:focus-visible + span { outline: 2px solid var(--ll-accent); outline-offset: 2px; }
  .add { width: 100%; padding: 12px; margin-top: 4px; min-height: 44px; background: none; border: 1px dashed var(--ll-line); border-radius: var(--ll-radius); cursor: pointer; color: var(--ll-accent); }
  .activity { margin-top: 24px; font-size: 14px; }
  .activity summary { cursor: pointer; color: var(--secondary-text-color); }
  .activity ul { list-style: none; padding: 0; margin: 8px 0 0; }
  .activity li { padding: 6px 0; border-bottom: 1px solid var(--ll-line); display: flex; gap: 6px; flex-wrap: wrap; }
  .activity time { margin-left: auto; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
  .pane { background: var(--ll-card); border: 1px solid var(--ll-line); border-radius: var(--ll-radius); padding: 20px 24px; align-self: start; min-width: 0; }
  main.narrow .pane { padding: 16px; }
  .intro h2 { font-size: 20px; font-weight: 400; margin: 0 0 8px; }
  .intro p { max-width: 60ch; color: var(--secondary-text-color); line-height: 1.5; }
  .pane-head { display: flex; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
  .pane-title { flex: 1 1 220px; min-width: 0; }
  .pane-title h2 { font-size: 22px; font-weight: 400; margin: 0; overflow-wrap: anywhere; }
  .sub { font-size: 13px; color: var(--secondary-text-color); margin: 4px 0 0; }
  h3.sec { font-size: 15px; font-weight: 500; margin: 28px 0 10px; }
  .ghost { min-height: 40px; padding: 0 14px; border-radius: 8px; border: 1px solid var(--ll-line); background: none; cursor: pointer; font-size: 14px; }
  .ghost:hover { border-color: var(--ll-accent); }
  .device-body { display: flex; flex-wrap: wrap; gap: 28px; margin-top: 18px; align-items: flex-start; }
  .device-fig { margin: 0; flex: 0 0 210px; display: flex; flex-direction: column; align-items: center; gap: 10px; position: sticky; top: 12px; }
  .device-fig figcaption { font-size: 12px; color: var(--secondary-text-color); text-align: center; line-height: 1.4; }
  svg.device { overflow: visible; }
  svg.device .frame { fill: color-mix(in srgb, var(--ll-card) 80%, var(--primary-background-color)); stroke: color-mix(in srgb, var(--primary-text-color) 30%, transparent); stroke-width: 1.5; }
  svg.device.wall .frame { fill: none; stroke-dasharray: 3 3; }
  svg.device .btn rect { fill: var(--ll-card); stroke: color-mix(in srgb, var(--primary-text-color) 25%, transparent); stroke-width: 1; transition: fill .15s; }
  svg.device .btn text { fill: var(--secondary-text-color); font-family: inherit; pointer-events: none; }
  svg.device .btn[role=button] { cursor: pointer; }
  svg.device .btn[role=button]:hover rect { stroke: var(--ll-accent); }
  svg.device .btn[role=button]:focus-visible { outline: none; }
  svg.device .btn[role=button]:focus-visible rect { stroke: var(--ll-accent); stroke-width: 2.5; }
  svg.device .btn.on rect { fill: var(--ll-soft); stroke: var(--ll-accent); }
  svg.device .btn.on text { fill: var(--ll-accent); }
  svg.device .btn.pressed rect { fill: var(--ll-accent); }
  svg.device .btn.pressed text { fill: var(--text-primary-color, #fff); }
  .slot-list { flex: 1 1 420px; min-width: 0; display: grid; gap: 20px; }
  .slot-group h4 { margin: 0 0 8px; font-size: 14px; font-weight: 500; color: var(--primary-text-color); }
  .slot-group.dim { opacity: .45; }
  .slot-group.focus h4 { color: var(--ll-accent); }
  .slots { display: grid; gap: 6px; }
  .slot { display: grid; grid-template-columns: minmax(130px, 190px) 20px minmax(0, 1fr) auto; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid var(--ll-line); border-radius: 10px; background: var(--ll-card); width: 100%; text-align: left; transition: background .2s, border-color .2s; }
  .slot.free { border-style: dashed; cursor: pointer; background: none; grid-template-columns: minmax(130px, 190px) 20px minmax(0, 1fr); }
  .slot.free:hover { border-color: var(--ll-accent); background: var(--ll-soft); }
  .slot.off { opacity: .65; }
  .slot.conflict { border-color: var(--ll-warn); }
  .slot.pressed { border-color: var(--ll-accent); background: var(--ll-soft); }
  .slot-ev { display: grid; gap: 2px; min-width: 0; }
  .slot-name { font-size: 14px; }
  .raw { font-size: 11px; color: var(--secondary-text-color); background: none; padding: 0; overflow-wrap: anywhere; }
  .slot-arrow { color: var(--ll-accent); text-align: center; }
  .slot.free .slot-arrow { color: var(--secondary-text-color); }
  .slot-free { font-size: 14px; color: var(--ll-accent); }
  .slot-act { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; min-width: 0; }
  .pill { display: inline-flex; align-items: center; padding: 3px 10px; border-radius: 14px; background: var(--ll-soft); color: var(--ll-accent); font-size: 13px; font-weight: 500; }
  .slot-tgt { font-size: 14px; overflow-wrap: anywhere; }
  .slot-note { font-size: 12px; color: var(--secondary-text-color); }
  .slot-link { flex-basis: 100%; font-size: 12px; color: var(--secondary-text-color); }
  .slot-btns { display: flex; gap: 2px; }
  .icon { width: 36px; height: 36px; border: 0; background: none; border-radius: 8px; cursor: pointer; color: var(--secondary-text-color); font-size: 16px; line-height: 1; display: inline-flex; align-items: center; justify-content: center; }
  .icon:hover:not(:disabled) { background: color-mix(in srgb, var(--ll-line) 70%, transparent); color: var(--primary-text-color); }
  .icon:disabled { opacity: .3; cursor: default; }
  .icon.menu { font-size: 22px; }
  .icon.sm { width: 28px; height: 28px; }
  .link-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 0 12px; }
  .setup { border: 1px solid var(--ll-accent); border-radius: var(--ll-radius); padding: 16px; margin-top: 16px; background: color-mix(in srgb, var(--ll-accent) 5%, transparent); }
  .setup h3 { margin: 0 0 12px; font-size: 16px; font-weight: 500; }
  .setup-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px 20px; }
  .setup-grid label, .setup-grid > div { display: grid; gap: 6px; align-content: start; }
  .lbl { font-size: 13px; color: var(--secondary-text-color); }
  .row-end { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
  .seg { display: flex; gap: 6px; }
  .seg.wrap { flex-wrap: wrap; }
  .seg button { min-height: 40px; padding: 0 12px; border-radius: 8px; border: 1px solid var(--ll-line); background: none; cursor: pointer; font-size: 14px; }
  .seg button.on { border-color: var(--ll-accent); background: var(--ll-soft); color: var(--ll-accent); font-weight: 500; }
  .who { display: flex; gap: 14px; align-items: flex-start; padding: 12px 14px; border: 1px solid var(--ll-line); border-radius: var(--ll-radius); margin-bottom: 8px; }
  .who svg { flex: none; }
  .who-text { flex: 1; min-width: 0; display: grid; gap: 6px; }
  .evs { display: flex; flex-wrap: wrap; gap: 6px; }
  .ev { padding: 4px 10px; border-radius: 14px; border: 1px solid var(--ll-line); background: none; font-size: 13px; cursor: pointer; text-align: left; }
  .ev.static { cursor: default; }
  .ev b { font-weight: 500; color: var(--ll-accent); }
  .ev:hover:not(.static) { border-color: var(--ll-accent); }
  .link.strong { font-weight: 500; font-size: 15px; padding: 0; text-align: left; }
  .assign { border: 1px solid var(--ll-accent); border-radius: var(--ll-radius); margin: 12px 0 0; overflow: hidden; }
  .assign-head { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; justify-content: space-between; padding: 12px 14px; background: var(--ll-soft); }
  .assign-head .live { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; }
  .assign-list { padding: 6px; display: grid; gap: 2px; }
  .opt { display: flex; align-items: center; gap: 12px; padding: 8px 10px; border-radius: 8px; border: 0; background: none; text-align: left; cursor: pointer; width: 100%; }
  .opt:hover { background: var(--ll-soft); }
  .opt span { display: grid; gap: 2px; flex: 1; min-width: 0; }
  .opt small { font-size: 12px; color: var(--secondary-text-color); }
  .opt-area { flex: none; }
  .motion-card { align-items: center; }
  .netz { display: grid; gap: 16px; }
  .pills { display: flex; flex-wrap: wrap; gap: 8px; }
  .pillbtn { min-height: 36px; padding: 0 14px; border-radius: 18px; border: 1px solid var(--ll-line); background: var(--ll-card); cursor: pointer; font-size: 14px; }
  .pillbtn.on { background: var(--ll-accent); border-color: var(--ll-accent); color: var(--text-primary-color, #fff); }
  .table-wrap { background: var(--ll-card); border: 1px solid var(--ll-line); border-radius: var(--ll-radius); overflow-x: auto; }
  table { border-collapse: separate; border-spacing: 0; width: 100%; font-size: 14px; }
  caption { text-align: left; padding: 14px 16px 4px; font-size: 13px; color: var(--secondary-text-color); }
  th, td { padding: 10px 14px; border-bottom: 1px solid var(--ll-line); text-align: left; vertical-align: top; }
  thead th { font-weight: 500; font-size: 13px; background: color-mix(in srgb, var(--ll-line) 25%, transparent); }
  th small, td small { color: var(--secondary-text-color); font-weight: 400; font-size: 12px; }
  tbody th { min-width: 180px; }
  .use { display: inline-block; margin: 0 4px 4px 0; padding: 3px 8px; border-radius: 12px; border: 0; background: var(--ll-soft); color: var(--ll-accent); font-size: 12px; font-weight: 500; cursor: pointer; text-align: left; }
  .addcell { width: 32px; height: 32px; border-radius: 8px; border: 1px dashed var(--ll-line); background: none; color: var(--secondary-text-color); cursor: pointer; font-size: 18px; }
  .addcell:hover { border-color: var(--ll-accent); color: var(--ll-accent); }
  .scrim { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 10; }
  .dialog { position: fixed; z-index: 11; left: 50%; top: 4vh; transform: translateX(-50%); width: min(860px, calc(100vw - 24px)); max-height: 92vh; display: flex; flex-direction: column; background: var(--ll-card); color: var(--primary-text-color); border-radius: 16px; box-shadow: 0 20px 60px rgba(0,0,0,.35); }
  .dlg-head { display: flex; align-items: center; gap: 14px; padding: 16px 20px; border-bottom: 1px solid var(--ll-line); }
  .dlg-head h2 { font-size: 19px; }
  .dlg-body { padding: 16px 20px; overflow-y: auto; display: grid; gap: 18px; }
  .dlg-foot { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 20px; border-top: 1px solid var(--ll-line); }
  .grow { flex: 1; }
  .field { display: grid; gap: 8px; }
  .field > label { display: grid; gap: 6px; }
  .field.grid2 { grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px 20px; }
  .tile-sec { grid-column: 1 / -1; font-size: 12px; color: var(--secondary-text-color); margin: 6px 0 -2px; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 8px; }
  .tile { display: grid; gap: 4px; align-content: start; min-height: 64px; padding: 10px 12px; border: 1px solid var(--ll-line); border-radius: 10px; background: var(--ll-card); text-align: left; cursor: pointer; }
  .tile span { font-size: 14px; font-weight: 500; }
  .tile small { font-size: 12px; color: var(--secondary-text-color); }
  .tile:hover { border-color: var(--ll-accent); }
  .tile.on { border-color: var(--ll-accent); background: var(--ll-soft); box-shadow: 0 0 0 1px var(--ll-accent); }
  .belong { border-top: 1px solid var(--ll-line); padding-top: 14px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px 20px; }
  .belong .hint { grid-column: 1 / -1; margin: 0; }
  .row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .row select { flex: 1; min-width: 0; }
  .row input[type=number] { width: 84px; }
  .ramp-preview { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--secondary-text-color); }
  .ramp-preview div { flex: 1; height: 10px; border-radius: 5px; background: linear-gradient(90deg, #2b2210, #ffcc66 70%, #fff6dc); border: 1px solid var(--ll-line); }
  .editor-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .title { flex: 1 1 200px; font-size: 22px; border: 0; border-bottom: 1px dashed var(--ll-line); border-radius: 0; background: none; padding: 4px 0; min-width: 0; }
  .title:hover, .title:focus { border-bottom: 1px solid var(--ll-accent); outline: none; }
  .title-wrap { flex: 1 1 220px; display: grid; gap: 2px; min-width: 0; }
  .title-wrap .lbl { font-size: 12px; }
  .bulb.multi { position: relative; }
  .bulb small { position: absolute; right: -4px; bottom: -4px; font-size: 10px; min-width: 16px; height: 16px; border-radius: 8px; background: var(--ll-accent); color: var(--text-primary-color, #fff); display: inline-flex; align-items: center; justify-content: center; filter: none; }
  .members { margin: 12px 0 0; display: grid; gap: 6px; }
  .evx { display: inline-flex; align-items: center; }
  .evx .x { margin-left: -2px; }
  .assign-search { padding: 4px 14px 0; }
  .assign-search .combo { margin-top: 6px; }
  .assign-search .combo-list { position: static; margin-top: 4px; }
  .hint.grouped { margin-top: 10px; }
  .head-btns { display: flex; gap: 8px; flex-wrap: wrap; }
  .link-rows { display: grid; gap: 8px; }
  .lrow { display: flex; align-items: center; gap: 4px; padding: 8px 4px 8px 14px; border: 1px solid var(--ll-line); border-radius: 10px; }
  .lrow-text { flex: 1; min-width: 0; display: grid; gap: 2px; }
  .lrow-name { font-size: 15px; font-weight: 500; }
  .lrow .switch { margin: 0 8px 0 6px; }
  .lrow code, .lrow .dev-meta { white-space: normal; overflow-wrap: anywhere; min-width: 0; }
  .banner.warnb { border-color: var(--ll-warn); background: color-mix(in srgb, var(--ll-warn) 10%, transparent); display: flex; flex-wrap: wrap; align-items: center; gap: 10px; justify-content: space-between; margin: 12px 0; }
  .banner.warnb p { margin: 0; }
  .sep { color: var(--secondary-text-color); }
  th .link:not(.strong) { font-weight: 400; padding: 0; }
  .rowname { display: flex; align-items: center; gap: 2px; }
  .gico { color: var(--ll-accent); margin-right: 4px; }
  .gico.big { font-size: 20px; }
  .chip.grp { border-color: var(--ll-accent); }
  .ev.grp { border-color: var(--ll-accent); }
  .ev small { color: var(--secondary-text-color); font-weight: 400; }
  .members-edit { margin-bottom: 4px; }
  .row-start { margin-top: 12px; display: flex; flex-wrap: wrap; gap: 8px; }
  .findbox { display: grid; grid-template-columns: 1fr auto 1fr; gap: 20px; align-items: start; margin: 20px 0 8px; }
  .findbox .or { align-self: center; color: var(--secondary-text-color); font-size: 13px; }
  .findbox p { margin: 0 0 8px; }
  .learn.big { padding: 18px; min-height: 120px; display: grid; align-content: center; gap: 6px; border-style: dashed; }
  .learn.big.live { border-style: solid; background: var(--ll-soft); }
  @media (max-width: 700px) { .findbox { grid-template-columns: 1fr; } .findbox .or { justify-self: center; } }
  .pane-title h2 .icon { vertical-align: middle; margin-left: 4px; }
  .inline { display: inline-flex; align-items: center; gap: 6px; font-size: 14px; }
  .warn { color: var(--ll-warn); font-size: 14px; line-height: 1.4; max-width: 80ch; }
  .warn.err { color: var(--error-color); }
  code { font-size: 12px; background: color-mix(in srgb, var(--ll-line) 50%, transparent); padding: 1px 4px; border-radius: 4px; }
  .wiring { display: grid; grid-template-columns: 1fr minmax(180px, 0.8fr) 1fr; margin: 20px 0; position: relative; }
  .col { padding: 0 20px; position: relative; min-width: 0; }
  .col:first-child { padding-left: 0; }
  .col:last-child { padding-right: 0; }
  .col.mid { border-left: 2px solid var(--ll-accent); border-right: 2px solid var(--ll-accent); border-radius: 4px; }
  .col.mid::before, .col.mid::after { content: ""; position: absolute; top: 42px; width: 10px; height: 10px; border-radius: 50%; background: var(--ll-accent); }
  .col.mid::before { left: -6px; }
  .col.mid::after { right: -6px; }
  h4 { font-size: 14px; font-weight: 500; margin: 0 0 12px; color: var(--secondary-text-color); }
  .item { border: 1px solid var(--ll-line); border-radius: 8px; padding: 8px 10px; margin-bottom: 8px; }
  .item-top { display: flex; justify-content: space-between; gap: 8px; font-size: 14px; font-weight: 500; overflow-wrap: anywhere; }
  .tag { font-weight: 400; color: var(--secondary-text-color); }
  .item-opts { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; font-size: 13px; color: var(--secondary-text-color); }
  .item-opts label { display: flex; align-items: center; gap: 4px; }
  input, select { background: var(--ll-card); border: 1px solid var(--ll-line); border-radius: 6px; padding: 6px 8px; min-height: 36px; }
  select { max-width: 100%; }
  .x { background: none; border: 0; cursor: pointer; font-size: 18px; line-height: 1; color: var(--secondary-text-color); padding: 0 4px; min-width: 24px; min-height: 24px; }
  .learnbtn { width: 100%; padding: 10px; min-height: 44px; border-radius: 8px; border: 1px solid var(--ll-accent); background: none; color: var(--ll-accent); cursor: pointer; }
  .learn { border: 1px solid var(--ll-accent); border-radius: 8px; padding: 10px; margin-top: 4px; }
  .learn p { margin: 0 0 8px; display: flex; align-items: center; gap: 8px; font-size: 14px; }
  .pulse { width: 10px; height: 10px; border-radius: 50%; background: var(--ll-accent); animation: pulse 1.2s ease-in-out infinite; flex: none; }
  @keyframes pulse { 50% { opacity: .25; } }
  @media (prefers-reduced-motion: reduce) { .pulse { animation: none; } }
  .cand { display: grid; width: 100%; text-align: left; gap: 2px; padding: 8px; margin-bottom: 6px; border-radius: 6px; border: 1px solid var(--ll-line); background: none; cursor: pointer; }
  .cand:hover { border-color: var(--ll-accent); }
  .cand small { color: var(--secondary-text-color); }
  .link { background: none; border: 0; color: var(--ll-accent); cursor: pointer; padding: 4px 0; font-size: 14px; }
  .combo { position: relative; margin-top: 8px; }
  .combo input { width: 100%; min-height: 40px; }
  .combo-list {
    position: absolute; z-index: 5; left: 0; right: 0; top: calc(100% + 4px);
    max-height: 320px; overflow-y: auto; margin: 0; padding: 4px; list-style: none;
    background: var(--ll-card); border: 1px solid var(--ll-line); border-radius: 8px;
    box-shadow: 0 6px 18px color-mix(in srgb, var(--primary-text-color) 18%, transparent);
  }
  .dialog .combo-list { position: static; margin-top: 4px; max-height: 240px; }
  .combo-list li { display: grid; grid-template-columns: 1fr auto; gap: 0 8px; padding: 6px 8px; border-radius: 6px; cursor: pointer; }
  .combo-list li.active, .combo-list li:hover { background: color-mix(in srgb, var(--ll-accent) 14%, transparent); }
  .opt-label { font-size: 14px; overflow-wrap: anywhere; }
  .opt-kind { font-size: 12px; color: var(--secondary-text-color); align-self: center; }
  .opt-sub { grid-column: 1 / -1; font-size: 12px; color: var(--secondary-text-color); overflow-wrap: anywhere; }
  .combo-empty { color: var(--secondary-text-color); font-size: 14px; padding: 8px; cursor: default; }
  .combo-list li.combo-group {
    display: block; position: sticky; top: -4px; z-index: 1; cursor: default;
    margin: 4px -4px 0; padding: 8px 12px 4px; border-radius: 0;
    font-size: 12px; font-weight: 500; color: var(--secondary-text-color);
    background: var(--ll-card); border-bottom: 1px solid var(--ll-line);
  }
  .combo-list li.combo-group:first-child { margin-top: -4px; }
  .combo-list li.combo-group:hover { background: var(--ll-card); }
  .profiles { display: grid; gap: 6px; }
  .profiles button { padding: 8px; min-height: 40px; border-radius: 8px; border: 1px solid var(--ll-line); background: none; cursor: pointer; }
  .profiles button.on { border-color: var(--ll-accent); background: var(--ll-soft); font-weight: 500; }
  .hint { font-size: 13px; color: var(--secondary-text-color); margin: 8px 0 0; line-height: 1.4; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 6px 4px 12px; border-radius: 16px; border: 1px solid var(--ll-line); font-size: 14px; }
  .chip.area { border-style: dashed; }
  .bsum { border-top: 1px solid var(--ll-line); padding-top: 12px; margin-bottom: 12px; }
  .options { border-top: 1px solid var(--ll-line); padding-top: 12px; }
  .motion { border-top: 1px solid var(--ll-line); padding: 12px 0 16px; }
  .motion h4 { margin-bottom: 4px; }
  .motion-now { font-size: 14px; margin: 8px 0 0; }
  .motion-now span { font-weight: 500; }
  .clist { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 8px; }
  .cchip { display: flex; align-items: center; gap: 6px; padding: 6px 6px 6px 4px; border: 1px solid var(--ll-line); border-radius: 10px; background: var(--ll-card); }
  .cchip.dragging { opacity: .4; }
  .grip { cursor: grab; color: var(--secondary-text-color); font-size: 12px; letter-spacing: -2px; padding: 0 2px; user-select: none; }
  .cchip input[type=color] { width: 44px; height: 30px; padding: 0; border: 1px solid var(--ll-line); border-radius: 6px; background: none; cursor: pointer; }
  .cchip input.kelvin { width: 120px; height: 8px !important; padding: 0 !important; min-height: 0; margin: 0 4px; appearance: none; -webkit-appearance: none; border-radius: 4px; background: linear-gradient(90deg, var(--k-lo), #fff4e8 55%, var(--k-hi)); border: 1px solid var(--ll-line); cursor: pointer; }
  .cchip input.kelvin::-webkit-slider-thumb { -webkit-appearance: none; width: 16px; height: 16px; border-radius: 50%; background: var(--ll-card); border: 2px solid var(--primary-text-color); }
  .cchip input.kelvin::-moz-range-thumb { width: 14px; height: 14px; border-radius: 50%; background: var(--ll-card); border: 2px solid var(--primary-text-color); }
  .swatch { display: inline-block; width: 22px; height: 22px; border-radius: 50%; border: 1px solid var(--ll-line); flex: none; }
  .swatch.sm { width: 16px; height: 16px; }
  .cval { font-size: 13px; font-variant-numeric: tabular-nums; min-width: 52px; }
  .cbtns { display: flex; }
  .presets { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
  .presets .hint { margin: 0 4px 0 0; }
  .preset { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px 4px 4px; border: 1px solid var(--ll-line); border-radius: 16px; background: none; cursor: pointer; font-size: 13px; }
  .preset.dot-only { padding: 3px; }
  .preset.custom { padding: 3px 10px 3px 3px; }
  .preset.custom input { width: 22px; height: 22px; border: 0; padding: 0; background: none; cursor: pointer; min-height: 0; }
  .preset:hover { border-color: var(--ll-accent); }
  .mgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px 24px; margin: 8px 0 14px; }
  .mgrid label { display: flex; flex-direction: column; gap: 4px; font-size: 14px; }
  .mgrid .row input:not([type]) { flex: 1; min-width: 0; }
  .mgrid .hint { margin: 0; font-size: 12px; }
  .banner { border: 1px solid var(--ll-accent); border-radius: var(--ll-radius); padding: 12px 16px; margin-bottom: 16px; font-size: 14px; background: color-mix(in srgb, var(--ll-accent) 8%, transparent); }
  .banner p { margin: 0 0 6px; }
  .banner ul { margin: 0 0 10px; padding-left: 18px; color: var(--secondary-text-color); }
  .banner button { padding: 6px 14px; border-radius: 8px; border: 1px solid var(--ll-accent); cursor: pointer; }
  .ext { font-size: 13px; color: var(--secondary-text-color); margin: 8px 0 0; }
  .link.small { font-size: 13px; padding: 6px 0 0; }
  .options summary { cursor: pointer; font-size: 14px; color: var(--secondary-text-color); }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px 20px; margin-top: 12px; font-size: 14px; }
  .grid label { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
  .grid input[type=number] { width: 76px; }
  .actions { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--ll-line); }
  .actions button { padding: 8px 16px; min-height: 40px; border-radius: 8px; border: 1px solid var(--ll-line); background: none; cursor: pointer; }
  .actions button:disabled { opacity: .5; cursor: default; }
  .actions .test { display: flex; gap: 8px; flex-wrap: wrap; }
  .primary { min-height: 40px; padding: 0 18px; border-radius: 8px; cursor: pointer; background: var(--ll-accent) !important; color: var(--text-primary-color, #fff) !important; border: 1px solid var(--ll-accent) !important; font-weight: 500; }
  .danger { color: var(--error-color) !important; }
  @media (max-width: 900px) {
    .wiring { grid-template-columns: 1fr; gap: 20px; }
    .col, .col:first-child, .col:last-child { padding: 0; }
    .col.mid { border: 0; border-top: 2px solid var(--ll-accent); border-bottom: 2px solid var(--ll-accent); padding: 12px 0; }
    .col.mid::before, .col.mid::after { display: none; }
  }
  @media (max-width: 600px) {
    .device-fig { flex-basis: 100%; position: static; }
    .slot { grid-template-columns: 1fr auto; }
    .slot .slot-arrow { display: none; }
    .slot .slot-act { grid-column: 1 / 2; }
    .slot.free { grid-template-columns: 1fr; }
    .slot-btns { grid-row: 1 / span 2; grid-column: 2; }
    .dialog { top: 0; left: 0; transform: none; width: 100vw; max-height: 100vh; height: 100vh; border-radius: 0; }
    .tab { padding: 0 10px; }
  }
`;

// An open Home Assistant tab may still hold an older version of this panel
// (HA was restarted after an update without reloading the page). A custom
// element cannot be defined twice, so reload the page once to get the new one.
const LL_VERSION = "0.5.5";
const existing = customElements.get("light-linker-panel");
if (!existing) {
  LightLinkerPanel.version = LL_VERSION;
  customElements.define("light-linker-panel", LightLinkerPanel);
} else if (existing.version !== LL_VERSION) {
  const key = `light-linker-reload-${LL_VERSION}`;
  let reloaded = false;
  try {
    reloaded = sessionStorage.getItem(key) === "1";
    sessionStorage.setItem(key, "1");
  } catch (_err) {
    /* storage blocked: reload anyway, at most once per page */
  }
  if (!reloaded) location.reload();
}
