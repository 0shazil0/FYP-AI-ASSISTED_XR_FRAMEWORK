"""
backend/services/step_policy_service.py
=========================================
Semantic retrieval layer for lesson matching inside /copilot.

ROLE IN ARCHITECTURE:
  Called at the TOP of the /copilot query handler (before the LLM):

    _find_matching_lesson(user_query, app_name)
          |
          v
    StepPolicyService.match_lesson(query, app_name)
          |
    sentence-transformers cosine similarity
    vs all published lesson titles in DB
          |
    If score >= threshold  ->  return DB steps  (skip LLM)
    Else                   ->  return None       (LLM generates)

PHASE 2 (now): RAG cosine similarity
  - Uses "all-MiniLM-L6-v2" (25 MB, CPU-only, fast ~2 ms/query)
  - Indexes lesson titles on first call, caches embeddings in memory
  - Re-indexes when new lessons are published (force_reindex=True)

PHASE 5 (later): Replace with OpenAdapt-ML SFT LoRA model
  - load_trained_model(checkpoint_path)
  - Input: (screenshot_embedding, ui_element_tokens, goal_text)
  - Output: (lesson_id, confidence)

DESIGN NOTES:
  - Lazy import of sentence-transformers so the rest of the backend
    still starts correctly even if the package is not installed.
  - Falls back gracefully (returns None) when the model is unavailable,
    so /copilot always works -- it just skips the DB lookup.
"""

from __future__ import annotations

import math
from typing import Optional

try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    _ST_OK = True
except ImportError:
    _ST_OK = False
    print(
        "[StepPolicy] WARNING: sentence-transformers not installed. "
        "Run: pip install sentence-transformers\n"
        "  /copilot will use LLM-only mode (no lesson DB matching)."
    )

# ---------------------------------------------------------------------------
# Module-level singleton (lazy-initialised)
# ---------------------------------------------------------------------------

_model: "SentenceTransformer | None" = None
_MODEL_NAME = "all-MiniLM-L6-v2"

# In-memory index: list of (lesson_id, lesson_title, embedding_vector)
_index: list[tuple[int, str, "np.ndarray"]] = []
_index_built = False


def _get_model() -> "SentenceTransformer | None":
    """Lazy-load the sentence-transformer model (singleton)."""
    global _model
    if not _ST_OK:
        return None
    if _model is None:
        print(f"[StepPolicy] Loading sentence-transformer model '{_MODEL_NAME}'...")
        _model = SentenceTransformer(_MODEL_NAME)
        print("[StepPolicy] Model loaded.")
    return _model


def _cosine(a: "np.ndarray", b: "np.ndarray") -> float:
    """Cosine similarity between two 1-D numpy arrays."""
    dot = float(np.dot(a, b))
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    return dot / norm if norm > 1e-9 else 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_index(lessons: list[dict]) -> None:
    """
    Build (or rebuild) the in-memory lesson title index.

    Args:
        lessons: List of lesson dicts from ``lesson_repository.list_lessons()``.
                 Each dict must have at least ``id`` and ``title`` keys.

    Call this once at startup after ``init_db()``, and again whenever
    new lessons are published (admin calls ``publish_lesson()``).
    """
    global _index, _index_built

    model = _get_model()
    if model is None or not lessons:
        _index = []
        _index_built = True
        return

    titles = [l.get("title", "") for l in lessons]
    embeddings = model.encode(titles, batch_size=32, show_progress_bar=False)

    _index = [
        (int(l["id"]), l.get("title", ""), emb)
        for l, emb in zip(lessons, embeddings)
    ]
    _index_built = True
    print(f"[StepPolicy] Index built: {len(_index)} lessons indexed.")


def match_lesson(
    user_query: str,
    app_name: str,
    lessons_by_id: dict[int, dict],
    threshold: float = 0.60,
) -> Optional[int]:
    """
    Find the best-matching lesson for a user query.

    Args:
        user_query:    The learner's natural-language question.
        app_name:      The currently active window app name (e.g. "Microsoft Word").
        lessons_by_id: Mapping {lesson_id: lesson_dict} for app-name filtering.
                       Only lessons whose ``app_name`` contains the active app
                       are considered.
        threshold:     Minimum cosine similarity to accept a match (0.0–1.0).
                       Default 0.60 is permissive enough for paraphrase queries.

    Returns:
        Matched lesson_id (int) if score >= threshold, else None.
    """
    if not _ST_OK or not _index:
        return None

    model = _get_model()
    if model is None:
        return None

    # Embed the query (fast -- ~2 ms on CPU)
    query_emb = model.encode([user_query], show_progress_bar=False)[0]

    best_id: Optional[int] = None
    best_score = -1.0
    app_lower = app_name.lower()

    for lesson_id, title, title_emb in _index:
        # Skip lessons from a different app
        lesson = lessons_by_id.get(lesson_id, {})
        lesson_app = lesson.get("app_name", "").lower()
        # Loose match: "word" in "microsoft word" or "winword.exe" in "word"
        if lesson_app and app_lower and not (
            lesson_app in app_lower
            or app_lower in lesson_app
            or any(tok in app_lower for tok in lesson_app.split())
        ):
            continue

        score = _cosine(query_emb, title_emb)
        if score > best_score:
            best_score = score
            best_id = lesson_id

    if best_id is not None and best_score >= threshold:
        print(
            f"[StepPolicy] Matched lesson_id={best_id} "
            f"score={best_score:.3f} >= threshold={threshold}"
        )
        return best_id

    print(
        f"[StepPolicy] No lesson match for '{user_query[:60]}' "
        f"(best_score={best_score:.3f})"
    )
    return None


def invalidate_index() -> None:
    """
    Clear the in-memory index so next call to build_index() rebuilds it.
    Call this after a lesson is published or deleted.
    """
    global _index, _index_built
    _index = []
    _index_built = False
    print("[StepPolicy] Index invalidated.")
