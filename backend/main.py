from __future__ import annotations
import logging, os, shutil, uuid
from statistics import median
from pathlib import Path
from fastapi import FastAPI, File, HTTPException, UploadFile, BackgroundTasks
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from backend.models.schemas import VideoProject, TranscriptSegment, Word
from backend.video.ffmpeg import probe, extract_audio, render_vertical, join_with_fades
from backend.video.face_detection import FaceSample, detect_consistent_face_anchors, sample_primary_face
from backend.transcription.whisper import transcribe
from backend.analysis.video_analysis import analyze, check_groq_accounts
from backend.captions.generator import write_ass, write_override_ass

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | clippy | %(message)s")
logger = logging.getLogger("clippy")
app = FastAPI(title="Clippy API")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])
DATA = Path(os.getenv("UPLOAD_DIR", "data/uploads")); OUT = Path(os.getenv("OUTPUT_DIR", "data/outputs")); DATA.mkdir(parents=True, exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=OUT), name="outputs")
projects: dict[str, VideoProject] = {}
groq_account_health: list[dict] = []

@app.on_event("startup")
def verify_groq_accounts() -> None:
    global groq_account_health
    groq_account_health = check_groq_accounts()
    for account in groq_account_health:
        logger.info("Groq %s configured=%s available=%s", account["account"], account["configured"], account["available"])

@app.get("/api/health")
def health() -> dict:
    return {"groq_accounts": groq_account_health}

class RenderRequest(BaseModel):
    clip_ids: list[str]
    anchor_id: str = "auto"
    orientation: str = "vertical"
    caption_overrides: dict[str, str] = {}

class TranscriptUpdate(BaseModel):
    transcript: list[TranscriptSegment]

class TranscriptionSettings(BaseModel):
    vocabulary: str = ""

class ClipSettings(BaseModel):
    duration: int = Field(default=30, ge=20, le=60)
    anchor_id: str = ""

class ProcessRequest(ClipSettings):
    vocabulary: str = ""

def prioritise_for_speaker(candidates, anchors: list[dict], anchor_id: str):
    """Rank semantic clips by the selected face's probable speaking activity."""
    if not anchor_id: return candidates
    target = next((anchor for anchor in anchors if anchor.get("id") == anchor_id), None)
    if not target: return candidates
    def activity(anchor: dict, start: float, end: float) -> tuple[float, float]:
        samples = [sample for sample in anchor.get("activity_timeline", []) if start <= sample.get("time", -1) <= end]
        if not samples: return 0.0, 0.0
        return len(samples) / max(1, round(end - start)), sum(sample.get("mouth_motion", 0) for sample in samples) / len(samples)
    for candidate in candidates:
        coverage, target_motion = activity(target, candidate.start, candidate.end)
        other_motion = max((activity(anchor, candidate.start, candidate.end)[1] for anchor in anchors if anchor is not target), default=0.0)
        confidence = coverage * 4 + max(0, target_motion - other_motion) * 45
        candidate.overall_score = min(100, round(candidate.overall_score + confidence))
        if coverage:
            candidate.reason = f"{candidate.reason} · Probable activity from selected face: {round(coverage * 100)}% of clip."
    return sorted(candidates, key=lambda item: item.overall_score, reverse=True)

def locked_frame(samples: list[FaceSample], fallback_x: float = .5) -> FaceSample:
    """Choose one persistent face cluster, then hold a single composition."""
    if not samples:
        return FaceSample(0, fallback_x, .5, 0, 0)
    clusters: list[list[FaceSample]] = []
    for sample in samples:
        group = next((group for group in clusters if abs(median(item.x for item in group) - sample.x) < .16), None)
        if group is None:
            clusters.append([sample])
        else:
            group.append(sample)
    # Persistence matters most; larger, more central faces break ties.
    selected = max(clusters, key=lambda group: (len(group), sum(item.width * item.height for item in group), -abs(median(item.x for item in group) - .5)))
    return FaceSample(0, median(item.x for item in selected), median(item.y for item in selected), median(item.width for item in selected), median(item.height for item in selected))

def activity(p: VideoProject, message: str) -> None:
    entries = list(p.media.get("activity_log", []))
    entries.append(f"{p.stage} · {message}")
    p.media["activity_log"] = entries[-30:]
    logger.info("[%s] %s", p.id, message)

