import os


def _env_flag(name: str, default: str = "false") -> bool:
	value = os.getenv(name, default)
	return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: str = "") -> list[str]:
	value = os.getenv(name, default)
	return [item.strip() for item in value.split(",") if item.strip()]

AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "15"))
SNAPSHOT_TIMEOUT_SECONDS = float(os.getenv("SNAPSHOT_TIMEOUT_SECONDS", "45"))
PROMPT_TIMEOUT_SECONDS = float(os.getenv("PROMPT_TIMEOUT_SECONDS", "45"))
FRAME_DIFF_THRESHOLD = float(os.getenv("FRAME_DIFF_THRESHOLD", "15.0"))

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-vl:4b")
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "512"))
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))
OLLAMA_THINK = _env_flag("OLLAMA_THINK", "false")

YOLO_MODEL_NAME = os.getenv("YOLO_MODEL_NAME", "yolo26n.pt")
YOLO_IMAGE_SIZE = int(os.getenv("YOLO_IMAGE_SIZE", "640"))
YOLO_CONFIDENCE_THRESHOLD = float(os.getenv("YOLO_CONFIDENCE_THRESHOLD", "0.5"))
YOLO_MAX_DETECTIONS = int(os.getenv("YOLO_MAX_DETECTIONS", "10"))
YOLO_EXPORT_ONNX = _env_flag("YOLO_EXPORT_ONNX", "true")

REASONING_USE_VLM_FALLBACK = _env_flag("REASONING_USE_VLM_FALLBACK", "false")

GROUNDING_DINO_ENABLED = _env_flag("GROUNDING_DINO_ENABLED", "false")
GROUNDING_DINO_MODEL_ID = os.getenv("GROUNDING_DINO_MODEL_ID", "IDEA-Research/grounding-dino-tiny")
GROUNDING_DINO_BOX_THRESHOLD = float(os.getenv("GROUNDING_DINO_BOX_THRESHOLD", "0.30"))
GROUNDING_DINO_TEXT_THRESHOLD = float(os.getenv("GROUNDING_DINO_TEXT_THRESHOLD", "0.25"))
GROUNDING_DINO_MAX_DETECTIONS = int(os.getenv("GROUNDING_DINO_MAX_DETECTIONS", "12"))
GROUNDING_DINO_TRIGGER_CONFIDENCE = float(os.getenv("GROUNDING_DINO_TRIGGER_CONFIDENCE", "0.55"))
GROUNDING_DINO_TRIGGER_DIFF_SCORE = float(os.getenv("GROUNDING_DINO_TRIGGER_DIFF_SCORE", "18.0"))
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
