from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str
    conversation_id: str | None = None


class FauxdexPlanRequest(BaseModel):
    task: str
    conversation_id: str | None = None


class FauxdexEngineRequest(BaseModel):
    task: str
    conversation_id: str | None = None
    mode: str = "fauxdex"


class MemoryCreateRequest(BaseModel):
    content: str
    kind: str = "manual"
    status: str = "KEEP"
    evidence: str | None = None
    confidence: float = 1.0


class FileIdsRequest(BaseModel):
    file_ids: list[int]


class TagApplyRequest(FileIdsRequest):
    tag: str


class DeletionQueueRequest(FileIdsRequest):
    reason: str | None = None


class DeletionQueuePathRequest(BaseModel):
    path: str
    reason: str | None = None


class MoveQueuedDuplicatesRequest(BaseModel):
    dry_run: bool = False
    limit: int | None = None
    remove_empty_folders: bool = True


class IndexSchedulerRequest(BaseModel):
    throttle_enabled: bool | None = None
    chat_idle_seconds: int | None = None


class WeatherSettingsRequest(BaseModel):
    provider: str | None = "open_meteo"
    location: str | None = None
    sync_enabled: bool | None = True
    latitude: float | None = None
    longitude: float | None = None


class AdminConnectStartRequest(BaseModel):
    host_label: str | None = None


class AdminConnectVerifyRequest(BaseModel):
    remote_code: str
    host_label: str | None = None


class AdminControlRequest(BaseModel):
    force: bool = False
    model: str | None = None


class HostStatsSettingsRequest(BaseModel):
    cpu_threshold_percent: int | None = None
    gpu_threshold_percent: int | None = None
    ram_threshold_percent: int | None = None
    vram_threshold_percent: int | None = None
    temperature_threshold_c: int | None = None
    poll_seconds: int | None = None
    schedule_enabled: bool | None = None
    quiet_start: str | None = None
    quiet_end: str | None = None


class AdminDevelopmentTaskCreateRequest(BaseModel):
    title: str
    description: str | None = None
    priority: str = "medium"
    status: str = "queued"


class AdminDevelopmentTaskUpdateRequest(BaseModel):
    status: str | None = None
    priority: str | None = None
    notes: str | None = None


class VideoAnalyzeRequest(BaseModel):
    path: str | None = None
    file_id: int | None = None
    preset: str | None = "standard_survey"
    interval_seconds: int = 60
    max_frames: int = 24
    update_index: bool = True
    detect_faces: bool = True
    detect_objects: bool = False


class VideoTranscribeRequest(BaseModel):
    path: str | None = None
    file_id: int | None = None
    update_index: bool = True
    prefer_subtitles: bool = True


class VideoArchiveScanRequest(BaseModel):
    preset: str | None = "quick_skim"
    update_index: bool = True
    rescan_existing: bool = False
    include_delete_queue: bool = False
    limit: int | None = None
    detect_faces: bool = True
    detect_objects: bool = False


class MediaSegmentRequest(BaseModel):
    path: str | None = None
    file_id: int | None = None
    start_seconds: float = 0
    end_seconds: float | None = None
    title: str | None = None
    summary: str | None = None
    timeline: str | None = None
    tags: list[str] = Field(default_factory=list)
    associations: list[str] = Field(default_factory=list)
    thumb_path: str | None = None


class ArchiveLocationRequest(BaseModel):
    path: str
    label: str | None = None


class ArchiveSourceSlotRequest(BaseModel):
    slot: str
    path: str


class CoWriterDocumentRequest(BaseModel):
    content: str


class CoWriterLoadRequest(BaseModel):
    path: str


class CoWriterPromptRequest(BaseModel):
    document: str
    instruction: str | None = None
    selected_text: str | None = None
    conversation_id: str | None = None
    chat_history: list[dict[str, str]] = Field(default_factory=list)


class ClipboardTextRequest(BaseModel):
    content: str
    source: str = "manual"


class NoteCreateRequest(BaseModel):
    title: str | None = None
    content: str = ""
    kind: str = "text"


class NoteUpdateRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    status: str | None = None


class PersonRequest(BaseModel):
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    notes: str | None = None
    sensitivity: str = "normal"


class PersonUpdateRequest(BaseModel):
    display_name: str | None = None
    aliases: list[str] | None = None
    notes: str | None = None
    sensitivity: str | None = None


class FaceObservationRequest(BaseModel):
    file_id: int | None = None
    path: str
    media_type: str = "image"
    frame_seconds: float | None = None
    bbox: dict | None = None
    crop_path: str | None = None
    embedding_ref: str | None = None
    detection_confidence: float | None = None
    cluster_id: str | None = None
    source: str = "manual"


class FaceDetectionRequest(BaseModel):
    path: str | None = None
    file_id: int | None = None
    force_video: bool | None = None


class VisionAnalysisRequest(BaseModel):
    path: str | None = None
    file_id: int | None = None
    update_index: bool = True


class FaceBackfillRequest(BaseModel):
    limit: int = 40
    include_video: bool = True
    force: bool = False


class PersonFaceLinkRequest(BaseModel):
    person_id: int
    face_observation_id: int | None = None
    cluster_id: str | None = None
    status: str = "confirmed"
    confidence: float = 1.0
    source: str = "user"


class TimelineEventRequest(BaseModel):
    title: str
    summary: str | None = None
    start_ts: float | None = None
    end_ts: float | None = None
    date_precision: str = "unknown"
    location_text: str | None = None
    confidence: float = 0.0
    status: str = "candidate"
    uncertainty_notes: str | None = None


class TimelineEventUpdateRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    start_ts: float | None = None
    end_ts: float | None = None
    date_precision: str | None = None
    location_text: str | None = None
    confidence: float | None = None
    status: str | None = None
    uncertainty_notes: str | None = None


class TimelineEvidenceRequest(BaseModel):
    evidence_type: str
    evidence_id: int | None = None
    path: str | None = None
    quote: str | None = None
    description: str | None = None
    confidence: float = 0.0


class TimelineEventPersonRequest(BaseModel):
    person_id: int
    role: str = "unknown"
    confidence: float = 0.0
