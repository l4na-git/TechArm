"""FastAPI application assembly."""

from __future__ import annotations

import asyncio
import json
import base64
import time
import tempfile
from pathlib import Path
from typing import List, Optional

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
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
from .services.vision import VisionService, VisionFrame
from .services.asr import ASRService
from .services.command_executor import CommandExecutor
from .services.calibration import ArmCalibration
from .state import AppState

import cv2
import numpy as np
import websockets

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
    current_region_id: Optional[str] = None
    material_id: Optional[str] = None


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
            settings,
            self.scripts,
            self.router,
            self.deepseek,
            self.repository,
        )
        self.asr = ASRService(settings)
        self.tts = VoiceVoxService(settings)
        arm_limits = self._load_json(settings.config_dir / "arm_limits.json")
        self.arm = ArmService(
            arm_limits,
            port=settings.so101_port,
            baudrate=settings.so101_baudrate,
            calibration_path=settings.so101_calibration_path,
        )
        self.vision = VisionService(settings)
        
        # Determine calibration path: LeRobot official first, then fallback
        self.calibration_path = settings.config_dir / "arm_calibration.json"
        if settings.so101_calibration_path:
            calib_path = Path(settings.so101_calibration_path)
            if calib_path.is_file():
                self.calibration_path = calib_path
                logger.info(f"Using LeRobot calibration: {self.calibration_path}")
            else:
                logger.warning(f"LeRobot calibration not found or not a file: {settings.so101_calibration_path}, using default: {self.calibration_path}")
        
        self.calibration_data = self._load_json(self.calibration_path)
        
        # Initialize command executor with calibration support
        self.calibration = ArmCalibration.from_file(self.calibration_path)
        self.command_executor = CommandExecutor(
            self.arm, self.calibration, self.repository
        )
        
        self.offload_calibration_requested = False
        self.offload_reset_requested = False

    def reload_scripts(self) -> None:
        self.scripts = load_scripts(self.scripts_path)
        self.dialogue = DialogueService(
            self.settings,
            self.scripts,
            self.router,
            self.deepseek,
            self.repository,
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

    def _build_offload_ws_url(base_url: str) -> str:
        trimmed = base_url.rstrip("/")
        if trimmed.startswith("http://"):
            trimmed = "ws://" + trimmed[len("http://"):]
        elif trimmed.startswith("https://"):
            trimmed = "wss://" + trimmed[len("https://"):]
        return f"{trimmed}/ws/vision_offload"

    def _update_vision_state(
        vision_frame: VisionFrame,
        current_region_id: Optional[str],
        current_material_id: Optional[str],
    ) -> None:
        ctx.state.vision_last_update = vision_frame.timestamp
        ctx.state.vision_material_visible = (
            len(vision_frame.markers_detected) >= 4
        )
        ctx.state.vision_hand_detected = vision_frame.hand_detected
        if vision_frame.hand_detected and vision_frame.fingertip_u is not None:
            ctx.state.vision_pointer = {
                "x": vision_frame.fingertip_u,
                "y": vision_frame.fingertip_v,
            }
        else:
            ctx.state.vision_pointer = None
        ctx.state.vision_current_region = current_region_id
        ctx.state.vision_current_material = current_material_id

    async def _websocket_vision_offload_proxy(websocket: WebSocket) -> None:
        offload_url = ctx.settings.vision_offload_url
        if not offload_url:
            return

        remote_ws_url = _build_offload_ws_url(offload_url)
        logger.info("Vision offload proxy connecting to %s", remote_ws_url)

        # Track last region for event triggering
        last_region_id: Optional[str] = None
        last_hand_source: Optional[str] = None
        region_dwell_frames = 0
        DWELL_THRESHOLD = 5  # Frames to trigger on_point event
        ON_POINT_COOLDOWN = 3.0
        last_trigger_region_id: Optional[str] = None
        last_trigger_time = 0.0
        ON_POINT_COOLDOWN = 3.0
        last_trigger_region_id: Optional[str] = None
        last_trigger_time = 0.0
        OFFLOAD_SCALE = 1.0
        OFFLOAD_JPEG_QUALITY = 50

        try:
            async with websockets.connect(remote_ws_url, max_size=None) as remote_ws:
                while True:
                    frame = ctx.vision.capture_frame()
                    if frame is None:
                        await asyncio.sleep(0.1)
                        continue

                    if OFFLOAD_SCALE != 1.0:
                        frame = cv2.resize(
                            frame,
                            None,
                            fx=OFFLOAD_SCALE,
                            fy=OFFLOAD_SCALE,
                            interpolation=cv2.INTER_AREA,
                        )
                    _, buffer = cv2.imencode(
                        ".jpg",
                        frame,
                        [cv2.IMWRITE_JPEG_QUALITY, OFFLOAD_JPEG_QUALITY],
                    )
                    payload = {"image": base64.b64encode(buffer).decode("utf-8")}
                    if ctx.offload_calibration_requested:
                        payload["force_calibrate"] = True
                        ctx.offload_calibration_requested = False
                    if ctx.offload_reset_requested:
                        payload["reset_calibration"] = True
                        ctx.offload_reset_requested = False

                    await remote_ws.send(json.dumps(payload))
                    response = await remote_ws.recv()
                    data = json.loads(response)
                    image = data.pop("image", None)

                    vision_frame = VisionFrame(**data)
                    if vision_frame.hand_source != last_hand_source:
                        logger.info(
                            "Offload hand source: %s", vision_frame.hand_source
                        )
                        last_hand_source = vision_frame.hand_source

                    # Map fingertip to material region if hand detected
                    current_region_id = None
                    current_material_id = None

                    if (
                        vision_frame.hand_detected
                        and vision_frame.fingertip_u is not None
                    ):
                        mapping = ctx.repository.map_point(
                            vision_frame.fingertip_u,
                            vision_frame.fingertip_v,
                        )

                        if mapping.region:
                            current_region_id = mapping.region.id
                            current_material_id = mapping.material_id

                            # Debug: Log coordinates and region
                            logger.debug(
                                "Hand at (%.3f, %.3f) -> region %s (bbox: x=%.3f, y=%.3f, w=%.3f, h=%.3f)",
                                vision_frame.fingertip_u,
                                vision_frame.fingertip_v,
                                current_region_id,
                                mapping.region.bbox.x,
                                mapping.region.bbox.y,
                                mapping.region.bbox.w,
                                mapping.region.bbox.h,
                            )

                            # Track region dwelling for event triggering
                            if current_region_id == last_region_id:
                                region_dwell_frames += 1

                                # Trigger on_point event after dwelling
                                if region_dwell_frames == DWELL_THRESHOLD:
                                    now = time.monotonic()
                                    if (
                                        current_region_id == last_trigger_region_id
                                        and now - last_trigger_time < ON_POINT_COOLDOWN
                                    ):
                                        pass
                                    else:
                                        last_trigger_region_id = current_region_id
                                        last_trigger_time = now
                                    logger.info(
                                        "Region pointed: %s (material: %s)",
                                        current_region_id,
                                        current_material_id,
                                    )
                                    ctx.state.last_region = current_region_id
                                    
                                    # Fire on_point event
                                    if mapping.region.on_point:
                                        try:
                                            async def _fire_on_point() -> None:
                                                response = await _build_dialogue_response(
                                                    mapping.region, "on_point"
                                                )
                                                logger.info(
                                                    "on_point triggered: %s",
                                                    response.get("text", ""),
                                                )
                                            asyncio.create_task(_fire_on_point())
                                        except Exception as e:
                                            logger.error(
                                                "Error in on_point handler: %s",
                                                e,
                                            )
                            else:
                                region_dwell_frames = 1
                                last_region_id = current_region_id
                        else:
                            last_region_id = None
                            region_dwell_frames = 0
                    else:
                        last_region_id = None
                        region_dwell_frames = 0

                    data = vision_frame.dict()
                    data["current_region_id"] = current_region_id
                    data["current_material_id"] = current_material_id
                    data["image"] = image
                    data["dwell_frames"] = region_dwell_frames
                    _update_vision_state(
                        vision_frame, current_region_id, current_material_id
                    )
                    await websocket.send_json(data)

                    # Send at ~10fps
                    await asyncio.sleep(0.1)

        except WebSocketDisconnect:
            logger.info("Vision offload proxy client disconnected")
        except Exception as e:
            logger.error("Vision offload proxy error: %s", e)

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
            return {
                "region": None,
                "dialogue": None,
                "executed_commands": [],
                "command_errors": [],
            }
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
        
        # Execute commands from dialogue response
        executed_commands, command_errors = await ctx.command_executor.execute_commands(
            dialogue.commands
        )
        
        # Convert executed commands to serializable format
        executed_cmds_list = [{"type": cmd.type.value, "region_id": cmd.region_id} 
                              for cmd in executed_commands]
        
        # Convert command errors to serializable format
        cmd_errors_list = [
            {
                "command": {"type": err.command.type.value, "region_id": err.command.region_id},
                "code": err.code.value,
                "detail": err.detail,
            }
            for err in command_errors
        ]
        
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
            "executed_commands": executed_cmds_list,
            "command_errors": cmd_errors_list,
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
        
        # ペイロードで current_region_id が指定されていればそれを使う
        if payload.current_region_id:
            material_id = payload.material_id or ctx.state.active_material
            mat = ctx.repository.list_materials().get(material_id)
            if mat:
                current_region = mat.get_region(payload.current_region_id)
        # なければ state の last_region を使う
        elif ctx.state.last_region:
            current_region = current_material.get_region(
                ctx.state.last_region
            )
        
        dialogue_resp = await ctx.dialogue.on_text(
            user_text=payload.text,
            material_id=payload.material_id or ctx.state.active_material,
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

    @app.post("/api/asr/transcribe")
    async def asr_transcribe(
        audio: UploadFile = File(...),
        language: Optional[str] = Form(None),
    ) -> dict:
        data = await audio.read()
        if not data:
            raise HTTPException(status_code=400, detail="Empty audio upload")

        suffix = Path(audio.filename or "").suffix or ".wav"
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(data)
                tmp_path = tmp.name

            result = await ctx.asr.transcribe_file(tmp_path, language=language)
        except Exception as exc:
            logger.error("ASR transcription failed: %s", exc)
            raise HTTPException(status_code=500, detail="ASR failed") from exc
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

        return {
            "text": result.text,
            "language": result.language,
            "segments": [
                {"start": seg.start, "end": seg.end, "text": seg.text}
                for seg in result.segments
            ],
        }

    @app.post("/api/dialogue/audio")
    async def dialogue_audio(
        audio: UploadFile = File(...),
        language: Optional[str] = Form(None),
    ) -> dict:
        data = await audio.read()
        if not data:
            raise HTTPException(status_code=400, detail="Empty audio upload")

        suffix = Path(audio.filename or "").suffix or ".wav"
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(data)
                tmp_path = tmp.name

            asr_result = await ctx.asr.transcribe_file(
                tmp_path, language=language
            )
        except Exception as exc:
            logger.error("ASR transcription failed: %s", exc)
            raise HTTPException(status_code=500, detail="ASR failed") from exc
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

        if not asr_result.text:
            return {
                "asr": {
                    "text": asr_result.text,
                    "language": asr_result.language,
                    "segments": [],
                },
                "dialogue": None,
                "audio_path": None,
            }

        current_material = ctx.repository.current
        if not current_material:
            raise HTTPException(
                status_code=400, detail="No material selected"
            )
        current_region = None
        pointer_coords = None
        material_visible = False
        current_region_id = None
        vision_ts = ctx.state.vision_last_update or 0.0
        if time.time() - vision_ts <= 2.5:
            material_visible = ctx.state.vision_material_visible
            if ctx.state.vision_current_material == ctx.state.active_material:
                current_region_id = ctx.state.vision_current_region
            pointer_coords = ctx.state.vision_pointer
        if current_region_id:
            current_region = current_material.get_region(current_region_id)

        dialogue_resp = await ctx.dialogue.on_text(
            user_text=asr_result.text,
            material_id=ctx.state.active_material,
            current_region=current_region,
            state="IDLE" if not current_region else "TARGET_SELECTED",
            require_pointing=True,
            material_visible=material_visible,
            pointer_coords=pointer_coords,
            prepend_point_ack=bool(pointer_coords and current_region),
        )

        audio_path = None
        if dialogue_resp.text:
            audio_path = await ctx.tts.synthesize(dialogue_resp.text)

        return {
            "asr": {
                "text": asr_result.text,
                "language": asr_result.language,
                "segments": [
                    {"start": seg.start, "end": seg.end, "text": seg.text}
                    for seg in asr_result.segments
                ],
            },
            "dialogue": {
                "text": dialogue_resp.text,
                "source": dialogue_resp.source,
                "commands": dialogue_resp.commands,
                "router_action": dialogue_resp.router_action,
                "router_fallback": dialogue_resp.router_fallback,
                "deepseek_time_ms": dialogue_resp.deepseek_time_ms,
            },
            "audio_path": str(audio_path) if audio_path else None,
        }

    @app.get("/api/tts/audio/{filename}")
    async def get_tts_audio(filename: str) -> FileResponse:
        audio_path = Path("cache/tts") / filename
        if not audio_path.exists():
            raise HTTPException(status_code=404, detail="Audio not found")
        return FileResponse(audio_path, media_type="audio/wav")

    @app.post("/api/arm/move")
    async def arm_move(payload: ArmMovePayload) -> dict:
        try:
            command = ArmCommand(
                x=payload.x,
                y=payload.y,
                z=payload.z,
                speed=payload.speed,
            )
            await ctx.arm.move_to(command)
            return {"status": "moving", "target": command.__dict__}
        except RuntimeError as exc:
            logger.warning("ARM move error: %s", exc)
            return {"status": "error", "code": "E_ARM", "detail": str(exc)}
        except Exception as exc:
            logger.error("ARM move unexpected error: %s", exc)
            return {"status": "error", "code": "E_ARM", "detail": str(exc)}

    @app.post("/api/arm/safe_pose")
    async def arm_safe_pose() -> dict:
        try:
            await ctx.arm.go_safe_pose()
            return {"status": "ok"}
        except RuntimeError as exc:
            logger.warning("ARM safe_pose error: %s", exc)
            return {"status": "error", "code": "E_ARM", "detail": str(exc)}
        except Exception as exc:
            logger.error("ARM safe_pose unexpected error: %s", exc)
            return {"status": "error", "code": "E_ARM", "detail": str(exc)}

    @app.post("/api/arm/init_pose")
    async def arm_init_pose() -> dict:
        try:
            await ctx.arm.go_init_pose()
            return {"status": "ok"}
        except RuntimeError as exc:
            logger.warning("ARM init_pose error: %s", exc)
            return {"status": "error", "code": "E_ARM", "detail": str(exc)}
        except Exception as exc:
            logger.error("ARM init_pose unexpected error: %s", exc)
            return {"status": "error", "code": "E_ARM", "detail": str(exc)}

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

    @app.post("/api/vision/start")
    async def start_vision() -> dict:
        """Start camera capture."""
        success = ctx.vision.start()
        if not success:
            raise HTTPException(
                status_code=500, detail="Failed to start camera"
            )
        return {"status": "started"}

    @app.post("/api/vision/stop")
    async def stop_vision() -> dict:
        """Stop camera capture."""
        ctx.vision.stop()
        return {"status": "stopped"}

    @app.post("/api/vision/calibrate")
    async def calibrate_vision() -> dict:
        """Trigger ArUco calibration."""
        if ctx.settings.vision_offload_url:
            ctx.offload_calibration_requested = True
            return {"status": "requested"}

        frame = ctx.vision.capture_frame()
        if frame is None:
            # Fallback to last processed frame if available.
            frame = ctx.vision.last_frame
        if frame is None:
            raise HTTPException(
                status_code=400, detail="Camera not started"
            )
        
        marker_ids, marker_corners = ctx.vision.detect_aruco_markers(frame)
        success = ctx.vision.calibrate_perspective(marker_corners)
        
        if not success:
            raise HTTPException(
                status_code=400,
                detail="Calibration failed. Ensure all 4 markers are visible.",
            )
        
        return {
            "status": "calibrated",
            "markers_detected": marker_ids,
        }

    @app.post("/api/vision/reset")
    async def reset_vision_calibration() -> dict:
        """Reset perspective calibration."""
        if ctx.settings.vision_offload_url:
            ctx.offload_reset_requested = True
            return {"status": "requested"}
        ctx.vision.reset_calibration()
        return {"status": "reset"}

    @app.websocket("/ws/vision")
    async def websocket_vision(websocket: WebSocket) -> None:
        """
        WebSocket endpoint for streaming vision frames with video.
        
        Sends VisionFrame JSON with base64-encoded image at ~10fps.
        Includes material region mapping when hand is detected.
        """
        await websocket.accept()
        logger.info("Vision WebSocket client connected")

        if ctx.settings.vision_offload_url:
            await _websocket_vision_offload_proxy(websocket)
            return
        
        # Track last region for event triggering
        last_region_id: Optional[str] = None
        region_dwell_frames = 0
        DWELL_THRESHOLD = 5  # Frames to trigger on_point event
        
        # Preview throttling to reduce CPU load
        preview_frame_count = 0
        last_image_base64: Optional[str] = None
        PREVIEW_EVERY_N = 3
        PREVIEW_SCALE = 0.4
        PREVIEW_JPEG_QUALITY = 40

        try:
            while True:
                vision_frame = ctx.vision.process_frame()
                if vision_frame is not None:
                    # Map fingertip to material region if hand detected
                    current_region_id = None
                    current_material_id = None
                    
                    if vision_frame.hand_detected and vision_frame.fingertip_u is not None:
                        mapping = ctx.repository.map_point(
                            vision_frame.fingertip_u,
                            vision_frame.fingertip_v
                        )
                        
                        if mapping.region:
                            current_region_id = mapping.region.id
                            current_material_id = mapping.material_id
                            
                            # Debug: Log coordinates and region
                            logger.debug(
                                "Hand at (%.3f, %.3f) -> region %s (bbox: x=%.3f, y=%.3f, w=%.3f, h=%.3f)",
                                vision_frame.fingertip_u,
                                vision_frame.fingertip_v,
                                current_region_id,
                                mapping.region.bbox.x,
                                mapping.region.bbox.y,
                                mapping.region.bbox.w,
                                mapping.region.bbox.h
                            )
                            
                            # Track region dwelling for event triggering
                            if current_region_id == last_region_id:
                                region_dwell_frames += 1
                                
                                # Trigger on_point event after dwelling
                                if region_dwell_frames == DWELL_THRESHOLD:
                                    now = time.monotonic()
                                    if (
                                        current_region_id == last_trigger_region_id
                                        and now - last_trigger_time < ON_POINT_COOLDOWN
                                    ):
                                        pass
                                    else:
                                        last_trigger_region_id = current_region_id
                                        last_trigger_time = now
                                    logger.info(
                                        "Region pointed: %s (material: %s)",
                                        current_region_id,
                                        current_material_id
                                    )
                                    ctx.state.last_region = current_region_id
                                    
                                    # Fire on_point event
                                    if mapping.region.on_point:
                                        try:
                                            async def _fire_on_point() -> None:
                                                response = await _build_dialogue_response(
                                                    mapping.region, "on_point"
                                                )
                                                logger.info(
                                                    "on_point triggered: %s",
                                                    response.get("text", "")
                                                )
                                            asyncio.create_task(_fire_on_point())
                                        except Exception as e:
                                            logger.error("Error in on_point handler: %s", e)
                            else:
                                region_dwell_frames = 1
                                last_region_id = current_region_id
                        else:
                            last_region_id = None
                            region_dwell_frames = 0
                    else:
                        last_region_id = None
                        region_dwell_frames = 0
                    
                    # Add mapping info to frame
                    vision_frame.current_region_id = current_region_id
                    vision_frame.current_material_id = current_material_id
                    _update_vision_state(
                        vision_frame, current_region_id, current_material_id
                    )
                    
                    # Get current frame for preview
                    preview_frame = ctx.vision.get_preview_frame()
                    preview_frame_count += 1
                    
                    # Encode frame to JPEG (throttled + downscaled)
                    frame_base64 = last_image_base64
                    if preview_frame is not None and preview_frame_count % PREVIEW_EVERY_N == 0:
                        if PREVIEW_SCALE != 1.0:
                            preview_frame = cv2.resize(
                                preview_frame,
                                None,
                                fx=PREVIEW_SCALE,
                                fy=PREVIEW_SCALE,
                                interpolation=cv2.INTER_AREA,
                            )
                        _, buffer = cv2.imencode(
                            ".jpg",
                            preview_frame,
                            [cv2.IMWRITE_JPEG_QUALITY, PREVIEW_JPEG_QUALITY],
                        )
                        frame_base64 = base64.b64encode(buffer).decode("utf-8")
                        last_image_base64 = frame_base64
                    
                    # Send frame data with image
                    data = vision_frame.dict()
                    data['image'] = frame_base64
                    data['dwell_frames'] = region_dwell_frames  # For UI feedback
                    await websocket.send_json(data)
                
                # Send at ~10fps
                await asyncio.sleep(0.1)
        
        except WebSocketDisconnect:
            logger.info("Vision WebSocket client disconnected")
        except Exception as e:
            logger.error("Vision WebSocket error: %s", e)

    @app.websocket("/ws/vision_offload")
    async def websocket_vision_offload(websocket: WebSocket) -> None:
        """
        WebSocket endpoint for vision offload processing.

        Receives JPEG frames and returns VisionFrame JSON with preview image.
        """
        await websocket.accept()
        logger.info("Vision offload WebSocket client connected")

        preview_frame_count = 0
        last_image_base64: Optional[str] = None
        PREVIEW_EVERY_N = 3
        PREVIEW_SCALE = 0.4
        PREVIEW_JPEG_QUALITY = 40

        try:
            while True:
                message = await websocket.receive_text()
                payload = json.loads(message)
                image_base64 = payload.get("image")
                if not image_base64:
                    continue

                frame_bytes = base64.b64decode(image_base64)
                frame_array = np.frombuffer(frame_bytes, dtype=np.uint8)
                frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
                if frame is None:
                    continue

                force_calibrate = bool(payload.get("force_calibrate"))
                if payload.get("reset_calibration"):
                    ctx.vision.reset_calibration()
                vision_frame = ctx.vision.process_frame_from_image(
                    frame, force_calibrate=force_calibrate
                )
                if vision_frame is None:
                    continue

                current_region_id = None
                current_material_id = None
                if (
                    vision_frame.hand_detected
                    and vision_frame.fingertip_u is not None
                ):
                    mapping = ctx.repository.map_point(
                        vision_frame.fingertip_u,
                        vision_frame.fingertip_v,
                    )
                    if mapping.region:
                        current_region_id = mapping.region.id
                        current_material_id = mapping.material_id

                vision_frame.current_region_id = current_region_id
                vision_frame.current_material_id = current_material_id
                _update_vision_state(
                    vision_frame, current_region_id, current_material_id
                )

                preview_frame = ctx.vision.get_preview_frame()
                preview_frame_count += 1
                frame_base64 = last_image_base64
                if (
                    preview_frame is not None
                    and preview_frame_count % PREVIEW_EVERY_N == 0
                ):
                    if PREVIEW_SCALE != 1.0:
                        preview_frame = cv2.resize(
                            preview_frame,
                            None,
                            fx=PREVIEW_SCALE,
                            fy=PREVIEW_SCALE,
                            interpolation=cv2.INTER_AREA,
                        )
                    _, buffer = cv2.imencode(
                        ".jpg",
                        preview_frame,
                        [cv2.IMWRITE_JPEG_QUALITY, PREVIEW_JPEG_QUALITY],
                    )
                    frame_base64 = base64.b64encode(buffer).decode("utf-8")
                    last_image_base64 = frame_base64

                data = vision_frame.dict()
                data["image"] = frame_base64
                await websocket.send_text(json.dumps(data))

        except WebSocketDisconnect:
            logger.info("Vision offload WebSocket client disconnected")
        except Exception as e:
            logger.error("Vision offload WebSocket error: %s", e)

    return app
