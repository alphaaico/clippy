import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ChevronDown,
  Clock3,
  FileVideo,
  LoaderCircle,
  Play,
  Sparkles,
  Upload,
  WandSparkles,
  X,
} from "lucide-react";
import "./styles.css";

type Word = { word: string; start: number; end: number };
type Segment = { start: number; end: number; text: string; words: Word[] };
type Clip = {
  id: string;
  title: string;
  start: number;
  end: number;
  reason: string;
  excerpt: string;
  overall_score: number;
};
type Project = {
  id: string;
  status: string;
  stage: string;
  media: Record<string, any>;
  transcript: Segment[];
  clip_candidates: Clip[];
  analysis: Record<string, unknown>;
  error?: string;
};
type Anchor = { id: string; label: string; x: number };
type GeneratedClip = {
  id: string;
  title: string;
  url: string;
  duration: number;
  orientation: "vertical" | "horizontal";
};
const demoTranscript: Segment[] = [
  {
    start: 0,
    end: 7,
    text: "The biggest mistake people make with AI is treating it as a magic button.",
    words: [],
  },
  {
    start: 7,
    end: 15,
    text: "The better question is where does a human decision create the most leverage?",
    words: [],
  },
  {
    start: 15,
    end: 23,
    text: "Start with the workflow, not the model. The workflow tells you what deserves automation.",
    words: [],
  },
  {
    start: 23,
    end: 31,
    text: "If you automate a broken process, you simply make the broken process faster.",
    words: [],
  },
];
const demoClips: Clip[] = [
  {
    id: "demo-1",
    title: "Why AI automation fails",
    start: 0,
    end: 15,
    overall_score: 92,
    reason:
      "A crisp contrarian opening followed by a clear, practical reframe.",
    excerpt:
      "The biggest mistake people make with AI is treating it as a magic button.",
  },
  {
    id: "demo-2",
    title: "Start with the workflow",
    start: 15,
    end: 31,
    overall_score: 86,
    reason: "Standalone operational insight with a memorable conclusion.",
    excerpt: "Start with the workflow, not the model.",
  },
];
const format = (seconds: number) =>
  `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0")}:${Math.floor(seconds % 60)
    .toString()
    .padStart(2, "0")}`;
