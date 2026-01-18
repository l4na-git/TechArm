import {
  FormEvent,
  useEffect,
  useMemo,
  useState,
  useCallback,
  type MouseEvent,
} from "react";
import { dump as dumpYAML, load as loadYAML } from "js-yaml";

type MaterialSummary = {
  material_id: string;
  regions: number;
  selected: boolean;
};

type MaterialAssets = {
  files: string[];
};

type BoundingBox = {
  x: number;
  y: number;
  w: number;
  h: number;
};

type Region = {
  id: string;
  type: string;
  label?: string;
  bbox: BoundingBox;
  on_point: string[];
  on_help: string[];
};

type MaterialData = {
  material_id: string;
  pdf_file?: string;
  regions: Region[];
};

type HealthResponse = {
  status: string;
  active_material: string | null;
  control_panel_url?: string | null;
};

type PointerEventPayload = {
  u: number;
  v: number;
  event: "on_point" | "on_help";
};

type ArmPayload = {
  x: number;
  y: number;
  z: number;
  speed: number;
};

type CalibrationPoint = {
  id: string;
  u: number | null;
  v: number | null;
  x: number | null;
  y: number | null;
  z: number | null;
};

type CalibrationData = {
  version: number;
  points: CalibrationPoint[];
};

type ScriptData = {
  role: {
    name: string;
    tone: string;
    rules: string[];
  };
  intent: IntentConfig;
  negative_rules: NegativeRule[];
  commands: CommandEntry[];
};

type IntentConfig = {
  greeting_reply: string;
  fallback_reply: string;
  greeting_terms: string[];
  on_topic: string[];
  off_topic: string[];
};

type NegativeRule = {
  id: string;
  when: string;
  action: string[];
};

type CommandEntry = {
  name: string;
  steps: CommandStep[];
};

type CommandStep = Record<string, string | boolean>;

const resolveApiBase = () => {
  if (import.meta.env.VITE_TEACHARM_API_URL) {
    return import.meta.env.VITE_TEACHARM_API_URL as string;
  }
  if (typeof window !== "undefined") {
    return `http://${window.location.hostname}:8000`;
  }
  return "http://localhost:8000";
};

const API_BASE = resolveApiBase();

const parseNullableNumber = (value: string): number | null => {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
};

const clamp01 = (value: number) => Math.min(1, Math.max(0, value));

const fetchJSON = async <T,>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }
  return (await response.json()) as T;
};

