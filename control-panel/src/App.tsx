import { FormEvent, useEffect, useMemo, useState } from "react";
import { dump as dumpYAML, load as loadYAML } from "js-yaml";

type MaterialSummary = {
  material_id: string;
  regions: number;
  selected: boolean;
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

type ScriptData = {
  role: {
    name: string;
    tone: string;
    rules: string[];
  };
  negative_rules: NegativeRule[];
  commands: CommandEntry[];
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

const API_BASE =
  import.meta.env.VITE_TEACHARM_API_URL ?? "http://localhost:8000";

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
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="section">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [materials, setMaterials] = useState<MaterialSummary[]>([]);
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
  const [dialogueText, setDialogueText] = useState("");
  const [loading, setLoading] = useState(false);
  const [scriptPath, setScriptPath] = useState("");
  const [scriptLoading, setScriptLoading] = useState(false);
  const [scriptData, setScriptData] = useState<ScriptData | null>(null);
  const [rawYaml, setRawYaml] = useState("");

  const appendLog = (message: string) => {
    setLog((prev) => [`${new Date().toLocaleTimeString()} ${message}`, ...prev]);
  };

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

  useEffect(() => {
    loadHealth();
    loadMaterials();
    loadScript();
    const timer = setInterval(() => {
      loadHealth();
    }, 5000);
    return () => clearInterval(timer);
  }, []);

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

  const healthStatus = useMemo(() => {
    if (!health) return "unknown";
    return health.status === "ok" ? "online" : "error";
  }, [health]);

  return (
    <main>
      <header>
        <h1>TeachArm Control Panel</h1>
        <p>API Base: {API_BASE}</p>
        <p>Status: {healthStatus}</p>
      </header>

      <Section title="Materials">
        <div className="materials">
          {materials.map((material) => (
            <button
              type="button"
              key={material.material_id}
              className={material.selected ? "selected" : ""}
              onClick={() => selectMaterial(material.material_id)}
              disabled={loading}
            >
              {material.material_id} ({material.regions})
            </button>
          ))}
        </div>
      </Section>

      <Section title="Pointer Event (manual)">
        <form
          onSubmit={(evt) => {
            evt.preventDefault();
            sendPointer(pointer);
          }}
          className="form-grid"
        >
          <label>
            u
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
            v
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
            event
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
          <button type="submit" disabled={loading}>
            Send
          </button>
        </form>
      </Section>

      <Section title="Dialogue Command">
        <div className="form-grid">
          <input
            type="text"
            placeholder="例: もう一回"
            value={dialogueText}
            onChange={(e) => setDialogueText(e.target.value)}
          />
          <button type="button" disabled={loading} onClick={sendDialogue}>
            Send Dialogue
          </button>
        </div>
      </Section>

      <Section title="Arm Control">
        <form
          className="form-grid"
          onSubmit={(evt: FormEvent) => {
            evt.preventDefault();
            moveArm(arm);
          }}
        >
          <label>
            x
            <input
              type="number"
              value={arm.x}
              onChange={(e) =>
                setArm((prev) => ({ ...prev, x: Number(e.target.value) }))
              }
            />
          </label>
          <label>
            y
            <input
              type="number"
              value={arm.y}
              onChange={(e) =>
                setArm((prev) => ({ ...prev, y: Number(e.target.value) }))
              }
            />
          </label>
          <label>
            z
            <input
              type="number"
              value={arm.z}
              onChange={(e) =>
                setArm((prev) => ({ ...prev, z: Number(e.target.value) }))
              }
            />
          </label>
          <label>
            speed
            <input
              type="number"
              step="0.01"
              value={arm.speed}
              onChange={(e) =>
                setArm((prev) => ({ ...prev, speed: Number(e.target.value) }))
              }
            />
          </label>
          <button type="submit" disabled={loading}>
            Move Arm
          </button>
          <button type="button" disabled={loading} onClick={sendSafePose}>
            Go Safe Pose
          </button>
        </form>
      </Section>

      <Section title="Logs">
        <div className="logs">
          {log.length === 0 && <p>No events yet.</p>}
          <ul>
            {log.map((entry, index) => (
              <li key={index}>{entry}</li>
            ))}
          </ul>
        </div>
      </Section>

      <Section title="Script Editor (common.yaml)">
        {scriptLoading && <p>Loading script...</p>}
        {!scriptLoading && scriptData && (
          <div className="script-form">
            <p className="script-path">{scriptPath}</p>
            <h3>Role</h3>
            <div className="form-grid">
              <label>
                名前
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
                トーン
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
              ルール（1 行につき 1 ルール）
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

            <h3>Negative Rules</h3>
            {scriptData.negative_rules.map((rule, idx) => (
              <div className="negative-rule" key={idx}>
                <div className="form-grid">
                  <label>
                    ID
                    <input
                      type="text"
                      value={rule.id}
                      onChange={(e) => {
                        const updated = [...scriptData.negative_rules];
                        updated[idx] = { ...rule, id: e.target.value };
                        setScriptData({ ...scriptData, negative_rules: updated });
                      }}
                    />
                  </label>
                  <label>
                    条件 (when)
                    <input
                      type="text"
                      value={rule.when}
                      onChange={(e) => {
                        const updated = [...scriptData.negative_rules];
                        updated[idx] = { ...rule, when: e.target.value };
                        setScriptData({ ...scriptData, negative_rules: updated });
                      }}
                    />
                  </label>
                </div>
                <label>
                  Action（カンマ区切り）
                  <input
                    type="text"
                    value={rule.action.join(", ")}
                    onChange={(e) => {
                      const updated = [...scriptData.negative_rules];
                      updated[idx] = {
                        ...rule,
                        action: e.target.value
                          .split(",")
                          .map((item) => item.trim())
                          .filter(Boolean),
                      };
                      setScriptData({ ...scriptData, negative_rules: updated });
                    }}
                  />
                </label>
                <button
                  type="button"
                  onClick={() => {
                    const updated = scriptData.negative_rules.filter(
                      (_, ridx) => ridx !== idx,
                    );
                    setScriptData({ ...scriptData, negative_rules: updated });
                  }}
                >
                  Remove Rule
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
              Add Negative Rule
            </button>

            <h3>Commands</h3>
            {scriptData.commands.map((command, cIdx) => (
              <div className="command-card" key={`${command.name}-${cIdx}`}>
                <div className="form-grid">
                  <label>
                    コマンド名
                    <input
                      type="text"
                      value={command.name}
                      onChange={(e) => {
                        const updated = [...scriptData.commands];
                        updated[cIdx] = { ...command, name: e.target.value };
                        setScriptData({ ...scriptData, commands: updated });
                      }}
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() =>
                      setScriptData({
                        ...scriptData,
                        commands: scriptData.commands.filter(
                          (_, idx) => idx !== cIdx,
                        ),
                      })
                    }
                  >
                    Remove Command
                  </button>
                </div>
                {command.steps.map((step, sIdx) => (
                  <div className="command-step" key={`${command.name}-${sIdx}`}>
                    <div className="command-step-header">
                      <span>Step {sIdx + 1}</span>
                      <button
                        type="button"
                        onClick={() => {
                          const updatedCommands = [...scriptData.commands];
                          const newSteps = command.steps.filter(
                            (_, idx) => idx !== sIdx,
                          );
                          updatedCommands[cIdx] = {
                            ...command,
                            steps: newSteps,
                          };
                          setScriptData({ ...scriptData, commands: updatedCommands });
                        }}
                      >
                        Remove Step
                      </button>
                    </div>
                    {Object.entries(step).map(([key, value]) => (
                      <div className="step-field" key={`${key}-${sIdx}`}>
                        <label>
                          {key}
                          {typeof value === "boolean" ? (
                            <input
                              type="checkbox"
                              checked={value}
                              onChange={(e) => {
                                const updatedCommands = [...scriptData.commands];
                                const updatedSteps = [...command.steps];
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
                                const updatedCommands = [...scriptData.commands];
                                const updatedSteps = [...command.steps];
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
                    <button
                      type="button"
                      onClick={() => {
                        const newKey = window.prompt("新しいフィールド名（例: SAY）");
                        if (!newKey) return;
                        const updatedCommands = [...scriptData.commands];
                        const updatedSteps = [...command.steps];
                        updatedSteps[sIdx] = { ...step, [newKey]: "" };
                        updatedCommands[cIdx] = {
                          ...command,
                          steps: updatedSteps,
                        };
                        setScriptData({ ...scriptData, commands: updatedCommands });
                      }}
                    >
                      Add Field
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() => {
                    const updatedCommands = [...scriptData.commands];
                    updatedCommands[cIdx] = {
                      ...command,
                      steps: [...command.steps, { SAY: "" }],
                    };
                    setScriptData({ ...scriptData, commands: updatedCommands });
                  }}
                >
                  Add Step
                </button>
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
              Add Command
            </button>

            <div className="script-actions">
              <button type="button" onClick={loadScript} disabled={scriptLoading}>
                Reload
              </button>
              <button type="button" onClick={saveScript} disabled={scriptLoading}>
                Save
              </button>
            </div>

            <details className="raw-yaml">
              <summary>YAML Preview</summary>
              <pre>{rawYaml}</pre>
            </details>
          </div>
        )}
      </Section>
    </main>
  );
}

function normalizeScript(data: Record<string, any>): ScriptData {
  const rawRole = data.role ?? {};
  const role = {
    name: rawRole.name ?? "",
    tone: rawRole.tone ?? "",
    rules: Array.isArray(rawRole.rules) ? rawRole.rules : [],
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
    negative_rules: script.negative_rules,
    commands,
  };
}