function App() {
  const [project, setProject] = useState<Project | null>(null),
    [selected, setSelected] = useState("demo-1"),
    [file, setFile] = useState<File | null>(null),
    [localUrl, setLocalUrl] = useState<string | null>(null),
    [generated, setGenerated] = useState<GeneratedClip[]>([]),
    [anchor, setAnchor] = useState(""),
    [orientation, setOrientation] = useState<"vertical" | "horizontal">(
      "vertical",
    ),
    [duration, setDuration] = useState(30),
    [active, setActive] = useState(0),
    [rendering, setRendering] = useState(false),
    [activity, setActivity] = useState<string[]>([]),
    [editingCaption, setEditingCaption] = useState<string | null>(null),
    [captionDrafts, setCaptionDrafts] = useState<Record<string, string>>({}),
    [settingsOpen, setSettingsOpen] = useState(false),
    [vocabulary, setVocabulary] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const clips = project?.clip_candidates ?? [];
  const transcript = project?.transcript ?? [];
  useEffect(() => {
    if (!project || project.status !== "processing") return;
    const i = window.setInterval(async () => {
      const p = await fetch(`/api/projects/${project.id}`).then((r) =>
        r.json(),
      );
      setProject(p);
      if (p.status !== "processing") {
        clearInterval(i);
        if (p.status === "ready" && p.clip_candidates?.length) {
          setSelected(p.clip_candidates[0].id);
          setAnchor("auto");
        }
      }
    }, 1800);
    return () => clearInterval(i);
  }, [project?.id, project?.status]);
  useEffect(() => {
    if (anchor) setGenerated([]);
  }, [anchor]);
  const log = (message: string) =>
    setActivity((items) =>
      [
        `${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}  ${message}`,
        ...items,
      ].slice(0, 8),
    );
  async function upload(f: File) {
    setFile(f);
    setGenerated([]);
    setAnchor("auto");
    setActivity([]);
    setLocalUrl(URL.createObjectURL(f));
    log(`Uploading ${f.name}`);
    const fd = new FormData();
    fd.append("video", f);
    try {
      const response = await fetch("/api/projects", {
        method: "POST",
        body: fd,
      });
      if (!response.ok) throw new Error(await response.text());
      const p = await response.json();
      setProject(p);
      log(`Upload complete · ${p.stage}`);
    } catch (error) {
      setProject(null);
      log(
        `Upload failed · ${error instanceof Error ? error.message : "Unknown error"}`,
      );
    }
  }
  function seek(t: number, i: number) {
    setActive(i);
    if (video.current) {
      video.current.currentTime = t;
      video.current.play();
    }
  }
  function clipCaptionText(clip: Clip) {
    return transcript
      .filter(
        (segment) => segment.end >= clip.start && segment.start <= clip.end,
      )
      .map((segment) => segment.text)
      .join(" ")
      .trim();
  }
  async function refresh() {
    if (!project) return;
    setGenerated([]);
    log(
      `Re-analysing for ~${duration} second clips${anchor ? " around the selected face" : ""}`,
    );
    try {
      const response = await fetch(`/api/projects/${project.id}/reanalyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ duration, anchor_id: anchor }),
      });
      if (!response.ok) throw new Error(await response.text());
      const p = await response.json();
      setProject(p);
      setSelected(p.clip_candidates?.[0]?.id || "");
      log(`New ~${duration} second recommendations ready`);
    } catch (error) {
      log(
        `Re-analysis failed · ${error instanceof Error ? error.message : "Unknown error"}`,
      );
    }
  }
  async function retranscribe() {
    if (!project) return;
    log("Re-transcribing with custom vocabulary");
    try {
      const response = await fetch(`/api/projects/${project.id}/retranscribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vocabulary }),
      });
      if (!response.ok) throw new Error(await response.text());
      const p = await response.json();
      setProject(p);
      setSelected(p.clip_candidates?.[0]?.id || "");
      setSettingsOpen(false);
      log("New transcript and key moments are ready");
    } catch (error) {
      log(
        `Re-transcription failed · ${error instanceof Error ? error.message : "Unknown error"}`,
      );
    }
  }
  async function processVideo() {
    if (!project) return;
    log(`Processing video for ~${duration} second moments`);
    try {
      const response = await fetch(`/api/projects/${project.id}/process`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ duration, vocabulary }),
      });
      if (!response.ok) throw new Error(await response.text());
      setProject(await response.json());
    } catch (error) {
      log(
        `Processing could not start · ${error instanceof Error ? error.message : "Unknown error"}`,
      );
    }
  }
  async function generate() {
    if (!project) return;
    const clipIds = project.clip_candidates.map((clip) => clip.id);
    if (!clipIds.length) {
      log("Generate skipped · no real key moments are available");
      return;
    }
    setRendering(true);
    log(
      `Generating all ${clipIds.length} ${orientation} previews · anchored to ${anchor}`,
    );
    try {
      const response = await fetch(`/api/projects/${project.id}/render`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          clip_ids: clipIds,
          anchor_id: anchor,
          orientation,
          caption_overrides: captionDrafts,
        }),
      });
      if (!response.ok) throw new Error(await response.text());
      const r = await response.json();
      setGenerated(r.clips);
      log(`Render complete · ${r.clips.length} previews are ready below`);
      window.setTimeout(
        () =>
          document
            .querySelector(".generated")
            ?.scrollIntoView({ behavior: "smooth", block: "start" }),
        50,
      );
    } catch (error) {
      log(
        `Render failed · ${error instanceof Error ? error.message : "Unknown error"}`,
      );
    } finally {
      setRendering(false);
    }
  }
  return (
    <main>
      <header>
        <div className="brand">
          <div className="mark">
            <img src="https://www.svgrepo.com/show/526412/video-library.svg" />
          </div>
          <span>clippy</span>
          <em>beta</em>
        </div>
        <div className="header-actions">
          <button className="ghost">How it works</button>
          <button className="avatar">T</button>
        </div>
      </header>
      {!file && (
        <section className="hero">
          <div className="eyebrow">
            <Sparkles size={14} /> AI VIDEO INTELLIGENCE
          </div>
          <h1>
            Turn long videos into
            <br />
            <i>clips worth watching.</i>
          </h1>
          <p>
            Upload a conversation, interview, or podcast. Clippy finds the
            ideas, frames the speaker, and makes the edit.
          </p>
        </section>
      )}
      {!file ? (
        <section className="upload-card" onClick={() => input.current?.click()}>
          <input
            ref={input}
            type="file"
            accept="video/mp4,video/quicktime,video/webm,video/x-matroska"
            onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
          />
          <div className="upload-icon">
            <Upload />
          </div>
          <h2>Drop your video here</h2>
          <p>
            or <b>choose a file</b> from your computer
          </p>
          <small>MP4, MOV, WebM, MKV · up to 2 GB</small>
        </section>
      ) : (
        <>
          <section className="workspace-head">
            <div className="file-pill">
              <FileVideo size={19} />
              <span>{file.name}</span>
              <button
                onClick={() => {
                  setFile(null);
                  setProject(null);
                  setLocalUrl(null);
                  setGenerated([]);
                }}
              >
                <X size={17} />
              </button>
            </div>
            <div
              title={project?.error}
              className={
                "status " + (project?.status === "failed" ? "failed" : "")
              }
            >
              <span></span>
              {project?.status === "loaded"
                ? "Video loaded"
                : project?.status === "processing"
                  ? project.stage
                  : project?.status === "failed"
                    ? `Processing failed · ${(project.error || "Unknown error").slice(0, 120)}`
                    : generated.length
                      ? "Generated previews ready"
                      : "Ready to clip"}
            </div>
          </section>
          {project?.status === "failed" && (
            <section className="failure-log">
              <p>PROCESSING LOG</p>
              {((project.media.activity_log || []) as string[])
                .slice(-6)
                .reverse()
                .map((entry, index) => (
                  <div key={index}>{entry}</div>
                ))}
            </section>
          )}
          {project?.status === "loaded" ? (
            <section className="process-setup">
              <div className="setup-video">
                <video controls src={localUrl || undefined} />
              </div>
              <div className="setup-copy">
                <p>VIDEO LOADED</p>
                <h2>Configure processing</h2>
                <div className="setup-meta">
                  <span>{project.media.resolution}</span>
                  <span>{format(Number(project.media.duration || 0))}</span>
                  <span>{project.media.video_codec}</span>
                </div>
                <label>
                  Preferred clip duration{" "}
                  <select
                    value={duration}
                    onChange={(event) =>
                      setDuration(Number(event.target.value))
                    }
                  >
                    {[20, 30, 40, 50, 60].map((value) => (
                      <option key={value} value={value}>
                        {value} seconds
                      </option>
                    ))}
                  </select>
                </label>
                <label className="vocabulary-input">
                  Transcript vocabulary{" "}
                  <textarea
                    placeholder="Names, brands, acronyms or technical terms (e.g. Digital Native Nexus, WITBOAD.AI)"
                    value={vocabulary}
                    onChange={(event) => setVocabulary(event.target.value)}
                  />
                </label>
                <small>
                  A target, not a hard cut. Vocabulary is passed to Whisper
                  before transcription begins.
                </small>
                <button className="generate" onClick={processVideo}>
                  <Sparkles size={17} /> Process Video
                </button>
              </div>
            </section>
          ) : (
            <>
              <section className="dashboard">
                <div className="video-panel">
                  <div className="player">
                    <div className="vertical-preview">
                      <span>ORIGINAL VIDEO</span>
                    </div>
                    {localUrl && (
                      <video
                        ref={video}
                        className="video-preview"
                        controls
                        src={localUrl}
                        onTimeUpdate={(e) => {
                          const t = e.currentTarget.currentTime;
                          const index = transcript.findIndex(
                            (x, i) =>
                              t >= x.start &&
                              (i === transcript.length - 1 ||
                                t < transcript[i + 1].start),
                          );
                          setActive(Math.max(0, index));
                        }}
                      />
                    )}
                  </div>
                  <div className="meta">
                    <span>{project?.media.resolution || "1920 × 1080"}</span>
                    <span>
                      {project?.media.duration
                        ? format(Number(project.media.duration))
                        : "Demo timeline"}
                    </span>
                    <span>English</span>
                  </div>
                </div>
                <div className="clips-panel">
                  <div className="panel-title">
                    <div>
                      <p>AI SELECTED · CLICK TO PREVIEW</p>
                      <h2>
                        Key moments <b>{clips.length}</b>
                      </h2>
                    </div>
                    <div>
                      <button
                        className="ghost small"
                        onClick={() => setSettingsOpen(!settingsOpen)}
                      >
                        Transcript settings
                      </button>
                      <button className="ghost small" onClick={refresh}>
                        <WandSparkles size={15} /> Refresh
                      </button>
                    </div>
                  </div>
                  {settingsOpen && (
                    <div className="transcription-settings">
                      <label>Vocabulary / names / brands</label>
                      <textarea
                        placeholder="e.g. Digital Native Nexus, WITBOAD.AI, Tushar Bhatnagar"
                        value={vocabulary}
                        onChange={(event) => setVocabulary(event.target.value)}
                      />
                      <button onClick={retranscribe}>
                        Save & re-transcribe
                      </button>
                    </div>
                  )}
                  {project?.status === "processing" ? (
                    <div className="thinking">
                      <LoaderCircle className="spin" />
                      <h3>Reading the conversation</h3>
                      <p>
                        Transcribing, understanding context, and looking for
                        complete ideas.
                      </p>
                    </div>
                  ) : (
                    <>
                      <div className="clip-list">
                        {clips.length ? (
                          clips.map((c, i) => (
                            <article
                              className={
                                "clip " + (selected === c.id ? "picked" : "")
                              }
                              key={c.id}
                              onClick={() => {
                                setSelected(c.id);
                                seek(c.start, 0);
                              }}
                            >
                              <div className="rank">
                                {String(i + 1).padStart(2, "0")}
                              </div>
                              <div className="clip-copy">
                                <div className="clip-top">
                                  <h3>{c.title}</h3>
                                  <strong>
                                    {c.overall_score}
                                    <small>/100</small>
                                  </strong>
                                </div>
                                <p>{c.reason}</p>
                                <div className="clip-foot">
                                  <Clock3 size={13} />
                                  {format(c.start)} — {format(c.end)}{" "}
                                  <span>{Math.round(c.end - c.start)}s</span>
                                  {selected === c.id && (
                                    <button
                                      className="edit-caption"
                                      onClick={(event) => {
                                        event.stopPropagation();
                                        setEditingCaption(
                                          editingCaption === c.id ? null : c.id,
                                        );
                                        setCaptionDrafts((drafts) => ({
                                          ...drafts,
                                          [c.id]:
                                            drafts[c.id] ?? clipCaptionText(c),
                                        }));
                                      }}
                                    >
                                      Edit captions
                                    </button>
                                  )}
                                </div>
                                {editingCaption === c.id && (
                                  <div className="caption-edit-wrap">
                                    <label>
                                      Caption copy · {format(c.start)} —{" "}
                                      {format(c.end)}
                                    </label>
                                    <textarea
                                      className="caption-editor"
                                      value={
                                        captionDrafts[c.id] ??
                                        clipCaptionText(c)
                                      }
                                      onClick={(event) =>
                                        event.stopPropagation()
                                      }
                                      onChange={(event) =>
                                        setCaptionDrafts((drafts) => ({
                                          ...drafts,
                                          [c.id]: event.target.value,
                                        }))
                                      }
                                    />
                                    <small>
                                      This replaces captions only for this{" "}
                                      {Math.round(c.end - c.start)}-second clip.
                                    </small>
                                  </div>
                                )}
                              </div>
                              {selected === c.id && (
                                <Play className="check" size={16} />
                              )}
                            </article>
                          ))
                        ) : (
                          <div className="empty-moments">
                            <h3>No usable key moments returned</h3>
                            <p>
                              Clippy will never render placeholder clips. Try
                              Refresh to re-run the semantic analysis with this
                              transcript.
                            </p>
                          </div>
                        )}
                      </div>
                      <div className="composer">
                        <div className="composer-top">
                          <span>FOCUS PERSON</span>
                          <div className="anchor-row">
                            <button
                              title="Auto framing — retain the full conversation when multiple people are visible"
                              aria-label="Auto framing"
                              className={anchor === "auto" ? "chosen anchor-auto" : "anchor-auto"}
                              onClick={() => setAnchor("auto")}
                            >
                              <span>AUTO</span>
                            </button>
                            {(
                              (project?.media.face_anchors || []) as Anchor[]
                            ).map((item) => (
                              <button
                                key={item.id}
                                title={item.label}
                                className={anchor === item.id ? "chosen" : ""}
                                onClick={() => setAnchor(item.id)}
                              >
                                {(item as any).thumbnail ? (
                                  <img src={(item as any).thumbnail} />
                                ) : (
                                  <span>?</span>
                                )}
                              </button>
                            ))}
                          </div>
                        </div>
                        <label className="duration-select">
                          Clip duration{" "}
                          <select
                            value={duration}
                            onChange={(event) =>
                              setDuration(Number(event.target.value))
                            }
                          >
                            {[20, 30, 40, 50, 60].map((value) => (
                              <option key={value} value={value}>
                                {value} seconds
                              </option>
                            ))}
                          </select>
                        </label>
                        <div className="format-toggle">
                          <button
                            className={
                              orientation === "vertical" ? "selected" : ""
                            }
                            onClick={() => {
                              setOrientation("vertical");
                              setGenerated([]);
                            }}
                          >
                            9:16
                          </button>
                          <button
                            className={
                              orientation === "horizontal" ? "selected" : ""
                            }
                            onClick={() => {
                              setOrientation("horizontal");
                              setGenerated([]);
                            }}
                          >
                            16:9
                          </button>
                        </div>
                        <button
                          className="generate"
                          onClick={generate}
                          disabled={rendering || !anchor || !clips.length}
                        >
                          {rendering ? (
                            <LoaderCircle className="spin" />
                          ) : (
                            <Sparkles size={17} />
                          )}{" "}
                          {rendering ? "Rendering…" : "Generate Clips"}
                        </button>
                      </div>
                    </>
                  )}
                </div>
              </section>
              {generated.length > 0 && (
                <section className="generated">
                  <div className="section-heading">
                    <div>
                      <p>GENERATED FROM KEY MOMENTS</p>
                      <h2>
                        Clip previews <b>{generated.length}</b>
                      </h2>
                    </div>
                  </div>
                  <div
                    className={
                      "generated-grid " +
                      (generated[0].orientation === "horizontal"
                        ? "horizontal-previews"
                        : "")
                    }
                  >
                    {generated.map((clip, index) => (
                      <article className="generated-card" key={clip.id}>
                        <div className="generated-video">
                          <span>
                            {String(index + 1).padStart(2, "0")} ·{" "}
                            {clip.orientation === "horizontal"
                              ? "16:9"
                              : "9:16"}
                          </span>
                          <video
                            controls
                            preload="metadata"
                            src={`${clip.url}?orientation=${clip.orientation}`}
                          />
                        </div>
                        <h3>{clip.title}</h3>
                        <p>
                          {clip.duration}s · Face anchor: {anchor}
                        </p>
                      </article>
                    ))}
                  </div>
                </section>
              )}
              <section className="lower">
                <div className="transcript">
                  <div className="section-heading">
                    <div>
                      <p>WORD-LEVEL TIMING</p>
                      <h2>Transcript</h2>
                    </div>
                    <button className="filter">
                      English <ChevronDown size={15} />
                    </button>
                  </div>
                  <div className="transcript-scroll">
                    {transcript.map((s, i) => (
                      <button
                        className={"segment " + (active === i ? "active" : "")}
                        key={i}
                        onClick={() => seek(s.start, i)}
                      >
                        <time>{format(s.start)}</time>
                        <span>{s.text}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </section>
            </>
          )}
        </>
      )}
      <footer>
        Made for ideas with a little more to say <span>·</span> Clippy POC
      </footer>
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
