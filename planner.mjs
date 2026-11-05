/** Pure helpers for saved progress, plate keys, and the depth/roof selects. No DOM, no network. */

export function plateKey(plate) {
  const items = (plate.items || [])
    .map((item) => `${item.part}@${item.x},${item.y},${item.rot}`)
    .sort()
    .join("|");
  const slots = (plate.slots || []).join(",");
  return `${plate.printer}|${slots}|${items}`;
}

export function reconcileProgress(progress, fingerprint, plates, hardware, assemble) {
  const prev = progress || { layoutKey: "", plates: {}, hardware: {}, assemble: {} };
  let note = "";
  let plateDone = { ...(prev.plates || {}) };
  if (plates) {
    if (prev.layoutKey && prev.layoutKey !== fingerprint) {
      plateDone = {};
      note = "Plate checks cleared because the layout changed.";
    }
    const alive = new Set(plates.map(plateKey));
    plateDone = Object.fromEntries(Object.entries(plateDone).filter(([key, done]) => done && alive.has(key)));
  }
  const hardwareDone = {};
  for (const row of hardware || []) {
    const old = (prev.hardware || {})[row.item];
    const sameQty = !!old && Number(old.qty) === Number(row.qty);
    hardwareDone[row.item] = { qty: Number(row.qty), done: sameQty && !!old.done };
  }
  let assembleDone = { ...(prev.assemble || {}) };
  if (assemble) {
    assembleDone = {};
    for (const row of assemble) {
      const old = (prev.assemble || {})[row.key];
      const sameQty = !!old && Number(old.qty) === Number(row.qty);
      assembleDone[row.key] = { qty: Number(row.qty), done: sameQty && !!old.done };
    }
  }
  return {
    progress: {
      ...prev,
      layoutKey: plates ? (fingerprint || "") : (prev.layoutKey || ""),
      plates: plateDone,
      hardware: hardwareDone,
      assemble: assembleDone,
    },
    note,
  };
}

/** missing | fits | unfit. A part fits the judged set only when every id fits. */
export function partFitsScope(part, ids) {
  if (!part || !part.file) return "missing";
  if (!ids || !ids.length || !part.fits) return "unknown";
  return ids.every((id) => part.fits[id]) ? "fits" : "unfit";
}

/**
 * Layer warning text. A fit matrix owns the sentence, including when `reasons` is empty.
 * Without a matrix, the page falls back to part fit.
 */
export function layerNotes(layerEntry, parts, ids, layerNumber) {
  if (layerEntry && Array.isArray(layerEntry.reasons)) return layerEntry.reasons.slice();
  const prefix = `L${layerNumber} ·`;
  const notes = [];
  for (const part of parts || []) {
    if (!String(part.group || "").startsWith(prefix)) continue;
    const fit = partFitsScope(part, ids);
    if (fit === "missing") notes.push(`File not found: ${part.name}`);
    else if (fit === "unfit") notes.push(`${part.qty}× ${part.name} does not fit`);
  }
  return notes;
}

/** Replace the untouched upstream H2C + Kobra pair with the fleet. A resized or extended list is kept. */
export function migratePrinters(saved, fleet) {
  if (!Array.isArray(saved) || saved.length !== 2 || !Array.isArray(fleet)) return saved;
  const h2c = saved.find((printer) => printer.id === "h2c");
  const kobra = saved.find((printer) => printer.id === "kobrax");
  if (!h2c || !kobra) return saved;
  const bed = (printer, x, y) => printer.bed && printer.bed[0] === x && printer.bed[1] === y;
  if (bed(h2c, 325, 320) && h2c.z === 320 && bed(kobra, 260, 260)) return JSON.parse(JSON.stringify(fleet));
  return saved;
}

/** The parts list always includes every required part. The fit control disables choices; it does not hide rows. */
export function visiblePartRows(parts) {
  return (parts || []).slice();
}

/**
 * When the fit control is on, a choice that does not fit is disabled unless it is the current
 * saved or imported value. That value stays selected and is marked.
 */
export function decorateChoices(entries, filterOn) {
  const items = (entries || []).map((entry) => {
    const current = !!entry.current;
    const fits = !!entry.fits;
    return {
      ...entry,
      current,
      fits,
      disabled: !!(filterOn && !fits && !current),
      mark: current && !fits ? "does not fit" : "",
    };
  });
  const warning = filterOn && items.length > 0 && !items.some((item) => item.fits)
    ? "No choice here fits the selected printer. The current one stays selected."
    : "";
  return { items, warning };
}

export const DEPTHS = [3, 4, 5, 6, 7];
export const ROOFS = ["none", "grid", "table", "bowl", "undertable", "heavyweight"];
export const DEFAULT_DEPTH = 5;

export function depthLabel(depth) {
  const n = Number(depth);
  return `${n} · ${(156.1 + (n - 3) * 42).toFixed(1)} mm`;
}

export function clampDepth(raw, fallback = DEFAULT_DEPTH) {
  const n = Number(raw);
  if (DEPTHS.includes(n)) return n;
  const fb = Number(fallback);
  return DEPTHS.includes(fb) ? fb : DEFAULT_DEPTH;
}

export function clampRoof(raw, fallback = "none") {
  if (ROOFS.includes(raw)) return raw;
  if (ROOFS.includes(fallback)) return fallback;
  return "none";
}

function staticCatalog(name) {
  if (name === "depth") return DEPTHS.map((value) => ({ value }));
  if (name === "roof") return ROOFS.map((value) => ({ value }));
  return [];
}

function catalogSelectOptions(name, fromBom, current, filterOn) {
  const selected = name === "depth" ? clampDepth(current) : clampRoof(current);
  const source = Array.isArray(fromBom) && fromBom.length ? fromBom : staticCatalog(name);
  const entries = source.map((entry) => ({
    ...entry,
    current: String(entry.value) === String(selected),
  }));
  const judged = entries.some((entry) => Object.prototype.hasOwnProperty.call(entry, "fits"));
  const decorated = judged && filterOn ? decorateChoices(entries, true) : null;
  const rows = decorated ? decorated.items : entries;
  return {
    selected,
    warning: decorated ? decorated.warning : "",
    options: rows.map((entry) => ({
      value: entry.value,
      disabled: !!(decorated && entry.disabled),
      selected: String(entry.value) === String(selected),
      mark: (decorated && entry.mark) || "",
      reason: entry.reason || "",
    })),
  };
}

/**
 * Depth and roof options for the Design tab.
 * An empty stack never calls /api/bom, so `choices` is missing and the static catalog is used.
 * Fit flags apply only while layers exist. Unfit values stay in the list.
 */
export function catalogChoicesFor(name, spec) {
  const layers = (spec && spec.layers) || [];
  const choices = spec && spec.choices;
  const live = layers.length && choices ? choices[name] : null;
  const current = spec ? spec.current : undefined;
  return catalogSelectOptions(name, live, current, !!(spec && spec.fitOnly));
}

export function checkedCount(progress) {
  const plates = Object.values((progress && progress.plates) || {}).filter(Boolean).length;
  const hardware = Object.values((progress && progress.hardware) || {}).filter((row) => row && row.done).length;
  const assemble = Object.values((progress && progress.assemble) || {}).filter((row) => row && row.done).length;
  return { plates, hardware, assemble };
}
