import os
import sys

# Resolve Windows Python 3.8+ DLL loading issue for nvidia cuDNN/cuBLAS packages
if sys.platform.startswith("win"):
    for p in sys.path:
        nvidia_dir = os.path.join(p, "nvidia")
        if os.path.isdir(nvidia_dir):
            for sub in os.listdir(nvidia_dir):
                bin_path = os.path.join(nvidia_dir, sub, "bin")
                if os.path.isdir(bin_path):
                    try:
                        os.add_dll_directory(bin_path)
                    except Exception:
                        pass

import uvicorn
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
import json
import asyncio
import time

# Load .env from the backend directory before importing config
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)
except ImportError:
    pass  # python-dotenv not installed; rely on shell environment


from config import (
    AI_TIMEOUT_SECONDS,
    FRAME_DIFF_THRESHOLD,
    PROMPT_TIMEOUT_SECONDS,
    SNAPSHOT_TIMEOUT_SECONDS,
    COPILOT_LLM_PROVIDER,
    COPILOT_OLLAMA_MODEL,
    COPILOT_USE_OLLAMA,
    COPILOT_OPENAI_MODEL,
    COPILOT_HF_MODEL_ID,
    COPILOT_HF_ENDPOINT_URL,
    COPILOT_HF_API_TOKEN,
    COPILOT_HF_TEMPERATURE,
    COPILOT_HF_MAX_NEW_TOKENS,
    COPILOT_SCREEN_WIDTH,
    COPILOT_SCREEN_HEIGHT,
    COPILOT_MAX_STEPS,
    COPILOT_MIN_CONFIDENCE,
    COPILOT_VERIFY_THRESHOLD,
    VALID_PERSONAS,
    WORKOUTX_API_KEY,
    WORKOUTX_API_URL,
    WORKOUTX_TIMEOUT,
    OMNIPARSER_ENABLED,
    PADDLEOCR_ENABLED,
    OLLAMA_BASE_URL,
    OLLAMA_API_KEY,
)
from services.frame_differ import FrameDiffer
from services.imu_fusion_service import ImuFusionService
from services.pipeline_service import PipelineService
from services.vlm_service import VlmService
from services.workout_service import WorkoutService

# ── Half 2: Copilot imports ──────────────────────────────────────────
from services.ui_detector import UIDetector
from services.llm_service import LLMCopilotService
from services.screen_capture import ScreenCapture
from services.screen_parser import ScreenParser
from services.safety_gate import SafetyGate
from services.verification_service import VerificationService
from services import step_policy_service as _step_policy   # RAG lesson matcher (Phase 3)
from services import lesson_repository                      # DB CRUD (Phase 3)
from db.database import init_db

# Optional fast-path helpers for template matching
try:
    import cv2 as _cv2
    import numpy as _np
    _CV2_OK = True
except ImportError:
    _cv2 = None  # type: ignore
    _np  = None  # type: ignore
    _CV2_OK = False

# Shared copilot singletons (one per backend process)
_copilot_llm = LLMCopilotService(
    provider=COPILOT_LLM_PROVIDER,
    use_ollama=COPILOT_USE_OLLAMA,
    ollama_model=COPILOT_OLLAMA_MODEL,
    ollama_base_url=OLLAMA_BASE_URL,
    ollama_api_key=OLLAMA_API_KEY,
    openai_model=COPILOT_OPENAI_MODEL,
    hf_model_id=COPILOT_HF_MODEL_ID,
    hf_endpoint_url=COPILOT_HF_ENDPOINT_URL,
    hf_api_token=COPILOT_HF_API_TOKEN,
    hf_temperature=COPILOT_HF_TEMPERATURE,
    hf_max_new_tokens=COPILOT_HF_MAX_NEW_TOKENS,
)
_copilot_screen = ScreenCapture(
    source_width=COPILOT_SCREEN_WIDTH,
    source_height=COPILOT_SCREEN_HEIGHT,
)
# ScreenParser: OmniParser + PaddleOCR grounding
# Only active for the UI Copilot (/copilot, /lesson) — never used in /stream.
_copilot_parser = ScreenParser(
    omni_enabled=OMNIPARSER_ENABLED,
    paddle_enabled=PADDLEOCR_ENABLED,
)
# Safety gate: filters narrator tts_text before it is spoken by Android TTS.
_copilot_safety = SafetyGate()
# Verification service: compares before/after screenshots to confirm step completion.
_copilot_verifier = VerificationService(threshold=float(COPILOT_VERIFY_THRESHOLD))

# ── FastAPI app with startup lifespan ──────────────────────────────────────
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app_instance):
    """Run startup tasks (DB init + lesson index build) then yield to serve requests."""
    try:
        await init_db()
        print("[Startup] SQLite DB initialised.")
    except Exception as e:
        print(f"[Startup] DB init failed (non-fatal): {e}")

    # Build in-memory lesson index so /copilot can match DB lessons instantly
    try:
        published = await lesson_repository.list_lessons(status="published")
        lessons_by_id_cache = {l["id"]: l for l in published}
        _step_policy.build_index(published)
        print(f"[Startup] Lesson index built: {len(published)} published lessons.")
    except Exception as e:
        print(f"[Startup] Lesson index build failed (non-fatal): {e}")
        lessons_by_id_cache = {}

    app_instance.state.lessons_by_id = lessons_by_id_cache
    yield
    # Shutdown: nothing to clean up for SQLite

app = FastAPI(title="NeuroGuide XR Backend", lifespan=lifespan)
pipeline_service = PipelineService()
demo_vlm_service = VlmService()
workout_service = WorkoutService()

# ── Gym machine label set (must match YOLO classes + LLM labels) ──────────────
ROBOFLOW_MACHINE_CLASSES: set[str] = {
    "flat bench press machine",
    "incline bench press machine",
    "lat pulldown machine",
    "leg press machine",
}


