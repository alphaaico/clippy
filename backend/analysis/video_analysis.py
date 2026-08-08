from __future__ import annotations
import json, os, re
from difflib import SequenceMatcher
from backend.models.schemas import TranscriptSegment, ClipCandidate, ClipScores

class GroqFailover:
    """Retries a request on the next configured Groq account when one fails."""
    def __init__(self):
        from groq import Groq
        configured = [
            ("primary", os.getenv("GROQ_API_KEY", ""), os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")),
            ("fallback", os.getenv("GROQ_FALLBACK_API_KEY", ""), os.getenv("GROQ_FALLBACK_MODEL") or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")),
        ]
        self.accounts = [(name, Groq(api_key=key), model) for name, key, model in configured if key]
        self.active = 0
        if not self.accounts:
            raise RuntimeError("No Groq API key is configured")

    def complete(self, prompt: str, temperature: float):
        failures: list[str] = []
        order = list(range(self.active, len(self.accounts))) + list(range(0, self.active))
        for index in order:
            name, client, model = self.accounts[index]
            try:
                response = client.chat.completions.create(
                    model=model, messages=[{"role":"user", "content":prompt}], temperature=temperature,
                    response_format={"type":"json_object"},
                )
                self.active = index
                return response.choices[0].message.content or "{}", name
            except Exception as error:
                failures.append(f"{name}: {error}")
        raise RuntimeError("All configured Groq accounts failed. " + " | ".join(failures))

def check_groq_accounts() -> list[dict[str, str | bool]]:
    """Lightweight launch health check; it does not send prompt tokens."""
    from groq import Groq
    configs = [
        ("primary", os.getenv("GROQ_API_KEY", "")),
        ("fallback", os.getenv("GROQ_FALLBACK_API_KEY", "")),
    ]
    status: list[dict[str, str | bool]] = []
    for name, key in configs:
        if not key:
            status.append({"account": name, "configured": False, "available": False})
            continue
        try:
            Groq(api_key=key).models.list()
            status.append({"account": name, "configured": True, "available": True})
        except Exception as error:
            status.append({"account": name, "configured": True, "available": False, "error": str(error)})
    return status

def _json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    return json.loads(match.group(0) if match else text)

def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())

def _find_phrase(words, phrase: str, start_at: int = 0) -> int | None:
    needle = _tokens(phrase)
    haystack = [_tokens(word.word)[0] if _tokens(word.word) else "" for word in words]
    if not needle: return None
    for index in range(start_at, len(haystack) - len(needle) + 1):
        if haystack[index:index + len(needle)] == needle: return index
    # LLMs occasionally omit a filler word or alter punctuation despite being
    # asked for verbatim anchors. Resolve a close contiguous phrase instead of
    # discarding an otherwise useful moment.
    best_index, best_score = None, 0.0
    low, high = max(1, len(needle) - 3), len(needle) + 3
    for index in range(start_at, len(haystack)):
        for size in range(low, high + 1):
            window = haystack[index:index + size]
            if not window: continue
            score = SequenceMatcher(None, needle, window).ratio()
            if score > best_score:
                best_index, best_score = index, score
    return best_index if best_score >= .62 else None

def _closest_segment(transcript: list[TranscriptSegment], phrase: str, after_time: float = 0) -> TranscriptSegment | None:
    """Map a semantic phrase back to the most credible transcript sentence.

    This is deliberately a fallback. The transcript remains the source of
    timing, but a one-word LLM paraphrase should not delete a good clip.
    """
    target = _tokens(phrase)
    if not target: return None
    target_set = set(target)
    best, best_score = None, 0.0
    for segment in transcript:
        if segment.end < after_time: continue
        candidate = _tokens(segment.text)
        if not candidate: continue
        coverage = len(target_set.intersection(candidate)) / max(1, min(len(target_set), 6))
        similarity = SequenceMatcher(None, target, candidate).ratio()
        score = max(coverage, similarity)
        if score > best_score:
            best, best_score = segment, score
    return best if best_score >= .42 else None

def _snap_to_transcript_boundaries(transcript: list[TranscriptSegment], start: float, end: float) -> tuple[float, float]:
    """Do not cut through the segment containing a selected anchor phrase."""
    start_segment = next((segment for segment in transcript if segment.start <= start <= segment.end), None)
    end_segment = next((segment for segment in transcript if segment.start <= end <= segment.end), None)
    return (start_segment.start if start_segment else start, end_segment.end if end_segment else end)

def _resolve_anchors(transcript: list[TranscriptSegment], start_text: str, end_text: str) -> tuple[float, float] | None:
    words = [word for segment in transcript for word in segment.words]
    start_index = _find_phrase(words, start_text)
    end_index = _find_phrase(words, end_text, start_index or 0)
    if start_index is not None and end_index is not None:
        end_index += max(0, len(_tokens(end_text)) - 1)
        if end_index < len(words) and words[end_index].end > words[start_index].start:
            start, end = _snap_to_transcript_boundaries(transcript, words[start_index].start, words[end_index].end)
            return max(0, start - .2), end + .35
    # A graceful fallback to the nearest source transcript boundaries. This
    # preserves complete spoken segments rather than rejecting a good idea
    # because of small differences between Groq and Whisper wording.
    start_segment = _closest_segment(transcript, start_text)
    if not start_segment: return None
    end_segment = _closest_segment(transcript, end_text, start_segment.start)
    if not end_segment or end_segment.end <= start_segment.start: return None
    return max(0, start_segment.start - .2), end_segment.end + .35

def _duration_window(target: int) -> tuple[int, int]:
    # Wide guardrails. Duration is a preference; a complete thought wins over
    # a mechanically perfect runtime. 60 seconds remains the hard cap.
    windows = {20:(12,32), 30:(16,45), 40:(22,55), 50:(28,60), 60:(34,60)}
    return windows.get(target, (16,45))

def _analyze_practical(transcript: list[TranscriptSegment], target_duration: int) -> tuple[dict, list[ClipCandidate]]:
    """POC-friendly selection: semantic selection first, light timestamp mapping second.

    There is intentionally no per-candidate rejection or duration validator in
    this path. The model sees the full transcript, selects useful moments, and
    Whisper only supplies the real timeline for those decisions.
    """
    timeline = "\n".join(f"[{segment.start:.2f}-{segment.end:.2f}] {segment.text}" for segment in transcript)
    groq = GroqFailover()
    overview_prompt = f'''Understand this complete video transcript. Return ONLY JSON: {{"summary":str,"topics":[str],"key_points":[str],"stories":[str],"strong_opinions":[str],"questions_answers":[str]}}.\n\n{timeline}'''
    overview_response, overview_account = groq.complete(overview_prompt, .2)
    overview = _json(overview_response)
    clips_prompt = f'''Use the complete transcript and video overview to choose 5 to 8 distinct, useful short-form moments. Target runtime is about {target_duration} seconds, but do not force an exact duration and do not reject a useful moment merely because it is shorter or longer. Prefer a clear idea, story, answer, opinion, lesson, or takeaway. Use start_text and end_text copied from the transcript; they should frame as much of the thought as is naturally useful. Do not invent timestamps. Return ONLY JSON: {{"clips":[{{"title":str,"start_text":str,"end_text":str,"reason":str,"scores":{{"importance":1-10,"standalone":1-10,"hook":1-10,"information_value":1-10,"completeness":1-10}}}}]}}.\n\nOVERVIEW:{json.dumps(overview)}\n\nTRANSCRIPT:{timeline}'''
    suggestions_response, clips_account = groq.complete(clips_prompt, .25)
    suggestions = _json(suggestions_response).get("clips", [])
    candidates: list[ClipCandidate] = []
    for suggestion in suggestions:
        resolved = _resolve_anchors(transcript, suggestion.get("start_text", ""), suggestion.get("end_text", ""))
        if not resolved: continue
        start, end = resolved
        if end <= start: continue
        scores = suggestion.get("scores", {})
        mapped = ClipScores(importance=scores.get("importance", 7), hook=scores.get("hook", 7), standalone=scores.get("standalone", 7), information_value=scores.get("information_value", 7), completeness=scores.get("completeness", 7))
        overall = round((mapped.importance + mapped.hook + mapped.standalone + mapped.information_value + mapped.completeness) / 50 * 100)
        candidates.append(ClipCandidate(id=f"clip-{len(candidates)+1}", title=suggestion.get("title", "Key moment"), start=start, end=end, reason=suggestion.get("reason", "Useful moment from the conversation."), excerpt=f"{suggestion.get('start_text', '')} … {suggestion.get('end_text', '')}", scores=mapped, overall_score=overall))
    candidates.sort(key=lambda candidate: candidate.overall_score, reverse=True)
    overview["groq_accounts_used"] = list(dict.fromkeys([overview_account, clips_account]))
    return overview, candidates[:5]

def analyze(transcript: list[TranscriptSegment], target_duration: int = 30) -> tuple[dict, list[ClipCandidate]]:
    if not os.getenv("GROQ_API_KEY"):
        return {"summary":"Connect Groq to generate semantic clip recommendations.","topics":[],"key_points":[]}, []
    return _analyze_practical(transcript, min(max(target_duration, 20), 60))
    from groq import Groq
    target_duration = min(max(target_duration, 20), 60); minimum, maximum = _duration_window(target_duration)
    timeline = "\n".join(f"[{segment.start:.2f}-{segment.end:.2f}] {segment.text}" for segment in transcript)
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    overview_prompt = f'''Understand this complete video transcript. Return ONLY JSON: {{"summary":str,"topics":[str],"key_points":[str],"stories":[str],"strong_opinions":[str],"questions_answers":[str]}}.\n\n{timeline}'''
    overview = _json(client.chat.completions.create(model=os.getenv("GROQ_MODEL","llama-3.3-70b-versatile"),messages=[{"role":"user","content":overview_prompt}],temperature=.2,response_format={"type":"json_object"}).choices[0].message.content or "{}")
    moments_prompt = f'''Using the overview and transcript below, identify up to 12 DISTINCT important ideas worth expanding into standalone social clips. Do not choose timestamps. Return ONLY JSON: {{"moments":[{{"topic":str,"anchor_text":str,"importance":1-10,"short_form_potential":1-10}}]}}. An anchor_text must be a distinctive phrase copied verbatim from the transcript. Reject duplicate ideas, filler, setup-only material and ideas that depend heavily on missing context. Return enough varied possibilities that five strong final clips can be selected.\n\nOVERVIEW:{json.dumps(overview)}\n\nTRANSCRIPT:{timeline}'''
    moments = _json(client.chat.completions.create(model=os.getenv("GROQ_MODEL","llama-3.3-70b-versatile"),messages=[{"role":"user","content":moments_prompt}],temperature=.2,response_format={"type":"json_object"}).choices[0].message.content or "{}").get("moments", [])
    candidates: list[ClipCandidate] = []
    for moment in moments:
        anchor = moment.get("anchor_text", ""); anchor_index = _find_phrase([word for segment in transcript for word in segment.words], anchor)
        if anchor_index is None: continue
        all_words = [word for segment in transcript for word in segment.words]; anchor_time = all_words[anchor_index].start
        context = [segment for segment in transcript if anchor_time - 45 <= segment.end and segment.start <= anchor_time + 75]
        context_text = "\n".join(f"[{segment.start:.2f}-{segment.end:.2f}] {segment.text}" for segment in context)
        expand_prompt = f'''Expand this important moment into one COMPLETE standalone short-form thought. Choose textual start_text and end_text from the context; do not invent timestamps. It must have a natural hook/setup, core idea, and payoff/conclusion. {target_duration}s is a preferred target, with a broad usable range of {minimum}-{maximum}s. Do not reject a complete, useful thought only because it is shorter or longer than the target. Reject only material that is genuinely incomplete, repetitive, filler, or unintelligible without missing context. Avoid beginnings like And/But/So/Like I mentioned unless you include needed context. Return ONLY JSON: {{"reject":bool,"title":str,"start_text":str,"end_text":str,"reason":str,"scores":{{"importance":1-10,"standalone":1-10,"hook":1-10,"information_value":1-10,"completeness":1-10,"short_form_suitability":1-10}}}}.\n\nMOMENT:{json.dumps(moment)}\n\nCONTEXT:{context_text}'''
        expanded = _json(client.chat.completions.create(model=os.getenv("GROQ_MODEL","llama-3.3-70b-versatile"),messages=[{"role":"user","content":expand_prompt}],temperature=.15,response_format={"type":"json_object"}).choices[0].message.content or "{}")
        if expanded.get("reject"): continue
        resolved = _resolve_anchors(transcript, expanded.get("start_text", ""), expanded.get("end_text", ""))
        if not resolved: continue
        start, end = resolved; duration = end - start
        if duration < minimum or duration > maximum: continue
        scores = expanded.get("scores", {}); mapped = ClipScores(importance=scores.get("importance", moment.get("importance", 7)), hook=scores.get("hook", 7), standalone=scores.get("standalone", 7), information_value=scores.get("information_value", 7), completeness=scores.get("completeness", 7))
        semantic_score = (mapped.importance + mapped.hook + mapped.standalone + mapped.information_value + mapped.completeness + scores.get("short_form_suitability",7)) / 60 * 100
        duration_penalty = min(10, abs(duration - target_duration) / max(target_duration, 1) * 10)
        overall = round(semantic_score - duration_penalty)
        candidates.append(ClipCandidate(id=f"clip-{len(candidates)+1}",title=expanded.get("title",moment.get("topic","Key moment")),start=start,end=end,reason=expanded.get("reason","Complete standalone thought."),excerpt=f"{expanded.get('start_text','')} … {expanded.get('end_text','')}",scores=mapped,overall_score=overall))
    candidates.sort(key=lambda candidate:candidate.overall_score, reverse=True)
    return overview, candidates[:5]
