# TeachArm AI Coding Guidelines

## Architecture Overview
TeachArm is a robotics education system for interactive learning with robotic arm assistance. It combines:
- **FastAPI backend** (`teacharm/`) with async service orchestration
- **React frontend** (`control-panel/`) for monitoring and manual control
- **Dialogue system**: Router (rule-based) → Script → DeepSeek (self-hosted via Tailscale)
- **Vision system**: ArUco marker detection + MediaPipe hand tracking for pointer recognition
- **Robotic arm**: SO-101 (6-DOF, Feetech STS3215 servos) controlled via LeRobot

**Data flow**: Material region pointer events (vision) → Router decision → Script lookup → TTS output (VOICEVOX) + Arm commands

## Key Components
- `teacharm/server.py`: FastAPI app assembly, CORS, route handlers for materials/dialogue/arm
- `teacharm/services/router.py`: Rule-based action dispatcher (script/DeepSeek selection)
- `teacharm/services/dialogue.py`: Orchestration: Router → Script → DeepSeek
- `teacharm/services/vision.py`: ArUco + MediaPipe hand detection, perspective transforms
- `teacharm/services/arm.py`: SO-101 kinematics & motor control
- `teacharm/services/tts.py`: VOICEVOX synthesis with disk cache
- `teacharm/config.py`: Pydantic BaseSettings for env-driven config
- `teacharm/state.py`: AppState container for runtime mutable state
- `materials/material_A.json`: Region definitions with bounding boxes (normalized 0-1)
- `scripts/common.yaml`: Dialogue scripts, intents, error recovery commands

## Dialogue System (Critical Pattern)
**Why**: Offline rule-based routing ensures demo stability; DeepSeek handles edge cases only.

**Flow**:
1. Region pointer event triggers `dialogue_service.on_region_event(region, event)`
2. Router evaluates `RouterInput` (state, ASR text, region ID, error codes) → determines action
3. Actions: `respond_script`, `generate_explanation`, `recover_suggest`, `repeat_last`, `reject`, `clarify`
4. If `respond_script`: look up script commands (e.g., `SAY`, `ARM_POINT_CENTER`) in `scripts/common.yaml`
5. If `generate_explanation`: call DeepSeek only if script unavailable
6. Response includes text, commands list, source metadata (for stats/debugging)

**Key insight**: Router is always called first. DeepSeek is fallback only.

## Configuration & Paths
Settings loaded from `.env` via Pydantic `BaseSettings` in `teacharm/config.py`.

**Pattern**: Paths resolved relative to `data_root` (default: project root).
```python
material_path = settings.resolve_path(settings.materials_dir)  # → "materials/"
```

**Critical env vars**:
- `OLLAMA_BASE_URL`, `OLLAMA_MODEL`: Router LLM backend (Ollama or DeepSeek)
- `VOICEVOX_BASE_URL`: TTS service (e.g., `http://127.0.0.1:50021`)
- `VOICEVOX_SPEAKER_NAME`, `VOICEVOX_STYLE_NAME`: Voice selection (e.g., "春日部つむぎ")
- `VISION_OFFLOAD_URL`: Optional remote vision processing
- `CONTROL_PANEL_URL`: Tailscale IP for frontend access
- `SO101_PORT`, `SO101_BAUDRATE`: Serial USB settings for arm

## Material & Region Handling
Materials are JSON files defining regions (clickable/pointable areas on curriculum PDFs).

**Region structure** (normalized 0-1 coords):
```json
{
  "id": "paragraph1",
  "type": "paragraph",
  "bbox": {"x": 0.05, "y": 0.05, "w": 0.9, "h": 0.25},
  "on_point": ["Q_INTRO"],
  "on_help": ["Q_HELP"],
  "extracted_text": "Optional PDF text"
}
```

**Bounding box validation**: `BoundingBox.contains(u, v)` checks normalized coords. Always validate u,v ∈ [0,1].

## Script Commands & Error Recovery
Scripts in `scripts/common.yaml` define teacher responses and arm actions.

**Common commands**:
- `SAY: "text"` – Speak via VOICEVOX
- `ARM_POINT_CENTER: true` – Arm moves to region center
- `ARM_SAFE_POSE: true` – Return to safe position

**Error codes** (from Vision/Arm):
- `E_CAM`: Camera not detected
- `E_MARKER`: ArUco markers out of frame
- `E_HAND`: Hand not detected
- `E_ARM`: Arm connection failed
- `E_INTERNAL`: Generic failure

Error recovery is hardcoded in `scripts/common.yaml` and triggered by Router action `recover_suggest`.

## Service Integration Pattern
All services initialize in `teacharm/server.py` and inject via `AppState`.

**Async-first**: External calls (Ollama, VOICEVOX, camera) use `async` + `httpx.AsyncClient`.

**Example**:
```python
async def on_region_event(self, region, event):
    router_input = RouterInput(state=state, current_region_id=region.id, ...)
    router_output = await self._router.route(router_input)  # Async call
    if router_output.action == "respond_script":
        return await self._respond_from_script(region, event, router_output)
```

## Development Workflow

**Backend setup** (Python 3.11 required per `pyproject.toml`):
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit Tailscale IPs, model URLs
python -m teacharm.main  # Runs on http://0.0.0.0:8000
```

**Frontend setup** (React + Vite):
```bash
cd control-panel
npm install
npm run dev  # Set VITE_TEACHARM_API_URL for remote backend
```

**Vision demos** (ArUco calibration, hand detection):
```bash
python demo_vision.py  # Interactive preview with keyboard controls
python test_vision.py  # Batch tests
```

**Arm control** (SO-101 motor tests):
```bash
python scripts/so101_fk.py  # Forward kinematics
python scripts/move_arm.py --target_x 0.3 --target_y 0.2 --target_z 0.15
```

## Vision System Details
**Double detection pass** (performance optimization):
1. ArUco marker detection: Run every frame (fast)
2. MediaPipe hand detection: Run every N frames (expensive), downscale factor 0.25
3. Fingertip smoothing: 5-frame window to reduce jitter
4. Max jump threshold: 40px to detect hand swaps

**Optional remote processing**: If `VISION_OFFLOAD_URL` set, offload vision to separate server.

## Key Patterns & Conventions
- **Error handling**: Always check `response.raise_for_status()` on `httpx` calls
- **Logging**: Use `get_logger(__name__)` (from `teacharm/logger.py`), not print()
- **Pydantic models**: All API payloads use Pydantic validators for type safety (see `teacharm/server.py` `PointerEvent`, `DialoguePayload`)
- **Normalized coords**: All UI/vision coords are 0-1 range (not pixels)
- **Cache**: TTS results cached on disk in `cache/tts/` by content hash
- **Stats tracking**: Router/DeepSeek maintain request/fallback counters for `/api/stats` endpoint

## References
- `README.md`: Full setup, API endpoints, Vision/Arm workflows
- `docs/`: Detailed specs, Vision offload, SO-101 setup, GitHub Actions deployment
- `tools/README.md`: ArUco generation, PDF extraction, coordinate conversion
- `requirements.txt`: Full dependency list (FastAPI, mediapipe, faster-whisper, etc.)
