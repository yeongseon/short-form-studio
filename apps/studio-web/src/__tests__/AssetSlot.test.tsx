import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import AssetSlot from "../components/creator/AssetSlot";
import type { AssetType, AssetStatus } from "../components/creator/AssetSlot";

describe("AssetSlot", () => {
  // ---- empty state ----

  describe("empty state", () => {
    it.each(["image", "audio", "subtitle"] as AssetType[])(
      "renders %s with empty placeholder",
      (type) => {
        render(<AssetSlot type={type} status="empty" />);
        const slot = screen.getByTestId(`asset-slot-${type}`);
        expect(slot).toBeInTheDocument();
        expect(slot).toHaveAttribute("data-status", "empty");
      },
    );

    it("does not show regenerate button when empty", () => {
      const onRegen = vi.fn();
      render(<AssetSlot type="image" status="empty" onRegenerate={onRegen} />);
      expect(screen.queryByTestId("regen-image")).not.toBeInTheDocument();
    });
  });

  // ---- loading state ----

  describe("loading state", () => {
    it.each(["image", "audio", "subtitle"] as AssetType[])(
      "renders %s with loading/shimmer indicator",
      (type) => {
        render(<AssetSlot type={type} status="loading" />);
        const slot = screen.getByTestId(`asset-slot-${type}`);
        expect(slot).toHaveAttribute("data-status", "loading");
        expect(slot).toHaveTextContent("Generating…");
      },
    );
  });

  // ---- ready state ----

  describe("ready state — image", () => {
    it("renders thumbnail when image URL provided", () => {
      render(
        <AssetSlot
          type="image"
          status="ready"
          url="/data/artifacts/img/scene-0.png"
        />,
      );
      const slot = screen.getByTestId("asset-slot-image");
      expect(slot).toHaveAttribute("data-status", "ready");
      const img = slot.querySelector("img");
      expect(img).toBeInTheDocument();
      expect(img!.src).toContain("/artifacts/img/scene-0.png");
    });

    it("shows Ready label", () => {
      render(<AssetSlot type="image" status="ready" url="/img.png" />);
      expect(screen.getByTestId("asset-slot-image")).toHaveTextContent("✓ Ready");
    });
  });

  describe("ready state — audio", () => {
    it("shows formatted duration", () => {
      render(
        <AssetSlot
          type="audio"
          status="ready"
          url="/data/artifacts/audio/sec-0.wav"
          duration={65.3}
        />,
      );
      expect(screen.getByTestId("asset-slot-audio")).toHaveTextContent("1:05");
    });

    it("shows seconds-only for short durations", () => {
      render(
        <AssetSlot type="audio" status="ready" url="/a.wav" duration={8.7} />
      );
      expect(screen.getByTestId("asset-slot-audio")).toHaveTextContent("9s");
    });

    it("renders hidden audio element for inline play", () => {
      render(
        <AssetSlot type="audio" status="ready" url="/audio.wav" duration={5} />,
      );
      expect(screen.getByTestId("audio-element-audio")).toBeInTheDocument();
    });
  });

  describe("ready state — subtitle", () => {
    it("shows cue count", () => {
      render(
        <AssetSlot
          type="subtitle"
          status="ready"
          url="/subs.srt"
          subtitleCount={12}
        />,
      );
      expect(screen.getByTestId("asset-slot-subtitle")).toHaveTextContent("12 cues");
    });

    it("shows singular cue label for 1", () => {
      render(
        <AssetSlot
          type="subtitle"
          status="ready"
          url="/subs.srt"
          subtitleCount={1}
        />,
      );
      expect(screen.getByTestId("asset-slot-subtitle")).toHaveTextContent("1 cue");
    });
  });

  // ---- regenerate button ----

  describe("regenerate button", () => {
    it("shows on hover when onRegenerate provided and status is ready", () => {
      const onRegen = vi.fn();
      render(
        <AssetSlot
          type="image"
          status="ready"
          url="/img.png"
          onRegenerate={onRegen}
        />,
      );
      const slot = screen.getByTestId("asset-slot-image");
      fireEvent.mouseEnter(slot);
      const btn = screen.getByTestId("regen-image");
      expect(btn).toBeInTheDocument();
      fireEvent.click(btn);
      expect(onRegen).toHaveBeenCalledTimes(1);
    });

    it("does not show regen button when disabled", () => {
      const onRegen = vi.fn();
      render(
        <AssetSlot
          type="audio"
          status="ready"
          url="/a.wav"
          onRegenerate={onRegen}
          disabled
        />,
      );
      expect(screen.queryByTestId("regen-audio")).not.toBeInTheDocument();
    });
  });

  // ---- preview ----

  describe("preview callback", () => {
    it("calls onPreview when image slot is clicked", () => {
      const onPreview = vi.fn();
      render(
        <AssetSlot
          type="image"
          status="ready"
          url="/img.png"
          onPreview={onPreview}
        />,
      );
      fireEvent.click(screen.getByTestId("asset-slot-image"));
      expect(onPreview).toHaveBeenCalledTimes(1);
    });

    it("calls onPreview for subtitle slot", () => {
      const onPreview = vi.fn();
      render(
        <AssetSlot
          type="subtitle"
          status="ready"
          url="/subs.srt"
          subtitleCount={5}
          onPreview={onPreview}
        />,
      );
      fireEvent.click(screen.getByTestId("asset-slot-subtitle"));
      expect(onPreview).toHaveBeenCalledTimes(1);
    });

    it("does not call onPreview when disabled", () => {
      const onPreview = vi.fn();
      render(
        <AssetSlot
          type="image"
          status="ready"
          url="/img.png"
          onPreview={onPreview}
          disabled
        />,
      );
      fireEvent.click(screen.getByTestId("asset-slot-image"));
      expect(onPreview).not.toHaveBeenCalled();
    });

    it("does not call onPreview when empty", () => {
      const onPreview = vi.fn();
      render(<AssetSlot type="image" status="empty" onPreview={onPreview} />);
      fireEvent.click(screen.getByTestId("asset-slot-image"));
      expect(onPreview).not.toHaveBeenCalled();
    });
  });
});
