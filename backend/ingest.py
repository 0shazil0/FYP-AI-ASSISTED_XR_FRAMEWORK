"""
backend/ingest.py
==================
One-command lesson ingestion CLI.

Usage:
    python ingest.py recordings/word_bold.json \\
        --title "Make text bold in Word" \\
        --app "WINWORD.EXE"

What it does:
    1. Parses the OpenAdapt JSON export
    2. Grounds each click to a semantic label (via OmniParser if available)
    3. Auto-extracts 96x96 template PNG at each click point
    4. Generates tts_text via Ollama (fallback: deterministic template)
    5. Saves lesson + steps + templates to neuroguide.db
    6. Publishes the lesson so /copilot uses it immediately
    7. Rebuilds the in-memory step policy index (next server restart picks it up)

Options:
    --title     Lesson display title (required for new lessons)
    --app       App process name, e.g. WINWORD.EXE, EXCEL.EXE (default: auto-detect)
    --org       Organisation ID (default: 1)
    --trainer   Trainer user ID (default: 1)
    --no-publish  Save as draft — do NOT publish automatically
    --threshold Minimum score for template matching (default: 0.75)
"""

import argparse
import asyncio
import sys
import os
from pathlib import Path

# Make sure we can import from backend/
_BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(_BACKEND_DIR))

# Load .env so Ollama URL/model/keys are available for GuidanceComposer
try:
    from dotenv import load_dotenv
    load_dotenv(_BACKEND_DIR / ".env")
except Exception:
    pass

from services.demo_ingestor import DemoIngestor
from services.guidance_composer import GuidanceComposer
from services import lesson_repository as lr
from services import step_policy_service as sp



async def main(args):
    print(f"\n[Ingest] File:   {args.json_file}")
    print(f"[Ingest] Title:  {args.title}")
    print(f"[Ingest] App:    {args.app}")
    print(f"[Ingest] Org:    {args.org}  Trainer: {args.trainer}\n")

    # ── Step 1: Ensure org + trainer user exist ──────────────────────
    org_id = args.org
    trainer_id = args.trainer
    try:
        org_id = await lr.get_or_create_org("Default Organisation")
        trainer_id = await lr.get_or_create_user(
            "trainer@neuroguide.local", "Trainer", org_id, "trainer"
        )
    except Exception as e:
        print(f"[Ingest] Warning: org/user lookup failed ({e}), using id=1 as fallback.")
        org_id = 1
        trainer_id = 1

    # ── Step 2: Create lesson record ─────────────────────────────────
    lesson_id = await lr.create_lesson(
        title=args.title,
        app_name=args.app,
        org_id=org_id,
        created_by=trainer_id,
        source_type="openadapt",
        source_path=args.json_file,
    )
    print(f"[Ingest] Lesson created: id={lesson_id}")

    # ── Step 3: Ingest steps ─────────────────────────────────────────
    composer = GuidanceComposer()
    ingestor = DemoIngestor(
        screen_parser=None,      # OmniParser grounding optional at ingest time
        guidance_composer=composer,
    )

    print(f"[Ingest] Parsing {args.json_file} ...")
    steps = ingestor.ingest_json(args.json_file, app_name_override=args.app)

    if not steps:
        print("[Ingest] ERROR: No action events found in JSON file.")
        print("         Check that the file contains click/type/scroll events.")
        sys.exit(1)

    print(f"[Ingest] Found {len(steps)} steps.")

    # ── Step 4: Save steps to DB ─────────────────────────────────────
    step_ids = await lr.upsert_steps(lesson_id, steps)
    print(f"[Ingest] Saved {len(step_ids)} steps to DB.")

    # ── Step 5: Save template records ────────────────────────────────
    saved_templates = 0
    for step, step_id in zip(steps, step_ids):
        tpl_path = step.get("template_path")
        if tpl_path and Path(tpl_path).exists():
            await lr.save_template(
                app_name=args.app,
                label=step.get("target", ""),
                file_path=tpl_path,
                step_id=step_id,
            )
            saved_templates += 1
    print(f"[Ingest] Saved {saved_templates} template records to DB.")

    # ── Step 6: Print step summary ───────────────────────────────────
    print("\n[Ingest] Steps:")
    for s in steps:
        tpl_indicator = "🖼 " if s.get("template_path") else "   "
        print(f"  {tpl_indicator}[{s['step_index']}] {s['action']:12} -> {s['target']:30}  \"{s['tts_text']}\"")

    # ── Step 7: Publish (or leave as draft) ──────────────────────────
    if not args.no_publish:
        await lr.publish_lesson(lesson_id)
        print(f"\n[Ingest] Lesson {lesson_id} PUBLISHED. /copilot will use it immediately.")

        # Rebuild the step policy index for the current process
        # (the server process will pick it up on next restart,
        #  or you can call /admin/lessons/rebuild-index when that endpoint exists)
        try:
            published = await lr.list_lessons(status="published")
            sp.build_index(published)
            print(f"[Ingest] Step policy index rebuilt: {len(published)} lessons.")
        except Exception as e:
            print(f"[Ingest] Index rebuild warning (non-fatal): {e}")
    else:
        print(f"\n[Ingest] Lesson {lesson_id} saved as DRAFT (--no-publish was set).")
        print("         Publish later with:")
        print(f"         python ingest.py --publish-id {lesson_id}")

    print()
    print("=" * 60)
    print(f"  DONE — lesson_id={lesson_id}  steps={len(steps)}  templates={saved_templates}")
    print("=" * 60)
    print()
    print("To test it live, start the backend (python main.py) and ask:")
    print(f'  "{args.title.lower()}"')
    print("You should see: [Copilot] Serving lesson_id=X from DB")
    print()


def cli():
    parser = argparse.ArgumentParser(
        description="Ingest an OpenAdapt JSON recording into NeuroGuide XR"
    )
    parser.add_argument(
        "json_file",
        help="Path to the OpenAdapt JSON export, e.g. recordings/word_bold.json"
    )
    parser.add_argument(
        "--title", "-t",
        required=True,
        help='Lesson display title, e.g. "Make text bold in Word"'
    )
    parser.add_argument(
        "--app", "-a",
        default="WINWORD.EXE",
        help="App process name (default: WINWORD.EXE)"
    )
    parser.add_argument(
        "--org", type=int, default=1,
        help="Organisation ID (default: 1)"
    )
    parser.add_argument(
        "--trainer", type=int, default=1,
        help="Trainer user ID (default: 1)"
    )
    parser.add_argument(
        "--no-publish", action="store_true",
        help="Save as draft instead of publishing immediately"
    )
    parser.add_argument(
        "--publish-id", type=int, default=None,
        help="Publish an existing draft lesson by ID (no JSON needed)"
    )

    args = parser.parse_args()

    # Handle --publish-id shortcut
    if args.publish_id:
        async def publish_only():
            await lr.publish_lesson(args.publish_id)
            published = await lr.list_lessons(status="published")
            sp.build_index(published)
            print(f"Lesson {args.publish_id} published. Index rebuilt ({len(published)} lessons).")
        asyncio.run(publish_only())
        return

    if not Path(args.json_file).exists():
        print(f"ERROR: File not found: {args.json_file}")
        print("       Place your OpenAdapt JSON export in the recordings/ folder.")
        sys.exit(1)

    asyncio.run(main(args))


if __name__ == "__main__":
    cli()
