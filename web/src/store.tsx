import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  biggestExportPrinter,
  defaultPlannerState,
  legalExportMode,
  legalFitTarget,
  loadPlannerState,
  plateKey,
  printersForExport,
  reconcileProgress,
  repairStackCatalog,
  STORAGE_KEY,
  THEME_STORAGE_KEY,
  normalizeTheme,
  themeIsDark,
} from "../../planner.mjs";
import { getJson, postJson } from "./api";
import { uid } from "./labels";
import { newLayer } from "./stack";
import type { Bom, ExportFile, Meta, Plan, PlannerState, PresetMap, Printer, SettingsSection, Spool, TabId, ThemeChoice } from "./types";

const COMPUTE_MS = import.meta.env.MODE === "test" ? 0 : 350;

type Store = {
  ready: boolean;
  bootError: string;
  meta: Meta | null;
  presets: PresetMap;
  state: PlannerState | null;
  bom: Bom | null;
  plan: Plan | null;
  planNote: string;
  exportFiles: ExportFile[];
  spools: Spool[];
  theme: ThemeChoice;
  setTheme: (choice: ThemeChoice) => void;
  settingsOpen: boolean;
  setSettingsOpen: (open: boolean) => void;
  settingsSection: SettingsSection;
  setSettingsSection: (section: SettingsSection) => void;
  archive: { done: number; total: number; msg?: string };
  status: string;
  exportStatus: string;
  helpTopic: string;
  showHelp: (topic: string) => void;
  expandedLayer: number | null;
  setExpandedLayer: (index: number | null) => void;
  viewer: { file: string; label: string; color: string } | null;
  openViewer: (file: string, label: string, color: string) => void;
  closeViewer: () => void;
  patch: (recipe: (draft: PlannerState) => void) => void;
  setTab: (tab: TabId) => void;
  addLayer: () => void;
  removeLayer: (index: number) => void;
  moveLayer: (index: number, delta: number) => void;
  saveProject: () => void;
  loadProject: (id: string) => void;
  newProject: () => void;
  deleteProject: (id: string) => void;
  importLayers: (layers: Array<Partial<PlannerState["stack"]["layers"][number]>>) => void;
  importPdf: (file: File) => Promise<void>;
  importStatus: string;
  saveStackFile: () => void;
  loadStackFile: (file: File) => Promise<void>;
  stackFileStatus: string;
  previewPlates: () => Promise<void>;
  runExport: (path: "/api/export" | "/api/export_test", extra?: Record<string, unknown>) => Promise<void>;
  loadSpools: () => Promise<void>;
  spoolStatus: string;
  rescanPresets: () => Promise<void>;
  uploadPresets: (files: FileList) => Promise<void>;
  presetStatus: string;
  showSample: () => Promise<void>;
  refreshPresets: (next: PresetMap) => void;
};

const Ctx = createContext<Store | null>(null);

function applyTheme(choice: ThemeChoice) {
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const dark = themeIsDark(choice, prefersDark);
  document.documentElement.classList.toggle("dark", dark);
  document.querySelector('meta[name="color-scheme"]')?.setAttribute("content", dark ? "dark" : "light");
}

function signature(state: PlannerState): string {
  return JSON.stringify({
    stack: state.stack,
    settings: state.settings,
    overrides: state.overrides,
    fitOnly: state.fitOnly,
    fitTarget: state.fitTarget,
  });
}

