# Product Requirements Document (PRD)

## Labi --- MVP Penilaian Recall Berbasis Information Units (IU)

**Versi:** 0.1\
**Status:** Draft untuk diskusi teknis\
**Tanggal:** 12 Oktober 2026\
**Fokus MVP:** Perekaman jawaban, transkripsi sebagai referensi
pendamping (bila tersedia), penilaian IU manual, dan penyimpanan hasil
sesi.

------------------------------------------------------------------------

## 1. Ringkasan Produk

Labi adalah aplikasi pendamping untuk membantu mencatat performa lansia
saat mengingat dan menceritakan kembali sebuah cerita. Untuk MVP ini,
Labi **tidak mendiagnosis demensia atau gangguan memori**. Labi
menyimpan bukti sesi dan menghitung kelengkapan informasi yang
disampaikan berdasarkan daftar *Information Units* (IU) yang telah
ditetapkan untuk setiap cerita.

Alur dasar:

1.  Labi menyediakan cerita yang telah ditentukan beserta daftar IU dan
    aturan penilaiannya.
2.  Pendamping membacakan cerita kepada lansia.
3.  Lansia menceritakan kembali cerita tersebut; pendamping merekam
    jawaban melalui aplikasi.
4.  Aplikasi mengunggah dan menyimpan rekaman agar bisa diputar ulang.
5.  Pendamping memeriksa jawaban dan menandai IU yang terpenuhi
    berdasarkan rubrik.
6.  Aplikasi menghitung skor IU Recall dan menyimpan hasil sesi.
7.  Pendamping dapat melihat riwayat sesi dan memutar ulang rekaman.

### 1.1 Sasaran MVP

-   Menyimpan rekaman jawaban lansia dengan aman dan mengaitkannya
    dengan sesi yang benar.
-   Menyediakan cerita statis yang memiliki daftar IU dan kriteria
    skoring.
-   Memungkinkan pendamping menilai setiap IU secara manual.
-   Menghitung skor IU Recall secara deterministik.
-   Menyimpan hasil penilaian per sesi agar dapat ditinjau kemudian.
-   Mendukung pengelolaan cerita dan IU melalui API CRUD, dengan
    pembatasan akses yang sesuai.

### 1.2 Di luar cakupan MVP

-   Diagnosis atau klasifikasi klinis, termasuk label "normal", "MCI",
    atau "demensia".
-   Penilaian otomatis isi cerita menggunakan AI/LLM.
-   Analisis otomatis jeda, speech rate, articulation rate, atau MATTR.
-   Transkripsi otomatis, kecuali ditambahkan sebagai integrasi
    terpisah. Pada MVP, transkripsi dapat dimasukkan atau dikoreksi
    secara manual jika diperlukan.
-   Penetapan ambang klinis atau rekomendasi medis.
-   Perekaman tanpa persetujuan dan pengelolaan akses yang tidak
    terotorisasi.

------------------------------------------------------------------------

## 2. Istilah dan Aturan Domain

### 2.1 Story

Cerita standar yang disediakan Labi untuk dibacakan kepada peserta.
Setiap story memiliki versi dan daftar IU yang berlaku pada versi
tersebut.

### 2.2 Information Unit (IU)

Satu informasi spesifik yang diharapkan dapat muncul dalam jawaban
recall. Setiap IU memiliki teks deskripsi, urutan tampilan, dan rubrik
yang menjelaskan kapan jawaban dianggap memenuhi IU.

Contoh IU untuk sebuah cerita: - Menyebut hari Minggu. - Menyebut pergi
ke pasar. - Menyebut membeli dua buah apel.

### 2.3 Session

Satu pelaksanaan tugas cerita kepada seorang peserta. Satu sesi minimal
terhubung dengan peserta, story version, pendamping, dan rekaman
jawaban.

### 2.4 IU assessment

Penilaian manual atas setiap IU untuk satu sesi. Status yang
disarankan: - `met` --- informasi memenuhi kriteria. - `not_met` ---
informasi tidak disebutkan atau tidak memenuhi kriteria. - `unclear` ---
jawaban ambigu/tidak dapat dipastikan; perlu ditinjau.

Untuk kalkulasi MVP, hanya `met` yang mendapat skor 1. `not_met` dan
`unclear` mendapat skor 0 pada skor sementara, tetapi hasil dengan IU
`unclear` harus ditandai sebagai **belum final** sampai pendamping
menyelesaikan peninjauan. Pilihan yang lebih sederhana adalah tidak
mengizinkan finalisasi selama masih ada IU `unclear`.

### 2.5 IU Recall Score

Rumus utama:

`IU Recall (%) = (jumlah IU berstatus met / jumlah IU yang berlaku untuk versi cerita) × 100`

Aturan: - Satu IU hanya dihitung satu kali, meskipun informasi
diulang. - Penyebutan sinonim dapat diterima hanya jika rubrik IU
menyatakannya. - IU yang hanya terpenuhi sebagian mengikuti rubrik yang
telah ditetapkan; jangan mengubah kriteria secara ad hoc antar-sesi. -
Penyebut adalah jumlah IU aktif yang dibekukan untuk versi cerita yang
digunakan pada sesi. - Jika tidak ada IU, sesi tidak dapat dinilai. -
Skor adalah kelengkapan informasi pada tugas tersebut, bukan persentase
"kesehatan memori".

------------------------------------------------------------------------

## 3. Pengguna dan Hak Akses

### 3.1 Peran

-   **Pendamping (`caregiver`)**: melihat cerita yang tersedia, membuat
    sesi, mengunggah rekaman, menilai IU, dan melihat sesi yang berhak
    diakses.
