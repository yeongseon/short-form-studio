import type { StoryboardResponse } from "../api/storyboard";
import type { VisualScene } from "../types/api";

export function scene(scene_id = "scene-0", prompt = "server initial"): VisualScene {
  return { scene_id, prompt, prompt_edited: false, prompt_source: "auto_generated",
    style_tags: [], mood: null, composition: null, generation_status: "pending" };
}

export function plan(version = 1, scenes = [scene(), scene("scene-1")]) {
  return { version, scenes };
}

export function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export function deferred<T>() {
  let resolve: (value: T) => void = () => { throw new Error("Promise not initialized"); };
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

export function storyboard(): StoryboardResponse {
  return { run_id: 1, total_paragraphs: 2, ready_paragraphs: 0, render_ready: false,
    paragraphs: [0, 1].map((i) => ({
      section_id: `sec-${i}`, scene_id: `scene-${i}`, order: i,
      text: `Script ${i}`, display_text: null, image_prompt: "server initial",
      image_url: null, audio_url: null, audio_duration: null, subtitles_url: null,
      subtitle_entries: null, status: i === 1 ? "generating_image" : "idle",
      stale_flags: null, image_asset_id: null, audio_artifact_id: null,
      subtitle_artifact_id: null, section_type: null, speaker: null, duration: null,
      turn_kind: null, visual_override: null,
    })) };
}
