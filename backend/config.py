"""
backend/config.py
=================
Central configuration for NeuroGuide XR backend.

HOW TO USE THIS FILE:
─────────────────────
All settings are read from environment variables (set them in backend/.env).
Defaults are defined below so the backend works out of the box in local FYP mode.

QUICK SWITCH — FYP (local, Ollama) vs PRODUCTION (NVIDIA NIM):
  Set  USE_NIM=false  in .env  →  everything runs locally via Ollama (default)
  Set  USE_NIM=true   in .env  →  all AI calls route to NVIDIA NIM API endpoints

SYSTEM OVERVIEW (which model does what):
─────────────────────────────────────────
  LAYER               LOCAL (Ollama)           PRODUCTION (NVIDIA NIM)
  ─────────────────   ─────────────────────    ─────────────────────────────
  UI Narrator         llama3.2 / qwen3         mistral-medium-3.5-128b
    → Converts policy-predicted action into a spoken coaching sentence.
    → This is the "voice" of the tutor: "Click the Insert tab at the top."

  Screen Vision       qwen3-vl:4b (Ollama)     nemotron-3-nano-omni-30b
    → Multimodal: understands screenshots + text together.
    → Used when the LLM planner needs to reason about what is on screen.

  Step Planner        qwen3-vl:4b (Ollama)     deepseek-v4-flash
    → Given context (query, controls, screenshot), outputs the JSON step list.
    → This is the "brain" that decides what the user should do next.

  OCR / Text reader   PaddleOCR (local CPU)    nemotron-ocr-v2
    → Reads button labels, menu text, form fields from a screenshot.
    → Used by ScreenParser to supplement OmniParser element detection.

  Content Safety      (disabled, pass-through) nemotron-3.5-content-safety
    → Filters narrator text before it is sent to Android TTS.
    → Prevents inappropriate content from being spoken to the learner.

NOTE: For the FYP demo, USE_NIM=false is recommended — everything works
      offline with no API key. Set USE_NIM=true once you have the NIM key.
"""

import os


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _env_flag(name: str, default: str = "false") -> bool:
    """Read a boolean environment variable. Accepts: 1/0, true/false, yes/no, on/off."""
    value = os.getenv(name, default)
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: str = "") -> list[str]:
    """Read a comma-separated list from an environment variable."""
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# GENERAL TIMING
# ─────────────────────────────────────────────────────────────────────────────

AI_TIMEOUT_SECONDS       = float(os.getenv("AI_TIMEOUT_SECONDS",       "15"))
SNAPSHOT_TIMEOUT_SECONDS = float(os.getenv("SNAPSHOT_TIMEOUT_SECONDS", "90"))
PROMPT_TIMEOUT_SECONDS   = float(os.getenv("PROMPT_TIMEOUT_SECONDS",   "90"))
FRAME_DIFF_THRESHOLD     = float(os.getenv("FRAME_DIFF_THRESHOLD",     "15.0"))


# ─────────────────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
#  NVIDIA NIM — PRODUCTION AI INFERENCE LAYER
#  ─────────────────────────────────────────────────────────────────────────
#  USE_NIM controls whether AI calls go to NVIDIA NIM or stay local (Ollama).
#
#  To enable NIM:
#    1. Get your API key from https://build.nvidia.com
#    2. Set  USE_NIM=true        in backend/.env
#    3. Set  NIM_API_KEY=nvapi-…  in backend/.env
#
#  All NIM models use the OpenAI-compatible endpoint at NIM_BASE_URL.
#  The openai Python package is used to call them.
# ═══════════════════════════════════════════════════════════════════════════

USE_NIM      = _env_flag("USE_NIM", "false")
NIM_API_KEY  = os.getenv("NIM_API_KEY", "").strip()
NIM_BASE_URL = os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")

# ── NIM Model IDs ────────────────────────────────────────────────────────────
# These are the NVIDIA NIM model names exactly as they appear in the NIM catalog.
# Only used when USE_NIM=true.

# ROLE: OCR / text recognition on software screenshots
# Reads button labels, menu items, form field values from a screenshot image.
# Stronger than PaddleOCR on complex or low-contrast UI elements.
NIM_OCR_MODEL     = os.getenv("NIM_OCR_MODEL",     "nvidia/nemotron-ocr-v2")

