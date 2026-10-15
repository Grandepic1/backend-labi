from __future__ import annotations

import asyncio
import json
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("app.analysis")

IU_STATUS_VALUES = ("met", "not_met", "unclear")
_MAX_FIELD_CHARS = 2000
_EVIDENCE_MAX_CHARS = 120

# Upstream overload is transient: Gemini returns 503 "high demand" spikes and
# 429 when throttled. Retrying with backoff keeps a single blip from failing an
# otherwise healthy analysis run.
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_RETRY_ATTEMPTS = 5
_RETRY_BASE_DELAY = 2.0  # seconds; doubles per attempt -> 2s, 4s, 8s, 16s


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
- evidence_quote harus SALINAN PERSIS dari transkrip: satu potongan bersambung, karakter per
  karakter, persis seperti tertulis. Ambil potongan TERPENDEK yang cukup mendukung IU
  (maksimal 120 karakter).
  DILARANG: memparafrase, mengubah urutan kata, memperbaiki ejaan atau tata bahasa, menambah
  kata, mengurangi kata, atau menggabungkan kata dari dua tempat berbeda dalam transkrip.
  Kutipan yang tidak ditemukan persis di transkrip akan DITOLAK oleh sistem, dan IU tersebut
  otomatis diturunkan menjadi "unclear" meskipun penilaian Anda benar. Karena itu salin apa
  adanya, termasuk bila kalimatnya terasa salah atau tidak baku.
  Contoh SALAH: transkrip berbunyi "jadinya berteduh, halus sampai di rumah", lalu dikutip
  "berteduh, jadinya berteduh" -> urutan kata diubah, DITOLAK.
  Contoh BENAR: kutipan "jadinya berteduh" -> ada persis di transkrip, DITERIMA.
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


def _parse_and_validate(payload: dict, codes: list[str], transcript: str) -> tuple[list[dict], list[str]]:
    """Validate structure, and report which quotes could not be verified.

    The unverifiable quotes are returned rather than downgraded here: the caller
    gets one chance to ask the model to copy the span correctly first, which is
    the actual failure mode. Measured on sessions 26-28, every single
    AI/human disagreement was a "met" whose quote had been paraphrased, not a
    wrong judgement.
    """
    items = payload.get("items")
    if not isinstance(items, list):
        raise AiInvalidOutput("field 'items' tidak ada atau bukan list")
    seen: dict[str, dict] = {}
    unverified: list[str] = []
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
            unverified.append(code)
        seen[code] = {
            "code": code,
            "status": status,
            "evidence_quote": quote,
            "rationale": rationale,
        }
    missing = [c for c in codes if c not in seen]
    if missing:
        raise AiInvalidOutput(f"IU belum dinilai: {', '.join(missing)}")
    return list(seen.values()), unverified


def _downgrade_unverified(items: list[dict], unverified: list[str]) -> list[dict]:
    """An unverifiable quote can only ever downgrade met -> unclear.

    Never the reverse: the quote is what makes the decision auditable, so a
    decision that cannot be cited is not allowed to stand as "met".
    """
    flagged = set(unverified)
    note = "kutipan tidak terverifikasi sebagai potongan persis transkrip"
    out: list[dict] = []
    for item in items:
        if item["code"] in flagged:
            rationale = item["rationale"]
            out.append(
                {
                    **item,
                    "status": "unclear",
                    "rationale": f"{rationale} [{note}]" if rationale else f"[{note}]",
                }
            )
        else:
            out.append(item)
    return out


def _quote_repair_message(unverified: list[str]) -> str:
    return (
        f"evidence_quote untuk {', '.join(unverified)} tidak ditemukan sebagai potongan persis "
        "di transkrip. Salin ulang HANYA potongan yang benar-benar ada di transkrip, karakter "
        "per karakter, tanpa mengubah urutan kata, tanpa memperbaiki ejaan, dan tanpa "
        "menggabungkan kata dari tempat berbeda. Jangan memparafrase. "
        "Balas ulang SELURUH item dalam format JSON yang sama."
    )


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:_MAX_FIELD_CHARS]


async def _complete(client: httpx.AsyncClient, messages: list[dict]) -> str:
    last_error = "AI request failed"
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
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
            last_error = f"{response.status_code} from {settings.AI_BASE_URL}/chat/completions"
            if response.status_code in _RETRY_STATUS and attempt < _RETRY_ATTEMPTS:
                await asyncio.sleep(_RETRY_BASE_DELAY * (2 ** (attempt - 1)))
                continue
            raise AiRequestFailed(last_error)
        try:
            return response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AiInvalidOutput("respons LLM tidak berisi choices[0].message.content") from exc
    raise AiRequestFailed(last_error)


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
            items, unverified = _parse_and_validate(_parse_json_object(content), codes, transcript)
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
            items, unverified = _parse_and_validate(
                _parse_json_object(retry_content), codes, transcript
            )

        # The model paraphrases instead of copying, which is the whole reason a
        # correct "met" ends up downgraded. One explicit, cheap correction is
        # worth it: it costs a single extra completion and is the difference
        # between the AI agreeing with the assessor and abstaining.
        if unverified:
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": _quote_repair_message(unverified)})
            try:
                repaired = await _complete(client, messages)
                repaired_items, _ = _parse_and_validate(
                    _parse_json_object(repaired), codes, transcript
                )
            except AiInvalidOutput as exc:
                # Keep the first answer rather than lose the run over the repair.
                logger.warning("perbaikan kutipan gagal: %s", exc)
            else:
                # Only the flagged items may change. Measured on session 26, a
                # repair round allowed to rewrite everything also flipped two
                # items whose quotes had been fine, so the repair is scoped to
                # exactly what it was asked to fix.
                repaired_by_code = {item["code"]: item for item in repaired_items}
                flagged = set(unverified)
                items = [
                    repaired_by_code.get(item["code"], item) if item["code"] in flagged else item
                    for item in items
                ]
                unverified = [
                    item["code"]
                    for item in items
                    if item["status"] == "met" and not _quote_verified(transcript, item["evidence_quote"])
                ]

    return _downgrade_unverified(items, unverified)