-   **Admin (`admin`)**: membuat/mengubah/mengarsipkan cerita dan IU,
    serta dapat melakukan audit sesuai kebijakan organisasi.

### 3.2 Prinsip akses

-   Semua endpoint yang mengakses data peserta, sesi, atau rekaman harus
    memeriksa autentikasi dan otorisasi.
-   Pendamping hanya boleh mengakses peserta/sesi yang ditugaskan
    kepadanya.
-   Perubahan story atau IU tidak boleh mengubah hasil historis secara
    retroaktif. Sesi menyimpan referensi ke versi cerita dan snapshot
    daftar IU yang digunakan.
-   URL file rekaman tidak boleh menjadi URL publik permanen. Gunakan
    endpoint streaming terotorisasi atau URL bertanda tangan yang
    kedaluwarsa.
-   Catat aktor dan waktu perubahan untuk tindakan penting.

------------------------------------------------------------------------

## 4. Alur Utama

1.  Pendamping memilih peserta.
2.  Pendamping memilih story aktif dan membuat sesi (`created`).
3.  Aplikasi menampilkan instruksi serta cerita untuk dibacakan.
4.  Pendamping merekam jawaban lansia.
5.  Aplikasi mengunggah file ke API upload. Backend menyimpan file dan
    metadata, lalu menghubungkannya ke sesi.
6.  Pendamping memutar ulang rekaman bila perlu dan mengisi penilaian
    IU.
7.  Aplikasi menghitung skor sementara.
8.  Pendamping mengonfirmasi dan memfinalisasi penilaian.
9.  Backend menyimpan hasil final, timestamp, serta rincian penilaian.
10. Pendamping membuka riwayat sesi untuk melihat skor dan memutar ulang
    rekaman.

Status sesi yang disarankan: - `created` --- sesi dibuat, belum ada
rekaman. - `recording_uploaded` --- rekaman berhasil tersimpan. -
`assessment_in_progress` --- penilaian sedang dilakukan. - `completed`
--- penilaian final telah disimpan. - `cancelled` --- sesi dibatalkan.

Transisi status harus divalidasi backend; misalnya sesi tidak dapat
`completed` jika rekaman belum ada atau semua IU belum memiliki
keputusan final.

------------------------------------------------------------------------

## 5. API yang Dibutuhkan

Prefix contoh: `/api/v1`. Semua request/response JSON kecuali endpoint
upload. Nama endpoint bersifat usulan dan dapat disesuaikan dengan stack
backend.

### 5.1 Ringkasan endpoint

  ---------------------------------------------------------------------------------------------------
  Method            Endpoint                                Fungsi                  Peran
  ----------------- --------------------------------------- ----------------------- -----------------
  `POST`            `/sessions`                             Membuat sesi untuk      Pendamping
                                                            peserta dan story       
                                                            version                 

  `GET`             `/stories`                              Melihat daftar cerita   Pendamping, Admin
                                                            aktif                   

  `GET`             `/stories/{storyId}`                    Melihat detail cerita   Pendamping, Admin
                                                            dan IU                  

  `POST`            `/sessions/{sessionId}/recording`       Upload rekaman dan      Pendamping
                                                            menyimpan metadata      

  `GET`             `/sessions/{sessionId}/recording`       Mendapatkan akses       Pendamping
                                                            playback terotorisasi   berwenang

  `GET`             `/sessions/{sessionId}`                 Melihat detail sesi dan Pendamping
                                                            statusnya               berwenang

  `PUT`             `/sessions/{sessionId}/assessment`      Menyimpan/memperbarui   Pendamping
                                                            penilaian IU (draft)    berwenang

  `POST`            `/sessions/{sessionId}/complete`        Validasi dan finalisasi Pendamping
                                                            penilaian               berwenang

  `GET`             `/sessions`                             Melihat riwayat sesi    Pendamping
                                                            dengan filter           berwenang

  `GET`             `/sessions/{sessionId}/result`          Melihat skor dan        Pendamping
                                                            rincian hasil           berwenang

  `POST`            `/admin/stories`                        Membuat cerita baru     Admin

  `PUT`             `/admin/stories/{storyId}`              Memperbarui             Admin
                                                            metadata/isi cerita     
                                                            dengan membuat versi    
                                                            baru                    

  `POST`            `/admin/stories/{storyId}/ius`          Menambahkan IU ke versi Admin
                                                            cerita yang dapat       
                                                            diedit                  

  `PUT`             `/admin/stories/{storyId}/ius/{iuId}`   Mengubah IU pada versi  Admin
                                                            draft                   

  `DELETE`          `/admin/stories/{storyId}/ius/{iuId}`   Menghapus IU dari versi Admin
                                                            draft                   

  `POST`            `/admin/stories/{storyId}/publish`      Menerbitkan versi       Admin
                                                            cerita agar dapat       
                                                            dipakai sesi baru       

  `POST`            `/admin/stories/{storyId}/archive`      Mengarsipkan cerita     Admin
                                                            agar tidak dipakai      
                                                            untuk sesi baru         
  ---------------------------------------------------------------------------------------------------

`DELETE` untuk story yang sudah dipakai dalam sesi sebaiknya tidak
menghapus data secara fisik. Gunakan pengarsipan dan pertahankan versi
historis.

### 5.2 Membuat sesi

**`POST /api/v1/sessions`**

Request:

``` json
{
  "participant_id": "uuid",
  "story_id": "uuid",
  "task_type": "immediate_recall",
  "session_note": "Opsional"
}
```

