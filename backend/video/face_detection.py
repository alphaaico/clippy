from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass
class FaceSample:
    time: float
    x: float
    y: float
    width: float
    height: float

def _faces(frame, detector):
    import cv2
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    detections = detector.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=5, minSize=(40, 40))
    frame_h, frame_w = frame.shape[:2]
    faces = [((x + w / 2) / frame_w, (y + h / 2) / frame_h, w / frame_w, h / frame_h) for x, y, w, h in detections]
    # Interview subjects' faces occupy the upper portion of the seated frame.
    # This removes common Haar false positives on hands, clothing and logos.
    return [(x, y, w, h) for x, y, w, h in faces if y < .55 and h >= .055 and w * h >= .005]

def _detector():
    import cv2
    cascade_path = Path(__file__).parent / "assets" / "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(str(cascade_path))
    if detector.empty(): raise RuntimeError("Face detector data is missing; expected " + str(cascade_path))
    return detector

def _mouth_patch(frame, x: float, y: float, w: float, h: float):
    """A small lower-face patch used as a lightweight lip-activity proxy."""
    import cv2
    frame_h, frame_w = frame.shape[:2]
    left = max(0, int((x - w / 2) * frame_w)); right = min(frame_w, int((x + w / 2) * frame_w))
    top = max(0, int((y + h * .05) * frame_h)); bottom = min(frame_h, int((y + h * .42) * frame_h))
    if right <= left or bottom <= top: return None
    return cv2.resize(cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2GRAY), (32, 12))

def detect_face_anchors(video_path: Path, duration: float, every_seconds: float = 1.0, thumbnail_dir: Path | None = None, project_id: str = "", start_seconds: float = 10.0) -> list[dict]:
    """Create durable speaker anchors from the conversation, skipping the intro."""
    import cv2
    capture = cv2.VideoCapture(str(video_path)); detector = _detector(); clusters: list[dict] = []
    capture.set(cv2.CAP_PROP_POS_MSEC, start_seconds * 1000)
    next_time = start_seconds
    try:
        while capture.isOpened():
            ok, frame = capture.read()
            if not ok: break
            now = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if now > duration: break
            if now < next_time: continue
            next_time += every_seconds
            for x, y, w, h in _faces(frame, detector):
                match = next((c for c in clusters if abs(c["x"] - x) < .16 and abs(c["y"] - y) < .18), None)
                if match:
                    count = match["count"] + 1; match["x"] = (match["x"] * match["count"] + x) / count; match["y"] = (match["y"] * match["count"] + y) / count; match["width"] = (match["width"] * match["count"] + w) / count; match["height"] = (match["height"] * match["count"] + h) / count; match["count"] = count
                else:
                    cluster = {"x": x, "y": y, "width": w, "height": h, "count": 1, "area": w*h, "observations": [], "last_mouth": None}
                    if thumbnail_dir:
                        frame_h, frame_w = frame.shape[:2]; left=max(0, int((x-w*.75)*frame_w)); right=min(frame_w, int((x+w*.75)*frame_w)); top=max(0, int((y-h*.9)*frame_h)); bottom=min(frame_h, int((y+h*.9)*frame_h))
                        crop = frame[top:bottom, left:right]
                        name = f"{project_id}-face-{len(clusters)+1}.jpg"; cv2.imwrite(str(thumbnail_dir / name), crop); cluster["thumbnail"] = f"/outputs/{name}"
                    clusters.append(cluster)
                    match = cluster
                patch = _mouth_patch(frame, x, y, w, h)
                previous = match.get("last_mouth")
                motion = 0.0 if patch is None or previous is None else float(abs(patch.astype("float32") - previous.astype("float32")).mean() / 255)
                match["last_mouth"] = patch
                match["observations"].append({"time": round(now, 2), "x": round(x, 3), "mouth_motion": round(motion, 4)})
    finally: capture.release()
    clusters.sort(key=lambda item: item["count"], reverse=True)
    anchors = []
    for index, cluster in enumerate(clusters[:3]):
        position = "Left" if cluster["x"] < .38 else "Right" if cluster["x"] > .62 else "Centre"
        observations = cluster.get("observations", [])
        activity = sum(item["mouth_motion"] for item in observations) / max(1, len(observations))
        anchors.append({"id": f"face-{index+1}", "label": f"Face {index+1} · {position}", "x": float(round(cluster["x"], 3)), "y": float(round(cluster["y"], 3)), "width": float(round(cluster["width"], 3)), "height": float(round(cluster["height"], 3)), "speaker_likelihood": round(activity, 4), "activity_timeline": observations, "thumbnail": cluster.get("thumbnail")})
    return anchors or [{"id": "center", "label": "Centre framing (no face detected)", "x": .5}]

