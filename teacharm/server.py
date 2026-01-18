"""FastAPI application assembly."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, validator
import yaml

from .config import Settings, load_settings
from .logger import get_logger
from .mapping import MaterialRepository
from .materials import Material, Region, load_materials
from .scripts import load_scripts
from .services.arm import ArmCommand, ArmService
from .services.deepseek import DeepSeekService
from .services.dialogue import DialogueService
from .services.router import RouterService
from .services.tts import VoiceVoxService
from .state import AppState

logger = get_logger(__name__)


class PointerEvent(BaseModel):
    u: float = Field(..., ge=0.0, le=1.0)
    v: float = Field(..., ge=0.0, le=1.0)
    event: str = Field(default="on_point", description="on_point または on_help")

    @validator("event")
    def _validate_event(cls, value: str) -> str:
        if value not in {"on_point", "on_help"}:
            raise ValueError("event must be 'on_point' or 'on_help'")
        return value


class DialoguePayload(BaseModel):
    text: str


class MaterialSelectionPayload(BaseModel):
    material_id: str


class ArmMovePayload(BaseModel):
    x: float
    y: float
    z: float
    speed: float = 0.2


class ScriptUpdatePayload(BaseModel):
    content: str


class CalibrationPointPayload(BaseModel):
    id: str
    u: Optional[float] = None
    v: Optional[float] = None
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None


class CalibrationPayload(BaseModel):
    version: int = 1
    points: List[CalibrationPointPayload]


class TeachArmContext:
    """Composition root for the API application."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.scripts_path = settings.scripts_dir / "common.yaml"
        self.scripts = load_scripts(self.scripts_path)
        materials = load_materials(settings.materials_dir)
        if not materials:
            raise RuntimeError("No material definitions found.")
        self.repository = MaterialRepository(materials)
        self.state = AppState(active_material=self.repository.current_id)
        
        # Initialize services
        self.router = RouterService(settings)
        self.deepseek = DeepSeekService(settings)
        self.dialogue = DialogueService(
            settings, self.scripts, self.router, self.deepseek
        )
        self.tts = VoiceVoxService(settings)
        arm_limits = self._load_json(settings.config_dir / "arm_limits.json")
        self.arm = ArmService(arm_limits)
        self.calibration_path = settings.config_dir / "arm_calibration.json"
        self.calibration = self._load_json(self.calibration_path)

    def reload_scripts(self) -> None:
        self.scripts = load_scripts(self.scripts_path)
        self.dialogue = DialogueService(
            self.settings, self.scripts, self.router, self.deepseek
        )

    def _load_json(self, path: Path) -> dict:
        if not path.exists():
            logger.warning(
                "Config file %s is missing; using empty defaults", path
            )
            return {}
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """Instantiate the FastAPI app with all dependencies wired."""
    settings = settings or load_settings()
    ctx = TeachArmContext(settings)
    app = FastAPI(title="TeachArm Control API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "active_material": ctx.state.active_material,
            "control_panel_url": settings.control_panel_url,
        }

    @app.get("/api/stats")
    async def get_stats() -> dict:
        """Get statistics for monitoring (Router and DeepSeek)."""
        return {
            "router": ctx.router.get_stats(),
            "deepseek": ctx.deepseek.get_stats(),
        }

    @app.get("/api/materials")
    async def list_materials() -> dict:
        return {
            "materials": [
                {
                    "material_id": mat.material_id,
                    "regions": len(mat.regions),
                    "selected": mat.material_id == ctx.repository.current_id,
                }
                for mat in ctx.repository.list_materials().values()
            ]
        }

    @app.get("/api/materials/assets")
    async def list_material_assets() -> dict:
        assets = []
        if settings.materials_dir.exists():
            assets = [
                path.name
                for path in settings.materials_dir.iterdir()
                if path.is_file() and path.suffix.lower() == ".pdf"
            ]
        assets.sort()
        return {"files": assets}

    @app.get("/api/materials/assets/{filename}")
    async def get_material_asset(filename: str) -> FileResponse:
        if "/" in filename or "\\" in filename:
            raise HTTPException(status_code=400, detail="Invalid filename")
        path = settings.materials_dir / filename
        if not path.exists() or path.suffix.lower() != ".pdf":
            raise HTTPException(status_code=404, detail="Asset not found")
        return FileResponse(path, media_type="application/pdf")

    @app.get("/api/materials/{material_id}")
    async def get_material(material_id: str) -> dict:
        """Get material definition JSON."""
        materials_dict = ctx.repository.list_materials()
        material = materials_dict.get(material_id)
        if not material:
            raise HTTPException(
                status_code=404, detail="Material not found"
            )
        return material.dict()

    @app.put("/api/materials/{material_id}")
    async def update_material(
        material_id: str, material_data: Material
    ) -> dict:
        """Update material definition JSON."""
        if material_id != material_data.material_id:
            raise HTTPException(
                status_code=400,
                detail="material_id mismatch"
            )
        
        # Validate the material data
        try:
            validated = Material(**material_data.dict())
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid material data: {str(e)}"
            )
        
        # Save to file
        json_path = settings.materials_dir / f"material_{material_id}.json"
        try:
            with json_path.open("w", encoding="utf-8") as f:
                json.dump(validated.dict(), f, ensure_ascii=False, indent=2)
            logger.info(f"Updated material: {material_id}")
        except Exception as e:
            logger.error(f"Failed to save material {material_id}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to save material: {str(e)}"
            )
        
        # Reload materials
        new_materials = load_materials(settings.materials_dir)
        ctx.repository._materials = new_materials
        
        return {"status": "success", "material_id": material_id}

    @app.post("/api/materials/select")
    async def select_material(payload: MaterialSelectionPayload) -> dict:
        try:
            material = ctx.repository.select(payload.material_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        ctx.state.active_material = material.material_id
        ctx.state.last_region = None
        return {"selected": material.material_id}

    async def _build_dialogue_response(
        region: Optional[Region], event: str
    ) -> dict:
        if not region:
            return {"region": None, "dialogue": None}
        ctx.state.last_region = region.id
        dialogue = await ctx.dialogue.on_region_event(
            region=region,
            event=event,
            material_id=ctx.state.active_material or "",
            state="TARGET_SELECTED",
            error_code=None,
        )
        audio = None
        if dialogue.text:
            audio = await ctx.tts.synthesize(dialogue.text)
        if audio is None and dialogue.text:
            logger.info("Audio synthesis skipped for text '%s'", dialogue.text)
        return {
            "region": {"id": region.id, "type": region.type},
            "dialogue": {
                "text": dialogue.text,
                "source": dialogue.source,
                "commands": dialogue.commands,
                "router_action": dialogue.router_action,
                "router_fallback": dialogue.router_fallback,
                "deepseek_time_ms": dialogue.deepseek_time_ms,
            },
            "audio_path": str(audio) if audio else None,
        }

    @app.post("/api/events/pointer")
    async def pointer_event(payload: PointerEvent) -> dict:
        mapping = ctx.repository.map_point(payload.u, payload.v)
        response = await _build_dialogue_response(
            mapping.region, payload.event
        )
        response["point"] = {
            "u": payload.u,
            "v": payload.v,
            "material_id": mapping.material_id,
        }
        return response

    @app.post("/api/dialogue")
    async def dialogue(payload: DialoguePayload) -> dict:
        logger.info("Dialogue request received: %s", payload.text)
        current_material = ctx.repository.current
        if not current_material:
            raise HTTPException(
                status_code=400, detail="No material selected"
            )
        current_region = None
        if ctx.state.last_region:
            current_region = current_material.get_region(
                ctx.state.last_region
            )
        
        dialogue_resp = await ctx.dialogue.on_text(
            user_text=payload.text,
            material_id=ctx.state.active_material,
            current_region=current_region,
            state="IDLE" if not current_region else "TARGET_SELECTED",
        )
        logger.info(
            "Dialogue response: %s (source: %s, action: %s)",
            dialogue_resp.text,
            dialogue_resp.source,
            dialogue_resp.router_action,
        )
        audio = None
        if dialogue_resp.text:
            audio = await ctx.tts.synthesize(dialogue_resp.text)
        return {
            "dialogue": {
                "text": dialogue_resp.text,
                "source": dialogue_resp.source,
                "commands": dialogue_resp.commands,
                "router_action": dialogue_resp.router_action,
                "router_fallback": dialogue_resp.router_fallback,
                "deepseek_time_ms": dialogue_resp.deepseek_time_ms,
            },
            "audio_path": str(audio) if audio else None,
        }

    @app.post("/api/arm/move")
    async def arm_move(payload: ArmMovePayload) -> dict:
        command = ArmCommand(
            x=payload.x,
            y=payload.y,
            z=payload.z,
            speed=payload.speed,
        )
        await ctx.arm.move_to(command)
        return {"status": "moving", "target": command.__dict__}

    @app.post("/api/arm/safe_pose")
    async def arm_safe_pose() -> dict:
        await ctx.arm.go_safe_pose()
        return {"status": "ok"}

    @app.get("/api/state")
    async def get_state() -> dict:
        return ctx.state.as_dict()

    @app.get("/api/scripts/common")
    async def get_common_script() -> dict:
        try:
            content = ctx.scripts_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="common.yaml not found"
            ) from exc
        return {"path": str(ctx.scripts_path), "content": content}

    @app.post("/api/scripts/common")
    async def update_common_script(payload: ScriptUpdatePayload) -> dict:
        try:
            data = yaml.safe_load(payload.content) or {}
        except yaml.YAMLError as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid YAML: {exc}"
            ) from exc
        if "commands" not in data:
            raise HTTPException(
                status_code=400, detail="commands section is required"
            )
        ctx.scripts_path.write_text(payload.content, encoding="utf-8")
        ctx.reload_scripts()
        return {"status": "updated"}

    @app.get("/api/calibration")
    async def get_calibration() -> dict:
        if not ctx.calibration:
            ctx.calibration = ctx._load_json(ctx.calibration_path)
        if "points" not in ctx.calibration:
            return {"version": 1, "points": []}
        return ctx.calibration

    @app.post("/api/calibration")
    async def update_calibration(payload: CalibrationPayload) -> dict:
        data = payload.dict()
        ctx.calibration = data
        ctx.calibration_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {"status": "updated"}

    return app
