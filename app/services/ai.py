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


def build_actionable_guidance(
    speech_metrics: dict,
    iu_results: list[dict] | None = None,
    trend_deltas: dict | None = None,
    survivor_profile: dict | None = None,
) -> dict:
    """Builds evidence-based clinical guidance and personalized home cognitive training.

    Frameworks:
    1. Semantic Feature Analysis (SFA - Boyle, 2010) for word-finding / pause reduction.
    2. Spaced Retrieval Training (SRT - Camp et al., 1996) for detail/number memory retention.
    3. Cognitive Stimulation Therapy (CST - Spector et al., 2003) for speech fluency & narrative reconstruction.
    """
    art_rate = float(speech_metrics.get("articulation_rate") or 0)
    sp_rate = float(speech_metrics.get("speech_rate") or 0)
    gap = art_rate - sp_rate
    pause_rate = float(speech_metrics.get("pause_rate_per_100_words") or 0)

    # Personalization attributes from survivor_profile (if provided)
    profile = survivor_profile or {}
    name = (profile.get("name") or "").strip()
    subject = name if name else "peserta"
    raw_topics = profile.get("preferred_topics") or []
    topics = {str(t).lower() for t in raw_topics if isinstance(t, str)}
    dur_pref = str(profile.get("preferred_session_duration") or "").strip()
    preferred_duration = int(dur_pref) if dur_pref in ("3", "5", "10") else None
    inst_pref = profile.get("instruction_preference")
    primary_lang = profile.get("primary_language")

    # Evaluate IUs
    ius = iu_results or []
    met_count = sum(1 for u in ius if u.get("suggested_status") == "met" or u.get("status") == "met")
    total_iu = len(ius)
    recall_pct = (met_count / total_iu * 100) if total_iu > 0 else None

    # Check missed detail-oriented IUs (numbers, time, specific location)
    missed_codes = {
        str(u.get("code"))
        for u in ius
        if u.get("suggested_status") in ("not_met", "unclear") or u.get("status") in ("not_met", "unclear")
    }
    missed_details = bool(missed_codes.intersection({"IU1", "IU5", "IU6", "IU8"}))

    sfa_needed = gap >= 40.0 or pause_rate >= 60.0
    srt_needed = missed_details or (recall_pct is not None and 50.0 <= recall_pct < 85.0)
    cst_needed = (art_rate > 0 and art_rate < 125.0) or (recall_pct is not None and recall_pct < 50.0)

    # Determine primary and secondary modes
    if sfa_needed and gap >= 50.0:
        primary_mode = "sfa"
        secondary_mode = "srt" if srt_needed else ("cst" if cst_needed else None)
    elif srt_needed:
        primary_mode = "srt"
        secondary_mode = "sfa" if sfa_needed else ("cst" if cst_needed else None)
    elif cst_needed:
        primary_mode = "cst"
        secondary_mode = "sfa" if sfa_needed else None
    else:
        primary_mode = "cst"
        secondary_mode = None

    # Urgency & Medical Escalation Check
    urgency_level = "routine"
    medical_alert = None
    if trend_deltas:
        delta_recall = trend_deltas.get("iu_recall_percent")
        if delta_recall is not None and delta_recall <= -20.0:
            urgency_level = "medical_consultation_advised"
            medical_alert = (
                "Peringatan Medis: Terdeteksi penurunan daya ingat recall cerita secara signifikan "
                f"({delta_recall:.1f}% dibanding baseline). Disarankan segera berkonsultasi dengan "
                "Dokter Spesialis Saraf (Neurolog) atau Terapis Wicara untuk evaluasi klinis mendalam."
            )
    if urgency_level == "routine" and recall_pct is not None and recall_pct < 40.0:
        urgency_level = "needs_monitoring"
        medical_alert = (
            "Catatan Pemantauan: Daya ingat terhadap detail cerita berada di bawah 40%. "
            "Disarankan untuk rutin melatih dan memantau progres pada sesi evaluasi berikutnya."
        )

    # Goals and Interpretation
    if primary_mode == "sfa":
        target_goal = "Mengurangi durasi hening saat mencari kata dan memperkecil kesenjangan laju bicara."
        overall_interpretation = (
            f"Artikulasi motorik {subject} baik ({art_rate:.1f} suku kata/menit saat bersuara), namun "
            f"terdapat kesenjangan laju bicara sebesar {gap:.1f} akibat jeda mencari kosakata (word retrieval). "
            "Fokus utama latihan adalah stimulasi penamaan objek di rumah."
        )
    elif primary_mode == "srt":
        target_goal = "Meningkatkan retensi detail cerita (angka, waktu, dan lokasi) hingga recall ≥ 80%."
        subj_cap = subject[:1].upper() + subject[1:]
        overall_interpretation = (
            f"{subj_cap} memahami kerangka cerita utama dengan baik, namun beberapa detail spesifik "
            "(seperti angka harga atau lokasi) masih terlewat. Fokus utama latihan adalah penguatan memori detail bertahap."
        )
    else:
        target_goal = "Meningkatkan kelancaran rangkaian kalimat naratif dan mencapai recall ≥ 70%."
        subj_cap = subject[:1].upper() + subject[1:]
        overall_interpretation = (
            f"{subj_cap} memerlukan stimulasi aktif dalam menyusun alur narasi yang runtut dan mempertahankan tempo bicara."
        )

    # Structured Exercise Library
    exercises = []
    if primary_mode == "sfa" or secondary_mode == "sfa":
        if "food" in topics:
            object_hint = "bahan makanan atau alat dapur kesukaan (misal: sendok sayur, ulekan, buah pisang, cangkir teh hangat)"
        elif "family" in topics:
            object_hint = "benda kenangan keluarga (misal: album foto keluarga, kacamata, jam dinding, tas bepergian)"
        elif "hobbies" in topics:
            object_hint = "alat atau perlengkapan hobi (misal: pot tanaman bunga, benang rajut, koran pagi, kaset lagu)"
        elif "daily_activities" in topics:
            object_hint = "benda aktivitas harian (misal: sisir rambut, sabun mandi, sandal rumah, kunci rumah)"
        else:
            object_hint = "satu benda umum di rumah (misal: sendok, buah apel, cangkir)"

        sfa_inst = (
            f"Pilih {object_hint}. Ajak {subject} menyebutkan ciri-cirinya: fungsinya apa, bentuk/warnanya apa, "
            f"dan di mana biasanya ditemukan. Beri waktu 5 detik agar {subject} memanggil nama benda secara mandiri."
        )
        if inst_pref == "short_simple":
            sfa_inst += " Sampaikan petunjuk secara singkat satu per satu."
        elif inst_pref == "companion_assistance":
            sfa_inst += f" Berikan petunjuk lembut (seperti membisikkan suku kata pertama) jika {subject} ragu."

        exercises.append({
            "training_mode": "sfa",
            "level": 1,
            "level_title": "Level 1 (Dasar) - Penamaan Objek Berbasis Ciri",
            "title": "Tebak Ciri Objek Sekitar (Semantic Feature Analysis)",
            "target_area": "Pencarian Kosakata (Word-Finding / Anomia)",
            "instructions": sfa_inst,
            "frequency": "1-2 kali sehari",
            "duration_minutes": preferred_duration or 5,
            "method_basis": "Semantic Feature Analysis (SFA - Boyle, 2010)",
        })

    if primary_mode == "srt" or secondary_mode == "srt":
        if "food" in topics:
            detail_example = f"'{subject} membeli 2 ikat bayam seharga 5 ribu di warung'"
        elif "family" in topics:
            detail_example = f"'Cucu {subject} yang bernama Budi akan berkunjung jam 4 sore nanti'"
        elif "daily_activities" in topics:
            detail_example = f"'{subject} selesai jalan pagi 3 keliling di taman depan rumah'"
        else:
            detail_example = "'Ibu beli 2 apel seharga 5 ribu di warung'"

        exercises.append({
            "training_mode": "srt",
            "level": 2,
            "level_title": "Level 2 (Menengah) - Retensi Detail Bertahap",
            "title": "Mengingat Detail Cerita Bertahap (Spaced Retrieval)",
            "target_area": "Memori Jangka Pendek & Detail Angka",
            "instructions": (
                f"Sebutkan 2-3 detail sederhana (misal: {detail_example}). "
                f"Minta {subject} mengulanginya setelah jeda waktu bertingkat: 30 detik pertama, lalu 2 menit kemudian, "
                "dan 5 menit kemudian saat santai."
            ),
            "frequency": "1 kali sehari",
            "duration_minutes": preferred_duration or 10,
            "method_basis": "Spaced Retrieval Training (SRT - Camp et al., 1996)",
        })

    if primary_mode == "cst" or secondary_mode == "cst" or not exercises:
        if "food" in topics:
            cst_inst = (
                f"Ajak {subject} menceritakan resep masakan favoritnya, makanan khas kampung halaman, atau menu sarapan hari ini secara runtut. "
                f"Berikan respon suportif dan biarkan {subject} menyelesaikan kalimat dengan temponya sendiri."
            )
        elif "family" in topics:
            cst_inst = (
                f"Ajak {subject} menceritakan momen berkesan bersama keluarga, cerita masa kecil anak/cucu, atau foto kenangan lama. "
                f"Berikan respon suportif dan biarkan {subject} menyelesaikan kalimat dengan temponya sendiri."
            )
        elif "memories" in topics:
            cst_inst = (
                f"Ajak {subject} bernostalgia tentang pengalaman masa muda, suasana tempat tinggal zaman dahulu, atau perjalanan berkesan yang pernah dialami. "
                f"Biarkan alur cerita mengalir santai tanpa tekanan."
            )
        else:
            cst_inst = (
                f"Ajak {subject} menceritakan kembali kegiatan atau menu makanan hari ini secara runtut. "
                f"Berikan respon suportif dan biarkan {subject} menyelesaikan kalimat dengan temponya sendiri."
            )

        exercises.append({
            "training_mode": "cst",
            "level": 3,
            "level_title": "Level 3 (Lanjutan) - Rekonstruksi Cerita Utuh",
            "title": "Menceritakan Pengalaman Santai (Narrative Stimulation)",
            "target_area": "Kelancaran Struktur Narasi & Artikulasi",
            "instructions": cst_inst,
            "frequency": "1 kali sehari",
            "duration_minutes": preferred_duration or 10,
            "method_basis": "Cognitive Stimulation Therapy (CST - Spector et al., 2003)",
        })

    daily_tips = [
        f"Beri jeda hening minimal 3-5 detik saat {subject} tampak berpikir; hindari langsung memotong atau menyelesaikan kalimatnya.",
        "Ajak berlatih dalam suasana santai tanpa gangguan suara televisi agar peserta dapat fokus.",
        f"Berikan apresiasi positif setiap kali {subject} berhasil mengingat atau mengoreksi kata secara mandiri.",
    ]
    if primary_lang == "jv":
        daily_tips.append(
            f"Gunakan Bahasa Jawa yang santun dan akrab saat latihan agar proses berpikir {subject} mengalir alami tanpa beban mencari padanan kata."
        )
    elif primary_lang == "su":
        daily_tips.append(
            f"Gunakan Bahasa Sunda yang santun dan akrab saat latihan agar suasana interaksi terasa hangat dan nyaman bagi {subject}."
        )

    return {
        "urgency_level": urgency_level,
        "medical_alert": medical_alert,
        "primary_mode": primary_mode,
        "secondary_mode": secondary_mode,
        "target_goal": target_goal,
        "overall_interpretation": overall_interpretation,
        "home_trainings": exercises,
        "caregiver_daily_tips": daily_tips,
    }
