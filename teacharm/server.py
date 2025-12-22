"""FastAPI application assembly."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
import yaml

from .config import Settings, load_settings
from .logger import get_logger
from .mapping import MaterialRepository
from .materials import Material, Region, load_materials
from .scripts import load_scripts
from .services.arm import ArmCommand, ArmService
from .services.dialogue import DialogueResponse, DialogueService
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
        self.dialogue = DialogueService(settings, self.scripts)
        self.tts = VoiceVoxService(settings)
        self.arm = ArmService(self._load_json(settings.config_dir / "arm_limits.json"))
        self.calibration = self._load_json(settings.config_dir / "arm_calibration.json")

    def reload_scripts(self) -> None:
        self.scripts = load_scripts(self.scripts_path)
        self.dialogue = DialogueService(self.settings, self.scripts)

    def _load_json(self, path: Path) -> dict:
        if not path.exists():
            logger.warning("Config file %s is missing; using empty defaults", path)
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

    @app.get("/api/materials")
    async def list_materials() -> dict:
        return {
            "materials": [
                {
                    "material_id": material.material_id,
                    "regions": len(material.regions),
                    "selected": material.material_id == ctx.repository.current_id,
                }
                for material in ctx.repository.list_materials().values()
            ]
        }

    @app.post("/api/materials/select")
    async def select_material(payload: MaterialSelectionPayload) -> dict:
        try:
            material = ctx.repository.select(payload.material_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        ctx.state.active_material = material.material_id
        ctx.state.last_region = None
        return {"selected": material.material_id}

    async def _build_dialogue_response(region: Optional[Region], event: str) -> dict:
        if not region:
            return {"region": None, "dialogue": None}
        ctx.state.last_region = region.id
        dialogue = await ctx.dialogue.on_region_event(region, event)
        audio = await ctx.tts.synthesize(dialogue.text) if dialogue.text else None
        if audio is None and dialogue.text:
            logger.info("Audio synthesis skipped for text '%s'", dialogue.text)
        return {
            "region": {"id": region.id, "type": region.type},
            "dialogue": {
                "text": dialogue.text,
                "source": dialogue.source,
                "commands": dialogue.commands,
            },
            "audio_path": str(audio) if audio else None,
        }

    @app.post("/api/events/pointer")
    async def pointer_event(payload: PointerEvent) -> dict:
        mapping = ctx.repository.map_point(payload.u, payload.v)
        response = await _build_dialogue_response(mapping.region, payload.event)
        response["point"] = {
            "u": payload.u,
            "v": payload.v,
            "material_id": mapping.material_id,
        }
        return response

    @app.post("/api/dialogue")
    async def dialogue(payload: DialoguePayload) -> dict:
        dialogue = await ctx.dialogue.on_text(payload.text)
        audio = await ctx.tts.synthesize(dialogue.text) if dialogue.text else None
        return {
            "dialogue": {
                "text": dialogue.text,
                "source": dialogue.source,
                "commands": dialogue.commands,
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
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="common.yaml not found")
        return {"path": str(ctx.scripts_path), "content": content}

    @app.post("/api/scripts/common")
    async def update_common_script(payload: ScriptUpdatePayload) -> dict:
        try:
            data = yaml.safe_load(payload.content) or {}
        except yaml.YAMLError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid YAML: {exc}") from exc
        if "commands" not in data:
            raise HTTPException(status_code=400, detail="commands section is required")
        ctx.scripts_path.write_text(payload.content, encoding="utf-8")
        ctx.reload_scripts()
        return {"status": "updated"}

    return app
