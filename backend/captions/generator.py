from __future__ import annotations
from pathlib import Path
from backend.models.schemas import TranscriptSegment

def ts(seconds: float) -> str:
    h, rem = divmod(max(seconds, 0), 3600); m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}".replace(".", ",")

def write_ass(segments: list[TranscriptSegment], start: float, end: float, output: Path) -> None:
    header = """[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Clippy,Arial,72,&H00FFFFFF,&H000000FF,&H00151B2D,&H66000000,-1,0,0,0,100,100,0,0,1,4,1,2,90,90,200,1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"""
    lines = []
    words = [w for seg in segments for w in seg.words if w.end >= start and w.start <= end]
    for i in range(0, len(words), 5):
        group = words[i:i + 5]
        if not group: continue
        text = " ".join(w.word.upper() for w in group).replace("{", "\\{").replace("}", "\\}")
        lines.append(f"Dialogue: 0,{ts(group[0].start-start)},{ts(group[-1].end-start)},Clippy,,0,0,0,,{text}")
    output.write_text(header + "\n".join(lines), encoding="utf-8")

def write_override_ass(text: str, start: float, end: float, output: Path) -> None:
    """Render a user-corrected clip caption while retaining the clip timeline."""
    header = """[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: Clippy,Arial,72,&H00FFFFFF,&H000000FF,&H00151B2D,&H66000000,-1,0,0,0,100,100,0,0,1,4,1,2,90,90,200,1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"""
    words = text.split(); lines = []; total = max(end - start, .1)
    for index in range(0, len(words), 5):
        group = words[index:index + 5]; group_start = start + total * index / len(words); group_end = start + total * min(index + 5, len(words)) / len(words)
        lines.append(f"Dialogue: 0,{ts(group_start-start)},{ts(group_end-start)},Clippy,,0,0,0,,{' '.join(group).upper()}")
    output.write_text(header + "\n".join(lines), encoding="utf-8")
