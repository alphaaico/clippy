from __future__ import annotations
import os
from pathlib import Path
from backend.models.schemas import TranscriptSegment, Word

def transcribe(audio_path: Path, initial_prompt: str | None = None) -> tuple[list[TranscriptSegment], str]:
    from faster_whisper import WhisperModel
    model = WhisperModel(os.getenv("WHISPER_MODEL", "base"), device="auto", compute_type="int8")
    segments, info = model.transcribe(str(audio_path), word_timestamps=True, vad_filter=True, initial_prompt=initial_prompt or None)
    output = []
    for segment in segments:
        output.append(TranscriptSegment(start=segment.start, end=segment.end, text=segment.text.strip(), words=[Word(word=w.word.strip(), start=w.start, end=w.end) for w in (segment.words or [])]))
    return output, info.language