# ROLE: Multimodal screen reasoning
# Understands screenshots + text + speech together.
# Used when the planner needs to reason about what is visible on screen.
NIM_VISION_MODEL  = os.getenv("NIM_VISION_MODEL",  "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning")

# ROLE: Step planner / workflow brain
# Given the query, app context, and UI element list → outputs the JSON step plan.
# Alternative options you can swap in: "step-3.7-flash", "nvidia/kimi-k2.6"
NIM_PLANNER_MODEL = os.getenv("NIM_PLANNER_MODEL", "nvidia/deepseek-v4-flash")

# ROLE: Narrator
# Converts the predicted action ("click PivotTable") into a natural coaching sentence.
# ("Step 1. Click PivotTable in the Insert menu. I am highlighting it now.")
NIM_NARRATOR_MODEL = os.getenv("NIM_NARRATOR_MODEL", "nvidia/mistral-medium-3.5-128b")

# ROLE: Content safety gate
# Filters narrator text before it is sent to Android TTS.
# Prevents inappropriate or sensitive content from being spoken to the learner.
# Only called when USE_NIM=true — otherwise the safety gate is a pass-through.
NIM_SAFETY_MODEL  = os.getenv("NIM_SAFETY_MODEL",  "nvidia/nemotron-3.5-content-safety")

if USE_NIM:
    if not NIM_API_KEY:
        print("[config] WARNING: USE_NIM=true but NIM_API_KEY is not set. "
              "Falling back to local Ollama. Set NIM_API_KEY=nvapi-... in backend/.env")
        USE_NIM = False
    else:
        print(f"[config] NVIDIA NIM enabled. Planner={NIM_PLANNER_MODEL!r}  "
              f"Narrator={NIM_NARRATOR_MODEL!r}  OCR={NIM_OCR_MODEL!r}")
else:
    print("[config] USE_NIM=false — all AI running locally via Ollama.")


# ─────────────────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
#  OLLAMA — LOCAL AI INFERENCE LAYER (default / FYP mode)
#  ─────────────────────────────────────────────────────────────────────────
#  Ollama runs models locally — no internet, no API key needed.
#  Used when USE_NIM=false (the default).
#
#  Recommended local models (pull once with: ollama pull <model>):
#    ollama pull llama3.2          ← fast narrator, text-only
#    ollama pull qwen3-vl:4b       ← multimodal, understands screenshots
#
#  OLLAMA_MODE=local  → uses http://127.0.0.1:11434 (PC localhost)
#  OLLAMA_MODE=cloud  → uses https://ollama.com (Ollama Cloud, requires OLLAMA_API_KEY)
# ═══════════════════════════════════════════════════════════════════════════

OLLAMA_MODE = os.getenv("OLLAMA_MODE", "local").strip().lower()
if OLLAMA_MODE not in {"local", "cloud"}:
    print(f"[config] Invalid OLLAMA_MODE='{OLLAMA_MODE}'. Falling back to 'local'.")
    OLLAMA_MODE = "local"

if OLLAMA_MODE == "cloud":
    # Ollama Cloud exposes the native /api/chat endpoint at https://ollama.com
    # (same request shape as local Ollama, not an OpenAI /v1 path)
    _default_base_url = "https://ollama.com"
    _default_model    = "gemma3:12b-cloud"
    _default_timeout  = "300"
    _default_num_pred = "1024"
else:
    _default_base_url = "http://127.0.0.1:11434"
    _default_model    = "qwen3-vl:4b"
    _default_timeout  = "150"
    _default_num_pred = "512"

OLLAMA_BASE_URL                 = os.getenv("OLLAMA_BASE_URL",                 _default_base_url)
OLLAMA_MODEL                    = os.getenv("OLLAMA_MODEL",                    _default_model)
OLLAMA_API_KEY                  = os.getenv("OLLAMA_API_KEY",                  "").strip()
OLLAMA_NUM_PREDICT              = int(os.getenv("OLLAMA_NUM_PREDICT",          _default_num_pred))
OLLAMA_TEMPERATURE              = float(os.getenv("OLLAMA_TEMPERATURE",        "0.2"))
OLLAMA_THINK                    = _env_flag("OLLAMA_THINK", "false")
OLLAMA_REQUEST_TIMEOUT_SECONDS  = float(os.getenv("OLLAMA_REQUEST_TIMEOUT_SECONDS", _default_timeout))

print(f"[config] Ollama mode={OLLAMA_MODE!r}  model={OLLAMA_MODEL!r}  url={OLLAMA_BASE_URL!r}")


