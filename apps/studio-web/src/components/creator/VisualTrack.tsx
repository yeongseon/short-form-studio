/**
 * VisualTrack — timeline surface showing image/video segments at their Timeline
 * positions, grouped by scene, with controlled (single-source-of-truth)
 * selection.
 *
 * Block placement is a pure function of duration + pixel width (layoutBlocks),
 * using the same time scale as the ruler/playhead so a block's left edge aligns
 * exactly with a playhead at its start time. Selection is controlled via the
 * selectedId prop + onSelect callback — the component holds no internal
 * selection state, so there is no second state model to drift.
 */

// --------------- pure layout model ---------------

export type VisualBlockKind = "image" | "video";

export interface VisualBlock {
  id: string;
  sceneId: string;
  kind: VisualBlockKind;
  source: string;
  startSeconds: number;
  durationSeconds: number;
}

export interface LaidBlock extends VisualBlock {
  left: number;
  width: number;
}

export interface SceneGroup {
  sceneId: string;
  blocks: VisualBlock[];
}

/**
 * Position blocks on a fixed pixel width using the shared time scale
 * (pxPerSecond = width / durationSeconds), so left = start * pxPerSecond and
 * width = duration * pxPerSecond — identical alignment to the ruler/playhead.
 */
export function layoutBlocks(
  blocks: VisualBlock[],
  durationSeconds: number,
  width: number,
): LaidBlock[] {
  if (durationSeconds <= 0) {
    return [];
  }
  const pxPerSecond = width / durationSeconds;
  return blocks.map((b) => ({
    ...b,
    left: b.startSeconds * pxPerSecond,
    width: b.durationSeconds * pxPerSecond,
  }));
}

/** Group blocks by sceneId, preserving first-seen (timeline) order. */
export function groupByScene(blocks: VisualBlock[]): SceneGroup[] {
  const order: string[] = [];
  const byScene = new Map<string, VisualBlock[]>();
  for (const block of blocks) {
    if (!byScene.has(block.sceneId)) {
      byScene.set(block.sceneId, []);
      order.push(block.sceneId);
    }
    byScene.get(block.sceneId)!.push(block);
  }
  return order.map((sceneId) => ({ sceneId, blocks: byScene.get(sceneId)! }));
}

// --------------- component ---------------

export interface VisualTrackProps {
  blocks: VisualBlock[];
  durationSeconds: number;
  width: number;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
}

export default function VisualTrack({
  blocks,
  durationSeconds,
  width,
  selectedId = null,
  onSelect,
}: VisualTrackProps) {
  const laid = layoutBlocks(blocks, durationSeconds, width);
  const laidById = new Map(laid.map((b) => [b.id, b]));
  const groups = groupByScene(blocks);

  return (
    <div
      data-testid="visual-track"
      style={{ position: "relative", width, minHeight: 56 }}
    >
      {groups.map((group) => {
        const groupBlocks = group.blocks
          .map((b) => laidById.get(b.id))
          .filter((b): b is LaidBlock => b !== undefined);
        const left = groupBlocks.length > 0 ? Math.min(...groupBlocks.map((b) => b.left)) : 0;
        const right =
          groupBlocks.length > 0
            ? Math.max(...groupBlocks.map((b) => b.left + b.width))
            : 0;
        return (
          <div
            key={group.sceneId}
            data-testid={`scene-group-${group.sceneId}`}
            style={{
              position: "absolute",
              left,
              width: right - left,
              top: 0,
              height: "100%",
              border: "1px dashed #3a3a3a",
              borderRadius: 4,
              pointerEvents: "none",
            }}
          />
        );
      })}
      {laid.map((block) => {
        const selected = selectedId === block.id;
        return (
          <div
            key={block.id}
            data-testid={`visual-block-${block.id}`}
            data-block-id={block.id}
            data-kind={block.kind}
            data-selected={selected ? "true" : "false"}
            role="button"
            tabIndex={0}
            aria-pressed={selected}
            onClick={() => onSelect?.(block.id)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect?.(block.id);
              }
            }}
            style={{
              position: "absolute",
              left: block.left,
              width: block.width,
              top: 4,
              bottom: 4,
              height: "calc(100% - 8px)",
              background: block.kind === "video" ? "#2b3a55" : "#3a2b55",
              border: selected ? "2px solid #e5484d" : "1px solid #555",
              borderRadius: 4,
              overflow: "hidden",
              cursor: "pointer",
              boxSizing: "border-box",
            }}
          >
            <div
              data-visual-block-label={block.id}
              style={{ fontSize: 10, color: "#cfcfcf", padding: 2 }}
            >
              {block.kind === "video" ? "🎬" : "🖼️"} {block.source}
            </div>
          </div>
        );
      })}
    </div>
  );
}
