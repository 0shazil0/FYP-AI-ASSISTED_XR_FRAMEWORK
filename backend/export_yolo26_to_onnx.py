from __future__ import annotations

from pathlib import Path

from config import YOLO_IMAGE_SIZE, YOLO_MODEL_NAME

try:
    from ultralytics import YOLO
except Exception as exception:  # pragma: no cover - runtime dependency
    raise SystemExit(
        "ultralytics is required before exporting YOLOv26 to ONNX. "
        f"Import failed with: {exception}"
    )


def main() -> None:
    source_model_name = YOLO_MODEL_NAME
    print(f"Loading source model: {source_model_name}")
    model = YOLO(source_model_name, task="detect")

    print("Exporting to ONNX...")
    exported_path = model.export(format="onnx", imgsz=YOLO_IMAGE_SIZE)
    print(f"Export complete: {exported_path}")

    onnx_path = Path(str(exported_path))
    print(f"Loading exported model: {onnx_path}")
    onnx_model = YOLO(str(onnx_path), task="detect")

    print("Running verification inference...")
    results = onnx_model("https://ultralytics.com/images/bus.jpg")
    print(f"Verification complete. Result count: {len(results)}")


if __name__ == "__main__":
    main()