export function PlannerProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [bootError, setBootError] = useState("");
  const [meta, setMeta] = useState<Meta | null>(null);
  const [presets, setPresets] = useState<PresetMap>({});
  const [state, setState] = useState<PlannerState | null>(null);
  const [bom, setBom] = useState<Bom | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planNote, setPlanNote] = useState("");
  const [exportFiles, setExportFiles] = useState<ExportFile[]>([]);
  const [spools, setSpools] = useState<Spool[]>([]);
  const [theme, setThemeState] = useState<ThemeChoice>(() => normalizeTheme(localStorage.getItem(THEME_STORAGE_KEY)));
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState<SettingsSection>("printers");
  const [archive, setArchive] = useState<{ done: number; total: number; msg?: string }>({ done: 0, total: 0 });
  const [status, setStatus] = useState("");
  const [exportStatus, setExportStatus] = useState("");
  const [helpTopic, setHelpTopic] = useState("");
  const [expandedLayer, setExpandedLayer] = useState<number | null>(null);
  const [viewer, setViewer] = useState<Store["viewer"]>(null);
  const [importStatus, setImportStatus] = useState("");
  const [stackFileStatus, setStackFileStatus] = useState("");
  const [spoolStatus, setSpoolStatus] = useState("");
  const [presetStatus, setPresetStatus] = useState("");
  const stateRef = useRef<PlannerState | null>(null);
  stateRef.current = state;

  useEffect(() => {
    applyTheme(theme);
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onMedia = () => {
      if (normalizeTheme(localStorage.getItem(THEME_STORAGE_KEY)) === "system") applyTheme("system");
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key === THEME_STORAGE_KEY) {
        const next = normalizeTheme(event.newValue);
        setThemeState(next);
        applyTheme(next);
      }
    };
    media.addEventListener("change", onMedia);
    window.addEventListener("storage", onStorage);
    return () => {
      media.removeEventListener("change", onMedia);
      window.removeEventListener("storage", onStorage);
    };
  }, [theme]);

  useEffect(() => {
    let cancel = false;
    void (async () => {
      try {
        const [nextMeta, nextPresets] = await Promise.all([getJson<Meta>("/api/meta"), getJson<PresetMap>("/api/presets")]);
        if (cancel) return;
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw && !localStorage.getItem("vault-configurator-backup-v1")) localStorage.setItem("vault-configurator-backup-v1", raw);
        const loaded = loadPlannerState(raw, nextMeta) as PlannerState;
        if (loaded.tab !== "stack" && loaded.tab !== "parts" && loaded.tab !== "plates" && loaded.tab !== "assemble") loaded.tab = "stack";
        setMeta(nextMeta);
        setPresets(nextPresets);
        setArchive(nextMeta.progress || { done: 0, total: 0 });
        setState(loaded);
        setReady(true);
      } catch (error) {
        if (!cancel) setBootError(error instanceof Error ? error.message : "The planner did not start.");
      }
    })();
    return () => {
      cancel = true;
    };
  }, []);

  useEffect(() => {
    if (!state) return;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }, [state]);

  useEffect(() => {
    if (!ready) return;
    const id = window.setInterval(() => {
      void getJson<{ done: number; total: number; msg?: string }>("/api/progress").then(setArchive).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(id);
  }, [ready]);

  const sig = state ? signature(state) : "";
  useEffect(() => {
    if (!stateRef.current || !meta) return;
    let cancel = false;
    const timer = window.setTimeout(() => {
      void (async () => {
        const current = stateRef.current;
        if (!current || cancel) return;
        if (!current.stack.layers.length) {
          setBom(null);
          setStatus("");
          return;
        }
        setStatus("Computing parts and geometry…");
        try {
          const next = await postJson<Bom>("/api/bom", {
            stack: current.stack,
            settings: current.settings,
            overrides: current.overrides,
            fitChoices: !!current.fitOnly,
            fitTarget: current.fitTarget,
          });
          if (cancel) return;
          setBom(next);
          setStatus("");
          if (next.stack) {
            const same = JSON.stringify(next.stack.layers) === JSON.stringify(current.stack.layers)
              && next.stack.depth === current.stack.depth
              && JSON.stringify(next.stack.roof || {}) === JSON.stringify(current.stack.roof || {});
            if (!same) {
              setState((prev) => {
                if (!prev) return prev;
                return {
                  ...prev,
                  stack: {
                    ...prev.stack,
                    layers: next.stack?.layers || prev.stack.layers,
                    depth: next.stack?.depth ?? prev.stack.depth,
                    roof: { ...prev.stack.roof, ...(next.stack?.roof || {}) },
                  },
                };
              });
            }
          }
          const hardware = (next.hardware || []).map((row) => ({ item: row.item, qty: Number(row.qty) }));
          const assemble = (next.parts || []).map((part) => ({ key: `${part.group}|${part.name}`, qty: Number(part.qty) }));
          const reconciled = reconcileProgress(current.progress, current.progress.layoutKey || "", null, hardware, assemble);
          setState((prev) => (prev ? { ...prev, progress: reconciled.progress } : prev));
          if (current.tab === "plates") {
            const planned = await postJson<{ plan: Plan }>("/api/plan", {
              stack: next.stack || current.stack,
              settings: current.settings,
              overrides: current.overrides,
            });
            if (cancel) return;
            setPlan(planned.plan);
            const again = reconcileProgress(reconciled.progress, planned.plan.fingerprint || "", planned.plan.plates, hardware, assemble);
            setPlanNote(again.note || "");
            setState((prev) => (prev ? { ...prev, progress: again.progress } : prev));
          }
        } catch (error) {
          if (!cancel) setStatus(error instanceof Error ? error.message : "Could not compute this stack.");
        }
      })();
    }, COMPUTE_MS);
    return () => {
      cancel = true;
      window.clearTimeout(timer);
    };
  }, [sig, ready, meta]);

  const api = useMemo<Store | null>(() => {
    if (!meta || !state) return null;
    const patch: Store["patch"] = (recipe) => {
      setState((prev) => {
        if (!prev) return prev;
        const next = structuredClone(prev);
        recipe(next);
        legalExportMode(next.settings);
        legalFitTarget(next);
        return next;
      });
    };
    const value: Store = {
      ready,
      bootError,
      meta,
      presets,
      state,
      bom,
      plan,
      planNote,
      exportFiles,
      spools,
      theme,
      setTheme: (choice) => {
        localStorage.setItem(THEME_STORAGE_KEY, choice);
        setThemeState(choice);
        applyTheme(choice);
      },
      settingsOpen,
      setSettingsOpen,
      settingsSection,
      setSettingsSection,
      archive,
      status,
      exportStatus,
      helpTopic,
      showHelp: (topic) => {
        if (stateRef.current?.help === false) return;
        setHelpTopic(topic);
      },
      expandedLayer,
      setExpandedLayer,
      viewer,
      openViewer: (file, label, color) => setViewer({ file, label, color }),
      closeViewer: () => setViewer(null),
      patch,
      setTab: (tab) => patch((draft) => {
        draft.tab = tab;
      }),
      addLayer: () => patch((draft) => {
        draft.stack.layers.push(newLayer(draft.stack, meta));
      }),
      removeLayer: (index) => patch((draft) => {
        draft.stack.layers.splice(index, 1);
      }),
      moveLayer: (index, delta) => patch((draft) => {
        const target = index + delta;
        if (target < 0 || target >= draft.stack.layers.length) return;
        const [row] = draft.stack.layers.splice(index, 1);
        draft.stack.layers.splice(target, 0, row);
      }),
      saveProject: () => patch((draft) => {
        const id = draft.activeProjectId || uid();
        draft.activeProjectId = id;
        const snap = {
          id,
          name: draft.stack.name || "untitled",
          savedAt: new Date().toISOString(),
          stack: structuredClone(draft.stack),
          overrides: structuredClone(draft.overrides),
          progress: structuredClone(draft.progress),
        };
        const index = draft.projects.findIndex((project) => project.id === id);
        if (index >= 0) draft.projects[index] = snap;
        else draft.projects.push(snap);
      }),
      loadProject: (id) => patch((draft) => {
        if (!id) {
          draft.activeProjectId = "";
          return;
        }
        const project = draft.projects.find((item) => item.id === id);
        if (!project) return;
        draft.activeProjectId = id;
        draft.stack = structuredClone(project.stack);
        repairStackCatalog(draft.stack, meta.depths, meta.roofs);
        draft.overrides = structuredClone(project.overrides || {});
        draft.progress = structuredClone(project.progress || { layoutKey: "", plates: {}, hardware: {}, assemble: {} });
      }),
      newProject: () => patch((draft) => {
        const fresh = defaultPlannerState(meta.defaults) as PlannerState;
        draft.stack = fresh.stack;
        draft.overrides = {};
        draft.progress = fresh.progress;
        draft.activeProjectId = "";
      }),
      deleteProject: (id) => patch((draft) => {
        draft.projects = draft.projects.filter((project) => project.id !== id);
        if (draft.activeProjectId === id) draft.activeProjectId = "";
      }),
      importLayers: (layers) => patch((draft) => {
        const blank = newLayer(draft.stack, meta);
        draft.stack.layers = layers.map((layer) => ({
          ...blank,
          ...layer,
          type: layer.type || blank.type,
          layout: layer.layout || blank.layout,
          height: Number(layer.height || blank.height),
          facades: layer.facades || blank.facades,
        }));
        draft.overrides = {};
      }),
      importPdf: async (file) => {
        setImportStatus("reading…");
        try {
          const response = await fetch("/api/import_pdf", { method: "POST", headers: { "Content-Type": "application/pdf" }, body: await file.arrayBuffer() });
          const payload = await response.json() as { error?: string; layers?: PlannerState["stack"]["layers"]; warnings?: string[] };
          if (payload.error) throw new Error(payload.error);
          patch((draft) => {
            const blank = newLayer({ ...draft.stack, layers: [] }, meta);
            draft.stack.layers = (payload.layers || []).map((layer) => ({
              ...blank,
              ...layer,
              type: layer.type || blank.type,
              layout: layer.layout || blank.layout,
              height: Number(layer.height || blank.height),
              facades: layer.facades || blank.facades,
            }));
            draft.overrides = {};
          });
          setImportStatus(`${payload.layers?.length || 0} layers imported. ${(payload.warnings || []).join(" ")}`);
        } catch (error) {
          setImportStatus(error instanceof Error ? error.message : "Could not read that PDF.");
        }
      },
      importStatus,
      saveStackFile: () => {
        const current = stateRef.current;
        if (!current) return;
        const blob = new Blob([JSON.stringify({ stack: current.stack, overrides: current.overrides }, null, 1)], { type: "application/json" });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `${current.stack.name || "vault-stack"}.json`;
        link.click();
        URL.revokeObjectURL(link.href);
      },
      loadStackFile: async (file) => {
        try {
          const payload = JSON.parse(await file.text()) as { stack?: PlannerState["stack"]; overrides?: PlannerState["overrides"] };
          if (!payload.stack || !Array.isArray(payload.stack.layers)) throw new Error("not a stack file");
          patch((draft) => {
            draft.stack = { ...defaultPlannerState(meta.defaults).stack, ...payload.stack } as PlannerState["stack"];
            repairStackCatalog(draft.stack, meta.depths, meta.roofs);
            draft.overrides = payload.overrides || {};
          });
          setStackFileStatus(`loaded “${payload.stack.name || "stack"}” (${payload.stack.layers.length} layers)`);
        } catch (error) {
          setStackFileStatus(error instanceof Error ? error.message : "Could not load that file.");
        }
      },
      stackFileStatus,
      previewPlates: async () => {
        const current = stateRef.current;
        if (!current) return;
        setExportStatus("Planning…");
        try {
          const result = await postJson<{ plan: Plan }>("/api/plan", { stack: current.stack, settings: current.settings, overrides: current.overrides });
          setPlan(result.plan);
          setExportFiles([]);
          const hardware = (bom?.hardware || []).map((row) => ({ item: row.item, qty: Number(row.qty) }));
          const assemble = (bom?.parts || []).map((part) => ({ key: `${part.group}|${part.name}`, qty: Number(part.qty) }));
          const reconciled = reconcileProgress(current.progress, result.plan.fingerprint || "", result.plan.plates, hardware, assemble);
          setPlanNote(reconciled.note || "");
          setState((prev) => (prev ? { ...prev, progress: reconciled.progress } : prev));
          setExportStatus("");
        } catch (error) {
          setExportStatus(error instanceof Error ? error.message : "Planning failed.");
        }
      },
      runExport: async (path, extra) => {
        const current = stateRef.current;
        if (!current) return;
        setExportStatus("Starting…");
        try {
          await postJson(path, { stack: current.stack, settings: current.settings, overrides: current.overrides, ...(extra || {}) });
          for (;;) {
            await new Promise((resolve) => window.setTimeout(resolve, 800));
            const report = await getJson<{ running?: boolean; percent?: number; msg?: string; error?: string; result?: { plan: Plan; files: ExportFile[]; seconds: number; zip: string } }>("/api/export_status");
            setExportStatus(`${report.percent ?? 0}% · ${report.msg || ""}`);
            if (report.error) throw new Error(report.error);
            if (!report.running && report.result) {
              setPlan(report.result.plan);
              setExportFiles(report.result.files || []);
              setExportStatus(`done in ${report.result.seconds}s`);
              if (meta.handoff === "none") {
                const link = document.createElement("a");
                link.href = "/api/download";
                link.download = report.result.zip;
                link.click();
              }
              break;
            }
          }
        } catch (error) {
          setExportStatus(error instanceof Error ? error.message : "Export failed.");
        }
      },
      loadSpools: async () => {
        const current = stateRef.current;
        if (!current) return;
        setSpoolStatus("loading…");
        try {
          const payload = await getJson<{ spools?: Spool[]; error?: string }>(`/api/spoolman?url=${encodeURIComponent(current.settings.spoolman || "")}`);
          setSpools(payload.spools || []);
          setSpoolStatus(`${payload.spools?.length || 0} spools`);
        } catch (error) {
          setSpoolStatus(error instanceof Error ? error.message : "Spoolman did not answer.");
        }
      },
      spoolStatus,
      rescanPresets: async () => {
        const next = await getJson<PresetMap>("/api/presets");
        setPresets(next);
      },
      uploadPresets: async (list) => {
        const picked = [...list].filter((file) => /(^|\/)(BambuStudio|AnycubicSlicerNext|OrcaSlicer)\/((system|user)\/.+\.json|\2\.conf)$/.test(file.webkitRelativePath));
        if (!picked.length) {
          setPresetStatus("no presets in that folder: pick the BambuStudio, AnycubicSlicerNext or OrcaSlicer folder itself");
          return;
        }
        const files: Record<string, string> = {};
        for (const file of picked) {
          const text = await file.text();
          files[file.webkitRelativePath] = file.name.endsWith(".conf") ? JSON.stringify({ preset_folder: (text.match(/"preset_folder"\s*:\s*"([\w-]+)"/) || [])[1] || "" }) : text;
        }
        await postJson("/api/presets_upload", { files });
        const next = await getJson<PresetMap>("/api/presets");
        setPresets(next);
        setPresetStatus("presets received");
      },
      presetStatus,
      showSample: async () => {
        const sample = await getJson<Plan>("/api/sample_plan");
        setPlan(sample);
        setPlanNote("");
      },
      refreshPresets: setPresets,
    };
    return value;
  }, [archive, bom, bootError, expandedLayer, exportFiles, exportStatus, helpTopic, importStatus, meta, plan, planNote, presetStatus, presets, ready, settingsOpen, settingsSection, spoolStatus, spools, stackFileStatus, state, status, theme, viewer]);

  if (bootError && !api) return <p className="boot-error">{bootError}</p>;
  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

export type ReadyStore = Omit<Store, "state" | "meta"> & { state: PlannerState; meta: Meta };

export function usePlanner(): ReadyStore {
  const value = useContext(Ctx);
  if (!value || !value.state || !value.meta) throw new Error("planner is not ready");
  return value as ReadyStore;
}

export function useMaybePlanner(): Store | null {
  return useContext(Ctx);
}

export function exportPrinters(state: PlannerState): Printer[] {
  return printersForExport(state.settings) as Printer[];
}

export function estimatePrinter(state: PlannerState): Printer | null {
  return biggestExportPrinter(state.settings) as Printer | null;
}

export { plateKey };
