"""Deskripsi deterministik dari deret sesi seorang peserta.

Lapisan ini mengubah angka menjadi kalimat. Teksnya dibangkitkan **dari** angka,
bukan oleh model bahasa, supaya:

- tidak mungkin bertentangan dengan datanya,
- hasilnya bisa direproduksi persis (LLM kita sudah terbukti nondeterministik),
- bisa disitasi dan diaudit kalimat per kalimat.

Aturan yang dipegang lapisan ini:

1. **Tidak ada kata "membaik" atau "memburuk".** Aplikasi ini alat ukur. Perubahan
   dilaporkan sebagai perubahan, dengan arah dan besarnya; menyebutnya baik atau
   buruk adalah penilaian klinis yang tetap milik pendamping.
2. **Setiap kalimat membawa angka yang menjadi dasarnya.** Tidak ada klaim tanpa
   bukti numerik di sebelahnya.
3. **Klaim tren ditekan kalau rentang waktunya terlalu pendek.** Tiga sesi yang
   selesai dalam delapan menit bukan tren; menyebutnya tren akan menyesatkan.
4. **Ukuran yang tidak punya cukup data dilaporkan sebagai tidak tersedia**,
   bukan diisi nol.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime

# Di bawah ini, perbedaan antar sesi lebih masuk akal dijelaskan oleh variasi
# pengukuran harian daripada oleh perubahan yang berarti. Ambang ini heuristik,
# bukan potongan klinis, dan sengaja dipilih konservatif.
MIN_SPAN_DAYS_FOR_TREND = 7.0

# Label dan satuan tiap ukuran yang ikut diringkas. Rata-rata dan median jeda
# ikut disertakan karena justru keduanya yang paling berbeda perilakunya:
# rata-rata jeda stabil, mediannya jauh lebih goyah.
MEASURES: list[tuple[str, str, str]] = [
    ("iu_recall_percent", "IU recall", "%"),
    ("speech_rate", "Speech rate", "suku kata/menit"),
    ("articulation_rate", "Articulation rate", "suku kata/menit"),
    ("pause_rate_per_100_words", "Frekuensi jeda", "per 100 kata"),
    ("silent_pause_total_ms", "Total durasi jeda", "ms"),
    ("silent_pause_mean_ms", "Rata-rata durasi jeda", "ms"),
    ("silent_pause_median_ms", "Median durasi jeda", "ms"),
    ("silent_pause_count", "Jumlah jeda senyap", "jeda"),
    ("syllable_count", "Jumlah suku kata", "suku kata"),
    ("word_count", "Jumlah kata", "kata"),
]

# Ukuran yang boleh dipakai untuk membandingkan kestabilan relatif. IU recall
# dikeluarkan karena skalanya persen dan bergantung pada penilaian manusia.
STABILITY_KEYS = {k for k, _, _ in MEASURES if k != "iu_recall_percent"}


def _num(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _id(value: float, digits: int = 2) -> str:
    """Angka dengan pemisah desimal koma, sesuai penulisan Bahasa Indonesia."""
    return f"{value:.{digits}f}".replace(".", ",")


@dataclass(slots=True)
class Summary:
    key: str
    label: str
    unit: str
    n: int
    mean: float | None = None
    sd: float | None = None
    cv: float | None = None
    minimum: float | None = None
    maximum: float | None = None


def summarize(points: list[dict], key: str, label: str, unit: str) -> Summary:
    values = [v for v in (_num(p.get(key)) for p in points) if v is not None]
    if not values:
        return Summary(key=key, label=label, unit=unit, n=0)
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if len(values) > 1 else None
    # CV hanya bermakna kalau rata-ratanya tidak nol dan tidak negatif.
    cv = (sd / mean * 100) if (sd is not None and mean > 0) else None
    return Summary(
        key=key,
        label=label,
        unit=unit,
        n=len(values),
        mean=mean,
        sd=sd,
        cv=cv,
        minimum=min(values),
        maximum=max(values),
    )


def _span(points: list[dict], timestamp_key: str) -> tuple[float | None, datetime | None, datetime | None]:
    stamps = sorted(p[timestamp_key] for p in points if p.get(timestamp_key))
    if len(stamps) < 2:
        return None, (stamps[0] if stamps else None), (stamps[0] if stamps else None)
    delta = stamps[-1] - stamps[0]
    return delta.total_seconds() / 86400, stamps[0], stamps[-1]


def build_description(points: list[dict], timestamp_key: str = "completed_at") -> dict:
    """Ubah deret sesi menjadi deskripsi terstruktur.

    `points` adalah daftar dict dengan kunci `session_id`, satu cap waktu di
    bawah `timestamp_key`, dan nilai tiap ukuran (boleh None bila tidak
    tersedia untuk sesi itu).

    `timestamp_key` harus menunjuk kolom yang **basis waktunya seragam** di
    seluruh baris. Mencampur kolom UTC dengan kolom waktu-lokal akan membuat
    rentang waktunya artefak, bukan fakta.
    """
    summaries = [summarize(points, k, label, unit) for k, label, unit in MEASURES]
    by_key = {s.key: s for s in summaries}

    span_days, first_at, last_at = _span(points, timestamp_key)
    # Rentang terlalu pendek untuk menyimpulkan perubahan; satu sesi jelas tidak
    # cukup. Dalam kedua kasus, klaim tren dimatikan sepenuhnya.
    trend_allowed = span_days is not None and span_days >= MIN_SPAN_DAYS_FOR_TREND

    statements: list[str] = []

    n_sessions = len(points)
    statements.append(f"Tersedia {n_sessions} sesi dengan hasil analisis.")
    if first_at and last_at:
        if span_days is not None and span_days < 1:
            minutes = (last_at - first_at).total_seconds() / 60
            statements.append(
                f"Seluruh sesi berada dalam rentang {_id(minutes, 0)} menit pada hari yang sama, "
                "jadi deret ini menggambarkan pengulangan dalam waktu dekat, bukan perkembangan "
                "antar minggu."
            )
        elif span_days is not None:
            statements.append(f"Rentang waktu antar sesi {_id(span_days, 1)} hari.")

    recall = by_key["iu_recall_percent"]
    if recall.n:
        latest = next(
            (_num(p.get("iu_recall_percent")) for p in reversed(points) if _num(p.get("iu_recall_percent")) is not None),
            None,
        )
        if latest is not None:
            statements.append(f"IU recall terakhir {_id(latest, 2)}%.")
        if recall.n > 1 and recall.sd is not None:
            statements.append(
                f"Sepanjang {recall.n} sesi yang dinilai final, IU recall rata-rata "
                f"{_id(recall.mean)}% (rentang {_id(recall.minimum)}–{_id(recall.maximum)}%, "
                f"SD {_id(recall.sd)})."
            )
    else:
        statements.append("Belum ada sesi dengan penilaian final, jadi IU recall belum tersedia.")

    speech = by_key["speech_rate"]
    artic = by_key["articulation_rate"]
    if speech.n and artic.n:
        statements.append(
            f"Articulation rate rata-rata {_id(artic.mean)} suku kata/menit "
            f"(rentang {_id(artic.minimum)}–{_id(artic.maximum)}), "
            f"speech rate rata-rata {_id(speech.mean)} suku kata/menit "
            f"(rentang {_id(speech.minimum)}–{_id(speech.maximum)})."
        )
        # Selisih ini temuan utama CSAP, jadi diperiksa per sesi, bukan hanya
        # pada rata-ratanya. Dinyatakan relatif terhadap speech rate
        # ("articulation rate sekian persen lebih tinggi"), karena itu arah
        # pembacaan yang lazim di literatur; penyebutnya disebut eksplisit
        # supaya tidak ambigu.
        paired = [
            (s, a)
            for s, a in ((_num(p.get("speech_rate")), _num(p.get("articulation_rate"))) for p in points)
            if s is not None and a is not None and s > 0
        ]
        if paired:
            lower = sum(1 for s, a in paired if s < a)
            gap = statistics.fmean((a - s) / s * 100 for s, a in paired)
            statements.append(
                f"Speech rate lebih rendah daripada articulation rate di {lower} dari {len(paired)} sesi; "
                f"articulation rate rata-rata {_id(gap, 1)}% lebih tinggi daripada speech rate."
            )

    # Kestabilan relatif: tanpa label baik/buruk, hanya perbandingan antar ukuran.
    ranked = sorted(
        (s for s in summaries if s.key in STABILITY_KEYS and s.cv is not None),
        key=lambda s: s.cv,
    )
    if len(ranked) >= 2:
        most, least = ranked[0], ranked[-1]
        statements.append(
            f"Ukuran paling stabil: {most.label.lower()} (CV {_id(most.cv, 1)}%). "
            f"Paling bervariasi: {least.label.lower()} (CV {_id(least.cv, 1)}%)."
        )
        mean_pause = next((s for s in ranked if s.key == "silent_pause_mean_ms"), None)
        median_pause = next((s for s in ranked if s.key == "silent_pause_median_ms"), None)
        if mean_pause and median_pause and mean_pause.cv and median_pause.cv:
            if median_pause.cv > mean_pause.cv:
                statements.append(
                    f"Median durasi jeda jauh lebih goyah daripada rata-ratanya "
                    f"(CV {_id(median_pause.cv, 1)}% vs {_id(mean_pause.cv, 1)}%), yang menunjukkan "
                    "distribusi jeda berekor panjang."
                )

    if trend_allowed and recall.n > 1 and recall.mean:
        delta = (_num(points[-1].get("iu_recall_percent")) or 0) - (
            _num(points[0].get("iu_recall_percent")) or 0
        )
        direction = "naik" if delta > 0 else ("turun" if delta < 0 else "tidak berubah")
        statements.append(
            f"IU recall dari sesi pertama ke sesi terakhir {direction} "
            f"{_id(abs(delta), 2)} poin persen."
        )

    caveats = [
        "Lapisan ini melaporkan perubahan, bukan penilaian. Baik atau buruknya tetap keputusan pendamping.",
        "Nilai jeda sebaiknya dianalisis setelah transformasi ln (CSAP §2.3); distribusinya "
        "log-normal, sehingga rata-rata aritmetika dan mediannya tidak stabil antar pengulangan.",
    ]
    participants = {p.get("participant_id") for p in points if p.get("participant_id") is not None}
    if len(participants) == 1:
        caveats.append("Seluruh sesi berasal dari satu penutur, jadi deret ini bukan sampel antar-peserta.")
    models = {p.get("asr_model") for p in points if p.get("asr_model") is not None}
    if len(models) > 1:
        caveats.append(
            "Deret ini mencampur lebih dari satu model ASR (" + ", ".join(sorted(models)) + "); "
            "angka antar sesi tidak sebanding."
        )
    elif models:
        caveats.append(
            f"Angka dihitung dengan model ASR {next(iter(models))}; akan berubah bila model diganti."
        )
    caveats.append(
        "Whisper menormalkan jeda terisi, sehingga total durasi fonasi sedikit berlebih "
        "dan articulation rate sedikit kurang."
    )

    return {
        "session_count": n_sessions,
        "span_days": round(span_days, 3) if span_days is not None else None,
        "trend_claim_allowed": trend_allowed,
        "summary": [
            {
                "key": s.key,
                "label": s.label,
                "unit": s.unit,
                "n": s.n,
                "mean": s.mean,
                "sd": s.sd,
                "cv": s.cv,
                "min": s.minimum,
                "max": s.maximum,
            }
            for s in summaries
        ],
        "statements": statements,
        "caveats": caveats,
    }


# --- Lapisan bahasa sehari-hari ---------------------------------------------
#
# Dua audiens, dua bahasa. Versi di atas ditujukan untuk peneliti dan lampiran
# paper: istilah CSAP dipakai apa adanya, dan singkatan statistik boleh muncul.
# Versi di bawah ditujukan untuk pendamping dan orang yang memakai aplikasi ini
# untuk dirinya sendiri. Bagi mereka, "CV 28,2%" dan "distribusi berekor
# panjang" bukan informasi, melainkan kebisingan.
#
# Aturan lapisan ini:
# - Tanpa singkatan statistik (SD, CV), tanpa istilah teknis (median, mean,
#   distribusi, ln), tanpa nama variabel CSAP.
# - Yang dilaporkan adalah arti angkanya, bukan namanya.
# - Satuan dibulatkan ke skala yang bisa dibayangkan orang (detik, bukan milidetik).
# - Tetap tanpa kata "membaik"/"memburuk", dan tetap menempelkan batasnya.

# Nama ukuran dalam bahasa sehari-hari, bukan nama CSAP-nya.


def _id_seconds(ms: float) -> str:
    return _id(ms / 1000, 2) + " detik"


def build_plain_description(
    points: list[dict], timestamp_key: str = "completed_at", self_view: bool = False
) -> dict:
    """Versi bahasa sehari-hari dari deskripsi deret sesi.

    `self_view` membedakan dua pembaca: pendamping (`False`, memakai "beliau")
    dan orang yang membaca hasilnya sendiri (`True`, memakai "Anda").
    """
    summaries = {s.key: s for s in (summarize(points, k, l, u) for k, l, u in MEASURES)}
    span_days, first_at, last_at = _span(points, timestamp_key)
    trend_allowed = span_days is not None and span_days >= MIN_SPAN_DAYS_FOR_TREND
    subject = "Anda" if self_view else "beliau"

    lines: list[str] = []
    n = len(points)
    lines.append(f"Ada {n} rekaman yang sudah dianalisis.")

    if span_days is not None:
        if span_days < 1:
            lines.append("Semuanya terekam pada hari yang sama.")
        else:
            lines.append(f"Rekaman-rekaman ini terekam dalam rentang {_id(span_days, 0)} hari.")

    # Ingatan tentang isi cerita.
    met = [p.get("met_count") for p in points if p.get("met_count") is not None]
    total = [p.get("total_iu") for p in points if p.get("total_iu") is not None]
    recall = summaries["iu_recall_percent"]
    if met and total:
        lines.append(
            f"Dalam {len(met)} rekaman yang sudah dinilai, rata-rata "
            f"{_id(statistics.fmean(met), 0)} dari {total[0]} hal penting dalam cerita "
            "berhasil diceritakan kembali."
        )
    elif recall.n:
        lines.append(f"Ingatan isi cerita rata-rata {_id(recall.mean, 0)}%.")

    # Kecepatan bicara. Dua angka ini sering membingungkan, jadi dibedakan
    # dengan jelas dan alasannya diterangkan.
    speech, artic = summaries["speech_rate"], summaries["articulation_rate"]
    if artic.n:
        lines.append(
            f"Saat {subject} benar-benar bersuara, kecepatannya sekitar "
            f"{_id(artic.mean, 0)} suku kata per menit."
        )
    if speech.n:
        lines.append(
            f"Kalau dihitung dari awal rekaman sampai akhir — termasuk saat berhenti "
            f"dan menarik napas — kecepatannya turun menjadi sekitar "
            f"{_id(speech.mean, 0)} suku kata per menit."
        )
    if speech.n and artic.n:
        lines.append(
            "Turunnya wajar: waktu untuk berpikir dan menarik napas ikut terhitung."
        )

    pause_mean = summaries["silent_pause_mean_ms"]
    pause_count = summaries["silent_pause_count"]
    if pause_mean.n and pause_count.n:
        lines.append(
            f"Dalam tiap rekaman ada sekitar {_id(pause_count.mean, 0)} jeda, "
            f"dengan panjang rata-rata {_id_seconds(pause_mean.mean)}."
        )

    # Konsistensi, diterjemahkan ke bahasa yang bisa dibayangkan.
    words = summaries["word_count"]
    pause_median = summaries["silent_pause_median_ms"]
    if words.n > 1 and words.cv is not None:
        if words.cv < 10:
            lines.append("Panjang cerita yang diceritakan cukup konsisten antar rekaman.")
        else:
            lines.append("Panjang cerita yang diceritakan cukup berbeda-beda antar rekaman.")
    if pause_median.n > 1 and pause_median.cv is not None and pause_median.cv > 20:
        lines.append(
            "Sebaliknya, panjang tiap jeda sangat berbeda-beda dari satu rekaman ke rekaman lain. "
            "Ini hal biasa — orang berhenti sebentar untuk hal yang berbeda-beda setiap kali bercerita."
        )

    if not trend_allowed:
        lines.append(
            "Rekaman-rekaman ini jaraknya masih terlalu dekat untuk bisa mengatakan apakah ada "
            "perubahan dari waktu ke waktu. Perlu beberapa rekaman lagi dengan jeda waktu lebih panjang."
        )

    notes = [
        "Angka-angka ini dihitung otomatis oleh komputer dari rekaman suara. Ini bukan diagnosis.",
        "Kalau ada yang terasa mengkhawatirkan, sebaiknya ditanyakan ke tenaga kesehatan.",
    ]
    participants = {p.get("participant_id") for p in points if p.get("participant_id") is not None}
    if len(participants) == 1:
        notes.append(
            "Semua rekaman ini dari diri sendiri, jadi gambaran ini hanya tentang Anda."
            if self_view
            else "Semua rekaman ini dari orang yang sama, jadi gambaran ini hanya tentang beliau."
        )

    return {
        "session_count": n,
        "trend_claim_allowed": trend_allowed,
        "lines": lines,
        "notes": notes,
    }
