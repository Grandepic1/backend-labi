from __future__ import annotations

import json

import httpx

from app.core.config import settings

IU_STATUS_VALUES = ("met", "not_met", "unclear")
_MAX_FIELD_CHARS = 2000
_EVIDENCE_MAX_CHARS = 120


class AiNotConfigured(RuntimeError):
    pass


class AiRequestFailed(RuntimeError):
    pass


class AiInvalidOutput(RuntimeError):
    pass


# Module constant so the prompt can be tuned without touching call sites.
IU_SYSTEM_PROMPT = """Anda asisten penilaian recall cerita untuk lansia. Anda menerima teks cerita asli, daftar Information Unit (IU) beserta aturan penilaiannya, dan transkrip jawaban peserta.

Tugas: tentukan untuk SETIAP IU apakah informasi tersebut muncul dalam transkrip jawaban peserta.

Aturan:
- "met": jawaban memenuhi aturan penilaian IU tersebut.
- "not_met": informasi tidak disebutkan atau tidak memenuhi aturan penilaian.
- "unclear": transkrip ambigu, terpotong, atau tidak dapat dipastikan.
- Satu IU dinilai satu kali saja, meskipun informasinya diulang.
- Terima sinonim/varian hanya jika rubrik atau accepted_variants menyatakannya. Varian di luar
  daftar hanya boleh diterima bila maknanya setara persis (mis. "putrinya" untuk "anak perempuan");
  bila ragu, pilih "unclear".
- Jangan menilai informasi di luar daftar IU. Jangan memberi diagnosis atau opini medis.
- evidence_quote harus kutipan SESINGKAT mungkin yang secara spesifik mendukung IU tersebut
  (satu frasa pendukung maksimal 120 karakter, bukan potongan transkrip umum). Kutipan generik
  yang sama untuk banyak IU dianggap tidak valid.
- Untuk "not_met": evidence_quote wajib null, dan rationale menjelaskan informasi apa yang
  tidak ditemukan dalam transkrip.
- Untuk "unclear": evidence_quote boleh null, atau frasa ambigu yang dikutip persis.

Contoh penalaran yang benar:
Transkrip: "ibu ke pasar beli apel"
IU harga lima ribu -> {"code":"IU6","status":"not_met","evidence_quote":null,
"rationale":"tidak ada penyebutan harga atau angka apa pun dalam transkrip"}

Balas HANYA JSON valid tanpa penjelasan tambahan dengan bentuk:
{"items":[{"code":"IU1","status":"met","evidence_quote":"...","rationale":"..."}]}"""


def _user_message(story_text: str, ius: list[dict], transcript: str) -> str:
    return (
        f"CERITA:\n{story_text}\n\n"
        f"DAFTAR IU:\n{json.dumps(ius, ensure_ascii=False)}\n\n"
        f"TRANSKRIP:\n{transcript}"
    )


def _parse_json_object(content: str) -> dict:
    raw = content.strip()
    if raw.startswith("```"):
        # Strip a fenced block: ```json … ``` (or bare ```).
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""
        if raw.rstrip().endswith("```"):
            raw = raw.rstrip()[:-3]
    try:
        payload = json.loads(raw.strip())
    except json.JSONDecodeError as exc:
        raise AiInvalidOutput(f"bukan JSON valid: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise AiInvalidOutput("payload bukan objek JSON")
    return payload


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _quote_verified(transcript: str, quote: str | None) -> bool:
    if not quote:
        return False
    if len(quote) > _EVIDENCE_MAX_CHARS:
        return False
    return _normalize(quote) in _normalize(transcript)


def _validate(payload: dict, codes: list[str], transcript: str) -> list[dict]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise AiInvalidOutput("field 'items' tidak ada atau bukan list")
    seen: dict[str, dict] = {}
    for entry in items:
        if not isinstance(entry, dict):
            raise AiInvalidOutput("elemen 'items' bukan objek")
        code = entry.get("code")
        if not isinstance(code, str) or not code.strip():
            raise AiInvalidOutput("elemen 'items' tanpa 'code'")
        code = code.strip()
        if code in seen:
            raise AiInvalidOutput(f"code duplikat: {code}")
        status = entry.get("status")
        if status not in IU_STATUS_VALUES:
            raise AiInvalidOutput(f"status tidak valid untuk {code}")
        quote = _clean_text(entry.get("evidence_quote"))
        rationale = _clean_text(entry.get("rationale"))
        if status == "not_met":
            quote = None
        elif status == "met" and not _quote_verified(transcript, quote):
            status = "unclear"
            note = "kutipan tidak terverifikasi sebagai potongan persis transkrip"
            rationale = f"{rationale} [{note}]" if rationale else f"[{note}]"
        seen[code] = {
            "code": code,
            "status": status,
            "evidence_quote": quote,
            "rationale": rationale,
        }
    missing = [c for c in codes if c not in seen]
    if missing:
        raise AiInvalidOutput(f"IU belum dinilai: {', '.join(missing)}")
    return list(seen.values())


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:_MAX_FIELD_CHARS]


async def _complete(client: httpx.AsyncClient, messages: list[dict]) -> str:
    try:
        response = await client.post(
            f"{settings.AI_BASE_URL.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.AI_API_KEY}"},
            json={"model": settings.AI_MODEL, "temperature": 0, "messages": messages},
        )
    except httpx.HTTPError as exc:
        # Never echo the request body (it carries the transcript).
        raise AiRequestFailed(f"{type(exc).__name__}: {settings.AI_BASE_URL}/chat/completions") from exc
    if response.status_code >= 400:
        raise AiRequestFailed(f"{response.status_code} from {settings.AI_BASE_URL}/chat/completions")
    try:
        return response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AiInvalidOutput("respons LLM tidak berisi choices[0].message.content") from exc


async def suggest_iu_statuses(*, story_text: str, ius: list[dict], transcript: str) -> list[dict]:
    model = settings.AI_MODEL.strip()
    if not model:
        raise AiNotConfigured("AI_MODEL is not set")

    codes = [str(iu["code"]) for iu in ius]
    messages: list[dict] = [
        {"role": "system", "content": IU_SYSTEM_PROMPT},
        {"role": "user", "content": _user_message(story_text, ius, transcript)},
    ]

    async with httpx.AsyncClient(timeout=settings.AI_TIMEOUT_SECONDS) as client:
        content = await _complete(client, messages)
        try:
            return _validate(_parse_json_object(content), codes, transcript)
        except AiInvalidOutput as first_error:
            messages.append({"role": "assistant", "content": content})
            messages.append(
                {
                    "role": "user",
                    "content": f"Output sebelumnya tidak valid: {first_error}. Balas ulang hanya JSON valid.",
                }
            )
            retry_content = await _complete(client, messages)
            # A second failure propagates as AiInvalidOutput.
            return _validate(_parse_json_object(retry_content), codes, transcript)