Aturan: - `participant_id` harus valid dan dapat diakses pendamping. -
`story_id` harus memiliki versi aktif yang sudah dipublikasikan. -
Backend menyimpan `story_version_id` yang dipakai sesi agar isi cerita
dan IU historis tidak berubah. - `task_type` untuk MVP dapat berupa
`immediate_recall`. Jika recall tertunda ditambahkan, gunakan jenis
tugas dan interval yang eksplisit; jangan mencampur skornya.

Response `201 Created`:

``` json
{
  "id": "session-uuid",
  "participant_id": "participant-uuid",
  "story_id": "story-uuid",
  "story_version_id": "story-version-uuid",
  "task_type": "immediate_recall",
  "status": "created",
  "created_at": "2026-10-12T01:00:00Z"
}
```

### 5.3 Daftar dan detail story

**`GET /api/v1/stories?status=published`**

Response:

``` json
{
  "data": [
    {
      "id": "story-uuid",
      "title": "Perjalanan ke Pasar",
      "version": 1,
      "estimated_duration_seconds": 45,
      "iu_count": 9
    }
  ]
}
```

**`GET /api/v1/stories/{storyId}`**

Response:

``` json
{
  "id": "story-uuid",
  "title": "Perjalanan ke Pasar",
  "version": 1,
  "story_text": "Pada hari Minggu, Ibu pergi ke pasar bersama anak perempuannya...",
  "instructions": "Bacakan cerita satu kali dengan tempo wajar. Minta peserta menceritakan kembali tanpa melihat teks.",
  "ius": [
    {
      "id": "iu-uuid-1",
      "code": "IU1",
      "description": "Menyebut hari Minggu",
      "accepted_variants": ["hari Minggu", "Minggu"],
      "scoring_rule": "Diberi skor met jika hari disebut sebagai Minggu",
      "display_order": 1
    }
  ]
}
```

Catatan: endpoint story untuk pendamping hanya mengembalikan informasi
yang diperlukan untuk menjalankan tugas. Rubrik skoring tetap tersedia
untuk pendamping karena ia harus menerapkannya secara konsisten.

### 5.4 Upload rekaman --- endpoint awal/prioritas

**`POST /api/v1/sessions/{sessionId}/recording`**

Content-Type: `multipart/form-data`

Field: - `file` --- file audio, wajib. - `duration_ms` --- durasi audio
dalam milidetik, opsional jika backend dapat mengekstraknya. -
`recorded_at` --- waktu perekaman, opsional; waktu server tetap
disimpan. - `transcript_text` --- opsional untuk transkripsi manual;
dapat juga disimpan melalui endpoint terpisah pada implementasi
berikutnya.

Validasi: - Sesi harus ada dan dapat diakses pendamping. - Sesi belum
difinalisasi/dibatalkan. - Format yang diizinkan, misalnya `audio/webm`,
`audio/mp4`, `audio/mpeg`, atau `audio/wav`, disesuaikan dengan
perangkat yang didukung. - Batasi ukuran file, misalnya 25 MB sebagai
nilai awal yang dapat dikonfigurasi. - Validasi MIME type dan signature
file; jangan hanya percaya pada nama file atau header dari klien. - Buat
nama file internal acak; jangan memakai nama asli file sebagai path
penyimpanan. - Simpan file di object storage/private storage, bukan
sebagai blob dalam tabel relasional kecuali ada alasan teknis kuat. -
Terapkan rate limit, autentikasi, otorisasi, dan kebijakan retensi. -
Jika sesi sudah memiliki rekaman, tentukan kebijakan: tolak upload kedua
dengan `409 Conflict`, atau dukung versi rekaman. Rekomendasi MVP: satu
rekaman aktif per sesi, dengan penggantian yang eksplisit dan tercatat.

Response `201 Created`:

``` json
{
  "id": "recording-uuid",
  "session_id": "session-uuid",
  "storage_status": "stored",
  "duration_ms": 58000,
  "mime_type": "audio/webm",
  "file_size_bytes": 482100,
  "created_at": "2026-10-12T01:02:00Z",
  "playback_url": "/api/v1/sessions/session-uuid/recording"
}
```

`playback_url` di atas adalah endpoint aplikasi, bukan path storage
publik. Untuk playback, backend harus memeriksa otorisasi sebelum
melakukan streaming atau mengembalikan URL bertanda tangan yang berumur
pendek.

Error yang umum: - `400 Bad Request` --- form/file tidak valid. -
`401 Unauthorized` --- belum terautentikasi. - `403 Forbidden` --- tidak
berhak mengakses sesi. - `404 Not Found` --- sesi tidak ditemukan atau
disembunyikan sesuai kebijakan akses. - `409 Conflict` --- rekaman sudah
ada dan penggantian tidak diizinkan. - `413 Payload Too Large` --- file
melebihi batas. - `415 Unsupported Media Type` --- format tidak
didukung.

### 5.5 Playback rekaman

**`GET /api/v1/sessions/{sessionId}/recording`**

Respons ideal berupa streaming audio dengan header yang sesuai
(`Content-Type`, `Accept-Ranges` jika didukung). Alternatifnya, API
dapat mengembalikan URL bertanda tangan dengan waktu kedaluwarsa
singkat.

Contoh response jika menggunakan URL bertanda tangan:

``` json
{
  "playback_url": "https://storage.example/signed-url",
  "expires_at": "2026-10-12T01:10:00Z",
  "mime_type": "audio/webm"
}
```

URL di atas hanya contoh bentuk response, bukan URL operasional. Jangan
mencatat token URL bertanda tangan ke log.

### 5.6 Menyimpan draft penilaian IU

**`PUT /api/v1/sessions/{sessionId}/assessment`**

Request:

