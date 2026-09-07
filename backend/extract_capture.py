"""
backend/extract_capture.py
============================
Converts an OpenAdapt capture (v1.2.5+) to a NeuroGuide-compatible JSON,
then ingests it into the lesson DB.

USAGE:
  # After recording with: openadapt capture start --name word-bold
  # The capture is saved to:  C:/Users/<YourName>/word-bold/recording.db

  # Run this script:
  python extract_capture.py "word-bold" \\
      --title "Make text bold in Word" \\
      --app "WINWORD.EXE"

  # If OpenAdapt saved it with a different folder name (uses --name literally):
  python extract_capture.py "Making text bold in word" \\
      --title "Make text bold in Word" --app "WINWORD.EXE"

  # Extract only (inspect JSON before ingesting):
  python extract_capture.py "word-bold" --extract-only

HOW IT WORKS:
  1. Finds the capture directory under ~/  (OpenAdapt stores as ~/capture-name/)
  2. Opens recording.db using OpenAdapt's SQLAlchemy session
  3. Filters to meaningful events: mouse_pressed=True clicks + key presses
  4. Extracts screenshot frames from the MP4 video at click timestamps
  5. Crops 96x96 template PNGs around each click point
  6. Writes recordings/<name>.json
  7. Ingests into neuroguide.db + publishes
"""

import argparse
import asyncio
import base64
import json
import os
import sys
from pathlib import Path

# Add backend/ to path for our own services
_BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(_BACKEND_DIR))

# Load .env so OLLAMA_BASE_URL / model / API keys are available
try:
    from dotenv import load_dotenv
    load_dotenv(_BACKEND_DIR / ".env")
except Exception:
    pass  # dotenv optional — env vars may already be set

# Also expose system Python site-packages so openadapt_capture (installed globally)
# is importable even when running inside the project venv
_sys_sp = r"C:\Users\PC\AppData\Roaming\Python\Python311\site-packages"
if _sys_sp not in sys.path and Path(_sys_sp).exists():
    sys.path.append(_sys_sp)



# ---------------------------------------------------------------------------
# Locate the capture directory
# ---------------------------------------------------------------------------

def find_capture_dir(name: str) -> Path:
    """
    OpenAdapt saves captures to ~/<capture-name>/  (the name you passed with --name).
    Search common locations.
    """
    home = Path.home()
    candidates = [
        home / name,
        Path(os.getcwd()) / name,
        Path(os.getcwd()) / "recordings" / name,
    ]
    for c in candidates:
        if (c / "recording.db").exists():
            return c

    # Fuzzy: find any folder under ~ that has a recording.db and name matches
    for folder in home.iterdir():
        if not folder.is_dir():
            continue
        if (folder / "recording.db").exists():
            folder_lower = folder.name.lower().replace(" ", "-").replace("_", "-")
            name_lower   = name.lower().replace(" ", "-").replace("_", "-")
            if folder_lower == name_lower or name_lower in folder_lower or folder_lower in name_lower:
                return folder

    return None


# ---------------------------------------------------------------------------
# Video frame extraction helper
# ---------------------------------------------------------------------------

def _extract_frame_at(video_path: Path, timestamp: float):
    """
    Extract a single frame from the MP4 at the given Unix timestamp.
    Returns numpy BGR image or None.
    """
    try:
        import cv2
        cap_ref_ts = None  # we need the video start time

        # OpenAdapt video filename encodes the start timestamp:
        # e.g.  oa_recording-1783860063.7023196.mp4
        import re
        m = re.search(r"oa_recording-(\d+\.?\d*)", video_path.name)
        if m:
            cap_ref_ts = float(m.group(1))
        else:
            return None

        offset_sec = timestamp - cap_ref_ts
        if offset_sec < 0:
            offset_sec = 0

        vc = cv2.VideoCapture(str(video_path))
        if not vc.isOpened():
            return None

        fps = vc.get(cv2.CAP_PROP_FPS) or 30.0
        frame_no = int(offset_sec * fps)
        vc.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ret, frame = vc.read()
        vc.release()
        return frame if ret else None
    except Exception as exc:
        print(f"[Extract] Frame extraction warning: {exc}")
        return None


def _frame_to_b64(frame) -> str:
    """Encode numpy BGR frame to base64 PNG string."""
    try:
        import cv2, numpy as np
        _, buf = cv2.imencode(".png", frame)
        return base64.b64encode(buf.tobytes()).decode()
    except Exception:
        return ""


def _crop_template(frame, px: int, py: int, size: int = 96) -> str:
    """Crop and save a template PNG. Returns relative path or empty string."""
    return ""  # placeholder — template extraction is done by DemoIngestor from screenshot_b64


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

