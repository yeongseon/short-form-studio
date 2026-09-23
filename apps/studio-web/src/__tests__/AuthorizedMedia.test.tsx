import { afterEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { fetchStoryboard, type StoryboardParagraph } from "../api/storyboard";
import SceneCard from "../components/creator/SceneCard";
import StoryboardCard from "../components/creator/StoryboardCard";

afterEach(() => { vi.unstubAllGlobals(); });

const paragraph: StoryboardParagraph = {
  section_id: "section-1", order: 0, text: "A scene", display_text: null,
  image_prompt: "Sunset", image_url: "data/artifacts/7/visual/scene.png",
  audio_url: "data/artifacts/7/audio/voice.wav", subtitles_url: "7/subtitles/captions.srt",
  audio_duration: 1, subtitle_entries: null, status: "ready", stale_flags: null,
  scene_id: "scene-1", image_asset_id: 11, audio_artifact_id: 22, subtitle_artifact_id: 33,
  section_type: null, speaker: null, duration: null, turn_kind: null, visual_override: null,
};

it("mounts authorized scene and storyboard media when storage paths arrive from the API", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
    run_id: 7, paragraphs: [paragraph], render_ready: true, total_paragraphs: 1, ready_paragraphs: 1,
  }))));
  const result = await fetchStoryboard(7);
  const first = result.paragraphs[0];
  if (!first) throw new Error("Missing paragraph fixture");
  render(<><SceneCard paragraph={first} currentStage="FINAL_REVIEW" /><StoryboardCard paragraph={first} /></>);
  for (const image of screen.getAllByRole("img")) {
    expect(image).toHaveAttribute("src", "/api/creator/runs/7/visual-assets/11/content");
  }
  for (const audio of document.querySelectorAll("audio")) {
    expect(audio).toHaveAttribute("src", "/api/creator/runs/7/artifacts/22/download");
  }
  expect(first.subtitles_url).toBe("/api/creator/runs/7/artifacts/33/download");
});

it("does not expose raw paths when media identity is missing", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
    run_id: 7, paragraphs: [{ ...paragraph, image_asset_id: null, audio_artifact_id: null, subtitle_artifact_id: null }],
  }))));
  const result = await fetchStoryboard(7);
  expect(result.paragraphs[0]).toMatchObject({ image_url: null, audio_url: null, subtitles_url: null });
});