``` json
{
  "items": [
    {
      "iu_id": "iu-uuid-1",
      "status": "met",
      "evidence_note": "Menyebut 'hari Minggu'"
    },
    {
      "iu_id": "iu-uuid-2",
      "status": "not_met",
      "evidence_note": null
    },
    {
      "iu_id": "iu-uuid-3",
      "status": "unclear",
      "evidence_note": "Ucapan kurang jelas; perlu dengarkan ulang"
    }
  ]
}
```

Aturan: - Setiap `iu_id` harus termasuk dalam versi cerita yang dipakai
sesi. - Tidak boleh ada IU duplikat dalam request. - `status` hanya
boleh `met`, `not_met`, atau `unclear`. - Draft dapat disimpan berulang
kali. - Backend menghitung skor sementara berdasarkan status, bukan
menerima skor dari klien. - Jika ada `unclear`, hasil belum boleh
difinalisasi.

Response:

``` json
{
  "session_id": "session-uuid",
  "assessment_status": "in_progress",
  "met_count": 1,
  "not_met_count": 1,
  "unclear_count": 1,
  "total_iu": 9,
  "provisional_recall_percent": 11.11,
  "is_final": false,
  "updated_at": "2026-10-12T01:04:00Z"
}
```

Nilai contoh di atas hanya menunjukkan format; pada implementasi,
`total_iu` dan angka hitungan harus berasal dari data IU versi cerita
yang benar-benar dipakai sesi.

### 5.7 Finalisasi penilaian

**`POST /api/v1/sessions/{sessionId}/complete`**

Request:

``` json
{
  "confirm": true
}
```

Validasi backend: - Rekaman tersedia. - Sesi belum dibatalkan atau
diselesaikan. - Semua IU memiliki status final `met` atau `not_met`. -
Jumlah IU yang dinilai sama dengan jumlah IU yang berlaku untuk versi
cerita sesi. - Pendamping memiliki hak akses. - Skor dihitung ulang di
backend; jangan mempercayai skor yang dikirim klien.

Response:

``` json
{
  "session_id": "session-uuid",
  "status": "completed",
  "result": {
    "met_count": 8,
    "not_met_count": 1,
    "total_iu": 9,
    "iu_recall_percent": 88.89
  },
  "completed_at": "2026-10-12T01:06:00Z"
}
```

### 5.8 Riwayat sesi dan hasil

**`GET /api/v1/sessions?participant_id={id}&page=1&page_size=20`**

Response:

``` json
{
  "data": [
    {
      "id": "session-uuid",
      "participant_id": "participant-uuid",
      "story_title": "Perjalanan ke Pasar",
      "story_version": 1,
      "status": "completed",
      "iu_recall_percent": 88.89,
      "completed_at": "2026-10-12T01:06:00Z",
      "has_recording": true
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_items": 1,
    "total_pages": 1
  }
}
```

**`GET /api/v1/sessions/{sessionId}/result`**

Response sebaiknya memuat: - skor final dan jumlah IU terpenuhi/tidak
terpenuhi; - rincian status per IU; - versi cerita yang digunakan; -
identitas pendamping penilai; - waktu perekaman, penilaian, dan
finalisasi; - tautan playback terotorisasi atau flag `has_recording`; -
catatan penilaian jika ada.

------------------------------------------------------------------------

## 6. Desain Database

Rekomendasi database relasional, misalnya PostgreSQL. File audio
disimpan di object storage privat; database hanya menyimpan metadata dan
object key.

### 6.1 Relasi utama

``` text
participants
    └── sessions
          ├── recordings
          ├── session_assessments
          │      └── session_assessment_items
          └── story_versions
                 └── story_information_units

stories
    └── story_versions
           └── story_information_units
```

### 6.2 Tabel `participants`

Mewakili lansia/peserta yang menjalani sesi.

  ----------------------------------------------------------------------------
  Attribute              Type              Constraint        Keterangan
  ---------------------- ----------------- ----------------- -----------------
  `id`                   UUID              PK                ID peserta

  `display_name`         VARCHAR(120)      NOT NULL          Nama tampilan
                                                             atau kode peserta
                                                             sesuai kebijakan
                                                             privasi

  `date_of_birth`        DATE              NULL              Opsional; hanya
                                                             simpan jika
                                                             memang dibutuhkan

  `preferred_language`   VARCHAR(10)       NOT NULL, default Bahasa tugas
                                           `id`              

  `created_at`           TIMESTAMPTZ       NOT NULL          Waktu dibuat

  `updated_at`           TIMESTAMPTZ       NOT NULL          Waktu diperbarui

  `archived_at`          TIMESTAMPTZ       NULL              Pengarsipan logis
  ----------------------------------------------------------------------------

Jangan menaruh informasi medis sensitif yang tidak diperlukan pada MVP.

### 6.3 Tabel `stories`

Identitas logis sebuah cerita, tidak menyimpan isi versi secara
langsung.

  -----------------------------------------------------------------------------
  Attribute         Type              Constraint        Keterangan
  ----------------- ----------------- ----------------- -----------------------
  `id`              UUID              PK                ID story

  `slug`            VARCHAR(100)      UNIQUE, NOT NULL  Kode stabil, mis.
                                                        `perjalanan-ke-pasar`

  `status`          VARCHAR(20)       NOT NULL          `draft`, `published`,
                                                        `archived`

  `created_by`      UUID              FK users.id       Admin pembuat

  `created_at`      TIMESTAMPTZ       NOT NULL          Waktu dibuat

  `updated_at`      TIMESTAMPTZ       NOT NULL          Waktu diperbarui
  -----------------------------------------------------------------------------

