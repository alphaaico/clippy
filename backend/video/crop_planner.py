from __future__ import annotations
from statistics import median
from .face_detection import FaceSample

def smooth(samples: list[FaceSample], alpha: float = .32) -> list[FaceSample]:
    if not samples: return []
    result = [samples[0]]
    for sample in samples[1:]:
        previous = result[-1]
        result.append(FaceSample(sample.time, alpha * sample.x + (1-alpha) * previous.x, alpha * sample.y + (1-alpha) * previous.y, sample.width, sample.height))
    return result

def horizontal_crop_center(samples: list[FaceSample]) -> float:
    """Stable face-centred X target, usable as a graceful centre-crop fallback."""
    return median(s.x for s in smooth(samples)) if samples else .5