def detect_consistent_face_anchors(video_path: Path, duration: float, sample_count: int = 30, thumbnail_dir: Path | None = None, project_id: str = "") -> list[dict]:
    """Offer only faces that recur across representative substantive frames.

    This deliberately excludes one-off intro cards, thumbnails and detector
    mistakes. It is a lightweight visual-consistency matcher, not face ID.
    """
    import cv2
    import numpy as np
    detector = _detector(); capture = cv2.VideoCapture(str(video_path)); clusters: list[dict] = []
    start = min(max(10.0, duration * .08), 60.0); finish = max(start + 1, duration * .95)
    times = [start + (finish - start) * index / max(1, sample_count - 1) for index in range(sample_count)]
    def crop_and_feature(frame, x, y, w, h):
        frame_h, frame_w = frame.shape[:2]; left=max(0, int((x-w*.7)*frame_w)); right=min(frame_w, int((x+w*.7)*frame_w)); top=max(0, int((y-h*.8)*frame_h)); bottom=min(frame_h, int((y+h*.8)*frame_h))
        crop = frame[top:bottom, left:right]
        if crop.size == 0: return None, None
        gray = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (32, 32)).astype("float32").reshape(-1)
        gray = (gray - gray.mean()) / (gray.std() + 1e-6)
        return crop, gray
    try:
        for now in times:
            capture.set(cv2.CAP_PROP_POS_MSEC, now * 1000); ok, frame = capture.read()
            if not ok: continue
            for x, y, w, h in _faces(frame, detector):
                crop, feature = crop_and_feature(frame, x, y, w, h)
                if feature is None: continue
                def similarity(cluster):
                    proto = cluster["feature"]
                    return float(np.dot(feature, proto) / (np.linalg.norm(feature) * np.linalg.norm(proto) + 1e-6))
                def match_score(cluster):
                    if not cluster["items"]: return -1.0
                    median_x = float(np.median([item["x"] for item in cluster["items"]])); median_y = float(np.median([item["y"] for item in cluster["items"]]))
                    position = max(0.0, 1 - abs(median_x - x) / .20 - abs(median_y - y) / .24)
                    return similarity(cluster) * .65 + position * .35
                match = max(clusters, key=match_score, default=None)
                # Same person may turn their head or wear glasses, so visual
                # similarity alone is too brittle. Require both a reasonable
                # appearance match and a stable interview position.
                if match is None or match_score(match) < .56 or similarity(match) < .42:
                    match = {"feature": feature, "items": [], "best_crop": crop, "best_area": w*h}
                    clusters.append(match)
                else:
                    count = len(match["items"]); match["feature"] = (match["feature"] * count + feature) / (count + 1)
                    if w*h > match["best_area"]: match["best_crop"] = crop; match["best_area"] = w*h
                motion = 0.0
                if match["items"]:
                    previous = match["items"][-1].get("mouth")
                    patch = _mouth_patch(frame, x, y, w, h)
                    motion = 0.0 if patch is None or previous is None else float(abs(patch.astype("float32") - previous.astype("float32")).mean() / 255)
                else: patch = _mouth_patch(frame, x, y, w, h)
                match["items"].append({"time": round(now, 2), "x": round(x, 3), "y": round(y, 3), "width": round(w, 3), "height": round(h, 3), "mouth_motion": round(motion, 4), "mouth": patch})
    finally:
        capture.release()
    minimum = max(3, sample_count // 8)
    stable = [cluster for cluster in clusters if len(cluster["items"]) >= minimum]
    stable.sort(key=lambda cluster: len(cluster["items"]), reverse=True)
    anchors = []
    for index, cluster in enumerate(stable[:3]):
        items = cluster["items"]; x = float(np.median([item["x"] for item in items])); y = float(np.median([item["y"] for item in items])); width = float(np.median([item["width"] for item in items])); height = float(np.median([item["height"] for item in items]))
        name = f"{project_id}-face-{index+1}.jpg"
        if thumbnail_dir: cv2.imwrite(str(thumbnail_dir / name), cluster["best_crop"])
        anchors.append({"id": f"face-{index+1}", "label": f"Face {index+1} · seen {len(items)}/{sample_count} frames", "x": round(x,3), "y": round(y,3), "width": round(width,3), "height": round(height,3), "speaker_likelihood": round(sum(item["mouth_motion"] for item in items) / len(items),4), "activity_timeline":[{key:value for key,value in item.items() if key != "mouth"} for item in items], "thumbnail": f"/outputs/{name}" if thumbnail_dir else None})
    return anchors or [{"id": "center", "label": "Centre framing (no consistent face)", "x": .5}]

def sample_primary_face(video_path: Path, start: float, end: float, every_seconds: float = 0.75, anchor_x: float | None = None) -> list[FaceSample]:
    """Sample frames and choose the largest, most central face on each frame.

    OpenCV's bundled Haar cascade is intentionally used here instead of
    ``mediapipe.solutions``: the currently installable MediaPipe wheels removed
    that namespace. This detector keeps the POC operational without requiring a
    downloadable model asset; absent detections correctly fall back to centre.
    """
    import cv2
    capture = cv2.VideoCapture(str(video_path)); fps = capture.get(cv2.CAP_PROP_FPS) or 30
    capture.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    cascade_path = Path(__file__).parent / "assets" / "haarcascade_frontalface_default.xml"
    detector = _detector()
    samples: list[FaceSample] = []; next_time = start
    try:
        while capture.isOpened():
            ok, frame = capture.read()
            if not ok: break
            now = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if now > end: break
            if now < next_time: continue
            next_time += every_seconds
            candidates = []
            for cx, cy, w, h in _faces(frame, detector):
                # Larger faces win, but a central speaker is preferred when faces are close.
                score = w * h - .045 * abs(cx - .5)
                candidates.append((score, cx, cy, w, h))
            if not candidates: continue
            if anchor_x is not None:
                chosen = min(candidates, key=lambda item: abs(item[1] - anchor_x))
                # Do not jump to the other guest when this person is briefly
                # missed; the render falls back to the saved anchor instead.
                if abs(chosen[1] - anchor_x) > .24: continue
                _, x, y, w, h = chosen
            else:
                _, x, y, w, h = max(candidates)
            samples.append(FaceSample(now, x, y, w, h))
    finally:
        capture.release()
    return samples