function Section({
  title,
  icon,
  children,
  defaultOpen = true,
  className = "",
}: {
  title: string;
  icon?: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
  className?: string;
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <section className={`section ${className}`}>
      <div
        className="section-header"
        onClick={() => setIsOpen(!isOpen)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === "Enter" && setIsOpen(!isOpen)}
      >
        <h2>
          {icon && <span>{icon}</span>}
          {title}
        </h2>
        <span className={`section-toggle ${!isOpen ? "collapsed" : ""}`}>
          ▼
        </span>
      </div>
      <div className={`section-content ${!isOpen ? "collapsed" : ""}`}>
        {children}
      </div>
    </section>
  );
}

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [materials, setMaterials] = useState<MaterialSummary[]>([]);
  const [materialAssets, setMaterialAssets] = useState<string[]>([]);
  const [selectedAsset, setSelectedAsset] = useState<string>("");
  const [log, setLog] = useState<string[]>([]);
  const [pointer, setPointer] = useState<PointerEventPayload>({
    u: 0.5,
    v: 0.5,
    event: "on_point",
  });
  const [arm, setArm] = useState<ArmPayload>({
    x: 0,
    y: 0,
    z: 0,
    speed: 0.2,
  });
  const [calibrationData, setCalibrationData] =
    useState<CalibrationData | null>(null);
  const [calibrationLoading, setCalibrationLoading] = useState(false);
  const [calibrationPreviewText, setCalibrationPreviewText] = useState("");
  const [selectedCalibrationIndex, setSelectedCalibrationIndex] =
    useState<number | null>(null);
  const [dialogueText, setDialogueText] = useState("");
  const [loading, setLoading] = useState(false);
  const [scriptPath, setScriptPath] = useState("");
  const [scriptLoading, setScriptLoading] = useState(false);
  const [scriptData, setScriptData] = useState<ScriptData | null>(null);
  const [rawYaml, setRawYaml] = useState("");
  const [commandFilter, setCommandFilter] = useState("");
  const [actionDrafts, setActionDrafts] = useState<Record<number, string>>({});
  
  // Material editor state
  const [editingMaterial, setEditingMaterial] = useState<MaterialData | null>(null);
  const [editingMaterialId, setEditingMaterialId] = useState<string>("");
  const [editingPdf, setEditingPdf] = useState<string>("");
  const [selectedRegionIndex, setSelectedRegionIndex] = useState<number | null>(null);
  const [drawingRect, setDrawingRect] = useState<{
    startX: number;
    startY: number;
    endX: number;
    endY: number;
  } | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [resizingRegion, setResizingRegion] = useState<{
    index: number;
    handle: "nw" | "ne" | "sw" | "se" | "move";
    startX: number;
    startY: number;
    originalBbox: BoundingBox;
  } | null>(null);

  const appendLog = useCallback((message: string) => {
    setLog((prev) => [
      `${new Date().toLocaleTimeString()} ${message}`,
      ...prev.slice(0, 99),
    ]);
  }, []);

  const loadHealth = async () => {
    try {
      const data = await fetchJSON<HealthResponse>("/health");
      setHealth(data);
      appendLog("Health updated");
    } catch (err) {
      appendLog(`Health error: ${(err as Error).message}`);
    }
  };

  const loadMaterials = async () => {
    try {
      const data = await fetchJSON<{ materials: MaterialSummary[] }>(
        "/api/materials",
      );
      setMaterials(data.materials);
      appendLog("Materials fetched");
    } catch (err) {
      appendLog(`Materials error: ${(err as Error).message}`);
    }
  };

  const loadMaterialAssets = async () => {
    try {
      const data = await fetchJSON<MaterialAssets>("/api/materials/assets");
      setMaterialAssets(data.files);
      if (!selectedAsset && data.files.length > 0) {
        setSelectedAsset(data.files[0]);
      }
      appendLog("Material assets loaded");
    } catch (err) {
      appendLog(`Assets error: ${(err as Error).message}`);
    }
  };

  const loadScript = async () => {
    setScriptLoading(true);
    try {
      const result = await fetchJSON<{ path: string; content: string }>(
        "/api/scripts/common",
      );
      setScriptPath(result.path);
      setRawYaml(result.content);
      const parsed = loadYAML(result.content) as Record<string, any>;
      setScriptData(normalizeScript(parsed));
      appendLog("Script loaded");
    } catch (err) {
      appendLog(`Script load error: ${(err as Error).message}`);
    } finally {
      setScriptLoading(false);
    }
  };

  const loadCalibration = async () => {
    setCalibrationLoading(true);
    try {
      const data = await fetchJSON<CalibrationData>("/api/calibration");
      setCalibrationData(data);
      appendLog("Calibration loaded");
    } catch (err) {
      appendLog(`Calibration error: ${(err as Error).message}`);
    } finally {
      setCalibrationLoading(false);
    }
  };

  useEffect(() => {
    loadHealth();
    loadMaterials();
    loadScript();
    loadCalibration();
    loadMaterialAssets();
    const timer = setInterval(() => {
      loadHealth();
    }, 5000);
    return () => clearInterval(timer);
  }, []);

  // Material editor functions
  const loadMaterialForEdit = async (materialId: string) => {
    try {
      const data = await fetchJSON<MaterialData>(`/api/materials/${materialId}`);
      setEditingMaterial(data);
      setEditingMaterialId(materialId);
      setSelectedRegionIndex(null);
      // 対応するPDFファイルを自動選択
      if (data.pdf_file && materialAssets.includes(data.pdf_file)) {
        setEditingPdf(data.pdf_file);
      }
      appendLog(`Loaded material ${materialId} for editing`);
    } catch (err) {
      appendLog(`Failed to load material: ${(err as Error).message}`);
    }
  };

  const saveMaterial = async () => {
    if (!editingMaterial) return;
    try {
      await fetchJSON(`/api/materials/${editingMaterial.material_id}`, {
        method: "PUT",
        body: JSON.stringify(editingMaterial),
      });
      appendLog(`Saved material ${editingMaterial.material_id}`);
      await loadMaterials();
    } catch (err) {
      appendLog(`Save error: ${(err as Error).message}`);
    }
  };

  const handlePdfMouseDown = (e: MouseEvent<HTMLDivElement>) => {
    // リサイズ・移動中は新規描画しない
    if (resizingRegion) return;
    
    const rect = e.currentTarget.getBoundingClientRect();
    const x = clamp01((e.clientX - rect.left) / rect.width);
    const y = clamp01((e.clientY - rect.top) / rect.height);
    
    // 新規矩形を描画開始
    setDrawingRect({ startX: x, startY: y, endX: x, endY: y });
    setIsDragging(true);
  };

  const handlePdfMouseMove = (e: MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = clamp01((e.clientX - rect.left) / rect.width);
    const y = clamp01((e.clientY - rect.top) / rect.height);

    // リサイズ中
    if (resizingRegion && editingMaterial) {
      const { index, handle, startX, startY, originalBbox } = resizingRegion;
      const dx = x - startX;
      const dy = y - startY;
      
      let newBbox = { ...originalBbox };
      
      if (handle === "move") {
        // 移動
        newBbox.x = clamp01(originalBbox.x + dx);
        newBbox.y = clamp01(originalBbox.y + dy);
      } else if (handle === "nw") {
        // 左上
        newBbox.x = clamp01(originalBbox.x + dx);
        newBbox.y = clamp01(originalBbox.y + dy);
        newBbox.w = clamp01(originalBbox.w - dx);
        newBbox.h = clamp01(originalBbox.h - dy);
      } else if (handle === "ne") {
        // 右上
        newBbox.y = clamp01(originalBbox.y + dy);
        newBbox.w = clamp01(originalBbox.w + dx);
        newBbox.h = clamp01(originalBbox.h - dy);
      } else if (handle === "sw") {
        // 左下
        newBbox.x = clamp01(originalBbox.x + dx);
        newBbox.w = clamp01(originalBbox.w - dx);
        newBbox.h = clamp01(originalBbox.h + dy);
      } else if (handle === "se") {
        // 右下
        newBbox.w = clamp01(originalBbox.w + dx);
        newBbox.h = clamp01(originalBbox.h + dy);
      }
      
      // 最小サイズチェック
      if (newBbox.w >= 0.01 && newBbox.h >= 0.01) {
        updateRegion(index, { bbox: newBbox });
      }
      return;
    }

    // 新規描画中
    if (isDragging && drawingRect) {
      setDrawingRect({ ...drawingRect, endX: x, endY: y });
    }
  };

  const handlePdfMouseUp = () => {
    // リサイズ終了
    if (resizingRegion) {
      setResizingRegion(null);
      return;
    }

    // 新規描画終了
    if (!drawingRect || !editingMaterial) {
      setIsDragging(false);
      return;
    }

    const { startX, startY, endX, endY } = drawingRect;
    const x = Math.min(startX, endX);
    const y = Math.min(startY, endY);
    const w = Math.abs(endX - startX);
    const h = Math.abs(endY - startY);

    if (w < 0.01 || h < 0.01) {
      appendLog("領域が小さすぎます");
      setIsDragging(false);
      setDrawingRect(null);
      return;
    }

    const newRegion: Region = {
      id: `region_${editingMaterial.regions.length + 1}`,
      type: "question",
      bbox: { x, y, w, h },
      on_point: [],
      on_help: [],
    };

    setEditingMaterial({
      ...editingMaterial,
      regions: [...editingMaterial.regions, newRegion],
    });
    setSelectedRegionIndex(editingMaterial.regions.length);
    setIsDragging(false);
    setDrawingRect(null);
    appendLog(`新しい領域を追加: ${newRegion.id}`);
  };

  const updateRegion = (index: number, updates: Partial<Region>) => {
    if (!editingMaterial) return;
    const updated = [...editingMaterial.regions];
    updated[index] = { ...updated[index], ...updates };
    setEditingMaterial({ ...editingMaterial, regions: updated });
  };

  const deleteRegion = (index: number) => {
    if (!editingMaterial) return;
    const updated = editingMaterial.regions.filter((_, i) => i !== index);
    setEditingMaterial({ ...editingMaterial, regions: updated });
    if (selectedRegionIndex === index) {
      setSelectedRegionIndex(null);
    }
  };

  const selectMaterial = async (materialId: string) => {
    setLoading(true);
    try {
      await fetchJSON("/api/materials/select", {
        method: "POST",
        body: JSON.stringify({ material_id: materialId }),
      });
      appendLog(`Selected material ${materialId}`);
      loadMaterials();
    } catch (err) {
      appendLog(`Select error: ${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  };

  const sendPointer = async (event: PointerEventPayload) => {
    setLoading(true);
    try {
      const result = await fetchJSON("/api/events/pointer", {
        method: "POST",
        body: JSON.stringify(event),
      });
      appendLog(`Pointer sent: ${JSON.stringify(result.region ?? {})}`);
    } catch (err) {
      appendLog(`Pointer error: ${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  };

  const sendDialogue = async () => {
    if (!dialogueText.trim()) return;
    setLoading(true);
    try {
      const result = await fetchJSON("/api/dialogue", {
        method: "POST",
        body: JSON.stringify({ text: dialogueText }),
      });
      appendLog(`Dialogue: ${result?.dialogue?.text ?? ""}`);
      setDialogueText("");
    } catch (err) {
      appendLog(`Dialogue error: ${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  };

  const moveArm = async (payload: ArmPayload) => {
    setLoading(true);
    try {
      await fetchJSON("/api/arm/move", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      appendLog("Arm move command sent");
    } catch (err) {
      appendLog(`Arm error: ${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  };

  const sendSafePose = async () => {
    setLoading(true);
    try {
      await fetchJSON("/api/arm/safe_pose", { method: "POST" });
      appendLog("Arm returning to safe pose");
    } catch (err) {
      appendLog(`Safe pose error: ${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  };

  const saveScript = async () => {
    if (!scriptData) return;
    if (scriptValidation.issues.length > 0) {
      appendLog("Script save blocked: fix validation errors.");
      return;
    }
    setScriptLoading(true);
    try {
      const yamlText = dumpYAML(denormalizeScript(scriptData), {
        lineWidth: 120,
        noRefs: true,
      });
      await fetchJSON("/api/scripts/common", {
        method: "POST",
        body: JSON.stringify({ content: yamlText }),
      });
      setRawYaml(yamlText);
      appendLog("Script updated");
    } catch (err) {
      appendLog(`Script save error: ${(err as Error).message}`);
    } finally {
      setScriptLoading(false);
    }
  };

  const saveCalibration = async () => {
    if (!calibrationData) return;
    setCalibrationLoading(true);
    try {
      await fetchJSON("/api/calibration", {
        method: "POST",
        body: JSON.stringify(calibrationData),
      });
      appendLog("Calibration updated");
    } catch (err) {
      appendLog(`Calibration save error: ${(err as Error).message}`);
    } finally {
      setCalibrationLoading(false);
    }
  };

  const updateCalibrationPoint = (
    index: number,
    key: keyof CalibrationPoint,
    value: string,
  ) => {
    if (!calibrationData) return;
    const updated = [...calibrationData.points];
    const point = updated[index];
    if (!point) return;
    updated[index] = {
      ...point,
      [key]: parseNullableNumber(value),
    };
    setCalibrationData({ ...calibrationData, points: updated });
  };

  const handleCalibrationClick = (event: MouseEvent<HTMLDivElement>) => {
    if (!calibrationData) return;
    if (selectedCalibrationIndex === null) {
      appendLog("Select a calibration point before clicking.");
      return;
    }
    const target = event.currentTarget;
    const rect = target.getBoundingClientRect();
    const u = clamp01((event.clientX - rect.left) / rect.width);
    const v = clamp01((event.clientY - rect.top) / rect.height);
    const updated = [...calibrationData.points];
    const point = updated[selectedCalibrationIndex];
    if (!point) return;
    updated[selectedCalibrationIndex] = { ...point, u, v };
    setCalibrationData({ ...calibrationData, points: updated });
    appendLog(
      `Calibration ${point.id} set to u=${u.toFixed(3)}, v=${v.toFixed(3)}`,
    );
  };

  const healthStatus = useMemo(() => {
    if (!health) return "unknown";
    return health.status === "ok" ? "online" : "error";
  }, [health]);

  const scriptValidation = useMemo(() => {
    if (!scriptData) {
      return {
        issues: [] as string[],
        duplicateNames: new Set<string>(),
        emptyNameIndexes: new Set<number>(),
        commandNameSet: new Set<string>(),
        unknownActionsByRule: new Map<number, string[]>(),
      };
    }
    const issues: string[] = [];
    const emptyNameIndexes = new Set<number>();
    const nameCounts = new Map<string, number>();
    scriptData.commands.forEach((command, idx) => {
      const trimmed = command.name.trim();
      if (!trimmed) {
        emptyNameIndexes.add(idx);
        return;
      }
      nameCounts.set(trimmed, (nameCounts.get(trimmed) ?? 0) + 1);
    });
    const duplicateNames = new Set<string>();
    nameCounts.forEach((count, name) => {
      if (count > 1) duplicateNames.add(name);
    });
    emptyNameIndexes.forEach((idx) => {
      issues.push(`Command #${idx + 1} has an empty name.`);
    });
    duplicateNames.forEach((name) => {
      issues.push(`Command name "${name}" is duplicated.`);
    });

    const commandNameSet = new Set<string>(nameCounts.keys());
    const unknownActionsByRule = new Map<number, string[]>();
    scriptData.negative_rules.forEach((rule, idx) => {
      const unknown = rule.action.filter((name) => !commandNameSet.has(name));
      if (unknown.length > 0) {
        unknownActionsByRule.set(idx, unknown);
        const label = rule.id || `#${idx + 1}`;
        issues.push(
          `Negative rule "${label}" references unknown command(s): ${unknown.join(", ")}.`,
        );
      }
    });

    return {
      issues,
      duplicateNames,
      emptyNameIndexes,
      commandNameSet,
      unknownActionsByRule,
    };
  }, [scriptData]);

  const commandNames = useMemo(() => {
    const names = Array.from(scriptValidation.commandNameSet);
    return names.sort((a, b) => a.localeCompare(b));
  }, [scriptValidation.commandNameSet]);

  const filteredCommands = useMemo(() => {
    if (!commandFilter.trim()) return commandNames;
    const lowered = commandFilter.trim().toLowerCase();
    return commandNames.filter((name) => name.toLowerCase().includes(lowered));
  }, [commandNames, commandFilter]);

  const commandSections = useMemo(() => {
    if (!scriptData) return [];
    const query = commandFilter.trim().toLowerCase();
    const source = query
      ? scriptData.commands.filter((command) =>
          command.name.toLowerCase().includes(query),
        )
      : scriptData.commands;
    const sections = new Map<string, CommandEntry[]>();
    source.forEach((command) => {
      const trimmed = command.name.trim();
      const prefix = trimmed.includes("_") ? trimmed.split("_")[0] : trimmed;
      const title = prefix || "Misc";
      if (!sections.has(title)) {
        sections.set(title, []);
      }
      sections.get(title)?.push(command);
    });
    return Array.from(sections.entries()).map(([title, commands]) => ({
      title,
      commands,
    }));
  }, [scriptData, commandFilter]);

  const knownStepKeys = useMemo(() => {
    if (!scriptData) return [];
    const keys = new Set<string>();
    scriptData.commands.forEach((command) => {
      command.steps.forEach((step) => {
        Object.keys(step).forEach((key) => keys.add(key));
      });
    });
    return Array.from(keys).sort((a, b) => a.localeCompare(b));
  }, [scriptData]);

  const addRuleAction = (ruleIndex: number, action: string) => {
    if (!scriptData) return;
    if (!action) return;
    const updated = [...scriptData.negative_rules];
    const rule = updated[ruleIndex];
    if (!rule) return;
    if (rule.action.includes(action)) return;
    updated[ruleIndex] = { ...rule, action: [...rule.action, action] };
    setScriptData({ ...scriptData, negative_rules: updated });
  };

  const removeRuleAction = (ruleIndex: number, action: string) => {
    if (!scriptData) return;
    const updated = [...scriptData.negative_rules];
    const rule = updated[ruleIndex];
    if (!rule) return;
    updated[ruleIndex] = {
      ...rule,
      action: rule.action.filter((item) => item !== action),
    };
    setScriptData({ ...scriptData, negative_rules: updated });
  };

  const addStepField = (
    commandIndex: number,
    stepIndex: number,
    key: string,
    value: string | boolean,
  ) => {
    if (!scriptData) return;
    const updatedCommands = [...scriptData.commands];
    const command = updatedCommands[commandIndex];
    if (!command) return;
    const updatedSteps = [...command.steps];
    const step = updatedSteps[stepIndex];
    if (!step || key in step) return;
    updatedSteps[stepIndex] = { ...step, [key]: value };
    updatedCommands[commandIndex] = { ...command, steps: updatedSteps };
    setScriptData({ ...scriptData, commands: updatedCommands });
  };

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="app-header-content">
          <h1>TeachArm Control Panel</h1>
          <div className="header-info">
            <div className="api-url">
              API: <code>{API_BASE}</code>
            </div>
            <span className={`status-badge ${healthStatus}`}>
              {healthStatus === "online" ? "接続中" : healthStatus === "error" ? "エラー" : "確認中"}
            </span>
          </div>
        </div>
      </header>

      <main>
        <div className="dashboard-grid">
          <Section title="教材選択" icon="📚" className="grid-col-6">
            <div className="materials">
              {materials.length === 0 && (
                <p className="helper-text">教材がありません</p>
              )}
              {materials.map((material) => (
                <button
                  type="button"
                  key={material.material_id}
                  className={material.selected ? "selected" : ""}
                  onClick={() => selectMaterial(material.material_id)}
                  disabled={loading}
                >
                  {material.material_id}
                  <span style={{ opacity: 0.7, marginLeft: "0.5rem" }}>
                    ({material.regions} 領域)
                  </span>
                </button>
              ))}
            </div>
          </Section>

          <Section title="ログ" icon="📋" className="grid-col-6">
            <div className="logs">
              {log.length === 0 && (
                <p className="logs-empty">イベントはまだありません</p>
              )}
              <ul>
                {log.map((entry, index) => (
                  <li key={index}>{entry}</li>
                ))}
              </ul>
            </div>
          </Section>

          <Section title="ポインタイベント" icon="👆" className="grid-col-6">
            <form
              onSubmit={(evt) => {
                evt.preventDefault();
                sendPointer(pointer);
              }}
              className="form-grid"
            >
              <label>
                <span>U 座標</span>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  max="1"
                  value={pointer.u}
                  onChange={(e) =>
                    setPointer((prev) => ({
                      ...prev,
                      u: Number(e.target.value),
                    }))
                  }
                />
              </label>
              <label>
                <span>V 座標</span>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  max="1"
                  value={pointer.v}
                  onChange={(e) =>
                    setPointer((prev) => ({
                      ...prev,
                      v: Number(e.target.value),
                    }))
                  }
                />
              </label>
              <label>
                <span>イベント種別</span>
                <select
                  value={pointer.event}
                  onChange={(e) =>
                    setPointer((prev) => ({
                      ...prev,
                      event: e.target.value as PointerEventPayload["event"],
                    }))
                  }
                >
                  <option value="on_point">on_point</option>
                  <option value="on_help">on_help</option>
                </select>
              </label>
              <button type="submit" className="btn-primary" disabled={loading}>
                送信
              </button>
            </form>
          </Section>

          <Section title="ダイアログ" icon="💬" className="grid-col-6">
            <div className="form-row">
              <label style={{ flex: 1 }}>
                <span>テキスト入力</span>
                <input
                  type="text"
                  placeholder="例: もう一回教えて"
                  value={dialogueText}
                  onChange={(e) => setDialogueText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      sendDialogue();
                    }
                  }}
                />
              </label>
              <button
                type="button"
                className="btn-primary"
                disabled={loading || !dialogueText.trim()}
                onClick={sendDialogue}
                style={{ alignSelf: "flex-end" }}
              >
                送信
              </button>
            </div>
          </Section>

          <Section title="アーム制御" icon="🦾" className="grid-col-12">
            <form
              className="form-grid"
              onSubmit={(evt: FormEvent) => {
                evt.preventDefault();
                moveArm(arm);
              }}
            >
              <label>
                <span>X 座標</span>
                <input
                  type="number"
                  step="0.01"
                  value={arm.x}
                  onChange={(e) =>
                    setArm((prev) => ({ ...prev, x: Number(e.target.value) }))
                  }
                />
              </label>
              <label>
                <span>Y 座標</span>
                <input
                  type="number"
                  step="0.01"
                  value={arm.y}
                  onChange={(e) =>
                    setArm((prev) => ({ ...prev, y: Number(e.target.value) }))
                  }
                />
              </label>
              <label>
                <span>Z 座標</span>
                <input
                  type="number"
                  step="0.01"
                  value={arm.z}
                  onChange={(e) =>
                    setArm((prev) => ({ ...prev, z: Number(e.target.value) }))
                  }
                />
              </label>
              <label>
                <span>速度</span>
                <input
                  type="number"
                  step="0.01"
                  min="0.01"
                  max="1"
                  value={arm.speed}
                  onChange={(e) =>
                    setArm((prev) => ({
                      ...prev,
                      speed: Number(e.target.value),
                    }))
                  }
                />
              </label>
              <button type="submit" className="btn-primary" disabled={loading}>
                移動
              </button>
              <button
                type="button"
                className="btn-success"
                disabled={loading}
                onClick={sendSafePose}
              >
                安全位置へ
              </button>
            </form>
          </Section>

          <Section
            title="座標登録"
            icon="📍"
            className="grid-col-12"
            defaultOpen={false}
          >
            {calibrationLoading && (
              <p className="helper-text">読み込み中...</p>
            )}
            {!calibrationLoading && calibrationData && (
              <div className="calibration">
                <div className="calibration-preview">
                  <label>
                    <span>テキストプレビュー（教材テキストを貼り付け）</span>
                    <textarea
                      rows={4}
                      value={calibrationPreviewText}
                      onChange={(e) =>
                        setCalibrationPreviewText(e.target.value)
                      }
                    />
                  </label>
                  <div
                    className="calibration-board"
                    onClick={handleCalibrationClick}
                  >
                    <div className="calibration-board-content">
                      {calibrationPreviewText || "ここをクリックして座標登録"}
                    </div>
                    {selectedCalibrationIndex !== null &&
                      calibrationData.points[selectedCalibrationIndex] &&
                      calibrationData.points[selectedCalibrationIndex].u !== null &&
                      calibrationData.points[selectedCalibrationIndex].v !== null && (
                        <div
                          className="calibration-marker"
                          style={{
                            left: `${
                              calibrationData.points[selectedCalibrationIndex].u *
                              100
                            }%`,
                            top: `${
                              calibrationData.points[selectedCalibrationIndex].v *
                              100
                            }%`,
                          }}
                        />
                      )}
                  </div>
                  <p className="helper-text">
                    先に表でポイントを選択してから、プレビュー上をクリックしてください。
                  </p>
                </div>
                <div className="calibration-preview">
                  <label>
                    <span>PDFプレビュー（教材PDFを選択）</span>
                    <div className="calibration-row">
                      <select
                        value={selectedAsset}
                        onChange={(e) => setSelectedAsset(e.target.value)}
                        disabled={materialAssets.length === 0}
                      >
                        {materialAssets.length === 0 && (
                          <option value="">PDFが見つかりません</option>
                        )}
                        {materialAssets.map((name) => (
                          <option key={name} value={name}>
                            {name}
                          </option>
                        ))}
                      </select>
                      {selectedAsset && (
                        <a
                          className="btn-link"
                          href={`${API_BASE}/api/materials/assets/${encodeURIComponent(
                            selectedAsset,
                          )}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          新しいタブで開く
                        </a>
                      )}
                    </div>
                  </label>
                  {selectedAsset && (
                    <div className="calibration-pdf">
                      <embed
                        src={`${API_BASE}/api/materials/assets/${encodeURIComponent(
                          selectedAsset,
                        )}`}
                        type="application/pdf"
                        className="calibration-pdf-frame"
                      />
                      <div
                        className="calibration-pdf-overlay"
                        onClick={handleCalibrationClick}
                      >
                        {selectedCalibrationIndex !== null &&
                          calibrationData.points[selectedCalibrationIndex] &&
                          calibrationData.points[selectedCalibrationIndex].u !==
                            null &&
                          calibrationData.points[selectedCalibrationIndex].v !==
                            null && (
                            <div
                              className="calibration-marker"
                              style={{
                                left: `${
                                  calibrationData.points[
                                    selectedCalibrationIndex
                                  ].u * 100
                                }%`,
                                top: `${
                                  calibrationData.points[
                                    selectedCalibrationIndex
                                  ].v * 100
                                }%`,
                              }}
                            />
                          )}
                      </div>
                    </div>
                  )}
                  <p className="helper-text">
                    PDF上のクリックで u/v を登録します（表示範囲に合わせて正規化）。
                  </p>
                </div>
                <div className="calibration-actions">
                  <button
                    type="button"
                    onClick={loadCalibration}
                    disabled={calibrationLoading}
                  >
                    リロード
                  </button>
                  <button
                    type="button"
                    className="btn-success"
                    onClick={saveCalibration}
                    disabled={calibrationLoading}
                  >
                    保存
                  </button>
                </div>
                <div className="calibration-table-wrapper">
                  <table className="calibration-table">
                    <thead>
                      <tr>
                        <th>ID</th>
                        <th>u</th>
                        <th>v</th>
                        <th>x</th>
                        <th>y</th>
                        <th>z</th>
                      </tr>
                    </thead>
                    <tbody>
                      {calibrationData.points.map((point, idx) => (
                        <tr
                          key={point.id}
                          className={
                            selectedCalibrationIndex === idx
                              ? "calibration-selected"
                              : ""
                          }
                          onClick={() => setSelectedCalibrationIndex(idx)}
                        >
                          <td>{point.id}</td>
                          <td>
                            <input
                              type="number"
                              step="0.01"
                              value={point.u ?? ""}
                              onChange={(e) =>
                                updateCalibrationPoint(idx, "u", e.target.value)
                              }
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              step="0.01"
                              value={point.v ?? ""}
                              onChange={(e) =>
                                updateCalibrationPoint(idx, "v", e.target.value)
                              }
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              step="0.01"
                              value={point.x ?? ""}
                              onChange={(e) =>
                                updateCalibrationPoint(idx, "x", e.target.value)
                              }
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              step="0.01"
                              value={point.y ?? ""}
                              onChange={(e) =>
                                updateCalibrationPoint(idx, "y", e.target.value)
                              }
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              step="0.01"
                              value={point.z ?? ""}
                              onChange={(e) =>
                                updateCalibrationPoint(idx, "z", e.target.value)
                              }
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </Section>

          <Section
            title="教材座標編集"
            icon="🎯"
            className="grid-col-12"
            defaultOpen={false}
          >
            <div className="material-editor">
              <div className="material-editor-header">
                <label>
                  <span>編集する教材を選択</span>
                  <select
                    value={editingMaterialId}
                    onChange={(e) => {
                      if (e.target.value) {
                        loadMaterialForEdit(e.target.value);
                      }
                    }}
                  >
                    <option value="">-- 選択してください --</option>
                    {materials.map((m) => (
                      <option key={m.material_id} value={m.material_id}>
                        {m.material_id} ({m.regions} 領域)
                      </option>
                    ))}
                  </select>
                </label>
                {editingMaterial && (
                  <button
                    type="button"
                    className="btn-success"
                    onClick={saveMaterial}
                  >
                    💾 保存
                  </button>
                )}
              </div>

              {editingMaterial && (
                <div className="material-editor-content">
                  <div className="material-editor-left">
                    <h3>PDF プレビュー</h3>
                    {editingMaterial.pdf_file && (
                      <p className="helper-text">
                        📄 {editingMaterial.pdf_file}
                      </p>
                    )}

                    {editingMaterial.pdf_file && (
                      <div
                        className="material-pdf-container"
                        onMouseDown={handlePdfMouseDown}
                        onMouseMove={handlePdfMouseMove}
                        onMouseUp={handlePdfMouseUp}
                        onMouseLeave={() => {
                          setIsDragging(false);
                          setDrawingRect(null);
                          setResizingRegion(null);
                        }}
                      >
                        <object
                          data={`${API_BASE}/api/materials/assets/${encodeURIComponent(
                            editingMaterial.pdf_file,
                          )}#toolbar=0&navpanes=0&scrollbar=0`}
                          type="application/pdf"
                          className="material-pdf-frame"
                        >
                          <p>PDFを表示できません</p>
                        </object>
                        <div className="material-pdf-overlay">
                          {/* 既存の領域を表示 */}
                          {editingMaterial.regions.map((region, idx) => (
                            <div
                              key={idx}
                              className={`material-region-box ${
                                selectedRegionIndex === idx ? "selected" : ""
                              }`}
                              style={{
                                left: `${region.bbox.x * 100}%`,
                                top: `${region.bbox.y * 100}%`,
                                width: `${region.bbox.w * 100}%`,
                                height: `${region.bbox.h * 100}%`,
                              }}
                              onMouseDown={(e) => {
                                e.stopPropagation();
                                setSelectedRegionIndex(idx);
                                setResizingRegion(null); // 前のリサイズ状態をクリア
                                // 矩形本体をドラッグで移動
                                const rect = e.currentTarget.parentElement!.getBoundingClientRect();
                                const x = clamp01((e.clientX - rect.left) / rect.width);
                                const y = clamp01((e.clientY - rect.top) / rect.height);
                                setResizingRegion({
                                  index: idx,
                                  handle: "move",
                                  startX: x,
                                  startY: y,
                                  originalBbox: { ...region.bbox },
                                });
                              }}
                            >
                              <span className="material-region-label">
                                {region.id} {selectedRegionIndex === idx ? "✓" : ""}
                              </span>
                              {/* リサイズハンドル (選択中のみ表示) */}
                              {selectedRegionIndex === idx && (
                                <>
                                  {["nw", "ne", "sw", "se"].map((handle) => (
                                    <div
                                      key={handle}
                                      className={`material-resize-handle handle-${handle}`}
                                      onMouseDown={(e) => {
                                        e.stopPropagation();
                                        const rect = e.currentTarget.parentElement!.parentElement!.getBoundingClientRect();
                                        const x = clamp01((e.clientX - rect.left) / rect.width);
                                        const y = clamp01((e.clientY - rect.top) / rect.height);
                                        setResizingRegion({
                                          index: idx,
                                          handle: handle as "nw" | "ne" | "sw" | "se",
                                          startX: x,
                                          startY: y,
                                          originalBbox: { ...region.bbox },
                                        });
                                      }}
                                    />
                                  ))}
                                </>
                              )}
                            </div>
                          ))}
                          {/* ドラッグ中の矩形 */}
                          {drawingRect && (
                            <div
                              className="material-region-box drawing"
                              style={{
                                left: `${Math.min(drawingRect.startX, drawingRect.endX) * 100}%`,
                                top: `${Math.min(drawingRect.startY, drawingRect.endY) * 100}%`,
                                width: `${Math.abs(drawingRect.endX - drawingRect.startX) * 100}%`,
                                height: `${Math.abs(drawingRect.endY - drawingRect.startY) * 100}%`,
                              }}
                            />
                          )}
                        </div>
                      </div>
                    )}
                    <p className="helper-text">
                      💡 PDF上でドラッグして矩形を追加 | 矩形をドラッグで移動 | 四隅の○をドラッグでリサイズ
                    </p>
                  </div>

                  <div className="material-editor-right">
                    <h3>領域一覧 ({editingMaterial.regions.length})</h3>
                    <div className="material-regions-list">
                      {editingMaterial.regions.map((region, idx) => (
                        <div
                          key={idx}
                          className={`material-region-item ${
                            selectedRegionIndex === idx ? "selected" : ""
                          }`}
                          onClick={() => {
                            setSelectedRegionIndex(idx);
                            setResizingRegion(null); // 前のリサイズ状態をクリア
                          }}
                        >
                          <div className="material-region-header">
                            <strong>{region.id}</strong>
                            <button
                              type="button"
                              className="btn-danger btn-sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                if (
                                  confirm(`領域 ${region.id} を削除しますか？`)
                                ) {
                                  deleteRegion(idx);
                                }
                              }}
                            >
                              🗑️
                            </button>
                          </div>
                          {selectedRegionIndex === idx && (
                            <div className="material-region-form">
                              <label>
                                <span>ID</span>
                                <input
                                  type="text"
                                  value={region.id}
                                  onChange={(e) =>
                                    updateRegion(idx, { id: e.target.value })
                                  }
                                />
                              </label>
                              <label>
                                <span>タイプ</span>
                                <select
                                  value={region.type}
                                  onChange={(e) =>
                                    updateRegion(idx, { type: e.target.value })
                                  }
                                >
                                  <option value="instruction">instruction (大問指示)</option>
                                  <option value="question">question (設問)</option>
                                  <option value="choice">choice (選択肢)</option>
                                  <option value="paragraph">paragraph (段落)</option>
                                  <option value="line">line (行)</option>
                                  <option value="word">word (単語)</option>
                                  <option value="diagram">diagram (図表)</option>
                                </select>
                              </label>
                              <label>
                                <span>ラベル (任意)</span>
                                <input
                                  type="text"
                                  value={region.label || ""}
                                  onChange={(e) =>
                                    updateRegion(idx, { label: e.target.value })
                                  }
                                />
                              </label>
                              <div className="bbox-grid">
                                <label>
                                  <span>x</span>
                                  <input
                                    type="number"
                                    step="0.01"
                                    min="0"
                                    max="1"
                                    value={region.bbox.x}
                                    onChange={(e) =>
                                      updateRegion(idx, {
                                        bbox: {
                                          ...region.bbox,
                                          x: Number(e.target.value),
                                        },
                                      })
                                    }
                                  />
                                </label>
                                <label>
                                  <span>y</span>
                                  <input
                                    type="number"
                                    step="0.01"
                                    min="0"
                                    max="1"
                                    value={region.bbox.y}
                                    onChange={(e) =>
                                      updateRegion(idx, {
                                        bbox: {
                                          ...region.bbox,
                                          y: Number(e.target.value),
                                        },
                                      })
                                    }
                                  />
                                </label>
                                <label>
                                  <span>w</span>
                                  <input
                                    type="number"
                                    step="0.01"
                                    min="0"
                                    max="1"
                                    value={region.bbox.w}
                                    onChange={(e) =>
                                      updateRegion(idx, {
                                        bbox: {
                                          ...region.bbox,
                                          w: Number(e.target.value),
                                        },
                                      })
                                    }
                                  />
                                </label>
                                <label>
                                  <span>h</span>
                                  <input
                                    type="number"
                                    step="0.01"
                                    min="0"
                                    max="1"
                                    value={region.bbox.h}
                                    onChange={(e) =>
                                      updateRegion(idx, {
                                        bbox: {
                                          ...region.bbox,
                                          h: Number(e.target.value),
                                        },
                                      })
                                    }
                                  />
                                </label>
                              </div>
                              <label>
                                <span>on_point (カンマ区切り)</span>
                                <input
                                  type="text"
                                  value={region.on_point.join(", ")}
                                  onChange={(e) =>
                                    updateRegion(idx, {
                                      on_point: e.target.value
                                        .split(",")
                                        .map((s) => s.trim())
                                        .filter((s) => s),
                                    })
                                  }
                                  placeholder="例: Q1_INTRO, SAY_HELLO"
                                />
                              </label>
                              <label>
                                <span>on_help (カンマ区切り)</span>
                                <input
                                  type="text"
                                  value={region.on_help.join(", ")}
                                  onChange={(e) =>
                                    updateRegion(idx, {
                                      on_help: e.target.value
                                        .split(",")
                                        .map((s) => s.trim())
                                        .filter((s) => s),
                                    })
                                  }
                                  placeholder="例: Q1_HINT"
                                />
                              </label>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                    {editingMaterial.regions.length === 0 && (
                      <p className="helper-text">
                        領域がありません。PDF上でドラッグして追加してください。
                      </p>
                    )}
                  </div>
                </div>
              )}

              {!editingMaterial && (
                <p className="helper-text">
                  教材を選択してください。
                </p>
              )}
            </div>
          </Section>

          <Section
            title="スクリプトエディタ"
            icon="📝"
            className="grid-col-12"
            defaultOpen={false}
          >
            {scriptLoading && <p className="helper-text">読み込み中...</p>}
            {!scriptLoading && scriptData && (
              <div className="script-form">
                <p className="script-path">📁 {scriptPath}</p>

                <h3>ロール設定</h3>
                <div className="form-grid form-grid-2">
                  <label>
                    <span>名前</span>
                    <input
                      type="text"
                      value={scriptData.role.name}
                      onChange={(e) =>
                        setScriptData({
                          ...scriptData,
                          role: { ...scriptData.role, name: e.target.value },
                        })
                      }
                    />
                  </label>
                  <label>
                    <span>トーン</span>
                    <input
                      type="text"
                      value={scriptData.role.tone}
                      onChange={(e) =>
                        setScriptData({
                          ...scriptData,
                          role: { ...scriptData.role, tone: e.target.value },
                        })
                      }
                    />
                  </label>
                </div>
                <label>
                  <span>ルール（1行に1ルール）</span>
                  <textarea
                    rows={4}
                    value={scriptData.role.rules.join("\n")}
                    onChange={(e) =>
                      setScriptData({
                        ...scriptData,
                        role: {
                          ...scriptData.role,
                          rules: e.target.value
                            .split("\n")
                            .map((line) => line.trim())
                            .filter(Boolean),
                        },
                      })
                    }
                  />
                </label>

                <h3>トピック判定</h3>
                <label>
                  <span>挨拶時の返答</span>
                  <input
                    type="text"
                    value={scriptData.intent.greeting_reply}
                    onChange={(e) =>
                      setScriptData({
                        ...scriptData,
                        intent: {
                          ...scriptData.intent,
                          greeting_reply: e.target.value,
                        },
                      })
                    }
                  />
                </label>
                <label>
                  <span>フォールバック返答</span>
                  <input
                    type="text"
                    value={scriptData.intent.fallback_reply}
                    onChange={(e) =>
                      setScriptData({
                        ...scriptData,
                        intent: {
                          ...scriptData.intent,
                          fallback_reply: e.target.value,
                        },
                      })
                    }
                  />
                </label>
                <label>
                  <span>挨拶語（1行に1語）</span>
                  <textarea
                    rows={4}
                    value={scriptData.intent.greeting_terms.join("\n")}
                    onChange={(e) =>
                      setScriptData({
                        ...scriptData,
                        intent: {
                          ...scriptData.intent,
                          greeting_terms: e.target.value
                            .split("\n")
                            .map((line) => line.trim())
                            .filter(Boolean),
                        },
                      })
                    }
                  />
                </label>
                <label>
                  <span>ON_TOPIC 例（1行に1項目）</span>
                  <textarea
                    rows={4}
                    value={scriptData.intent.on_topic.join("\n")}
                    onChange={(e) =>
                      setScriptData({
                        ...scriptData,
                        intent: {
                          ...scriptData.intent,
                          on_topic: e.target.value
                            .split("\n")
                            .map((line) => line.trim())
                            .filter(Boolean),
                        },
                      })
                    }
                  />
                </label>
                <label>
                  <span>OFF_TOPIC 例（1行に1項目）</span>
                  <textarea
                    rows={4}
                    value={scriptData.intent.off_topic.join("\n")}
                    onChange={(e) =>
                      setScriptData({
                        ...scriptData,
                        intent: {
                          ...scriptData.intent,
                          off_topic: e.target.value
                            .split("\n")
                            .map((line) => line.trim())
                            .filter(Boolean),
                        },
                      })
                    }
                  />
                </label>

                <h3>ネガティブルール</h3>
                {scriptData.negative_rules.map((rule, idx) => (
                  <div className="negative-rule" key={idx}>
                    <div className="form-grid form-grid-2">
                      <label>
                        <span>ID</span>
                        <input
                          type="text"
                          value={rule.id}
                          onChange={(e) => {
                            const updated = [...scriptData.negative_rules];
                            updated[idx] = { ...rule, id: e.target.value };
                            setScriptData({
                              ...scriptData,
                              negative_rules: updated,
                            });
                          }}
                        />
                      </label>
                      <label>
                        <span>条件 (when)</span>
                        <input
                          type="text"
                          value={rule.when}
                          onChange={(e) => {
                            const updated = [...scriptData.negative_rules];
                            updated[idx] = { ...rule, when: e.target.value };
                            setScriptData({
                              ...scriptData,
                              negative_rules: updated,
                            });
                          }}
                        />
                      </label>
                    </div>
                    <label>
                      <span>アクション（コマンド）</span>
                      <div className="chip-row">
                        {rule.action.length === 0 && (
                          <span className="chip muted">アクションなし</span>
                        )}
                        {rule.action.map((action) => {
                          const isUnknown =
                            !scriptValidation.commandNameSet.has(action);
                          return (
                            <button
                              type="button"
                              key={`${rule.id}-${action}`}
                              className={`chip clickable ${isUnknown ? "unknown" : ""}`}
                              onClick={() => removeRuleAction(idx, action)}
                              title="クリックで削除"
                            >
                              {action} ×
                            </button>
                          );
                        })}
                      </div>
                      <div className="action-row">
                        <select
                          value={actionDrafts[idx] ?? ""}
                          onChange={(e) =>
                            setActionDrafts((prev) => ({
                              ...prev,
                              [idx]: e.target.value,
                            }))
                          }
                          disabled={commandNames.length === 0}
                        >
                          <option value="">アクションを追加...</option>
                          {commandNames.map((name) => (
                            <option key={`${rule.id}-${name}`} value={name}>
                              {name}
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          onClick={() => {
                            const selected = actionDrafts[idx];
                            if (!selected) return;
                            addRuleAction(idx, selected);
                            setActionDrafts((prev) => ({ ...prev, [idx]: "" }));
                          }}
                          disabled={!actionDrafts[idx]}
                        >
                          追加
                        </button>
                      </div>
                    </label>
                    <button
                      type="button"
                      className="btn-danger btn-sm"
                      onClick={() => {
                        const updated = scriptData.negative_rules.filter(
                          (_, ridx) => ridx !== idx
                        );
                        setScriptData({
                          ...scriptData,
                          negative_rules: updated,
                        });
                      }}
                    >
                      ルールを削除
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() =>
                    setScriptData({
                      ...scriptData,
                      negative_rules: [
                        ...scriptData.negative_rules,
                        { id: "NEW_RULE", when: "", action: [] },
                      ],
                    })
                  }
                >
                  ネガティブルールを追加
                </button>

                <h3>コマンド一覧</h3>
                <div className="command-meta">
                  <span>{commandNames.length} 件のコマンド</span>
                  <input
                    type="text"
                    placeholder="🔍 コマンドを検索..."
                    value={commandFilter}
                    onChange={(e) => setCommandFilter(e.target.value)}
                  />
                </div>
                <div className="command-list">
                  {filteredCommands.length === 0 && (
                    <span className="chip muted">該当なし</span>
                  )}
                  {filteredCommands.map((name) => (
                    <span key={`known-${name}`} className="chip">
                      {name}
                    </span>
                  ))}
                </div>
                {knownStepKeys.length > 0 && (
                  <p className="helper-text">
                    利用可能なステップキー: {knownStepKeys.join(", ")}
                  </p>
                )}
                {scriptValidation.issues.length > 0 && (
                  <div className="script-issues">
                    <strong>⚠️ 保存前に修正してください</strong>
                    <ul>
                      {scriptValidation.issues.map((issue) => (
                        <li key={issue}>{issue}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {commandSections.map((section) => (
                  <div className="command-section" key={section.title}>
                    <div className="command-section-header">
                      <h4>{section.title}</h4>
                      <span>{section.commands.length} コマンド</span>
                    </div>
                    {section.commands.map((command) => {
                      const cIdx = scriptData.commands.indexOf(command);
                      return (
                        <div
                          className="command-card"
                          key={`${command.name}-${cIdx}`}
                        >
                          <div className="command-title">
                            <h4>{command.name.trim() || "名前未設定"}</h4>
                            <div className="command-title-actions">
                              <button
                                type="button"
                                className="btn-sm"
                                onClick={() => {
                                  const newName = window.prompt(
                                    "コマンド名を入力してください",
                                    command.name
                                  );
                                  if (newName === null) return;
                                  const updated = [...scriptData.commands];
                                  updated[cIdx] = {
                                    ...command,
                                    name: newName.trim(),
                                  };
                                  setScriptData({
                                    ...scriptData,
                                    commands: updated,
                                  });
                                }}
                              >
                                名前変更
                              </button>
                              <button
                                type="button"
                                className="btn-danger btn-sm"
                                onClick={() =>
                                  setScriptData({
                                    ...scriptData,
                                    commands: scriptData.commands.filter(
                                      (_, idx) => idx !== cIdx
                                    ),
                                  })
                                }
                              >
                                削除
                              </button>
                            </div>
                          </div>
                          {command.steps.map((step, sIdx) => (
                            <div
                              className="command-step"
                              key={`${command.name}-${sIdx}`}
                            >
                              <div className="command-step-header">
                                <span>ステップ {sIdx + 1}</span>
                                <button
                                  type="button"
                                  className="btn-sm btn-danger"
                                  onClick={() => {
                                    const updatedCommands = [
                                      ...scriptData.commands,
                                    ];
                                    const newSteps = command.steps.filter(
                                      (_, idx) => idx !== sIdx
                                    );
                                    updatedCommands[cIdx] = {
                                      ...command,
                                      steps: newSteps,
                                    };
                                    setScriptData({
                                      ...scriptData,
                                      commands: updatedCommands,
                                    });
                                  }}
                                >
                                  ステップ削除
                                </button>
                              </div>
                              {Object.entries(step).map(([key, value]) => (
                                <div
                                  className="step-field"
                                  key={`${key}-${sIdx}`}
                                >
                                  <label>
                                    <span>{key}</span>
                                    {typeof value === "boolean" ? (
                                      <input
                                        type="checkbox"
                                        checked={value}
                                        onChange={(e) => {
                                          const updatedCommands = [
                                            ...scriptData.commands,
                                          ];
                                          const updatedSteps = [
                                            ...command.steps,
                                          ];
                                          updatedSteps[sIdx] = {
                                            ...step,
                                            [key]: e.target.checked,
                                          };
                                          updatedCommands[cIdx] = {
                                            ...command,
                                            steps: updatedSteps,
                                          };
                                          setScriptData({
                                            ...scriptData,
                                            commands: updatedCommands,
                                          });
                                        }}
                                      />
                                    ) : (
                                      <input
                                        type="text"
                                        value={String(value)}
                                        onChange={(e) => {
                                          const updatedCommands = [
                                            ...scriptData.commands,
                                          ];
                                          const updatedSteps = [
                                            ...command.steps,
                                          ];
                                          updatedSteps[sIdx] = {
                                            ...step,
                                            [key]: e.target.value,
                                          };
                                          updatedCommands[cIdx] = {
                                            ...command,
                                            steps: updatedSteps,
                                          };
                                          setScriptData({
                                            ...scriptData,
                                            commands: updatedCommands,
                                          });
                                        }}
                                      />
                                    )}
                                  </label>
                                </div>
                              ))}
                              <div className="step-actions">
                                <button
                                  type="button"
                                  className="btn-sm"
                                  onClick={() =>
                                    addStepField(cIdx, sIdx, "SAY", "")
                                  }
                                  disabled={"SAY" in step}
                                >
                                  + SAY
                                </button>
                                <button
                                  type="button"
                                  className="btn-sm"
                                  onClick={() =>
                                    addStepField(
                                      cIdx,
                                      sIdx,
                                      "ARM_POINT_CENTER",
                                      true
                                    )
                                  }
                                  disabled={"ARM_POINT_CENTER" in step}
                                >
                                  + ARM_POINT_CENTER
                                </button>
                                <button
                                  type="button"
                                  className="btn-sm"
                                  onClick={() => {
                                    const newKey = window.prompt(
                                      "新しいフィールド名（例: SAY）"
                                    );
                                    if (!newKey) return;
                                    addStepField(cIdx, sIdx, newKey, "");
                                  }}
                                >
                                  + カスタム
                                </button>
                              </div>
                            </div>
                          ))}
                          <button
                            type="button"
                            className="btn-sm"
                            onClick={() => {
                              const updatedCommands = [...scriptData.commands];
                              updatedCommands[cIdx] = {
                                ...command,
                                steps: [...command.steps, { SAY: "" }],
                              };
                              setScriptData({
                                ...scriptData,
                                commands: updatedCommands,
                              });
                            }}
                          >
                            + ステップを追加
                          </button>
                        </div>
                      );
                    })}
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() =>
                    setScriptData({
                      ...scriptData,
                      commands: [
                        ...scriptData.commands,
                        {
                          name: `command_${scriptData.commands.length + 1}`,
                          steps: [{ SAY: "" }],
                        },
                      ],
                    })
                  }
                >
                  + 新規コマンド
                </button>

                <div className="script-actions">
                  <button
                    type="button"
                    onClick={loadScript}
                    disabled={scriptLoading}
                  >
                    リロード
                  </button>
                  <button
                    type="button"
                    className="btn-success"
                    onClick={saveScript}
                    disabled={
                      scriptLoading || scriptValidation.issues.length > 0
                    }
                  >
                    保存
                  </button>
                </div>
                <p className="helper-text">
                  保存内容は即時反映されます。反映されない場合は API の再起動
                  （コード変更時）や API Base の接続先を確認してください。
                </p>

                <details className="raw-yaml">
                  <summary>📄 YAML プレビュー</summary>
                  <pre>{rawYaml}</pre>
                </details>
              </div>
            )}
          </Section>
        </div>
      </main>
    </div>
  );
}

function normalizeScript(data: Record<string, any>): ScriptData {
  const rawRole = data.role ?? {};
  const role = {
    name: rawRole.name ?? "",
    tone: rawRole.tone ?? "",
    rules: Array.isArray(rawRole.rules) ? rawRole.rules : [],
  };
  const rawIntent = data.intent ?? {};
  const intent = {
    greeting_reply:
      rawIntent.greeting_reply ??
      "こんにちは！今日はどの教材の、どのあたりで困ってる？（文章/選択肢/言葉など）",
    fallback_reply:
      rawIntent.fallback_reply ??
      "どの教材のどこが気になる？（文章/選択肢/言葉）",
    greeting_terms: Array.isArray(rawIntent.greeting_terms)
      ? rawIntent.greeting_terms
      : ["こんにちは", "おはよう", "こんばんは", "やあ", "はじめまして", "こんちは"],
    on_topic: Array.isArray(rawIntent.on_topic)
      ? rawIntent.on_topic
      : [
          "教材の内容",
          "問題",
          "このアプリの使い方",
          "学習の進め方",
          "TeachArmの操作",
        ],
    off_topic: Array.isArray(rawIntent.off_topic)
      ? rawIntent.off_topic
      : [
          "ゲームに誘う",
          "雑談を続ける",
          "学習と無関係な話題（天気/恋バナ/暇つぶし等）",
        ],
  };
  const negative =
    Array.isArray(data.negative_rules) && data.negative_rules.length > 0
      ? data.negative_rules.map((rule: any) => ({
          id: rule.id ?? "",
          when: rule.when ?? "",
          action: Array.isArray(rule.action) ? rule.action : [],
        }))
      : [];
  const commandsEntries = Object.entries<Record<string, any>[]>(
    data.commands ?? {},
  ).map(([name, steps]) => ({
    name,
    steps: steps.map((step) => ({ ...step })),
  }));
  return {
    role,
    intent,
    negative_rules: negative,
    commands: commandsEntries,
  };
}

function denormalizeScript(script: ScriptData): Record<string, any> {
  const commands = script.commands.reduce<Record<string, CommandStep[]>>(
    (acc, entry) => {
      acc[entry.name] = entry.steps;
      return acc;
    },
    {},
  );
  return {
    role: script.role,
    intent: script.intent,
    negative_rules: script.negative_rules,
    commands,
  };
}