async def _fetch_exercises(fetch_req: dict) -> list[dict]:
    query = str(fetch_req.get("query") or fetch_req.get("name") or "").strip()
    body_part = str(fetch_req.get("bodyPart") or "").strip()
    equipment = str(fetch_req.get("equipment") or "").strip()

    if query:
        exercises = await workout_service.search(name=query, limit=2)
        if exercises:
            return exercises
        if body_part or equipment:
            return await workout_service.search(bodyPart=body_part, equipment=equipment, limit=2)

    return await workout_service.search(
        bodyPart=body_part,
        equipment=equipment,
        name=query,
        limit=2,
    )


def _clamp_step(step: int, total_steps: int) -> int:
    if total_steps <= 0:
        return 1
    return max(1, min(step, total_steps))


def _sanitize_completed_steps(completed_steps: list, total_steps: int) -> list[int]:
    sanitized: list[int] = []
    for item in completed_steps:
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue

        if 1 <= value <= total_steps and value not in sanitized:
            sanitized.append(value)

    sanitized.sort()
    return sanitized


def _build_step_update_response(step_guidance: dict, *, action: str) -> dict:
    current_step = int(step_guidance.get("current_step", 1) or 1)
    total_steps = int(step_guidance.get("total_steps", 1) or 1)
    current_step = _clamp_step(current_step, total_steps)
    completed_steps = _sanitize_completed_steps(step_guidance.get("completed_steps", []), total_steps)
    step_guidance["current_step"] = current_step
    step_guidance["completed_steps"] = completed_steps
    is_complete = bool(step_guidance.get("is_complete", False)) or len(completed_steps) >= total_steps
    step_guidance["is_complete"] = is_complete

    steps = step_guidance.get("steps", [])

    instruction_text = "Follow the highlighted step."
    target_object = "scene"
    visual_type = "highlight"
    location_3d = [0.0, 0.0, 1.3]

    if isinstance(steps, list) and len(steps) >= current_step and not is_complete:
        step_item = steps[current_step - 1]
        if isinstance(step_item, dict):
            instruction_text = str(step_item.get("instruction", instruction_text))
            target_object = str(step_item.get("target_object", target_object))
            visual_type = str(step_item.get("visual_hint", visual_type))

    if is_complete:
        instruction_text = "All steps completed. You can capture a new snapshot or ask a follow-up question."
        visual_type = "highlight"
        target_object = "scene"

    active_hint = step_guidance.get("active_hint", {})
    if isinstance(active_hint, dict):
        location = active_hint.get("location_3d", location_3d)
        if isinstance(location, list) and len(location) == 3:
            location_3d = [float(location[0]), float(location[1]), float(location[2])]

    return {
        "type": "step_update",
        "task": "step_guidance",
        "action": action,
        "instruction_text": instruction_text,
        "visual_type": visual_type,
        "location_3d": location_3d,
        "objects_detected": [target_object] if target_object and target_object != "scene" else [],
        "step_guidance": step_guidance,
        "user_message": (
            f"Completed {len(completed_steps)}/{total_steps} steps"
            if is_complete
            else f"Step {current_step}/{total_steps}"
        ),
    }


def _apply_step_action(step_guidance: dict, action: str) -> dict:
    if not isinstance(step_guidance, dict):
        return {}

    total_steps = int(step_guidance.get("total_steps", 1) or 1)
    current_step = int(step_guidance.get("current_step", 1) or 1)

    normalized_action = action.strip().lower()
    completed_steps = step_guidance.get("completed_steps", [])
    if not isinstance(completed_steps, list):
        completed_steps = []
    completed_steps = _sanitize_completed_steps(completed_steps, total_steps)

    is_complete = bool(step_guidance.get("is_complete", False))

    if normalized_action in {"next", "step_next", "forward"}:
        current_step += 1
        is_complete = False
    elif normalized_action in {"previous", "prev", "step_prev", "back"}:
        current_step -= 1
        # Moving back re-opens the current and subsequent steps for correction.
        completed_steps = [item for item in completed_steps if item < max(1, current_step + 1)]
        is_complete = False
    elif normalized_action in {"reset", "restart"}:
        current_step = 1
        completed_steps = []
        is_complete = False
    elif normalized_action in {"complete", "step_complete", "done"}:
        if current_step not in completed_steps:
            completed_steps.append(current_step)
        completed_steps = _sanitize_completed_steps(completed_steps, total_steps)
        if len(completed_steps) >= total_steps:
            is_complete = True
            current_step = total_steps
        else:
            next_step = current_step + 1
            while next_step in completed_steps and next_step <= total_steps:
                next_step += 1
            current_step = _clamp_step(next_step, total_steps)
            is_complete = False

    current_step = _clamp_step(current_step, total_steps)
    step_guidance["current_step"] = current_step
    step_guidance["completed_steps"] = completed_steps
    step_guidance["is_complete"] = is_complete

    steps = step_guidance.get("steps", [])
    if isinstance(steps, list) and len(steps) >= current_step and not is_complete:
        step_item = steps[current_step - 1]
        if isinstance(step_item, dict):
            active_hint = step_guidance.get("active_hint", {})
            if not isinstance(active_hint, dict):
                active_hint = {}
            active_hint["visual_type"] = str(step_item.get("visual_hint", active_hint.get("visual_type", "highlight")))
            active_hint["target_object"] = str(step_item.get("target_object", active_hint.get("target_object", "scene")))
            step_guidance["active_hint"] = active_hint

    if is_complete:
        active_hint = step_guidance.get("active_hint", {})
        if not isinstance(active_hint, dict):
            active_hint = {}
        active_hint["visual_type"] = "highlight"
        active_hint["target_object"] = "scene"
        step_guidance["active_hint"] = active_hint

    return step_guidance