### 6.4 Tabel `story_versions`

Setiap perubahan substansial pada cerita atau IU menghasilkan versi
baru. Versi yang telah dipakai sesi tidak boleh diubah.

  Attribute                      Type           Constraint                       Keterangan
  ------------------------------ -------------- -------------------------------- ---------------------------------
  `id`                           UUID           PK                               ID versi
  `story_id`                     UUID           FK stories.id, NOT NULL          Story induk
  `version_number`               INT            NOT NULL                         Nomor versi
  `title`                        VARCHAR(200)   NOT NULL                         Judul cerita
  `story_text`                   TEXT           NOT NULL                         Teks cerita yang dibacakan
  `instructions`                 TEXT           NOT NULL                         Instruksi baku untuk pendamping
  `language`                     VARCHAR(10)    NOT NULL, default `id`           Bahasa
  `estimated_duration_seconds`   INT            NULL                             Estimasi durasi
  `status`                       VARCHAR(20)    NOT NULL                         `draft`, `published`, `retired`
  `published_at`                 TIMESTAMPTZ    NULL                             Waktu publikasi
  `created_by`                   UUID           FK users.id                      Pembuat versi
  `created_at`                   TIMESTAMPTZ    NOT NULL                         Waktu dibuat
  `UNIQUE`                       ---            (`story_id`, `version_number`)   Versi unik per story

### 6.5 Tabel `story_information_units`

Daftar IU yang berlaku untuk satu versi cerita.

  --------------------------------------------------------------------------------
  Attribute             Type              Constraint             Keterangan
  --------------------- ----------------- ---------------------- -----------------
  `id`                  UUID              PK                     ID IU

  `story_version_id`    UUID              FK story_versions.id,  Versi cerita
                                          NOT NULL               

  `code`                VARCHAR(20)       NOT NULL               Kode tampilan,
                                                                 mis. `IU1`

  `description`         TEXT              NOT NULL               Informasi yang
                                                                 harus ditemukan

  `scoring_rule`        TEXT              NOT NULL               Aturan keputusan
                                                                 `met`

  `accepted_variants`   JSONB             NOT NULL, default `[]` Sinonim/frasa
                                                                 yang diterima
                                                                 sebagai panduan

  `display_order`       INT               NOT NULL               Urutan IU di UI

  `is_active`           BOOLEAN           NOT NULL, default TRUE Aktif pada versi
                                                                 draft

  `created_at`          TIMESTAMPTZ       NOT NULL               Waktu dibuat

  `UNIQUE`              ---               (`story_version_id`,   Kode IU unik
                                          `code`)                dalam versi
  --------------------------------------------------------------------------------

`accepted_variants` adalah panduan untuk manusia, bukan mesin penilai
otomatis. Jika aturan skoring berubah setelah versi dipublikasikan, buat
versi cerita baru.

### 6.6 Tabel `sessions`

Satu pelaksanaan tugas untuk seorang peserta.

  --------------------------------------------------------------------------------
  Attribute            Type              Constraint           Keterangan
  -------------------- ----------------- -------------------- --------------------
  `id`                 UUID              PK                   ID sesi

  `participant_id`     UUID              FK participants.id,  Peserta
                                         NOT NULL             

  `story_id`           UUID              FK stories.id, NOT   Story induk
                                         NULL                 

  `story_version_id`   UUID              FK                   Versi persis yang
                                         story_versions.id,   dipakai
                                         NOT NULL             

  `caregiver_id`       UUID              FK users.id, NOT     Pendamping pelaksana
                                         NULL                 

  `task_type`          VARCHAR(30)       NOT NULL             MVP:
                                                              `immediate_recall`

  `status`             VARCHAR(30)       NOT NULL             Status alur sesi

  `session_note`       TEXT              NULL                 Catatan opsional
                                                              yang relevan

  `started_at`         TIMESTAMPTZ       NULL                 Waktu mulai

  `completed_at`       TIMESTAMPTZ       NULL                 Waktu finalisasi

  `cancelled_at`       TIMESTAMPTZ       NULL                 Waktu pembatalan

  `created_at`         TIMESTAMPTZ       NOT NULL             Waktu dibuat

  `updated_at`         TIMESTAMPTZ       NOT NULL             Waktu diperbarui
  --------------------------------------------------------------------------------

Tambahkan indeks pada `(participant_id, created_at DESC)`,
`(caregiver_id, created_at DESC)`, dan `status` sesuai pola query.

### 6.7 Tabel `recordings`

Metadata file audio. Byte audio disimpan di storage privat.

  ---------------------------------------------------------------------------
  Attribute             Type              Constraint        Keterangan
  --------------------- ----------------- ----------------- -----------------
  `id`                  UUID              PK                ID rekaman

  `session_id`          UUID              FK sessions.id,   Sesi terkait
                                          NOT NULL          

  `storage_provider`    VARCHAR(30)       NOT NULL          Mis. `s3`, `gcs`,
                                                            atau
                                                            `local_private`

  `storage_key`         TEXT              UNIQUE, NOT NULL  Object key
                                                            internal, bukan
                                                            URL publik

  `original_filename`   VARCHAR(255)      NULL              Nama asli hanya
                                                            untuk metadata,
                                                            tidak untuk path

  `mime_type`           VARCHAR(100)      NOT NULL          Tipe audio
                                                            tervalidasi

  `file_size_bytes`     BIGINT            NOT NULL          Ukuran file

  `duration_ms`         BIGINT            NULL              Durasi audio

  `checksum_sha256`     CHAR(64)          NULL              Integritas file

  `recorded_at`         TIMESTAMPTZ       NULL              Waktu perekaman
                                                            dari perangkat

  `uploaded_by`         UUID              FK users.id, NOT  Pengunggah
                                          NULL              

  `created_at`          TIMESTAMPTZ       NOT NULL          Waktu tersimpan

  `deleted_at`          TIMESTAMPTZ       NULL              Penghapusan logis
                                                            sesuai kebijakan
                                                            retensi
  ---------------------------------------------------------------------------