def extract_capture(capture_dir: Path, out_path: Path) -> list[dict]:
    """
    Read the OpenAdapt recording.db and convert to NeuroGuide event JSON.
    Embeds screenshot_b64 so DemoIngestor can extract 96x96 templates.
    """
    db_path = capture_dir / "recording.db"
    if not db_path.exists():
        print(f"[Extract] ERROR: No recording.db in {capture_dir}")
        sys.exit(1)

    # Load session
    from openadapt_capture.db import get_session_for_path
    from openadapt_capture.db.models import Recording, ActionEvent

    session = get_session_for_path(str(db_path))
    rec = session.query(Recording).first()
    if rec is None:
        print("[Extract] ERROR: recording.db has no recording row.")
        sys.exit(1)

    print(f"[Extract] Recording: '{rec.task_description}' (id={rec.id})")

    # Pull ALL action events
    all_events = (
        session.query(ActionEvent)
        .filter(ActionEvent.recording_id == rec.id)
        .order_by(ActionEvent.timestamp)
        .all()
    )
    print(f"[Extract] Total events in DB: {len(all_events)}")

    # Filter to meaningful, overlayable events only
    # Rules:
    #   KEEP clicks (mouse_pressed=True) at non-zero coordinates
    #   KEEP type events only if they carry a printable character AND have coordinates
    #   KEEP scroll events at non-zero coordinates
    #   DROP keyboard shortcuts (Ctrl+X, Alt+F4, etc.) — can't draw AR overlay on them
    #   DROP events at (0, 0) — these have no valid screen position
    #   DEDUPLICATE near-identical clicks (same ±10px within 0.5 s)

    CLICK_NAMES  = {"click", "double_click", "right_click"}
    SCROLL_NAMES = {"scroll", "mouse_scroll"}

    # Modifier keys to skip entirely
    MODIFIER_KEYS = {
        "ctrl_l", "ctrl_r", "ctrl", "alt_l", "alt_r", "alt",
        "shift_l", "shift_r", "shift", "super_l", "super_r",
        "caps_lock", "tab", "escape", "return", "enter",
        "backspace", "delete", "insert", "home", "end",
        "page_up", "page_down", "f1","f2","f3","f4","f5","f6",
        "f7","f8","f9","f10","f11","f12",
    }

    def _is_printable_key(e) -> bool:
        ch = (e.key_char or "").strip()
        return len(ch) == 1 and ch.isprintable() and ch not in "\t\r\n"

    pre_dedup = []
    for e in all_events:
        name = (e.name or "").lower()
        px   = int(e.mouse_x or 0)
        py   = int(e.mouse_y or 0)

        if name in CLICK_NAMES:
            if getattr(e, "mouse_pressed", False) and (px != 0 or py != 0):
                pre_dedup.append(e)
        elif name in SCROLL_NAMES:
            if px != 0 or py != 0:
                pre_dedup.append(e)
        # Keep typed text if it has coordinates and is a real character
        elif "type" in name or name in {"press", "key_press"}:
            key_id = (e.key_char or e.key_name or "").lower()
            if key_id in MODIFIER_KEYS:
                continue
            if _is_printable_key(e) and (px != 0 or py != 0):
                pre_dedup.append(e)

    # Deduplicate: drop click if previous click was <0.5s ago and within 15px
    DEDUP_SEC = 0.5
    DEDUP_PX  = 15
    filtered = []
    for e in pre_dedup:
        if filtered and (e.name or "").lower() in CLICK_NAMES:
            prev = filtered[-1]
            dt   = abs((e.timestamp or 0) - (prev.timestamp or 0))
            dpx  = abs(int(e.mouse_x or 0) - int(prev.mouse_x or 0))
            dpy  = abs(int(e.mouse_y or 0) - int(prev.mouse_y or 0))
            if dt < DEDUP_SEC and dpx < DEDUP_PX and dpy < DEDUP_PX:
                continue  # skip duplicate
        filtered.append(e)

    print(f"[Extract] Meaningful events after filtering+dedup: {len(filtered)} "
          f"(from {len(all_events)} raw)")


    # Find the video file for frame extraction
    video_path = None
    for f in capture_dir.glob("oa_recording-*.mp4"):
        video_path = f
        break

    if video_path:
        print(f"[Extract] Video found: {video_path.name} — will extract screenshot frames")
    else:
        print("[Extract] No video found — templates will be skipped (screenshots not available)")

    # Convert to NeuroGuide event dicts
    events_out = []
    for ev in filtered:
        name    = (ev.name or "").lower()
        px      = int(ev.mouse_x or 0)
        py      = int(ev.mouse_y or 0)
        key_ch  = ev.key_char or ev.key_name or ""
        ts      = ev.timestamp or 0.0

        # Map to simple action type
        if name in CLICK_NAMES or "click" in name:
            act = "click"
        elif "scroll" in name:
            act = "scroll"
        else:
            act = "type"

        # Extract screenshot from video at this timestamp
        sc_b64 = ""
        if video_path and act == "click":
            frame = _extract_frame_at(video_path, ts)
            if frame is not None:
                sc_b64 = _frame_to_b64(frame)

        events_out.append({
            "type":           act,
            "x":              px,
            "y":              py,
            "text":           key_ch if act == "type" else "",
            "window_app":     "",          # not reliably available in this schema
            "window_title":   "",
            "timestamp":      ts,
            "screenshot_b64": sc_b64,
        })

    print(f"[Extract] Converted {len(events_out)} events to NeuroGuide format.")

    # Write JSON
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(events_out, f, indent=2)
    print(f"[Extract] Saved: {out_path}")

    session.close()
    return events_out


