from functools import lru_cache
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "backend-labi"
    APP_ENV: str = "development"  # development | production
    DEBUG: bool = True

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.strip().lower() == "production"

    @property
    def debug_mode(self) -> bool:
        """Effective debug flag — always off in production."""
        return self.DEBUG and not self.is_production

    @property
    def sql_echo(self) -> bool:
        """SQL statement logging — dev only, never in production."""
        return self.debug_mode

    @property
    def docs_url(self) -> str | None:
        return None if self.is_production else "/docs"

    @property
    def redoc_url(self) -> str | None:
        return None if self.is_production else "/redoc"

    # CORS — list your frontend domains here (comma-separated in .env):
    # FRONTEND_URLS=http://localhost:3000,https://app.example.com
    # Kept as a plain string because pydantic-settings JSON-decodes
    # list-typed env values before validators run; use cors_origins.
    FRONTEND_URLS: str = "http://localhost:3000"

    @property
    def cors_origins(self) -> list[str]:
        v = self.FRONTEND_URLS.strip()
        if v.startswith("["):
            import json

            return [str(o).rstrip("/") for o in json.loads(v)]
        return [o.strip().rstrip("/") for o in v.split(",") if o.strip()]

    # Auth (JWT)
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Labi MVP — local private audio storage.
    # Recordings are stored under STORAGE_DIR and served only via
    # authorized endpoints.
    STORAGE_DIR: str = "./storage"
    # 25 MB as configurable initial limit.
    MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024
    # Allowed audio MIME types.
    ALLOWED_AUDIO_MIME: str = "audio/webm,audio/mp4,audio/mpeg,audio/wav,audio/x-wav,audio/ogg"

    @property
    def allowed_audio_mime_set(self) -> set[str]:
        return {m.strip().lower() for m in self.ALLOWED_AUDIO_MIME.split(",") if m.strip()}

    # --- Labi analysis: audio measurement (ffmpeg/ffprobe) ---
    FFMPEG_BIN: str = "ffmpeg"
    FFPROBE_BIN: str = "ffprobe"
    # Hard cap around one media subprocess.
    FFMPEG_TIMEOUT_SECONDS: int = 120
    # silencedetect noise floor in dB. Only used when PAUSE_ADAPTIVE_NOISE is
    # off, or as the fallback when the peak level cannot be measured.
    PAUSE_NOISE_DB: float = -30.0
    # An absolute floor is an a-priori threshold, which CSAP §2.3 rules out, and
    # it fails in practice: the recordings differ by ~6 dB of headroom, so a
    # fixed -30 dB found 0 pauses in one session and 41 in another. The floor is
    # therefore derived per file from its measured peak level.
    PAUSE_ADAPTIVE_NOISE: bool = True
    PAUSE_NOISE_MARGIN_DB: float = 18.0
    # Clamp so a click or a silent file cannot move the floor somewhere absurd.
    PAUSE_NOISE_MIN_DB: float = -45.0
    PAUSE_NOISE_MAX_DB: float = -15.0
    # Technical detection floor only (silencedetect cannot go much lower):
    # every detected pause is stored, so the CSAP a-posteriori threshold
    # analysis stays possible on the raw rows.
    # 100 ms was cutting into the observed distribution (the shortest pause kept
    # for session 25 was 123 ms), and CSAP explicitly applies no a-priori
    # threshold, so the floor is lowered to 50 ms. Anything dropped here is
    # dropped before storage and cannot be recovered later.
    PAUSE_MIN_MS: int = 50
    # Tokens removed from the transcript before counting words (CSAP: filled
    # pauses are annotated only to be removed).
    FILLED_PAUSE_TOKENS: str = "eee,ee,eeh,ehm,em,hmm,hm,mmm,mm,eh,ah,oh,uh,uhm"

    @property
    def filled_pause_token_set(self) -> set[str]:
        return {t.strip().lower() for t in self.FILLED_PAUSE_TOKENS.split(",") if t.strip()}

    # --- Labi analysis: local LLM (LM Studio OpenAI-compatible server) ---
    AI_BASE_URL: str = "http://127.0.0.1:1234/v1"
    # LM Studio ignores the value but requires a bearer header.
    AI_API_KEY: str = "lm-studio"
    # Model id from GET {AI_BASE_URL}/models; empty disables IU suggestions.
    AI_MODEL: str = ""
    # Local models are slow; this is the httpx timeout for one completion.
    AI_TIMEOUT_SECONDS: int = 600

    # --- Labi analysis: local ASR (faster-whisper, in-process) ---
    ASR_MODEL: str = "large-v3"
    # auto | cpu | cuda. Default is cpu: ctranslate2's "auto" selects CUDA
    # whenever a driver is visible, then fails at decode time when the CUDA
    # runtime (cuBLAS/cuDNN) is not installed. Set cuda + float16 explicitly
    # on a machine with the full CUDA runtime.
    ASR_DEVICE: str = "cpu"
    ASR_COMPUTE_TYPE: str = "int8"  # int8 on CPU, float16 with cuda
    ASR_MODEL_DIR: str = "./models"
    ASR_LANGUAGE: str = "id"  # "" = auto-detect
    ASR_BEAM_SIZE: int = 5
    ASR_VAD_FILTER: bool = True
    # Word-level timestamps. Needed to join a silent pause to the word that
    # follows it (CSAP items 11-18); costs one extra alignment pass per run.
    ASR_WORD_TIMESTAMPS: bool = True
    # Run language identification alongside the forced-language transcription.
    # Forcing ASR_LANGUAGE makes Whisper skip detection, so _info.language is
    # always the forced value and carries no signal; a separate detection pass
    # is the only way to notice a transcript that came out in another language.
    ASR_DETECT_LANGUAGE: bool = True
    # Hard cap around one transcription.
    ASR_TIMEOUT_SECONDS: int = 1800

    # MySQL connection parts (matches existing .env keys)
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USERNAME: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "labi"

    # Full URL override, e.g. mysql+asyncmy://user:pass@host:3306/db
    # (a +pymysql URL is accepted too and converted as needed)
    DATABASE_URL: str | None = None

    def _auth(self) -> str:
        password = quote_plus(self.DB_PASSWORD) if self.DB_PASSWORD else ""
        if password:
            return f"{self.DB_USERNAME}:{password}@"
        return f"{self.DB_USERNAME}@" if self.DB_USERNAME else ""

    @property
    def sqlalchemy_database_url(self) -> str:
        """Sync URL (pymysql) — used by Alembic."""
        if self.DATABASE_URL:
            return self.DATABASE_URL.replace("+asyncmy://", "+pymysql://")
        return (
            f"mysql+pymysql://{self._auth()}"
            f"{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def sqlalchemy_async_url(self) -> str:
        """Async URL (asyncmy) — used by the FastAPI app."""
        if self.DATABASE_URL:
            return self.DATABASE_URL.replace("+pymysql://", "+asyncmy://")
        return (
            f"mysql+asyncmy://{self._auth()}"
            f"{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
