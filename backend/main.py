import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import json
import asyncio


from config import (
    AI_TIMEOUT_SECONDS,
    FRAME_DIFF_THRESHOLD,
    PROMPT_TIMEOUT_SECONDS,
    SNAPSHOT_TIMEOUT_SECONDS,
)
from services.frame_differ import FrameDiffer
from services.pipeline_service import PipelineService
from services.vlm_service import VlmService

app = FastAPI(title="NeuroGuide XR Backend")
pipeline_service = PipelineService()
demo_vlm_service = VlmService()


def _clamp_step(step: int, total_steps: int) -> int:
    if total_steps <= 0:
        return 1
    return max(1, min(step, total_steps))


def _build_step_update_response(step_guidance: dict, *, action: str) -> dict:
    current_step = int(step_guidance.get("current_step", 1) or 1)
    total_steps = int(step_guidance.get("total_steps", 1) or 1)
    steps = step_guidance.get("steps", [])

    instruction_text = "Follow the highlighted step."
    target_object = "scene"
    visual_type = "highlight"
    location_3d = [0.0, 0.0, 1.3]

    if isinstance(steps, list) and len(steps) >= current_step:
        step_item = steps[current_step - 1]
        if isinstance(step_item, dict):
            instruction_text = str(step_item.get("instruction", instruction_text))
            target_object = str(step_item.get("target_object", target_object))
            visual_type = str(step_item.get("visual_hint", visual_type))

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
        "user_message": f"Step {current_step}/{total_steps}",
    }


def _apply_step_action(step_guidance: dict, action: str) -> dict:
    if not isinstance(step_guidance, dict):
        return {}

    total_steps = int(step_guidance.get("total_steps", 1) or 1)
    current_step = int(step_guidance.get("current_step", 1) or 1)

    normalized_action = action.strip().lower()
    if normalized_action in {"next", "step_next", "forward"}:
        current_step += 1
    elif normalized_action in {"previous", "prev", "step_prev", "back"}:
        current_step -= 1
    elif normalized_action in {"reset", "restart"}:
        current_step = 1

    current_step = _clamp_step(current_step, total_steps)
    step_guidance["current_step"] = current_step

    steps = step_guidance.get("steps", [])
    if isinstance(steps, list) and len(steps) >= current_step:
        step_item = steps[current_step - 1]
        if isinstance(step_item, dict):
            active_hint = step_guidance.get("active_hint", {})
            if not isinstance(active_hint, dict):
                active_hint = {}
            active_hint["visual_type"] = str(step_item.get("visual_hint", active_hint.get("visual_type", "highlight")))
            active_hint["target_object"] = str(step_item.get("target_object", active_hint.get("target_object", "scene")))
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
async def health_check():
    return {"status": "ok"}

@app.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    client_ip = websocket.client.host if websocket.client else "unknown"
    print(f"Client connected to stream: {client_ip}")
    frame_differ = FrameDiffer(threshold=FRAME_DIFF_THRESHOLD)
    last_snapshot_image_bytes = None
    last_snapshot_scene_summary = ""
    last_snapshot_objects = []
    last_step_guidance = {}
    latest_imu = {}
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
                        latest_imu = dict(payload.get("imu_data", {}))

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
                    await websocket.send_json(response)

                elif msg_type == "snapshot":
                    if isinstance(payload.get("imu_data"), dict):
                        latest_imu = dict(payload.get("imu_data", {}))

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

                    try:
                        snapshot_result = await asyncio.wait_for(
                            demo_vlm_service.analyze_snapshot(image_bytes),
                            timeout=max(SNAPSHOT_TIMEOUT_SECONDS, AI_TIMEOUT_SECONDS),
                        )
                    except asyncio.TimeoutError:
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

                elif msg_type == "prompt":
                    user_prompt = str(payload.get("prompt", "")).strip()
                    if not user_prompt:
                        await websocket.send_json({"type": "error", "message": "Missing prompt"})
                        continue

                    if last_snapshot_image_bytes is None:
                        await websocket.send_json({"type": "error", "message": "No analyzed snapshot available yet. Tap Snap first."})
                        continue

                    try:
                        followup_result = await asyncio.wait_for(
                            demo_vlm_service.answer_followup(
                                last_snapshot_image_bytes,
                                scene_summary=last_snapshot_scene_summary,
                                objects_detected=last_snapshot_objects,
                                user_prompt=user_prompt,
                            ),
                            timeout=max(PROMPT_TIMEOUT_SECONDS, AI_TIMEOUT_SECONDS),
                        )
                    except asyncio.TimeoutError:
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
                    latest_imu = dict(imu_payload)
                    await websocket.send_json({"type": "imu_ack", "received": True})
                
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

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