# ---------------------------------------------------------------------------
# Ingest into NeuroGuide DB
# ---------------------------------------------------------------------------

async def ingest(json_path: Path, title: str, app: str):
    from services.demo_ingestor import DemoIngestor
    from services.guidance_composer import GuidanceComposer
    from services import lesson_repository as lr
    from services import step_policy_service as sp
    from db.database import init_db

    await init_db()

    org_id     = await lr.get_or_create_org("Default Organisation")
    trainer_id = await lr.get_or_create_user(
        "trainer@neuroguide.local", "Trainer", org_id, "trainer"
    )

    lesson_id = await lr.create_lesson(
        title=title, app_name=app,
        org_id=org_id, created_by=trainer_id,
        source_type="openadapt", source_path=str(json_path),
    )
    print(f"\n[Ingest] Lesson created: id={lesson_id}  title='{title}'")

    ingestor = DemoIngestor(guidance_composer=GuidanceComposer())
    steps    = ingestor.ingest_json(str(json_path), app_name_override=app)

    if not steps:
        print("[Ingest] No steps extracted — check the JSON file.")
        return

    step_ids = await lr.upsert_steps(lesson_id, steps)

    saved_tpl = 0
    for step, step_id in zip(steps, step_ids):
        tpl = step.get("template_path")
        if tpl and Path(tpl).exists():
            await lr.save_template(app, step.get("target", ""), tpl, step_id)
            saved_tpl += 1

    await lr.publish_lesson(lesson_id)

    published = await lr.list_lessons(status="published")
    sp.build_index(published)

    print()
    print("=" * 60)
    print(f"  DONE  lesson_id={lesson_id}  steps={len(steps)}  templates={saved_tpl}")
    print(f"  '{title}' is PUBLISHED — /copilot will serve it from DB")
    print("=" * 60)
    print()
    print("Test: start backend then ask in AR:")
    print(f'  "{title.lower()}"')
    print("  Expected log: [Copilot] Serving lesson_id=X from DB")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract an OpenAdapt capture and ingest into NeuroGuide XR"
    )
    parser.add_argument(
        "capture_name",
        help=(
            "The --name you used with 'openadapt capture start --name <name>'. "
            "OpenAdapt stores captures at ~/capture-name/ by default."
        )
    )
    parser.add_argument(
        "--title", "-t", default="",
        help='Lesson title, e.g. "Make text bold in Word"'
    )
    parser.add_argument(
        "--app", "-a", default="WINWORD.EXE",
        help="App process name (default: WINWORD.EXE)"
    )
    parser.add_argument(
        "--capture-dir", default="",
        help="Override capture directory path (if not under ~/capture-name/)"
    )
    parser.add_argument(
        "--extract-only", action="store_true",
        help="Only write the JSON, do not ingest into the DB"
    )
    args = parser.parse_args()

    title       = args.title or args.capture_name.replace("-", " ").title()
    capture_dir = Path(args.capture_dir) if args.capture_dir else find_capture_dir(args.capture_name)
    out_path    = Path("recordings") / f"{args.capture_name.replace(' ', '_')}.json"

    if capture_dir is None:
        print(f"[Extract] ERROR: Could not find capture '{args.capture_name}'")
        print(f"          Searched under: {Path.home()}/")
        print(f"          Use --capture-dir to specify the exact path.")
        print(f"          Example: --capture-dir \"C:/Users/PC/Making text bold in word\"")
        sys.exit(1)

    print(f"[Extract] Capture directory: {capture_dir}")
    extract_capture(capture_dir, out_path)

    if not args.extract_only:
        asyncio.run(ingest(out_path, title, args.app))
    else:
        print(f"\nJSON saved to: {out_path}")
        print(f"To ingest:")
        print(f'  python ingest.py {out_path} --title "{title}" --app "{args.app}"')


if __name__ == "__main__":
    main()