# ─────────────────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
#  UI COPILOT — SOFTWARE TRAINING MODE CONFIG
#  ─────────────────────────────────────────────────────────────────────────
#  These settings control the /copilot and /lesson WebSocket endpoints.
#  The UI Copilot captures the PC screen, sends it to the LLM, and returns
#  step-by-step AR overlays to guide the learner.
#
#  COPILOT_LLM_PROVIDER options:
#    "ollama"   → use local Ollama (recommended for FYP)
#    "openai"   → use OpenAI API (GPT-4o etc.)
#    "ui_tars"  → use HuggingFace UI-TARS model endpoint
#    "nim"      → use NVIDIA NIM (auto-selected when USE_NIM=true)
#
#  CONFIDENCE GATE:
#    COPILOT_MIN_CONFIDENCE controls when AR overlays are shown.
#    If the step policy confidence < this value, the overlay is suppressed
#    and the user is shown a "low confidence — please try again" message.
#    Default: 0.0 (disabled for FYP — enable in production).
# ═══════════════════════════════════════════════════════════════════════════

COPILOT_LLM_PROVIDER     = os.getenv("COPILOT_LLM_PROVIDER",  "ollama").strip().lower()
COPILOT_USE_OLLAMA       = _env_flag("COPILOT_USE_OLLAMA",    "true")

# ROLE: Step planner model (Ollama local)
# This model receives the user query, app context, and visible UI elements,
# then returns a JSON list of steps: click/type/scroll actions with target labels.
COPILOT_OLLAMA_MODEL     = os.getenv("COPILOT_OLLAMA_MODEL",  "qwen3-vl:4b")

# ROLE: Step planner model (OpenAI fallback)
COPILOT_OPENAI_MODEL     = os.getenv("COPILOT_OPENAI_MODEL",  "gpt-4o")

# ROLE: Step planner model (HuggingFace UI-TARS)
# UI-TARS is specifically designed for GUI understanding and UI action generation.
COPILOT_HF_MODEL_ID      = os.getenv("COPILOT_HF_MODEL_ID",   "ByteDance-Seed/UI-TARS-1.5")
COPILOT_HF_ENDPOINT_URL  = os.getenv("COPILOT_HF_ENDPOINT_URL", "").strip()
COPILOT_HF_API_TOKEN     = os.getenv(
    "COPILOT_HF_API_TOKEN",
    os.getenv("HF_TOKEN", os.getenv("HUGGINGFACEHUB_API_TOKEN", "")),
).strip()
COPILOT_HF_TEMPERATURE   = float(os.getenv("COPILOT_HF_TEMPERATURE",     "0.1"))
COPILOT_HF_MAX_NEW_TOKENS= int(os.getenv("COPILOT_HF_MAX_NEW_TOKENS",   "1024"))

# Screen capture resolution — must match the trainer's PC display
# Change these if your PC uses a different screen resolution.
COPILOT_SCREEN_WIDTH     = int(os.getenv("COPILOT_SCREEN_WIDTH",         "1920"))
COPILOT_SCREEN_HEIGHT    = int(os.getenv("COPILOT_SCREEN_HEIGHT",        "1080"))
COPILOT_JPEG_QUALITY     = int(os.getenv("COPILOT_JPEG_QUALITY",          "65"))

# Maximum number of steps the LLM is allowed to return per query.
# Increase if lessons have longer workflows (e.g., 12+ step SOPs).
COPILOT_MAX_STEPS        = int(os.getenv("COPILOT_MAX_STEPS",              "8"))

# Confidence gate: minimum policy confidence to show an AR overlay.
# 0.0 = always show (disabled — good for FYP).
# 0.7 = only show overlay when policy is 70%+ confident (recommended for production).
COPILOT_MIN_CONFIDENCE   = float(os.getenv("COPILOT_MIN_CONFIDENCE",      "0.0"))

# Step verification: minimum Jaccard diff score to consider a step "done".
# 0.15 means 15% of UI elements must have changed (screen changed meaningfully).
# Lower = easier to pass. Higher = stricter confirmation required.
COPILOT_VERIFY_THRESHOLD = float(os.getenv("COPILOT_VERIFY_THRESHOLD",    "0.15"))

