/**
 * AssetDropZone — drag-and-drop (and keyboard file-input) asset upload that
 * places or replaces media via an EditorCommand rather than mutating the
 * Timeline directly.
 *
 * A drop or file-input change is classified by MIME (uploadKindForFile);
 * unsupported types are rejected locally with an error state and no upload. A
 * supported file is uploaded through the validated upload API with idle →
 * uploading → ready/error states and a cancel affordance. On success the zone
 * emits a placeAsset (or replaceAsset, when targetSegmentId is set) command via
 * onCommand — accepted placement is expressed as a command so it stays routed
 * through the validated EditorCommand boundary and remains undoable. Cancelling
 * an in-flight upload discards its result and emits no command.
 */

import { useRef, useState } from "react";

import { uploadAsset, uploadKindForFile } from "../../api/assets";

export type AssetPlacementCommand =
  | { type: "placeAsset"; sceneId: string; assetId: number }
  | { type: "replaceAsset"; sceneId: string; segmentId: string; assetId: number };

type ZoneStatus = "idle" | "uploading" | "ready" | "error";

export interface AssetDropZoneProps {
  workspaceId: number;
  sceneId: string;
  targetSegmentId?: string;
  onCommand?: (command: AssetPlacementCommand) => void;
}

export default function AssetDropZone({
  workspaceId,
  sceneId,
  targetSegmentId,
  onCommand,
}: AssetDropZoneProps) {
  const [status, setStatus] = useState<ZoneStatus>("idle");
  const [message, setMessage] = useState<string>("");
  const cancelledRef = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = (file: File): void => {
    const kind = uploadKindForFile(file);
    if (kind === null) {
      setStatus("error");
      setMessage(`Unsupported file type: ${file.type || "unknown"}`);
      return;
    }
    cancelledRef.current = false;
    setStatus("uploading");
    setMessage(`Uploading ${file.name}…`);
    uploadAsset(workspaceId, kind, file)
      .then((asset) => {
        if (cancelledRef.current) {
          return;
        }
        setStatus("ready");
        setMessage(`Placed ${file.name}`);
        onCommand?.(
          targetSegmentId === undefined
            ? { type: "placeAsset", sceneId, assetId: asset.id }
            : {
                type: "replaceAsset",
                sceneId,
                segmentId: targetSegmentId,
                assetId: asset.id,
              },
        );
      })
      .catch((err: unknown) => {
        if (cancelledRef.current) {
          return;
        }
        setStatus("error");
        setMessage(err instanceof Error ? err.message : "Upload failed");
      });
  };

  const cancel = (): void => {
    cancelledRef.current = true;
    setStatus("idle");
    setMessage("");
  };

  return (
    <div
      data-testid="asset-drop-zone"
      data-status={status}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        const file = e.dataTransfer.files[0];
        if (file) {
          handleFile(file);
        }
      }}
      style={{
        border: status === "error" ? "2px dashed #e5484d" : "2px dashed #555",
        borderRadius: 8,
        padding: 16,
        textAlign: "center",
        color: "#c0c0c0",
        background: "#1f1f1f",
      }}
    >
      <p style={{ margin: "0 0 8px" }}>
        {status === "idle"
          ? "Drop an image, video, or audio file here"
          : message}
      </p>

      <label style={{ display: "inline-block", cursor: "pointer" }}>
        <span data-testid="asset-upload-button">Choose file</span>
        <input
          ref={inputRef}
          data-testid="asset-file-input"
          type="file"
          accept="image/*,video/*,audio/*"
          style={{ display: "block", marginTop: 4 }}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) {
              handleFile(file);
            }
          }}
        />
      </label>

      {status === "uploading" && (
        <button type="button" data-testid="asset-cancel-upload" onClick={cancel}>
          Cancel
        </button>
      )}
    </div>
  );
}