# Allow all origins for the MVP
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "NeuroGuide XR Backend is running"}

@app.get("/health")
@app.get("/api/v1/status")
async def health_check():
    return {"status": "ok", "service": "NeuroGuide XR"}



@app.get("/workoutx/gif/{gif_name}")
async def workoutx_gif(gif_name: str):
    if not WORKOUTX_API_KEY:
        raise HTTPException(status_code=400, detail="WORKOUTX_API_KEY is not configured.")

    safe_name = gif_name.strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="gif name missing.")
    if not safe_name.lower().endswith(".gif"):
        safe_name = f"{safe_name}.gif"

    url = f"{WORKOUTX_API_URL.rstrip('/')}/gifs/{safe_name}"
    try:
        async with httpx.AsyncClient(timeout=WORKOUTX_TIMEOUT) as client:
            resp = await client.get(url, headers={"X-WorkoutX-Key": WORKOUTX_API_KEY})
            resp.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"WorkoutX gif fetch failed: {exc}")

    media_type = resp.headers.get("Content-Type", "image/gif")
    return Response(content=resp.content, media_type=media_type)

@app.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    client_ip = websocket.client.host if websocket.client else "unknown"
    print(f"Client connected to stream: {client_ip}")
    # Clear VLM session memory for a fresh coaching session
    demo_vlm_service.clear_history()
    frame_differ = FrameDiffer(threshold=FRAME_DIFF_THRESHOLD)
    imu_fusion_service = ImuFusionService()
    last_snapshot_image_bytes = None
    last_snapshot_scene_summary = ""
    last_snapshot_objects = []
    last_step_guidance = {}
    latest_imu = {}
    last_yolo_detections: list[dict] = []   # persisted YOLO detections for prompt context
    # ── YOLO 2-second stable-detection state ──────────────────────────
    machine_first_seen: dict[str, float] = {}   # label -> timestamp first seen
    last_machine_suggested: str = ""            # label last sent as suggestion chips
    last_guidance = {
        "type": "guidance",
        "task": "general_guidance",
        "instruction_text": "Hold steady and center the target object.",
        "visual_type": "highlight",
        "location_3d": [0.0, 0.0, 1.3],
        "objects_detected": [],
        "step_number": 1,
        "total_steps": 1,
    }
    
    try:
        while True:
            # Wait for data from the client (Unity AR app)
            data = await websocket.receive_text()
            
            try:
                # Expecting JSON payload with image data or commands
                payload = json.loads(data)
                
                # Basic logging of received data type
                msg_type = payload.get("type", "unknown")
                print(f"Received message of type: {msg_type}")
                
                if msg_type == "frame":
                    if isinstance(payload.get("imu_data"), dict):
                        latest_imu = imu_fusion_service.update(dict(payload.get("imu_data", {})))

                    image_data = payload.get("image_data")
                    if not image_data:
                        await websocket.send_json({"type": "error", "message": "Missing image_data"})
                        continue

                    image_bytes, bgr_image = pipeline_service.decode_frame(image_data)
                    if image_bytes is None or bgr_image is None:
                        await websocket.send_json({"type": "error", "message": "Invalid image encoding"})
                        continue

                    should_process, diff_score = frame_differ.should_process(bgr_image)
                    if not should_process:
                        cached = dict(last_guidance)
                        cached["debug"] = {"cache_hit": True, "diff_score": round(diff_score, 2)}
                        print(
                            "Cached guidance reused | "
                            f"diff={round(diff_score, 2)} | "
                            f"objects={cached.get('objects_detected', [])}"
                        )
                        await websocket.send_json(cached)
                        continue

                    try:
                        ai_payload = await asyncio.wait_for(
                            pipeline_service.process_frame(
                                image_bytes,
                                bgr_image,
                                diff_score=diff_score,
                                raw_payload=payload,
                            ),
                            timeout=AI_TIMEOUT_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        ai_payload = {
                            "task": "general_guidance",
                            "instruction_text": "AI timeout. Keep camera steady and retry.",
                            "visual_type": "highlight",
                            "location_3d": [0.0, 0.0, 1.3],
                            "objects_detected": [],
                            "step_number": 1,
                            "total_steps": 1,
                            "confidence": 0.0,
                            "reasoning_source": "timeout_fallback",
                            "debug": {},
                        }

                    payload_dict = ai_payload.model_dump() if hasattr(ai_payload, "model_dump") else dict(ai_payload)
                    model_debug = payload_dict.pop("debug", {})
                    response = {
                        "type": "guidance",
                        **payload_dict,
                        "debug": {"cache_hit": False, "diff_score": round(diff_score, 2)},
                    }
                    response["debug"].update(model_debug)
                    if latest_imu:
                        response["debug"]["imu"] = latest_imu
                    print(
                        "Guidance generated | "
                        f"objects={response.get('objects_detected', [])} | "
                        f"detection_count={response.get('debug', {}).get('detection_count', 0)} | "
                        f"open_vocab_triggered={response.get('debug', {}).get('open_vocab_triggered', False)} | "
                        f"open_vocab_reason={response.get('debug', {}).get('open_vocab_reason', '')} | "
                        f"confidence={response.get('confidence', 0.0)} | "
                        f"source={response.get('reasoning_source', 'unknown')} | "
                        f"detector_error={response.get('debug', {}).get('detector_error', '')} | "
                        f"open_vocab_error={response.get('debug', {}).get('open_vocab_error', '')}"
                    )
                    last_guidance = response

                    # ── Persist YOLO detections from frame response ──────────
                    # Extract object_hints (from detection_service / pipeline)
                    # These carry label, confidence, bbox_norm, cx_norm, cy_norm
                    raw_hints = response.get("debug", {}).get("object_hints", [])
                    if raw_hints:
                        last_yolo_detections = [
                            det for det in raw_hints
                            if isinstance(det, dict)
                        ]

                    # ── Proactive YOLO machine suggestion chips (2-second cooldown) ──
                    _now = time.monotonic()
                    for det in last_yolo_detections:
                        lbl = str(det.get("label", det.get("class_name", ""))).strip()
                        lbl_lower = lbl.lower()
                        if lbl_lower not in ROBOFLOW_MACHINE_CLASSES:
                            continue

                        # Track first-seen time per label
                        if lbl_lower not in machine_first_seen:
                            machine_first_seen[lbl_lower] = _now

                        stable_seconds = _now - machine_first_seen[lbl_lower]
                        already_suggested = (last_machine_suggested == lbl_lower)

                        if stable_seconds >= 2.0 and not already_suggested:
                            suggestions = WorkoutService.build_suggestions(lbl)
                            response["yolo_machine_alert"] = {
                                "label": lbl,
                                "display_name": lbl_lower.title(),
                                "confidence": det.get("confidence", 0.0),
                                "cx_norm": det.get("cx_norm", 0.5),
                                "cy_norm": det.get("cy_norm", 0.5),
                                "bbox_norm": det.get("bbox_norm", []),
                            }
                            await websocket.send_json({
                                "type": "yolo_machine_suggestion",
                                "label": lbl,
                                "display_name": lbl_lower.title(),
                                "suggestions": suggestions,
                            })
                            last_machine_suggested = lbl_lower
                        break  # first/highest-conf machine only

                    # Reset first-seen for labels no longer in frame
                    detected_lower = {
                        str(d.get("label", d.get("class_name", ""))).lower().strip()
                        for d in last_yolo_detections
                    }
                    for gone_lbl in list(machine_first_seen.keys()):
                        if gone_lbl not in detected_lower:
                            del machine_first_seen[gone_lbl]
                            if last_machine_suggested == gone_lbl:
                                last_machine_suggested = ""  # allow re-suggest if machine reappears

                    await websocket.send_json(response)

                elif msg_type == "snapshot":
                    if isinstance(payload.get("imu_data"), dict):
                        latest_imu = imu_fusion_service.update(dict(payload.get("imu_data", {})))

                    image_data = payload.get("image_data")
                    if not image_data:
                        await websocket.send_json({"type": "error", "message": "Missing image_data"})
                        continue

                    # Debug log the incoming data
                    print(f"[DEBUG] Snapshot handler: received image_data of length {len(image_data)}")

                    image_bytes, bgr_image = pipeline_service.decode_frame(image_data)
                    if image_bytes is None or bgr_image is None:
                        print(f"[DEBUG] Snapshot handler: decode_frame failed - no image or bytes")
                        await websocket.send_json({"type": "error", "message": "Invalid image encoding"})
                        continue

                    print(f"[DEBUG] Snapshot handler: successfully decoded image, shape={bgr_image.shape if bgr_image is not None else 'None'}")

                    snapshot_timeout = max(SNAPSHOT_TIMEOUT_SECONDS, AI_TIMEOUT_SECONDS)

                    try:
                        snapshot_result = await asyncio.wait_for(
                            demo_vlm_service.analyze_snapshot(
                                image_bytes,
                                yolo_detections=last_yolo_detections,
                            ),
                            timeout=snapshot_timeout,
                        )
                    except asyncio.TimeoutError:
                        print(f"[DEBUG] Snapshot handler: timeout after {snapshot_timeout:.1f}s")
                        await websocket.send_json({"type": "error", "message": "Snapshot analysis timed out."})
                        continue

                    last_snapshot_image_bytes = image_bytes
                    last_snapshot_scene_summary = str(snapshot_result.get("scene_summary", ""))
                    last_snapshot_objects = [str(item) for item in snapshot_result.get("objects_detected", [])]

                    response = {
                        "type": "snapshot_result",
                        **snapshot_result,
                    }
                    if latest_imu:
                        response["imu"] = latest_imu
                    if isinstance(response.get("step_guidance"), dict):
                        last_step_guidance = dict(response.get("step_guidance", {}))
                    print(
                        "Snapshot analyzed | "
                        f"scene={last_snapshot_scene_summary} | "
                        f"objects={last_snapshot_objects}"
                    )
                    await websocket.send_json(response)

                    # ── Machine detection from LLM snap (if YOLO missed it) ─────
                    # If the VLM itself identified a gym machine in objects_detected,
                    # emit suggestion chips exactly as we do for YOLO detections.
                    for obj in last_snapshot_objects:
                        obj_lower = obj.strip().lower()
                        if obj_lower in ROBOFLOW_MACHINE_CLASSES:
                            suggestions = WorkoutService.build_suggestions(obj.strip())
                            await websocket.send_json({
                                "type": "yolo_machine_suggestion",
                                "label": obj.strip(),
                                "display_name": obj.strip().title(),
                                "suggestions": suggestions,
                                "source": "llm",
                            })
                            break  # first machine only

                    # ── Fetch exercise data if LLM requested it ──────────────
                    fetch_req = snapshot_result.get("fetch_exercise")
                    if isinstance(fetch_req, dict):
                        exercises = await _fetch_exercises(fetch_req)
                        if exercises:
                            await websocket.send_json({
                                "type": "exercise_data",
                                "exercises": exercises,
                            })

                elif msg_type == "prompt":
                    user_prompt = str(payload.get("prompt", "")).strip()
                    if not user_prompt:
                        await websocket.send_json({"type": "error", "message": "Missing prompt"})
                        continue

                    if last_snapshot_image_bytes is None:
                        await websocket.send_json({"type": "error", "message": "No analyzed snapshot available yet. Tap Snap first."})
                        continue

                    prompt_timeout = max(PROMPT_TIMEOUT_SECONDS, AI_TIMEOUT_SECONDS)

                    try:
                        followup_result = await asyncio.wait_for(
                            demo_vlm_service.answer_followup(
                                last_snapshot_image_bytes,
                                scene_summary=last_snapshot_scene_summary,
                                objects_detected=last_snapshot_objects,
                                user_prompt=user_prompt,
                                yolo_detections=last_yolo_detections,
                            ),
                            timeout=prompt_timeout,
                        )
                    except asyncio.TimeoutError:
                        print(f"[DEBUG] Prompt handler: timeout after {prompt_timeout:.1f}s")
                        await websocket.send_json({"type": "error", "message": "Prompt processing timed out."})
                        continue

                    response = {
                        "type": "prompt_response",
                        **followup_result,
                    }
                    if latest_imu:
                        response["imu"] = latest_imu
                    if isinstance(response.get("step_guidance"), dict):
                        last_step_guidance = dict(response.get("step_guidance", {}))
                    print(
                        "Prompt answered | "
                        f"prompt={user_prompt} | "
                        f"objects={response.get('objects_detected', [])}"
                    )
                    await websocket.send_json(response)

                    # ── Fetch exercise data if LLM requested it ──────────────
                    fetch_req = followup_result.get("fetch_exercise")
                    if isinstance(fetch_req, dict):
                        exercises = await _fetch_exercises(fetch_req)
                        if exercises:
                            await websocket.send_json({
                                "type": "exercise_data",
                                "exercises": exercises,
                            })

                elif msg_type == "step_control":
                    action = str(payload.get("action", "")).strip().lower()
                    if not action:
                        await websocket.send_json({"type": "error", "message": "Missing step action."})
                        continue

                    if not isinstance(last_step_guidance, dict) or not last_step_guidance:
                        await websocket.send_json({"type": "error", "message": "No step guidance available yet. Tap Snap first."})
                        continue

                    last_step_guidance = _apply_step_action(last_step_guidance, action)
                    step_update = _build_step_update_response(last_step_guidance, action=action)
                    if latest_imu:
                        step_update["imu"] = latest_imu
                    await websocket.send_json(step_update)

                elif msg_type == "imu":
                    imu_payload = payload.get("imu")
                    if not isinstance(imu_payload, dict):
                        await websocket.send_json({"type": "error", "message": "Invalid imu payload."})
                        continue
                    latest_imu = imu_fusion_service.update(dict(imu_payload))
                    await websocket.send_json({"type": "imu_ack", "received": True, "imu": latest_imu})
                
                elif msg_type == "set_persona":
                    persona_id = str(payload.get("persona", "")).strip().lower()
                    if persona_id in VALID_PERSONAS:
                        demo_vlm_service.set_persona(persona_id)
                        await websocket.send_json({
                            "type": "persona_ack",
                            "persona": persona_id,
                            "message": f"Persona switched to {persona_id.replace('_', ' ').title()}",
                        })
                    else:
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Unknown persona '{persona_id}'. Valid: gym_trainer, chef, physiotherapist",
                        })

                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                    
                else:
                    await websocket.send_json({"type": "error", "message": f"Unknown message type: {msg_type}"})
                    
            except json.JSONDecodeError:
                print("Received invalid JSON data")
                await websocket.send_json({"type": "error", "message": "Invalid JSON payload"})
                
    except WebSocketDisconnect:
        print(f"Client disconnected from stream: {client_ip}")
    except Exception as e:
        print(f"WebSocket error: {e}")