if COPILOT_LLM_PROVIDER not in {"ollama", "openai", "ui_tars", "nim"}:
    print(f"[config] Invalid COPILOT_LLM_PROVIDER='{COPILOT_LLM_PROVIDER}'. Falling back to 'ollama'.")
    COPILOT_LLM_PROVIDER = "ollama"


# ─────────────────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
#  SCREEN PARSER — OmniParser + PaddleOCR
#  ─────────────────────────────────────────────────────────────────────────
#  OmniParser parses UI screenshots into structured elements with bounding boxes.
#  PaddleOCR reads text labels from those screenshots.
#  Both run locally on CPU — no internet, no API key needed.
#
#  OmniParser setup (one-time):
#    git clone https://github.com/microsoft/OmniParser
#    pip install -r OmniParser/requirements.txt
#    # Download weights (~200 MB) per OmniParser README:
#    # https://huggingface.co/microsoft/OmniParser-v2
#    # Place in: OmniParser/weights/
#
#  PaddleOCR setup (one-time):
#    pip install paddleocr paddlepaddle
#
#  OMNIPARSER_ENABLED: set to false if weights are not yet downloaded.
#  PADDLEOCR_ENABLED:  set to false if PaddleOCR is not installed.
# ═══════════════════════════════════════════════════════════════════════════

OMNIPARSER_ENABLED      = _env_flag("OMNIPARSER_ENABLED",    "true")
OMNIPARSER_REPO_PATH    = os.getenv("OMNIPARSER_REPO_PATH",  "OmniParser")
OMNIPARSER_WEIGHTS_PATH = os.getenv("OMNIPARSER_WEIGHTS_PATH", "OmniParser/weights")

PADDLEOCR_ENABLED       = _env_flag("PADDLEOCR_ENABLED",     "true")
PADDLEOCR_LANG          = os.getenv("PADDLEOCR_LANG",        "en")


# ─────────────────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
#  DATABASE — LESSON & PROGRESS STORAGE
#  ─────────────────────────────────────────────────────────────────────────
#  SQLite for FYP (file-based, zero setup, works on one machine).
#  Switch to PostgreSQL for production by changing DB_DRIVER and DATABASE_URL.
#
#  DB_DRIVER options:
#    "sqlite"    → uses DB_PATH (default: neuroguide.db in backend folder)
#    "postgres"  → uses DATABASE_URL (requires asyncpg: pip install asyncpg)
#
#  To switch to PostgreSQL:
#    1. pip install asyncpg
#    2. Set DB_DRIVER=postgres in .env
#    3. Set DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/neuroguide
# ═══════════════════════════════════════════════════════════════════════════

DB_DRIVER    = os.getenv("DB_DRIVER",    "sqlite").strip().lower()
DB_PATH      = os.getenv("DB_PATH",      "neuroguide.db")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


# ─────────────────────────────────────────────────────────────────────────────
# YOLO OBJECT DETECTION  (Live Assistant — DO NOT MODIFY)
# Used only by the /stream endpoint (Live Scene). Does not affect UI Copilot.
# ─────────────────────────────────────────────────────────────────────────────

YOLO_MODEL_NAME               = os.getenv("YOLO_MODEL_NAME",               "yolo26n.onnx")
YOLO_IMAGE_SIZE               = int(os.getenv("YOLO_IMAGE_SIZE",            "640"))
YOLO_CONFIDENCE_THRESHOLD     = float(os.getenv("YOLO_CONFIDENCE_THRESHOLD","0.5"))
YOLO_MAX_DETECTIONS           = int(os.getenv("YOLO_MAX_DETECTIONS",        "10"))
YOLO_EXPORT_ONNX              = _env_flag("YOLO_EXPORT_ONNX", "false")


# ─────────────────────────────────────────────────────────────────────────────
# IMU SENSOR FUSION  (Live Assistant — DO NOT MODIFY)
# ─────────────────────────────────────────────────────────────────────────────

IMU_FUSION_ALPHA              = float(os.getenv("IMU_FUSION_ALPHA",         "0.24"))
IMU_MAX_STALENESS_SECONDS     = float(os.getenv("IMU_MAX_STALENESS_SECONDS","1.5"))
IMU_HIGH_MOTION_THRESHOLD     = float(os.getenv("IMU_HIGH_MOTION_THRESHOLD","2.2"))
REASONING_USE_VLM_FALLBACK    = _env_flag("REASONING_USE_VLM_FALLBACK", "false")