Untuk MVP satu rekaman per sesi dapat diberlakukan dengan unique
constraint pada `session_id`. Jika kelak mendukung pengambilan ulang,
tambahkan `version_number`, `is_active`, dan riwayat penggantian.

### 6.8 Tabel `transcripts` (opsional, disarankan jika transkripsi disimpan)

Walaupun transkripsi terutama untuk referensi pendamping, menyimpannya
dapat membantu audit penilaian. Jika tidak ingin menyimpan teks, UI
dapat hanya menggunakan pemutaran audio dan catatan manual.

  Attribute         Type          Constraint                   Keterangan
  ----------------- ------------- ---------------------------- ---------------------
  `id`              UUID          PK                           ID transkrip
  `session_id`      UUID          FK sessions.id, NOT NULL     Sesi terkait
  `recording_id`    UUID          FK recordings.id, NOT NULL   Rekaman sumber
  `text`            TEXT          NOT NULL                     Teks ucapan
  `source`          VARCHAR(20)   NOT NULL                     `manual` atau `asr`
  `review_status`   VARCHAR(20)   NOT NULL                     `draft`, `reviewed`
  `created_by`      UUID          FK users.id, NOT NULL        Pembuat/pemeriksa
  `created_at`      TIMESTAMPTZ   NOT NULL                     Waktu dibuat
  `updated_at`      TIMESTAMPTZ   NOT NULL                     Waktu diperbarui

Jika menggunakan transkripsi otomatis di masa depan, simpan sumber dan
status review. Jangan menganggap teks ASR selalu benar.

### 6.9 Tabel `session_assessments`

Ringkasan penilaian untuk sesi. Draft dapat diperbarui; hasil final
sebaiknya tidak ditimpa tanpa jejak audit.

  ---------------------------------------------------------------------------
  Attribute             Type              Constraint        Keterangan
  --------------------- ----------------- ----------------- -----------------
  `id`                  UUID              PK                ID penilaian

  `session_id`          UUID              FK sessions.id,   Satu penilaian
                                          UNIQUE, NOT NULL  aktif per sesi
                                                            pada MVP

  `assessor_id`         UUID              FK users.id, NOT  Pendamping
                                          NULL              penilai

  `status`              VARCHAR(20)       NOT NULL          `draft`, `final`

  `total_iu`            INT               NOT NULL          Total IU dari
                                                            versi cerita

  `met_count`           INT               NOT NULL          Jumlah IU
                                                            terpenuhi

  `not_met_count`       INT               NOT NULL          Jumlah IU tidak
                                                            terpenuhi

  `unclear_count`       INT               NOT NULL, default IU yang belum
                                          0                 jelas

  `iu_recall_percent`   NUMERIC(5,2)      NULL              Nilai
                                                            final/preview
                                                            yang dihitung
                                                            backend

  `finalized_at`        TIMESTAMPTZ       NULL              Waktu finalisasi

  `created_at`          TIMESTAMPTZ       NOT NULL          Waktu dibuat

  `updated_at`          TIMESTAMPTZ       NOT NULL          Waktu diperbarui
  ---------------------------------------------------------------------------

Angka ringkasan dapat disimpan untuk query yang cepat, tetapi backend
harus menghitung ulang dari detail IU saat finalisasi. Jangan menerima
nilai skor final yang dihitung klien sebagai sumber kebenaran.

### 6.10 Tabel `session_assessment_items`

Menyimpan keputusan pendamping untuk setiap IU dalam sesi.

  -----------------------------------------------------------------------------------
  Attribute         Type              Constraint                    Keterangan
  ----------------- ----------------- ----------------------------- -----------------
  `id`              UUID              PK                            ID item penilaian

  `assessment_id`   UUID              FK session_assessments.id,    Penilaian induk
                                      NOT NULL                      

  `iu_id`           UUID              FK                            IU yang dinilai
                                      story_information_units.id,   
                                      NOT NULL                      

  `status`          VARCHAR(20)       NOT NULL                      `met`, `not_met`,
                                                                    `unclear`

  `evidence_note`   TEXT              NULL                          Catatan
                                                                    bukti/frasa yang
                                                                    diucapkan

  `assessed_at`     TIMESTAMPTZ       NOT NULL                      Waktu dinilai

  `UNIQUE`          ---               (`assessment_id`, `iu_id`)    Satu keputusan
                                                                    per IU per
                                                                    penilaian
  -----------------------------------------------------------------------------------

Validasi backend harus memastikan `iu_id` termasuk dalam
`story_version_id` yang direferensikan sesi.

### 6.11 Tabel `users` dan `audit_logs`

Jika autentikasi belum ditangani oleh sistem lain, dibutuhkan tabel
`users` atau integrasi identitas yang setara.

Kolom minimum `users`: - `id` UUID PK - `name` VARCHAR(120) - `email`
VARCHAR(255) UNIQUE, jika login memakai email - `role` VARCHAR(20),
misalnya `caregiver` atau `admin` - `status` VARCHAR(20) - `created_at`,
`updated_at` TIMESTAMPTZ