# ═══════════════════════════════════════════════════════════════════
# HALF 2 — SOFTWARE UI ASSISTANCE WEBSOCKET (/copilot)
# This route is completely independent of /stream (Half 1).
# Each connected Unity client gets its own UIDetector instance.
# ═══════════════════════════════════════════════════════════════════

# ── Phase 3 Helpers ───────────────────────────────────────────────

def _template_match(
    template_path: str,
    screenshot_bytes: bytes,
    screen_w: int,
    screen_h: int,
    confidence: float = 0.75,
    expected_x: float | None = None,
    expected_y: float | None = None,
):
    """
    Try to locate ``template_path`` inside the current screenshot using
    OpenCV normalised cross-correlation (TM_CCOEFF_NORMED).
    Includes stddev check (skips uniform/blank patches) and optional proximity check.
    """
    if not _CV2_OK or not template_path:
        return None
    import os
    if not os.path.exists(template_path):
        return None
    try:
        templ  = _cv2.imread(template_path, _cv2.IMREAD_COLOR)
        sc_arr = _np.frombuffer(screenshot_bytes, _np.uint8)
        screen = _cv2.imdecode(sc_arr, _cv2.IMREAD_COLOR)
        if templ is None or screen is None:
            return None

        # Check standard deviation — skip uniform/blank patches (e.g. solid white document area)
        _, stddev = _cv2.meanStdDev(templ)
        if _np.mean(stddev) < 12.0:
            return None

        th, tw = templ.shape[:2]
        result = _cv2.matchTemplate(screen, templ, _cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = _cv2.minMaxLoc(result)
        if max_val < confidence:
            return None

        cx = float(max_loc[0] + tw // 2)
        cy = float(max_loc[1] + th // 2)

        # Proximity sanity check: reject matches that jump > 350px away from recorded position
        if expected_x is not None and expected_y is not None:
            import math
            dist = math.hypot(cx - expected_x, cy - expected_y)
            if dist > 350.0:
                return None

        return {"x": cx, "y": cy, "width": float(tw), "height": float(th)}
    except Exception as exc:
        print(f"[Copilot] _template_match error: {exc}")
        return None



async def _find_matching_lesson(
    user_query: str,
    app_name: str,
    lessons_by_id: dict,
) -> "list[dict] | None":
    """
    Check if any published lesson in the DB matches this query.
    Uses sentence-transformers cosine similarity via step_policy_service.

    Returns a list of step dicts (compatible with the existing resolved-steps
    format) if a match is found, or None (caller falls back to LLM).
    """
    lesson_id = _step_policy.match_lesson(user_query, app_name, lessons_by_id)
    if lesson_id is None:
        return None
    try:
        db_steps = await lesson_repository.get_steps(lesson_id)
        if not db_steps:
            return None
        # Map DB rows to the step dict shape /copilot already understands
        steps: list[dict] = []
        for s in db_steps:
            steps.append({
                "action":        s.get("action", "click"),
                "target":        s.get("target", ""),
                "type":          s.get("target_type", "Button"),
                "tts_text":      s.get("tts_text", ""),
                "template_path": s.get("template_path"),
                "step_id":       s.get("id"),
                "bbox_x1":       s.get("bbox_x1"),
                "bbox_y1":       s.get("bbox_y1"),
                "bbox_x2":       s.get("bbox_x2"),
                "bbox_y2":       s.get("bbox_y2"),
                "resolved":      False,
                "source":        "lesson_db",
                "x": None, "y": None, "width": None, "height": None,
            })

        return steps
    except Exception as exc:
        print(f"[Copilot] _find_matching_lesson error: {exc}")
        return None


@app.websocket("/copilot")
async def copilot_endpoint(websocket: WebSocket):
    """
    Spatial AR Copilot WebSocket endpoint.

    Message types from Unity → Backend:
        {"type": "query",      "query": "...", "app": "Word"}
        {"type": "get_screen"}
        {"type": "step_done", "step_index": 0}
        {"type": "ping"}

    Message types Backend → Unity:
        {"type": "copilot_steps", "steps": [...], "total": N, "query": "..."}
        {"type": "screen_frame",  "image": "<base64>", "width": W, "height": H}
        {"type": "step_ack",     "step_index": N}
        {"type": "error",        "message": "..."}
        {"type": "pong"}
    """
    await websocket.accept()
    client_ip = websocket.client.host if websocket.client else "unknown"
    print(f"[Copilot] Client connected: {client_ip}")

    # Per-connection UI detector (owns the window handle)
    detector = UIDetector()
    last_app_name = ""
    # Tracks the resolved step list so step_done can look up the right step dict
    last_resolved_steps: list = []
    # Before-snapshot: JPEG bytes taken just before sending steps to Unity.
    # Used by VerificationService to diff against the after state.
    last_before_snap: bytes | None = None
    last_attempted_step: int = -1
    consecutive_attempts: int = 0
    # Lesson session tracking (Phase 3)
    active_lesson_id: "int | None" = None
    active_session_id: "int | None" = None
    # Lesson index for this connection (from app.state, built at startup)
    lessons_by_id: dict = getattr(app.state, "lessons_by_id", {})
    
    # Synchronize outgoing messages to prevent websockets AssertionError on concurrent writes
    send_lock = asyncio.Lock()

    # ── Background Task: Continuous Screen Streaming ─────────────
    # We push raw JPEG bytes as quickly as possible (targeting ~15 FPS)
    # without depending on explicit client-side "get_screen" polls.
    async def stream_screen_loop(ws: WebSocket):
        try:
            # Give Unity client 1 second to fully initialize its receive loop
            await asyncio.sleep(1.0)
            while True:
                # Capture frame as raw bytes (skips Base64 entirely)
                frame_bytes = await asyncio.to_thread(_copilot_screen.capture_bytes, quality=65)
                if frame_bytes:
                    try:
                        async with send_lock:
                            await ws.send_bytes(frame_bytes)
                    except (WebSocketDisconnect, RuntimeError):
                        break  # Client disconnected
                    except Exception as e:
                        if "assert waiter is None" in str(e) or "AssertionError" in repr(e):
                            break # Internal Starlette websockets concurrent close race condition
                        else:
                            print(f"[Copilot] Send error: {e}")
                            break
                            
                # Cap the framerate (~15fps -> ~66ms per frame)
                await asyncio.sleep(0.066)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if "closed" not in str(e).lower() and "close" not in str(e).lower():
                print(f"[Copilot] Stream loop error: {e}")

    stream_task = asyncio.create_task(stream_screen_loop(websocket))

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                async with send_lock:
                    await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = payload.get("type", "")
            if msg_type != "get_screen" and msg_type != "ping":
                print(f"[Copilot] Received: {msg_type}")

            # ── QUERY: user asks "how do I insert a chart?" ──────────
            if msg_type == "query":
                user_query = str(payload.get("query", "")).strip()
                app_name = str(payload.get("app", "Word")).strip()

                if not user_query:
                    async with send_lock:
                        await websocket.send_json({"type": "error", "message": "Empty query"})
                    continue

                # (Re-)connect to app if needed
                if app_name != last_app_name or not detector.is_connected():
                    connected = detector.connect(app_name)
                    if not connected:
                        async with send_lock:
                            await websocket.send_json({
                                "type": "error",
                                "message": f"Could not find '{app_name}' running on this PC. Please open it first.",
                            })
                        continue
                    last_app_name = app_name

                # Get grounding context (real control names) to reduce LLM hallucination
                available_controls = detector.get_control_titles_for_prompt()

                # Provide a current screenshot to providers that support visual grounding (e.g., UI-TARS).
                screenshot_bytes = await asyncio.to_thread(_copilot_screen.capture_bytes, 70)

                # ── Phase 3: Try DB lesson first, fall back to LLM ─────────
                db_steps = await _find_matching_lesson(user_query, app_name, lessons_by_id)
                is_db_lesson = bool(db_steps)

                if is_db_lesson:
                    # ── DB path ────────────────────────────────────────────
                    steps_raw = db_steps
                    matched_id = _step_policy.match_lesson(user_query, app_name, lessons_by_id)
                    if matched_id:
                        active_lesson_id = matched_id
                        try:
                            active_session_id = await lesson_repository.start_session(matched_id, 1)
                        except Exception:
                            active_session_id = None
                    print(f"[Copilot] Serving lesson_id={active_lesson_id} from DB ({len(steps_raw)} steps)")

                    # Resolve step coordinates: template → recording coords
                    resolved = list(steps_raw)
                    for step in resolved:
                        tpl_path = step.get("template_path")
                        matched_by_template = False

                        bx1 = step.get("bbox_x1")
                        by1 = step.get("bbox_y1")
                        bx2 = step.get("bbox_x2")
                        by2 = step.get("bbox_y2")
                        exp_x = int((bx1 + (bx2 or bx1)) / 2 * COPILOT_SCREEN_WIDTH) if bx1 is not None else None
                        exp_y = int((by1 + (by2 or by1)) / 2 * COPILOT_SCREEN_HEIGHT) if by1 is not None else None

                        # Tier 1: OpenCV template matching on current screen
                        if tpl_path and screenshot_bytes:
                            match_result = await asyncio.to_thread(
                                _template_match,
                                tpl_path,
                                screenshot_bytes,
                                COPILOT_SCREEN_WIDTH,
                                COPILOT_SCREEN_HEIGHT,
                                0.75,
                                exp_x,
                                exp_y,
                            )
                            if match_result:
                                step.update(
                                    x=match_result["x"], y=match_result["y"],
                                    width=match_result["width"], height=match_result["height"],
                                    resolved=True, source="template",
                                )
                                matched_by_template = True
                                print(f"[Copilot] Template matched '{step.get('target','')}' -> ({match_result['x']:.0f},{match_result['y']:.0f})")

                        # Tier 2: Stored recording coordinates (normalised → pixels)
                        if not matched_by_template:
                            if bx1 is not None and by1 is not None:
                                cx = exp_x
                                cy = exp_y
                                w  = max(int(((bx2 or bx1) - bx1) * COPILOT_SCREEN_WIDTH), 64)
                                h  = max(int(((by2 or by1) - by1) * COPILOT_SCREEN_HEIGHT), 64)
                                step.update(x=cx, y=cy, width=w, height=h, resolved=True, source="recording_coords")
                                print(f"[Copilot] Recording coords '{step.get('target','')}' -> ({cx},{cy})")
                            else:
                                step.setdefault("resolved", False)


                else:
                    # ── LLM path ───────────────────────────────────────────
                    active_lesson_id = None
                    active_session_id = None
                    steps_raw = await asyncio.to_thread(
                        _copilot_llm.parse_query,
                        user_query,
                        app_name,
                        available_controls,
                        COPILOT_MAX_STEPS,
                        screenshot_bytes,
                    )

                    if not steps_raw:
                        async with send_lock:
                            await websocket.send_json({
                                "type": "error",
                                "message": "AI could not generate steps for this query.",
                            })
                        continue

                    # Pywinauto resolution
                    resolved = await asyncio.to_thread(
                        detector.get_multiple_elements,
                        steps_raw,
                    )

                    # OmniParser fallback for step 0 only
                    if resolved and not resolved[0].get("resolved", False) and screenshot_bytes:
                        tgt0 = resolved[0].get("target", "")
                        print(f"[Copilot] Step 0 '{tgt0}' unresolved. Trying OmniParser...")
                        parsed_elements = await asyncio.to_thread(
                            _copilot_parser.parse,
                            screenshot_bytes,
                            COPILOT_SCREEN_WIDTH,
                            COPILOT_SCREEN_HEIGHT,
                        )
                        el = _copilot_parser.find_element(parsed_elements, tgt0)
                        if el:
                            cx, cy = _copilot_parser.center_px(el, COPILOT_SCREEN_WIDTH, COPILOT_SCREEN_HEIGHT)
                            w,  h  = _copilot_parser.size_px(el, COPILOT_SCREEN_WIDTH, COPILOT_SCREEN_HEIGHT)
                            resolved[0].update(x=cx, y=cy, width=w, height=h, resolved=True, source="omniparser")
                            print(f"[Copilot] OmniParser resolved '{tgt0}' -> ({cx:.0f},{cy:.0f})")

                # ── Safety gate: filter tts_text before sending to Unity/TTS ──
                for step in resolved:
                    raw_tts = step.get("tts_text", "")
                    if raw_tts:
                        step["tts_text"] = _copilot_safety.filter(raw_tts)

                # ── Before snapshot for verification (Day 2 gate) ──────────
                # Capture the screen AFTER steps are sent so the verifier has
                # a stable baseline of "what the screen looked like at step 0".
                # We do this as a best-effort fire-and-forget (don't block send).
                last_resolved_steps = resolved
                last_before_snap = await asyncio.to_thread(
                    _copilot_verifier.snapshot, _copilot_screen
                )

                async with send_lock:
                    await websocket.send_json({
                        "type": "copilot_steps",
                        "query": user_query,
                        "app": app_name,
                        "total": len(resolved),
                        "steps": resolved,
                    })
                print(f"[Copilot] Sent {len(resolved)} steps for query: '{user_query}'")

            # ── GET_SCREEN (Deprecated): Live screenshots now pushed automatically via Binary channel
            elif msg_type == "get_screen":
                pass # Handled by the background push loop


            # ── STEP_DONE: Unity confirms user completed a step ──────────
            elif msg_type == "step_done":
                step_idx = int(payload.get("step_index", -1))
                print(f"[Copilot] step_done received for step {step_idx}.")

                # Track consecutive verification attempts for this step
                if step_idx == last_attempted_step:
                    consecutive_attempts += 1
                else:
                    last_attempted_step = step_idx
                    consecutive_attempts = 1

                # Look up the step dict so verifier knows what action/target to narrate
                step_dict: dict = {"step_index": step_idx}
                if 0 <= step_idx < len(last_resolved_steps):
                    step_dict = dict(last_resolved_steps[step_idx])
                    step_dict["step_index"] = step_idx

                # Capture after-screenshot and run diff in thread pool
                after_snap = await asyncio.to_thread(
                    _copilot_verifier.snapshot, _copilot_screen
                )
                result = await asyncio.to_thread(
                    _copilot_verifier.verify,
                    last_before_snap,
                    after_snap,
                    step_dict,
                )

                # Override verification result if the user is persistently retrying
                if consecutive_attempts >= 2 and not result.passed:
                    result.passed = True
                    result.tts_text = "I will proceed to the next step. Let's continue."
                    print(f"[Copilot] Step {step_idx} force-passed due to consecutive attempts.")

                next_step_data = None
                if result.passed:
                    next_idx = step_idx + 1
                    if 0 <= next_idx < len(last_resolved_steps):
                        next_step = last_resolved_steps[next_idx]
                        target_name = next_step.get("label") or next_step.get("target") or ""
                        control_type = next_step.get("type", "Button")
                        print(f"[Copilot] Resolving next step {next_idx} dynamically for target '{target_name}'...")
                        
                        # 1. Try pywinauto first
                        rect = None
                        if detector.is_connected():
                            try:
                                rect = detector.get_element_rect(target_name, control_type)
                            except Exception as ex:
                                print(f"[Copilot] Dynamic pywinauto exception: {ex}")
                                
                        if rect:
                            cx, cy, w, h = rect["x"], rect["y"], rect["width"], rect["height"]
                            next_step.update(x=cx, y=cy, width=w, height=h, resolved=True, source="pywinauto")
                            next_step_data = {"x": cx, "y": cy, "width": w, "height": h, "resolved": True}
                            print(f"[Copilot] Dynamic pywinauto resolved '{target_name}' -> ({cx:.0f}, {cy:.0f})")
                        else:
                            # 2. Template matching (Phase 3 — fast, uses trainer-recorded patch ~15 ms)
                            tpl_path = next_step.get("template_path")
                            if tpl_path and after_snap:
                                tpl_result = await asyncio.to_thread(
                                    _template_match, tpl_path, after_snap,
                                    COPILOT_SCREEN_WIDTH, COPILOT_SCREEN_HEIGHT
                                )
                                if tpl_result:
                                    tcx, tcy, tw, th = tpl_result
                                    next_step.update(x=tcx, y=tcy, width=tw, height=th, resolved=True, source="template")
                                    next_step_data = {"x": tcx, "y": tcy, "width": tw, "height": th, "resolved": True}
                                    print(f"[Copilot] Dynamic template matched '{target_name}' -> ({tcx:.0f}, {tcy:.0f})")

                            # 3. OmniParser fallback (slow — only when both above fail)
                            if not next_step.get("resolved") and after_snap:
                                print(f"[Copilot] Target '{target_name}' not resolved by pywinauto. Running dynamic OmniParser...")
                                parsed_elements = await asyncio.to_thread(
                                    _copilot_parser.parse,
                                    after_snap,
                                    COPILOT_SCREEN_WIDTH,
                                    COPILOT_SCREEN_HEIGHT,
                                )
                                el = _copilot_parser.find_element(parsed_elements, target_name)
                                if el:
                                    cx, cy = _copilot_parser.center_px(el, COPILOT_SCREEN_WIDTH, COPILOT_SCREEN_HEIGHT)
                                    w, h = _copilot_parser.size_px(el, COPILOT_SCREEN_WIDTH, COPILOT_SCREEN_HEIGHT)
                                    next_step.update(x=cx, y=cy, width=w, height=h, resolved=True, source="omniparser")
                                    next_step_data = {"x": cx, "y": cy, "width": w, "height": h, "resolved": True}
                                    print(f"[Copilot] Dynamic OmniParser resolved '{target_name}' -> ({cx:.0f}, {cy:.0f})")
                                else:
                                    print(f"[Copilot] Dynamic OmniParser failed to resolve '{target_name}'.")


                # Update before-snap for next step
                last_before_snap = after_snap

                # Phase 3: track learner progress silently in DB (no-op if LLM path)
                if active_session_id is not None and result.passed:
                    try:
                        step_id_for_log = (
                            last_resolved_steps[step_idx].get("step_id")
                            if 0 <= step_idx < len(last_resolved_steps) else None
                        )
                        await lesson_repository.log_step_event(
                            active_session_id, step_id_for_log or 0,
                            "verified_pass", result.diff_score
                        )
                        next_progress_idx = step_idx + 1
                        await lesson_repository.update_session_step(
                            active_session_id, next_progress_idx
                        )
                        if next_progress_idx >= len(last_resolved_steps):
                            await lesson_repository.complete_session(active_session_id)
                            print(f"[Copilot] Lesson session {active_session_id} completed.")
                    except Exception as _prog_err:
                        print(f"[Copilot] Progress tracking error (non-fatal): {_prog_err}")

                # Filter verification coaching text through safety gate
                safe_tts = _copilot_safety.filter(result.tts_text)

                async with send_lock:
                    await websocket.send_json({
                        "type":       "step_verification",
                        "step_index": step_idx,
                        "passed":     result.passed,
                        "diff_score": result.diff_score,
                        "tts_text":   safe_tts,
                        "next_step":  next_step_data,
                    })

            # ── PING / keepalive ─────────────────────────────────────
            elif msg_type == "ping":
                async with send_lock:
                    await websocket.send_json({"type": "pong"})

            else:
                async with send_lock:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown message type: {msg_type}",
                    })

    except WebSocketDisconnect:
        print(f"[Copilot] Client disconnected: {client_ip}")
    except Exception as e:
        if "closed" not in str(e).lower() and "close" not in str(e).lower():
            print(f"[Copilot] Unhandled error: {e}")
        try:
            async with send_lock:
                await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        # Guarantee we cancel the stream loop when the connection drops
        stream_task.cancel()


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
