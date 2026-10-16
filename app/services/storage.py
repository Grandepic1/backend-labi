import hashlib
import secrets
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings

# Magic numbers for content sniffing (don't trust client MIME/filename alone).
_SIGNATURES: list[tuple[bytes, set[str]]] = [
    (b"ID3", {"audio/mpeg"}),
    (b"\xff\xfb", {"audio/mpeg"}),
    (b"\xff\xf3", {"audio/mpeg"}),
    (b"\xff\xf2", {"audio/mpeg"}),
    (b"RIFF", {"audio/wav", "audio/x-wav"}),  # RIFF....WAVE
    (b"OggS", {"audio/ogg"}),
    (b"\x1a\x45\xdf\xa3", {"audio/webm"}),  # EBML
    (b"\x00\x00\x00\x18ftypmp42", {"audio/mp4"}),
    (b"\x00\x00\x00 ftypmp42", {"audio/mp4"}),
    (b"\x00\x00\x00\x1cftypM4A", {"audio/mp4", "audio/m4a", "audio/x-m4a"}),
    (b"\x00\x00\x00 ftypM4A", {"audio/mp4", "audio/m4a", "audio/x-m4a"}),
    (b"fLaC", {"audio/x-flac", "audio/flac"}),
]

_EXT_BY_MIME = {
    "audio/webm": ".webm",
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/ogg": ".ogg",
}


def storage_root() -> Path:
    root = Path(settings.STORAGE_DIR) / "recordings"
    root.mkdir(parents=True, exist_ok=True)
    return root


def sniff_mime(head: bytes, declared: str) -> str | None:
    declared = (declared or "").split(";")[0].strip().lower()
    if declared not in settings.allowed_audio_mime_set:
        return None
    for magic, mimes in _SIGNATURES:
        if head.startswith(magic):
            if declared in mimes:
                return declared
            # RIFF container check needs WAVE marker
            if magic == b"RIFF" and b"WAVE" in head[:16] and declared in mimes:
                return declared
            return None
    # Unknown signature: reject text/script/executables explicitly
    stripped = head.lstrip()
    if stripped.startswith((b"#!", b"<", b"{", b"MZ", b"%PDF", b"\x7fELF")):
        return None
    return declared


async def save_upload(file: UploadFile, session_id: int) -> dict:
    declared = (file.content_type or "").split(";")[0].strip().lower()
    if declared not in settings.allowed_audio_mime_set:
        raise ValueError("UNSUPPORTED_TYPE")

    head = await file.read(32)
    # Rewind for full read
    await file.seek(0)
    if sniff_mime(head, declared) is None:
        raise ValueError("UNSUPPORTED_TYPE")

    sha = hashlib.sha256()
    size = 0
    chunks: list[bytes] = []
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > settings.MAX_UPLOAD_BYTES:
            raise ValueError("TOO_LARGE")
        sha.update(chunk)
        chunks.append(chunk)
    if size == 0:
        raise ValueError("EMPTY")

    ext = _EXT_BY_MIME.get(declared, ".bin")
    key = f"session_{session_id}/{secrets.token_hex(16)}{ext}"
    dest = storage_root() / key
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        for c in chunks:
            f.write(c)
    return {
        "storage_key": key,
        "mime_type": declared,
        "file_size_bytes": size,
        "checksum_sha256": sha.hexdigest(),
    }


def resolve_path(storage_key: str) -> Path:
    base = storage_root()
    p = (base / storage_key).resolve()
    if base.resolve() not in p.parents and p != base.resolve():
        raise ValueError("INVALID_KEY")
    return p