# ─────────────────────────────────────────────────────────────────────────────
# GROUNDING DINO  (Live Assistant — DO NOT MODIFY)
# ─────────────────────────────────────────────────────────────────────────────

GROUNDING_DINO_ENABLED                    = _env_flag("GROUNDING_DINO_ENABLED", "false")
GROUNDING_DINO_MODEL_ID                   = os.getenv("GROUNDING_DINO_MODEL_ID", "IDEA-Research/grounding-dino-tiny")
GROUNDING_DINO_BOX_THRESHOLD              = float(os.getenv("GROUNDING_DINO_BOX_THRESHOLD",          "0.30"))
GROUNDING_DINO_TEXT_THRESHOLD             = float(os.getenv("GROUNDING_DINO_TEXT_THRESHOLD",         "0.25"))
GROUNDING_DINO_MAX_DETECTIONS             = int(os.getenv("GROUNDING_DINO_MAX_DETECTIONS",           "12"))
GROUNDING_DINO_TRIGGER_CONFIDENCE         = float(os.getenv("GROUNDING_DINO_TRIGGER_CONFIDENCE",     "0.55"))
GROUNDING_DINO_TRIGGER_DIFF_SCORE         = float(os.getenv("GROUNDING_DINO_TRIGGER_DIFF_SCORE",     "18.0"))
GROUNDING_DINO_MIN_TRIGGER_INTERVAL_SECONDS = float(os.getenv("GROUNDING_DINO_MIN_TRIGGER_INTERVAL_SECONDS", "3.0"))
GROUNDING_DINO_DEFAULT_LABELS = _env_csv(
    "GROUNDING_DINO_DEFAULT_LABELS",
    "person,bottle,door,chair,table,bench,barbell,dumbbell,kettlebell,phone,bag",
)
GROUNDING_DINO_GYM_LABELS = _env_csv(
    "GROUNDING_DINO_GYM_LABELS",
    "person,bench,barbell,dumbbell,kettlebell,weight plate,exercise machine,water bottle,towel",
)
GROUNDING_DINO_COOKING_LABELS = _env_csv(
    "GROUNDING_DINO_COOKING_LABELS",
    "person,knife,cutting board,pot,pan,bowl,plate,spoon,fork,bottle,vegetable,fruit",
)


# ─────────────────────────────────────────────────────────────────────────────
# ROBOFLOW GYM DETECTOR  (Live Assistant — DO NOT MODIFY)
# ─────────────────────────────────────────────────────────────────────────────

ROBOFLOW_API_KEY    = os.getenv("ROBOFLOW_API_KEY",  "").strip()
ROBOFLOW_PROJECT    = os.getenv("ROBOFLOW_PROJECT",  "").strip()
ROBOFLOW_VERSION    = os.getenv("ROBOFLOW_VERSION",  "1").strip()
ROBOFLOW_CONFIDENCE = int(os.getenv("ROBOFLOW_CONFIDENCE", "40"))
ROBOFLOW_OVERLAP    = int(os.getenv("ROBOFLOW_OVERLAP",    "30"))


# ─────────────────────────────────────────────────────────────────────────────
# PERSONA SYSTEM  (Live Assistant — DO NOT MODIFY)
# Valid persona IDs: "gym_trainer" | "chef" | "physiotherapist"
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_PERSONA = os.getenv("DEFAULT_PERSONA", "gym_trainer").strip().lower()
VALID_PERSONAS  = {"gym_trainer", "chef", "physiotherapist"}
if DEFAULT_PERSONA not in VALID_PERSONAS:
    print(f"[config] Invalid DEFAULT_PERSONA='{DEFAULT_PERSONA}'. Falling back to 'gym_trainer'.")
    DEFAULT_PERSONA = "gym_trainer"


# ─────────────────────────────────────────────────────────────────────────────
# WORKOUTX EXERCISE API  (Live Assistant — DO NOT MODIFY)
# ─────────────────────────────────────────────────────────────────────────────

WORKOUTX_API_URL = os.getenv("WORKOUTX_API_URL", "https://api.workoutxapp.com/v1")
WORKOUTX_API_KEY = os.getenv("WORKOUTX_API_KEY", "wx_dab047e44ed6f56d784c232136fe4c1b56f269c1ab5b7594a1e60b5a")
WORKOUTX_TIMEOUT = float(os.getenv("WORKOUTX_TIMEOUT", "8"))