`audit_logs` direkomendasikan untuk merekam tindakan sensitif: - `id`
UUID PK - `actor_user_id` UUID FK users.id - `action` VARCHAR(100) -
`entity_type` VARCHAR(100) - `entity_id` UUID - `metadata` JSONB,
hindari memasukkan teks sensitif atau token - `created_at` TIMESTAMPTZ

------------------------------------------------------------------------

## 7. Contoh Data dan Perhitungan

Story memiliki 9 IU. Setelah mendengarkan jawaban, pendamping
menetapkan: - 8 IU `met` - 1 IU `not_met` - 0 IU `unclear`

Perhitungan backend:

``` text
met_count = 8
not_met_count = 1
unclear_count = 0
total_iu = 9

iu_recall_percent = (met_count / total_iu) * 100
                  = (8 / 9) * 100
                  = 88.89
```

Contoh hasil:

``` json
{
  "session_id": "session-uuid",
  "status": "completed",
  "result": {
    "met_count": 8,
    "not_met_count": 1,
    "unclear_count": 0,
    "total_iu": 9,
    "iu_recall_percent": 88.89
  }
}
```

Interpretasi yang diperbolehkan: "8 dari 9 informasi target muncul dalam
jawaban pada sesi ini."\
Interpretasi yang tidak diperbolehkan: "Memori peserta 88,89% sehat"
atau diagnosis apa pun.

------------------------------------------------------------------------

## 8. Persyaratan Fungsional

### Must-have (MVP)

-   [ ] Pendamping dapat membuat sesi dengan peserta dan versi cerita
    yang valid.
-   [ ] Cerita dan daftar IU dapat dilihat sebelum tugas.
-   [ ] Rekaman dapat diunggah dan disimpan secara privat.
-   [ ] Rekaman dapat diputar ulang oleh pengguna yang berwenang.
-   [ ] Pendamping dapat menilai semua IU secara manual.
-   [ ] Sistem mencegah finalisasi jika masih ada IU `unclear` atau
    belum dinilai.
-   [ ] Skor dihitung di backend dengan rumus IU Recall.
-   [ ] Hasil dan rincian penilaian tersimpan per sesi.
-   [ ] Riwayat sesi dapat difilter berdasarkan peserta dan tanggal.
-   [ ] Versi cerita historis tetap dapat ditelusuri.
-   [ ] Otorisasi dan validasi file diberlakukan pada API.

### Should-have

-   [ ] Transkripsi teks dapat disimpan dan diperiksa pendamping.
-   [ ] Pendamping dapat mencatat bukti frasa untuk IU tertentu.
-   [ ] Indikator status upload dan retry jika koneksi gagal.
-   [ ] Audit log untuk perubahan cerita, IU, dan finalisasi.
-   [ ] Penggantian rekaman melalui tindakan eksplisit dan tercatat.

### Not in MVP

-   [ ] AI menilai IU secara otomatis.
-   [ ] Analisis jeda atau kecepatan bicara.
-   [ ] Penetapan ambang klinis atau klasifikasi risiko otomatis.
-   [ ] Perbandingan dengan norma populasi atau klaim
    sensitivitas/spesifisitas.

------------------------------------------------------------------------

## 9. Persyaratan Nonfungsional

### Keamanan dan privasi

-   Semua trafik menggunakan HTTPS.
-   Audio dan transkrip merupakan data sensitif; akses harus berbasis
    peran dan hubungan pendamping-peserta.
-   Storage rekaman tidak boleh publik.
-   Terapkan enkripsi saat transit dan saat tersimpan jika didukung
    infrastruktur.
-   Tentukan persetujuan peserta/wali, tujuan penggunaan, retensi, serta
    prosedur penghapusan sebelum pilot.
-   Jangan menaruh audio, transkrip lengkap, atau signed URL di log
    aplikasi.
-   Batasi ukuran file dan validasi format konten.
-   Gunakan UUID atau ID acak, bukan data pribadi dalam object key.

### Keandalan

-   Upload yang gagal tidak boleh menghasilkan rekaman "tersimpan"
    palsu.
-   Gunakan checksum opsional untuk pemeriksaan integritas.
-   Hindari sesi ganda akibat retry; dukung idempotency key untuk
    operasi pembuatan sesi/upload jika diperlukan.
-   Gunakan transaksi database saat menyimpan penilaian dan
    memfinalisasi sesi.

### Konsistensi data

-   Skor final dihitung ulang oleh backend.
-   Penilaian final dan versi cerita yang digunakan harus dapat diaudit.
-   Versi cerita yang telah dipakai tidak boleh diedit in-place.
-   Perubahan skor final harus melalui alur koreksi dengan jejak audit,
    bukan overwrite diam-diam.

### Usability

-   Daftar IU harus mudah dibaca dan dicentang oleh pendamping.
-   Tersedia pemutaran ulang audio dari layar penilaian.
-   Tampilkan jumlah IU terpenuhi dan total IU secara jelas.
-   Hindari label diagnosis; gunakan bahasa deskriptif seperti "8 dari 9
    IU terpenuhi".

------------------------------------------------------------------------

## 10. Aturan Validasi dan Error

-   `400 Bad Request`: payload tidak valid atau field wajib hilang.
-   `401 Unauthorized`: autentikasi tidak tersedia/tidak valid.
-   `403 Forbidden`: pengguna tidak memiliki akses.
-   `404 Not Found`: entitas tidak ditemukan.
-   `409 Conflict`: state tidak memungkinkan operasi, misalnya sesi
    sudah final.
-   `413 Payload Too Large`: file terlalu besar.
-   `415 Unsupported Media Type`: format file tidak didukung.
-   `422 Unprocessable Entity`: aturan domain gagal, misalnya finalisasi
    masih memiliki IU yang belum dinilai.
