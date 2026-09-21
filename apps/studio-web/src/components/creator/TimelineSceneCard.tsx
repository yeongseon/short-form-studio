/**
 * TimelineSceneCard — Scene-View-primary card for a Timeline-backed mixed-media
 * scene.
 *
 * Adapts the Scene Card idea to Timeline drafts: it summarizes script, assets
 * (image/video counts), total duration, and transitions at a glance
 * (summarizeScene, a pure derivation). Scene View stays primary — the inline
 * editor is hidden until Edit is pressed, and Edit is disabled while review is
 * locked so existing review gates are preserved. Selection is controlled
 * (selected + onSelect) so it can be shared across sibling track surfaces, and
 * editor actions are routed through onCommand rather than mutating the scene
 * directly (validated EditorCommand boundary).
 */

import { useState } from "react";

// --------------- pure scene model ---------------

export type SceneSegmentKind = "image" | "video";

export interface TimelineSceneSegment {
  id: string;
  kind: SceneSegmentKind;
  assetLabel: string;
  durationSeconds: number;
  transition: string | null;
}

export interface TimelineScene {
  sceneId: string;
  script: string;
  segments: TimelineSceneSegment[];
}

export interface SceneSummary {
  totalDuration: number;
  imageCount: number;
  videoCount: number;
  transitions: string[];
}

/** Derive at-a-glance summaries (duration, asset counts, transitions) for a scene. */
export function summarizeScene(scene: TimelineScene): SceneSummary {
  let totalDuration = 0;
  let imageCount = 0;
  let videoCount = 0;
  const transitions: string[] = [];
  for (const seg of scene.segments) {
    totalDuration += seg.durationSeconds;
    if (seg.kind === "image") {
      imageCount += 1;
    } else {
      videoCount += 1;
    }
    if (seg.transition !== null && !transitions.includes(seg.transition)) {
      transitions.push(seg.transition);
    }
  }
  return { totalDuration, imageCount, videoCount, transitions };
}

export type SceneCommand = { type: "retime"; sceneId: string };

// --------------- component ---------------

export interface TimelineSceneCardProps {
  scene: TimelineScene;
  selected?: boolean;
  reviewLocked?: boolean;
  onSelect?: (sceneId: string) => void;
  onCommand?: (command: SceneCommand) => void;
}

export default function TimelineSceneCard({
  scene,
  selected = false,
  reviewLocked = false,
  onSelect,
  onCommand,
}: TimelineSceneCardProps) {
  const [editing, setEditing] = useState(false);
  const summary = summarizeScene(scene);

  return (
    <div
      data-testid={`timeline-scene-card-${scene.sceneId}`}
      data-selected={selected ? "true" : "false"}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onClick={() => onSelect?.(scene.sceneId)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect?.(scene.sceneId);
        }
      }}
      style={{
        border: selected ? "2px solid #e5484d" : "1px solid #444",
        borderRadius: 6,
        padding: 10,
        background: "#1f1f1f",
        cursor: "pointer",
      }}
    >
      <p data-testid="scene-script" style={{ margin: "0 0 8px", color: "#e0e0e0" }}>
        {scene.script}
      </p>

      <div style={{ display: "flex", gap: 12, fontSize: 11, color: "#a0a0a0" }}>
        <span data-testid="scene-duration-summary">{summary.totalDuration}s</span>
        <span data-testid="scene-asset-summary">
          {summary.imageCount} image{summary.imageCount === 1 ? "" : "s"},{" "}
          {summary.videoCount} video{summary.videoCount === 1 ? "" : "s"}
        </span>
        <span data-testid="scene-transition-summary">
          {summary.transitions.length > 0 ? summary.transitions.join(", ") : "no transitions"}
        </span>
      </div>

      <div style={{ marginTop: 8 }}>
        <button
          type="button"
          data-testid="scene-edit-button"
          disabled={reviewLocked}
          onClick={(e) => {
            e.stopPropagation();
            if (!reviewLocked) {
              setEditing((v) => !v);
            }
          }}
        >
          {editing ? "Close" : "Edit"}
        </button>
      </div>

      {editing && !reviewLocked && (
        <div data-testid="scene-editor" style={{ marginTop: 8 }}>
          <button
            type="button"
            data-testid="scene-command-retime"
            onClick={(e) => {
              e.stopPropagation();
              onCommand?.({ type: "retime", sceneId: scene.sceneId });
            }}
          >
            Re-time scene
          </button>
        </div>
      )}
    </div>
  );
}