def process(project_id: str, path: Path, duration: int):
    p = projects[project_id]
    try:
        p.status = "processing"; p.media["clip_duration"] = duration
        p.stage = "Extracting audio"; activity(p, "Starting audio extraction")
        audio = path.with_suffix(".wav"); extract_audio(path, audio)
        p.stage = "Transcribing"; activity(p, "Audio ready; starting Faster-Whisper")
        p.transcript, language = transcribe(audio, p.media.get("transcription_vocabulary")); p.media["language"] = language
        p.stage = "Analysing content"; activity(p, "Transcript ready; calling Groq with automatic account failover")
        p.analysis, p.clip_candidates = analyze(p.transcript, duration)
        activity(p, f"Groq analysis returned {len(p.clip_candidates)} key moments using {', '.join(p.analysis.get('groq_accounts_used', [])) or 'configured account'}")
        p.stage = "Detecting faces"; activity(p, "Starting face detection")
        p.media["face_anchors"] = detect_consistent_face_anchors(path, float(p.media.get("duration", 0)), thumbnail_dir=OUT, project_id=project_id)
        p.stage = "Ready"; p.status = "ready"; activity(p, f"Ready with {len(p.clip_candidates)} clip candidates and {len(p.media['face_anchors'])} face anchors")
    except Exception as e:
        logger.exception("[%s] Processing failed", project_id)
        p.status = "failed"; p.error = str(e); p.stage = "Failed"; activity(p, f"ERROR: {type(e).__name__}: {e}")

@app.post("/api/projects", response_model=VideoProject)
async def upload(background_tasks: BackgroundTasks, video: UploadFile = File(...)):
    if Path(video.filename or "").suffix.lower() not in {".mp4", ".mov", ".webm", ".mkv"}: raise HTTPException(415, "Supported formats: MP4, MOV, WebM, MKV")
    pid = uuid.uuid4().hex[:10]; path = DATA / f"{pid}{Path(video.filename or '').suffix.lower()}"
    with path.open("wb") as f: shutil.copyfileobj(video.file, f)
    logger.info("[%s] Uploaded %s", pid, video.filename)
    projects[pid] = VideoProject(id=pid, status="loaded", stage="Video loaded", media={**probe(path), "filename": video.filename, "source_path": str(path)})
    return projects[pid]

@app.post("/api/projects/{project_id}/process", response_model=VideoProject)
def start_process(project_id: str, settings: ProcessRequest, background_tasks: BackgroundTasks):
    p = projects.get(project_id)
    if not p: raise HTTPException(404, "Project not found")
    if p.status == "processing": raise HTTPException(409, "Project is already processing")
    p.media["transcription_vocabulary"] = settings.vocabulary.strip()
    background_tasks.add_task(process, project_id, Path(p.media["source_path"]), settings.duration)
    p.status = "processing"; p.stage = "Queued for processing"; p.media["clip_duration"] = settings.duration
    return p

@app.get("/api/projects/{project_id}", response_model=VideoProject)
def project(project_id: str):
    if project_id not in projects: raise HTTPException(404, "Project not found")
    return projects[project_id]

@app.post("/api/projects/{project_id}/reanalyze", response_model=VideoProject)
def reanalyze(project_id: str, settings: ClipSettings):
    p = projects.get(project_id)
    if not p: raise HTTPException(404, "Project not found")
    try:
        logger.info("[%s] Re-analysing for 30-second clip recommendations", project_id)
        p.status = "processing"; p.stage = f"Finding ~{settings.duration} second clips"; p.media["clip_duration"] = settings.duration
        p.analysis, p.clip_candidates = analyze(p.transcript, settings.duration)
        p.clip_candidates = prioritise_for_speaker(p.clip_candidates, p.media.get("face_anchors", []), settings.anchor_id)
        p.status = "ready"; p.stage = "Ready"
        return p
    except Exception as e:
        logger.exception("[%s] Re-analysis failed", project_id)
        p.status = "failed"; p.stage = "Failed"; p.error = str(e)
        raise HTTPException(500, str(e))

