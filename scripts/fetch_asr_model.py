import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faster_whisper import WhisperModel  # noqa: E402

from app.core.config import settings  # noqa: E402


def main() -> None:
    root = Path(settings.ASR_MODEL_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    print(
        f"loading model={settings.ASR_MODEL} device={settings.ASR_DEVICE} "
        f"compute_type={settings.ASR_COMPUTE_TYPE} into {root}"
    )
    model = WhisperModel(
        settings.ASR_MODEL,
        device=settings.ASR_DEVICE,
        compute_type=settings.ASR_COMPUTE_TYPE,
        download_root=str(root),
    )
    # Touching the tokenizer forces the whole model to be present on disk.
    _ = model.model
    print(f"model directory: {root}")
    print("model ready")


if __name__ == "__main__":
    main()
