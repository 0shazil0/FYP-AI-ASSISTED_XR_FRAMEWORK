"""
backend/patch_tts.py
======================
Retroactively regenerate tts_text for existing lesson steps that got
coordinate-based fallback labels (e.g. "Click element_at_1367_1180").

USAGE:
    # Preview what will be updated (dry run)
    python patch_tts.py --lesson-id 4 --dry-run

    # Apply to all published lessons
    python patch_tts.py --all

    # Apply to a specific lesson
    python patch_tts.py --lesson-id 4

    # Manually provide step labels for a lesson (best quality)
    python patch_tts.py --lesson-id 4 --labels "Home tab,Bold button,Bold button,document area,Home tab,Close"
"""

import argparse
import asyncio
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(_BACKEND_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(_BACKEND_DIR / ".env")
except Exception:
    pass

from db.database import init_db
from services import lesson_repository as lr
from services.guidance_composer import GuidanceComposer


_COORD_LABEL_PREFIX = "element_at_"


def _is_fallback_label(label: str) -> bool:
    return label.startswith(_COORD_LABEL_PREFIX) or not label.strip()


async def patch_lesson(lesson_id: int, manual_labels: list[str] | None, dry_run: bool):
    lesson = await lr.get_lesson(lesson_id)
    if not lesson:
        print(f"  [!] Lesson {lesson_id} not found.")
        return

    steps = await lr.get_steps(lesson_id)
    print(f"\n  Lesson {lesson_id}: '{lesson['title']}' — {len(steps)} steps")

    composer = GuidanceComposer()
    app_name = lesson.get("app_name", "")

    patched = 0
    for s in steps:
        idx    = s["step_index"]
        action = s.get("action", "click")
        label  = s.get("target") or ""
        cur_tts = s.get("tts_text") or ""

        # Determine the label to use
        if manual_labels and idx < len(manual_labels):
            new_label = manual_labels[idx].strip()
        elif _is_fallback_label(label):
            # Try to guess a human label from the action + coordinate
            # (no OmniParser at this point, so just use action)
            new_label = label  # keep as-is if no manual override
        else:
            new_label = label  # already has a good label

        # Only regenerate if label is still a coordinate (and no manual override)
        if _is_fallback_label(new_label) and not manual_labels:
            print(f"    [{idx}] SKIP — still coordinate-based (use --labels to fix)")
            continue

        new_tts = composer.compose(action, new_label or label, idx + 1, app_name)
        print(f"    [{idx}] {action:8} | label='{new_label}' | tts='{new_tts}'")

        if not dry_run:
            await lr.update_step(s["id"], {
                "target":   new_label if not _is_fallback_label(new_label) else label,
                "tts_text": new_tts,
            })
            patched += 1

    if dry_run:
        print(f"  [DRY RUN] Would patch {len(steps)} steps — pass without --dry-run to apply.")
    else:
        print(f"  Patched {patched} steps.")


async def main(args):
    await init_db()

    manual_labels = None
    if args.labels:
        manual_labels = args.labels.split(",")

    if args.all:
        lessons = await lr.list_lessons(status="published")
        for l in lessons:
            await patch_lesson(l["id"], manual_labels, args.dry_run)
    elif args.lesson_id:
        await patch_lesson(args.lesson_id, manual_labels, args.dry_run)
    else:
        print("Specify --lesson-id <id> or --all")


def cli():
    parser = argparse.ArgumentParser(description="Patch tts_text for existing lessons")
    parser.add_argument("--lesson-id", type=int, help="Lesson ID to patch")
    parser.add_argument("--all", action="store_true", help="Patch all published lessons")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without saving")
    parser.add_argument(
        "--labels",
        help='Comma-separated labels for each step, e.g. "Home tab,Bold button,document"'
    )
    asyncio.run(main(parser.parse_args()))


if __name__ == "__main__":
    cli()