@app.put("/api/projects/{project_id}/transcript", response_model=VideoProject)
def update_transcript(project_id: str, update: TranscriptUpdate):
    p = projects.get(project_id)
    if not p: raise HTTPException(404, "Project not found")
    rebuilt: list[TranscriptSegment] = []
    for segment in update.transcript:
        tokens = segment.text.split()
        duration = max(segment.end - segment.start, .01)
        words = [Word(word=token, start=segment.start + duration * index / len(tokens), end=segment.start + duration * (index + 1) / len(tokens)) for index, token in enumerate(tokens)] if tokens else []
        rebuilt.append(TranscriptSegment(start=segment.start, end=segment.end, text=segment.text.strip(), words=words))
    p.transcript = rebuilt
    logger.info("[%s] Transcript caption edits saved", project_id)
    return p

@app.post("/api/projects/{project_id}/retranscribe", response_model=VideoProject)
def retranscribe(project_id: str, settings: TranscriptionSettings):
    p = projects.get(project_id)
    if not p: raise HTTPException(404, "Project not found")
    try:
        p.status = "processing"; p.stage = "Re-transcribing with vocabulary"; p.media["transcription_vocabulary"] = settings.vocabulary.strip()
        source = Path(p.media["source_path"]); audio = source.with_suffix(".wav")
        if not audio.exists(): extract_audio(source, audio)
        p.transcript, language = transcribe(audio, p.media["transcription_vocabulary"]); p.media["language"] = language
        p.stage = "Analysing content"; p.analysis, p.clip_candidates = analyze(p.transcript, int(p.media.get("clip_duration", 30)))
        p.status = "ready"; p.stage = "Ready"; logger.info("[%s] Re-transcribed with custom vocabulary", project_id)
        return p
    except Exception as e:
        logger.exception("[%s] Re-transcription failed", project_id); p.status = "failed"; p.stage = "Failed"; p.error = str(e); raise HTTPException(500, str(e))

@app.post("/api/projects/{project_id}/render")
def render(project_id: str, request: RenderRequest):
    p = projects.get(project_id)
    if not p: raise HTTPException(404, "Project not found")
    clips = [next((c for c in p.clip_candidates if c.id == clip_id), None) for clip_id in request.clip_ids]
    if not clips or any(clip is None for clip in clips): raise HTTPException(404, "One or more clips were not found")
    clips = [clip for clip in clips if clip is not None]
    try:
        logger.info("[%s] Rendering %d selected clips", project_id, len(clips))
        p.stage = "Generating clip"; source = Path(p.media["source_path"]); results = []; render_id = uuid.uuid4().hex[:8]
        anchors = p.media.get("face_anchors", [])
        anchor = next((item for item in anchors if item["id"] == request.anchor_id), {"id": "auto", "x": .5}) if request.anchor_id == "auto" else next((item for item in anchors if item["id"] == request.anchor_id), {"id": "center", "x": .5})
        for index, clip in enumerate(clips):
            logger.info("[%s] Face-aware crop for %s", project_id, clip.id)
            ass = OUT / f"{project_id}-{render_id}-{clip.id}.ass"; part = OUT / f"{project_id}-{render_id}-{request.orientation}-part-{index}.mp4"
            # A selected person is a framing anchor, not a moving camera target.
            # Locking the crop to the anchor prevents detector jitter/panning.
            # Re-identify the chosen face inside this clip. A video-wide face
            # position is unreliable when the source switches camera framing.
            observed = sample_primary_face(source, clip.start, clip.end, anchor_x=None if anchor["id"] == "auto" else float(anchor.get("x", .5)))
            frame = locked_frame(observed, float(anchor.get("x", .5)))
            faces = [FaceSample(clip.start, frame.x, frame.y, frame.width, frame.height)]
            override = request.caption_overrides.get(clip.id, "").strip()
            write_override_ass(override, clip.start, clip.end, ass) if override else write_ass(p.transcript, clip.start, clip.end, ass)
            render_vertical(source, part, clip.start, clip.end, ass, faces, request.orientation, auto_layout=anchor["id"] == "auto")
            results.append({"id": clip.id, "title": clip.title, "url": f"/outputs/{part.name}", "duration": round(clip.end - clip.start), "orientation": request.orientation})
        p.stage = "Complete"; logger.info("[%s] Rendered %d clip previews", project_id, len(results)); return {"clips": results, "anchor": anchor["id"]}
    except Exception as e:
        logger.exception("[%s] Render failed", project_id)
        raise HTTPException(500, str(e))
