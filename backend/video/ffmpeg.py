from __future__ import annotations
import json, subprocess
from pathlib import Path
from backend.video.face_detection import FaceSample
from backend.video.crop_planner import smooth

def run(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", *args], check=True, capture_output=True)

def probe(path: Path) -> dict:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate", "-of", "json", str(path)], check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    return {"duration": round(float(data["format"].get("duration", 0)), 2), "resolution": f'{video.get("width", 0)} × {video.get("height", 0)}', "frame_rate": video.get("r_frame_rate", "—"), "video_codec": video.get("codec_name", "—"), "audio_codec": audio.get("codec_name", "—")}

def extract_audio(video: Path, audio: Path) -> None:
    run("-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio))

def face_x_expression(samples: list[FaceSample], clip_start: float) -> str:
    """Create an FFmpeg per-frame crop expression from a smoothed face timeline."""
    points = smooth(samples) or [FaceSample(clip_start, .5, .5, 0, 0)]
    relative = [(max(0, item.time - clip_start), item.x) for item in points]
    def crop_at(face: str) -> str:
        # Off-centre people are placed towards the outer third. This reserves
        # the body-facing side of the frame for shoulders, hands and torso.
        target = f"if(gt({face}\\,.62)\\,.68\\,if(lt({face}\\,.38)\\,.32\\,.50))"
        return f"max(0\\,min(iw-ih*9/16\\,{face}*iw-ih*9/16*{target}))"
    expression = crop_at(f"{relative[-1][1]:.5f}")
    for index in range(len(relative) - 2, -1, -1):
        current_t, current_x = relative[index]
        next_t, next_x = relative[index + 1]
        duration = max(next_t - current_t, .01)
        face = f"({current_x:.5f}+({next_x-current_x:.5f})*(t-{current_t:.5f})/{duration:.5f})"
        expression = f"if(lt(t\\,{next_t:.5f})\\,{crop_at(face)}\\,{expression})"
    return expression

def render_vertical(source: Path, output: Path, start: float, end: float, ass_file: Path, faces: list[FaceSample], orientation: str = "vertical", auto_layout: bool = False) -> None:
    # Crop X is evaluated every frame, interpolating between face samples instead
    # of using one static centre crop. If detection misses, it gracefully centres.
    if orientation == "horizontal":
        vf = f"crop=ih*16/9:ih:(iw-ih*16/9)/2:0,scale=1920:1080,subtitles='{ass_file.as_posix()}'"
    elif auto_layout:
        # A two-person conversation cannot fit naturally inside a narrow 9:16
        # crop. Preserve the original frame on a portrait canvas instead of
        # silently choosing one guest as the default subject.
        vf = f"scale=1080:-2,pad=1080:1920:0:(oh-ih)/2:color=0x171a28,subtitles='{ass_file.as_posix()}'"
    else:
        crop_x = face_x_expression(faces, start)
        vf = f"crop=ih*9/16:ih:{crop_x}:0,scale=1080:1920,subtitles='{ass_file.as_posix()}'"
    run("-ss", str(start), "-to", str(end), "-i", str(source), "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-c:a", "aac", "-movflags", "+faststart", str(output))

def join_with_fades(parts: list[Path], durations: list[float], output: Path, fade: float = .35) -> None:
    """Join pre-rendered 9:16 clips with a short video/audio crossfade."""
    if len(parts) == 1:
        parts[0].replace(output)
        return
    args: list[str] = []
    for part in parts: args.extend(["-i", str(part)])
    video_label, audio_label, elapsed = "0:v", "0:a", durations[0]
    filters: list[str] = []
    for index in range(1, len(parts)):
        next_video, next_audio = f"{index}:v", f"{index}:a"
        out_video, out_audio = f"v{index}", f"a{index}"
        offset = max(0, elapsed - fade)
        filters.append(f"[{video_label}][{next_video}]xfade=transition=fade:duration={fade}:offset={offset}[{out_video}]")
        filters.append(f"[{audio_label}][{next_audio}]acrossfade=d={fade}[{out_audio}]")
        video_label, audio_label = out_video, out_audio
        elapsed += durations[index] - fade
    run(*args, "-filter_complex", ";".join(filters), "-map", f"[{video_label}]", "-map", f"[{audio_label}]", "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart", str(output))
