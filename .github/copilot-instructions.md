# TeachArm AI Coding Guidelines

## Architecture Overview
TeachArm is a robotics education system with a FastAPI backend (`teacharm/`) and React frontend (`control-panel/`). The backend integrates vision, mapping, dialogue, and arm control services. Services are loosely coupled with async interfaces, using Pydantic for data validation.

Key components:
- `teacharm/server.py`: FastAPI app assembly with CORS, routes for materials, events, dialogue, arm control
- `teacharm/services/`: Arm (so-101 stub), Dialogue (Ollama + scripts), TTS (VOICEVOX)
- `config/`: JSON/YAML configs (arm_limits.json, voicevox_params.yaml)
- `materials/`: JSON material definitions with regions and event mappings
- `scripts/common.yaml`: Dialogue scripts with commands, intents, negative rules

## Configuration Patterns
Use Pydantic `BaseSettings` in `teacharm/config.py` for env-driven config. Paths are resolved relative to `data_root` (default: project root).

Examples:
- Load materials: `load_materials(settings.resolve_path(settings.materials_dir))`
- Access env vars: `OLLAMA_BASE_URL`, `VOICEVOX_BASE_URL`, `CONTROL_PANEL_URL`

## Service Integration
Services are initialized in `teacharm/server.py` and injected via `AppState`. Use async methods for external calls (Ollama, VOICEVOX).

Example service call:
```python
response = await dialogue_service.on_region_event(region, "on_point")
```

## Material and Script Handling
Materials define regions with bounding boxes (normalized 0-1 coords) and event handlers. Scripts map events to commands like `SAY`, `ARM_POINT_CENTER`.

Example material region:
```json
{
  "id": "q1",
  "type": "question",
  "bbox": {"x": 0.05, "y": 0.05, "w": 0.9, "h": 0.25},
  "on_point": ["Q_INTRO"]
}
```

## Development Workflow
- Backend: `UV_PYTHON_PREFERENCE=managed uv venv --python 3.11; source .venv/bin/activate; uv pip install -r requirements.txt; python -m teacharm.main`
- Frontend: `cd control-panel; npm install; npm run dev` (set `VITE_TEACHARM_API_URL` for remote backend)
- Config: Copy `.env.example` to `.env`, set Tailscale IPs, model URLs

## Key Conventions
- Use `__future__` annotations and type hints throughout
- Log via `teacharm.logger.get_logger(__name__)`
- Cache TTS audio in `cache/tts/`
- Validate inputs with Pydantic models (e.g., `PointerEvent`, `ArmMovePayload`)
- Handle errors gracefully with try/except, log warnings for missing configs

Reference: `README.md` for setup, `docs/` for specs.</content>
<parameter name="filePath">/Users/tagra/MyProgram/school/2nd/Robotics/TechArm/.github/copilot-instructions.md