-   `500 Internal Server Error`: kesalahan tak terduga; jangan
    mengembalikan stack trace ke klien.

Format error yang disarankan:

``` json
{
  "error": {
    "code": "ASSESSMENT_INCOMPLETE",
    "message": "Penilaian belum lengkap.",
    "details": {
      "unassessed_iu_count": 1,
      "unclear_iu_count": 1
    }
  }
}
```

------------------------------------------------------------------------

## 11. Acceptance Criteria

1.  Pendamping yang berwenang dapat membuat sesi dengan story version
    yang sudah dipublikasikan.
2.  File audio yang valid berhasil disimpan; API mengembalikan metadata
    rekaman dan status berhasil.
3.  Pengguna yang berwenang dapat memutar ulang audio; pengguna tanpa
    hak akses ditolak.
4.  File yang melebihi batas atau berformat tidak didukung ditolak
    dengan kode error yang tepat.
5.  Pendamping dapat menyimpan draft penilaian IU dan melanjutkannya
    kemudian.
6.  Backend menolak IU yang tidak termasuk dalam versi cerita sesi.
7.  Backend menolak finalisasi jika masih ada IU yang belum dinilai atau
    berstatus `unclear`.
8.  Dengan 8 IU `met` dari total 9, backend menghasilkan `88.89`.
9.  Hasil final dapat diambil kembali melalui API hasil dan muncul dalam
    riwayat sesi.
10. Mengubah story untuk sesi baru tidak mengubah teks/IU atau hasil
    sesi lama.
11. Skor final tidak dapat diubah melalui request klien yang memalsukan
    nilai skor.
12. Semua akses terhadap audio diperiksa berdasarkan autentikasi dan
    otorisasi.

------------------------------------------------------------------------

## 12. Prioritas Implementasi

### Tahap 1 --- Fondasi data dan upload

1.  Autentikasi dan otorisasi dasar.
2.  Tabel peserta, story/version, IU, session, dan recording.
3.  `GET /stories` dan `GET /stories/{id}`.
4.  `POST /sessions`.
5.  `POST /sessions/{id}/recording`.
6.  `GET /sessions/{id}/recording` untuk playback privat.

### Tahap 2 --- Penilaian IU

1.  Tabel assessment dan assessment items.
2.  `PUT /sessions/{id}/assessment`.
3.  Kalkulasi preview IU Recall di backend.
4.  `POST /sessions/{id}/complete`.
5.  `GET /sessions/{id}/result`.

### Tahap 3 --- Riwayat dan administrasi cerita

1.  `GET /sessions` dengan pagination/filter.
2.  CRUD story dan IU untuk admin.
3.  Publikasi versi cerita dan pengarsipan.
4.  Audit log dan pengujian hak akses.

### Tahap 4 --- Uji coba MVP

1.  Uji alur end-to-end dengan data fiktif.
2.  Uji variasi jawaban dan rubrik IU.
3.  Uji konsistensi dua penilai pada sebagian rekaman.
4.  Uji kegagalan upload, retry, dan akses playback.
5.  Evaluasi apakah instruksi dan cerita dipahami konsisten oleh
    peserta.

------------------------------------------------------------------------

## 13. Keputusan yang Masih Perlu Dikonfirmasi

Sebelum implementasi, tim perlu memutuskan:

1.  **Identitas peserta:** apakah `participants` dikelola di Labi atau
    berasal dari sistem lain?
2.  **Transkripsi:** apakah MVP menyimpan transkripsi manual, atau hanya
    audio + penilaian IU?
3.  **Batas ukuran/durasi audio:** angka awal 25 MB hanya usulan
    konfigurasi.
4.  **Format audio:** format yang dihasilkan perangkat web/mobile yang
    ditargetkan.
5.  **Penggantian rekaman:** apakah satu sesi boleh punya rekaman ulang?
6.  **Recall tertunda:** apakah masuk MVP atau hanya recall segera
    terlebih dahulu? Jika ditambahkan, perlu interval dan jenis sesi
    yang eksplisit.
7.  **Penghapusan data:** berapa lama audio/transkrip disimpan dan siapa
    yang boleh menghapusnya?
8.  **Rubrik IU:** siapa yang menyusun dan menyetujui kriteria
    accepted/partial/incorrect?
9.  **Koreksi hasil final:** apakah admin dapat membuka ulang sesi
    dengan audit log?
10. **Autentikasi:** apakah menggunakan sistem login internal atau
    penyedia identitas eksternal?

------------------------------------------------------------------------

## 14. Catatan Ilmiah dan Batas Klaim

IU Recall adalah ukuran operasional untuk menghitung proporsi informasi
target yang muncul dalam jawaban pada suatu tugas recall. Nilainya
dipengaruhi oleh banyak faktor, termasuk kemampuan mendengar dan
memahami cerita, perhatian, bahasa, kelelahan, kondisi lingkungan, serta
konsistensi instruksi dan penilaian.

Karena itu: - Jangan menafsirkan IU Recall sebagai persentase kesehatan
memori. - Jangan menyimpulkan gangguan kognitif dari satu skor atau
perubahan skor saja. - Gunakan cerita, instruksi, interval, dan rubrik
yang sebanding saat membandingkan sesi. - Untuk klaim skrining klinis,
Labi membutuhkan penelitian validasi terhadap asesmen kognitif standar
dan supervisi profesional.

**Definisi keberhasilan MVP:** Labi dapat merekam dan menyimpan jawaban
dengan aman, membantu pendamping menilai IU secara konsisten, menghitung
IU Recall secara deterministik, dan menampilkan riwayat hasil yang dapat
ditelusuri.
