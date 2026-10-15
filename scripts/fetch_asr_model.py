import argparse
import os
import sys
from pathlib import Path

# On Windows, ensure nvidia runtime DLLs (cublas, cudnn) are discoverable by ctranslate2
if sys.platform == "win32":
    for _sub in ("cublas", "cudnn", "cuda_nvrtc"):
        _bin_dir = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia" / _sub / "bin"
        if _bin_dir.is_dir():
            try:
                os.add_dll_directory(str(_bin_dir))
            except Exception:
                pass
            os.environ["PATH"] = str(_bin_dir) + os.pathsep + os.environ.get("PATH", "")

# Add project root to sys.path so app modules can be imported
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Attempt to load project settings; fall back to sane defaults if not in full environment
try:
    from app.core.config import settings
    DEFAULT_MODEL = settings.ASR_MODEL
    DEFAULT_DIR = settings.ASR_MODEL_DIR
    DEFAULT_DEVICE = settings.ASR_DEVICE
    DEFAULT_COMPUTE_TYPE = settings.ASR_COMPUTE_TYPE
except Exception:
    DEFAULT_MODEL = "large-v3"
    DEFAULT_DIR = "./models"
    DEFAULT_DEVICE = "cpu"
    DEFAULT_COMPUTE_TYPE = "int8"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and verify Whisper ASR models for LabI (defaults to large-v3)."
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Whisper model size/name (default: {DEFAULT_MODEL}). Options: tiny, base, small, medium, large-v3, large-v3-turbo",
    )
    parser.add_argument(
        "--output-dir",
        "--model-dir",
        type=str,
        default=DEFAULT_DIR,
        help=f"Destination directory for model weights (default: {DEFAULT_DIR})",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=DEFAULT_DEVICE,
        help=f"Device to test/load model on: cpu | cuda | auto (default: {DEFAULT_DEVICE})",
    )
    parser.add_argument(
        "--compute-type",
        type=str,
        default=DEFAULT_COMPUTE_TYPE,
        help=f"Compute type: int8 | float16 | float32 | default (default: {DEFAULT_COMPUTE_TYPE})",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Only download the weights without initializing CTranslate2 into RAM/VRAM",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    root = Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(" LabI Transcriber Model Downloader")
    print("=" * 60)
    print(f" Target Model : {args.model}")
    print(f" Storage Path : {root}")
    if not args.download_only:
        print(f" Test Device  : {args.device}")
        print(f" Compute Type : {args.compute_type}")
    print("=" * 60)
    print(f"Downloading model '{args.model}' (large-v3 is ~3.1 GB, this may take a few minutes)...")

    try:
        from faster_whisper import WhisperModel, download_model
    except ImportError:
        print(
            "\n[ERROR] 'faster-whisper' package is not installed.\n"
            "Please run: uv run python scripts/fetch_asr_model.py\n"
            "or:         pip install faster-whisper\n"
        )
        sys.exit(1)

    try:
        # Download weights to disk
        download_model(args.model, output_dir=str(root))
        print("[OK] Model files downloaded successfully.")

        if args.download_only:
            print("Download-only specified; skipping in-memory model instantiation.")
        else:
            print("Verifying model loading into memory...")
            model = WhisperModel(
                args.model,
                device=args.device,
                compute_type=args.compute_type,
                download_root=str(root),
            )
            # Touching the tokenizer forces the whole model to be present on disk
            _ = model.model
            print("[OK] Model verified and ready for transcription.")

        print(f"\nModel ready in: {root}")
    except Exception as exc:
        print(f"\n[ERROR] Failed to fetch or verify model: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()

