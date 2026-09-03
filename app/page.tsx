"use client";

import { useEffect, useState, type FormEvent } from "react";
import { buildInterruptionScene, createProject, loadDemoFile, saveShot, submitRender, uploadAsset, type InterruptionDraft } from "../src/web/workspace-client";

const initialDraft: InterruptionDraft = { shotName: "Opening interruption", sourceVideo: "", pauseAt: "7.4", characterAsset: "", position: "foreground_right", entrance: "slide_left", gesture: "shrug_and_point", dialogueText: "Wait — there is a clearer way.", voice: "alloy", lipSync: "rhubarb", captionsEnabled: true, captionStyle: "lower_third", logo: "", width: "1920", height: "1080", fps: "30" };
type Project = { id: string; name: string; workspaceId: string }; type Shot = { id: string; name: string }; type Job = { id: string; status: string; progress: number; output_url?: string; error_message?: string };

export default function Home() {
  const [projectName, setProjectName] = useState("My first film");
  const [project, setProject] = useState<Project | null>(null);
  const [draft, setDraft] = useState(initialDraft);
  const [shot, setShot] = useState<Shot | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState<"project" | "shot" | "render" | null>(null);
  const [notice, setNotice] = useState("Create a project to establish your anonymous workspace.");
  const [error, setError] = useState("");
  const [history, setHistory] = useState<Job[]>([]);
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [characterFile, setCharacterFile] = useState<File | null>(null);
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [setup, setSetup] = useState<{ ready: boolean; services: Record<string, boolean> } | null>(null);

  useEffect(() => { fetch("/api/setup-status").then((response) => response.json()).then(setSetup).catch(() => undefined); }, []);

  function update<K extends keyof InterruptionDraft>(key: K, value: InterruptionDraft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
    if (shot) { setShot(null); setJob(null); setNotice("Draft changed. Save a new shot snapshot before rendering."); }
  }
  async function loadDemo(role: "source_video" | "character" | "logo") {
    try {
      const file = await loadDemoFile(role);
      if (role === "source_video") setSourceFile(file);
      if (role === "character") setCharacterFile(file);
      if (role === "logo") setLogoFile(file);
      setNotice(`${file.name} loaded. Save the shot to upload it to Blob.`);
      setError("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Demo file could not be loaded."); }
  }
  async function onCreateProject(event: FormEvent) {
    event.preventDefault(); setBusy("project"); setError("");
    try { setProject(await createProject(projectName)); setNotice("Project created. Complete the Scene v1 editor and save the shot."); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Project could not be created."); }
    finally { setBusy(null); }
  }
  async function onSaveShot(event: FormEvent) {
    event.preventDefault(); if (!project) return; setBusy("shot"); setError("");
    try {
      const next = { ...draft };
      if (sourceFile) next.sourceVideo = await uploadAsset(sourceFile, project.workspaceId, project.id, "source_video");
      if (characterFile) next.characterAsset = await uploadAsset(characterFile, project.workspaceId, project.id, "character");
      if (logoFile) next.logo = await uploadAsset(logoFile, project.workspaceId, project.id, "logo");
      setDraft(next);
      setShot(await saveShot(project.id, next.shotName, buildInterruptionScene(next))); setJob(null); setNotice("Shot snapshot saved and ready to submit.");
    }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Shot could not be saved."); }
    finally { setBusy(null); }
  }
  async function onRender() {
    if (!project || !shot) return; setBusy("render"); setError("");
    try { const nextJob = await submitRender(project.id, shot.id, buildInterruptionScene(draft)); setJob(nextJob); setHistory((items) => [nextJob, ...items]); setNotice("Render accepted by the control plane."); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Render could not be submitted."); }
    finally { setBusy(null); }
  }

  return <main className="workspace">
    <header className="hero"><div><img className="brand-logo" src="/ulo-videos-logo.svg" alt="ulo-videos" /><h1>Build one precise interruption.</h1></div><p>Scene v1 turns a source clip, character, and cue into a deterministic render request. No account required; this workspace is tied to a secure browser cookie.</p></header>
    <div className="workspace-grid">
      <section className="editor" aria-labelledby="editor-title">
        <div className="step-heading"><span>01</span><div><h2 id="editor-title">Create a project</h2><p>The project owns every shot and render in this browser workspace.</p></div></div>
        <form className="project-row" onSubmit={onCreateProject}><label><span>Project name</span><input value={projectName} onChange={(e) => setProjectName(e.target.value)} maxLength={120} required disabled={Boolean(project)} /></label><button disabled={Boolean(project) || busy !== null}>{project ? "Project ready" : busy === "project" ? "Creating…" : "Create project"}</button></form>
        <div className="divider" />
        <div className="step-heading"><span>02</span><div><h2>Compose Scene v1</h2><p>Edit the interruption template. The API performs authoritative contract validation when you save.</p></div></div>
        <form className="scene-form" onSubmit={onSaveShot}>
          <fieldset disabled={!project || busy !== null}><legend>Shot and timing</legend><div className="fields two"><Field label="Shot name"><input value={draft.shotName} onChange={(e) => update("shotName",e.target.value)} maxLength={120} required /></Field><Field label="Interrupt at (seconds)"><input type="number" min="0" step="0.1" value={draft.pauseAt} onChange={(e) => update("pauseAt",e.target.value)} required /></Field></div><Field label="Source video" container><div className="file-row"><label className="file-picker"><span>{sourceFile?.name || (draft.sourceVideo ? "Uploaded source" : "Choose a video file")}</span><input className="file-input" type="file" accept="video/mp4,video/quicktime,video/webm" onChange={(e) => setSourceFile(e.target.files?.[0] || null)} required={!draft.sourceVideo && !sourceFile} /></label><button type="button" className="secondary demo-button" onClick={() => loadDemo("source_video")}>Load demo</button></div></Field>{sourceFile&&<small className="file-ready">✓ Ready to upload: {sourceFile.name}</small>}{draft.sourceVideo&&<small>Uploaded source: {draft.sourceVideo}</small>}</fieldset>
          <fieldset disabled={!project || busy !== null}><legend>Spokescharacter</legend><Field label="Character .blend file" container><div className="file-row"><label className="file-picker"><span>{characterFile?.name || (draft.characterAsset ? "Uploaded character" : "Choose a .blend file")}</span><input className="file-input" type="file" accept=".blend,application/x-blender" onChange={(e) => setCharacterFile(e.target.files?.[0] || null)} required={!draft.characterAsset && !characterFile} /></label><button type="button" className="secondary demo-button" onClick={() => loadDemo("character")}>Load demo</button></div></Field>{characterFile&&<small className="file-ready">✓ Ready to upload: {characterFile.name}</small>}<div className="fields three"><Field label="Position"><select value={draft.position} onChange={(e) => update("position",e.target.value as InterruptionDraft["position"])}><option value="foreground_left">Left</option><option value="foreground_center">Center</option><option value="foreground_right">Right</option></select></Field><Field label="Entrance"><select value={draft.entrance} onChange={(e) => update("entrance",e.target.value as InterruptionDraft["entrance"])}><option value="pop_in">Pop in</option><option value="fade_in">Fade in</option><option value="slide_left">Slide left</option><option value="slide_right">Slide right</option></select></Field><Field label="Gesture"><select value={draft.gesture} onChange={(e) => update("gesture",e.target.value as InterruptionDraft["gesture"])}><option value="shrug_and_point">Shrug + point</option><option value="wave">Wave</option><option value="nod">Nod</option><option value="talk_idle">Talk idle</option></select></Field></div><Field label="Dialogue"><textarea value={draft.dialogueText} onChange={(e) => update("dialogueText",e.target.value)} rows={3} /></Field><div className="fields two"><Field label="Voice reference"><input value={draft.voice} onChange={(e) => update("voice",e.target.value)} required /></Field><Field label="Lip-sync reference"><input value={draft.lipSync} onChange={(e) => update("lipSync",e.target.value)} required /></Field></div></fieldset>
          <fieldset disabled={!project || busy !== null}><legend>Brand and output</legend><Field label="Logo image file" container><div className="file-row"><label className="file-picker"><span>{logoFile?.name || (draft.logo ? "Uploaded logo" : "Choose an image file")}</span><input className="file-input" type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" onChange={(e) => setLogoFile(e.target.files?.[0] || null)} required={!draft.logo && !logoFile} /></label><button type="button" className="secondary demo-button" onClick={() => loadDemo("logo")}>Load demo</button></div></Field>{logoFile&&<small className="file-ready">✓ Ready to upload: {logoFile.name}</small>}<div className="fields two"><Field label="Caption placement"><select value={draft.captionStyle} onChange={(e) => update("captionStyle",e.target.value as InterruptionDraft["captionStyle"])}><option value="none">None</option><option value="lower_third">Lower third</option><option value="top">Top</option><option value="center">Center</option></select></Field><label className="check"><input type="checkbox" checked={draft.captionsEnabled} onChange={(e) => update("captionsEnabled",e.target.checked)} /><span>Generate captions</span></label></div><div className="fields three"><Field label="Width"><input type="number" min="1" value={draft.width} onChange={(e) => update("width",e.target.value)} required /></Field><Field label="Height"><input type="number" min="1" value={draft.height} onChange={(e) => update("height",e.target.value)} required /></Field><Field label="FPS"><input type="number" min="1" value={draft.fps} onChange={(e) => update("fps",e.target.value)} required /></Field></div></fieldset>
          <div className="actions"><button disabled={!project || busy !== null}>{busy === "shot" ? "Saving…" : shot ? "Shot saved" : "Save shot"}</button><button type="button" className="secondary" onClick={onRender} disabled={!shot || busy !== null}>{busy === "render" ? "Submitting…" : "Submit render"}</button></div>
        </form><div className={`notice ${error ? "error" : ""}`} role="status" aria-live="polite">{error || notice}</div>
      </section>
      <aside className="rail"><section className="status-card"><p className="eyebrow">Flow status</p><ol><li className={project?"done":"current"}>Project {project?.name || "not created"}</li><li className={shot?"done":project?"current":""}>Shot {shot?.name || "not saved"}</li><li className={job?"done":shot?"current":""}>Render {job ? `${job.status} · ${job.id}` : "not submitted"}</li></ol>{job ? <p className="job-note">Latest: <strong>{job.status}</strong> ({job.progress}%). {job.output_url ? <a href={job.output_url} target="_blank" rel="noreferrer">Open MP4</a> : null}</p>:null}{history.length>0&&<div className="history"><strong>Render history</strong>{history.slice(0,5).map((item)=><div key={item.id}>{item.id} · {item.status} · {item.progress}% {item.output_url ? <a href={item.output_url} target="_blank" rel="noreferrer">MP4</a> : null}</div>)}</div>}</section>
      <section className="setup-card"><p className="eyebrow">Cloud renderer</p><h2>{setup?.ready ? "Ready to render" : "Deployment status"}</h2><p>{setup?.ready ? "All production services are connected. Save a shot, then submit it for cloud rendering." : "The editor is available, but rendering is waiting on deployment configuration."}</p><ul>{[["Blob","Media storage",setup?.services.blob], ["Supabase","Projects, shots, and render jobs",setup?.services.supabase], ["Queue","Job dispatch",setup?.services.queue], ["Worker","FFmpeg render execution",setup?.services.worker]].map(([name, description, connected]) => <li key={String(name)} className={connected ? "connected" : "missing"}><strong>{connected ? "✓" : "!"} {name}</strong><span>{connected ? `${description} connected` : `${description} is not configured`}</span></li>)}</ul>{setup?.ready ? <p className="setup-foot">Production is configured. The first worker pass renders the deterministic FFmpeg baseline; Blender, Piper, and Rhubarb stages can be added next.</p> : <p className="setup-foot">An administrator must configure the missing service before rendering can start.</p>}</section></aside>
    </div>
  </main>;
}

function Field({label, children, container = false}:{label:string;children:React.ReactNode;container?:boolean}) { const Wrapper = container ? "div" : "label"; return <Wrapper className={container ? "field" : undefined}><span>{label}</span>{children}</Wrapper>; }
