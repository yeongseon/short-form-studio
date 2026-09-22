import { useState, useCallback, type FormEvent } from "react";

export interface IdeaFormData {
  title: string;
  ideaBrief: string;
  targetDuration: number;
  contentGoal: string;
}

interface IdeaFormProps {
  onSubmit: (data: IdeaFormData) => void;
  submitting?: boolean;
  error?: string | null;
}

export default function IdeaForm({ onSubmit, submitting = false, error = null }: IdeaFormProps) {
  const [title, setTitle] = useState("");
  const [ideaBrief, setIdeaBrief] = useState("");
  const [durationSelection, setDurationSelection] = useState("60");
  const [customDuration, setCustomDuration] = useState("60");
  const [contentGoal, setContentGoal] = useState("");

  const targetDuration = Number(durationSelection === "custom" ? customDuration : durationSelection);
  const durationValid = Number.isFinite(targetDuration) && targetDuration > 0;
  const canSubmit = title.trim() !== "" && ideaBrief.trim() !== "" && durationValid && !submitting;

  const handleSubmit = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      if (!canSubmit) return;
      onSubmit({ title: title.trim(), ideaBrief: ideaBrief.trim(), targetDuration, contentGoal: contentGoal.trim() });
    },
    [canSubmit, onSubmit, title, ideaBrief, targetDuration, contentGoal],
  );

  return (
    <form data-testid="idea-form" onSubmit={handleSubmit}>
      {error && (
        <div
          data-testid="idea-form-error"
          role="alert"
          style={{
            padding: "8px 12px",
            marginBottom: 16,
            background: "#fef2f2",
            border: "1px solid #fca5a5",
            borderRadius: 4,
            color: "#b91c1c",
            fontSize: 13,
          }}
        >
          {error}
        </div>
      )}

      <div style={{ marginBottom: 16 }}>
        <label htmlFor="idea-title" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
          Title <span style={{ color: "#c00" }}>*</span>
        </label>
        <input
          id="idea-title"
          type="text"
          required
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          disabled={submitting}
          placeholder="Project title"
          style={{ width: "100%", padding: "8px 12px", border: "1px solid #ccc", borderRadius: 4, fontSize: 14, boxSizing: "border-box" }}
        />
      </div>

      <div style={{ marginBottom: 16 }}>
        <label htmlFor="idea-brief" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
          Idea Brief <span style={{ color: "#c00" }}>*</span>
        </label>
        <textarea
          id="idea-brief"
          required
          value={ideaBrief}
          onChange={(e) => setIdeaBrief(e.target.value)}
          disabled={submitting}
          placeholder="Describe your video idea..."
          rows={4}
          style={{ width: "100%", padding: "8px 12px", border: "1px solid #ccc", borderRadius: 4, fontSize: 14, resize: "vertical", boxSizing: "border-box" }}
        />
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 16, marginBottom: 16 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <label htmlFor="target-duration" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
            Target Duration (seconds)
          </label>
          <select
            id="target-duration"
            value={durationSelection}
            onChange={(e) => setDurationSelection(e.target.value)}
            disabled={submitting}
            aria-describedby="duration-guidance"
            style={{ width: "100%", padding: "8px 12px", border: "1px solid #ccc", borderRadius: 4, fontSize: 14, boxSizing: "border-box" }}
          >
            {[15, 30, 45, 60, 90].map((seconds) => (
              <option key={seconds} value={seconds}>{seconds} seconds</option>
            ))}
            <option value="custom">Custom</option>
          </select>
          {durationSelection === "custom" && (
            <div style={{ marginTop: 12 }}>
              <label htmlFor="custom-duration" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
                Custom duration (seconds)
              </label>
              <input
                id="custom-duration"
                type="number"
                required
                step="any"
                value={customDuration}
                onChange={(e) => setCustomDuration(e.target.value)}
                disabled={submitting}
                aria-invalid={!durationValid}
                aria-describedby={durationValid ? "duration-guidance" : "duration-error duration-guidance"}
                style={{ width: "100%", padding: "8px 12px", border: "1px solid #ccc", borderRadius: 4, fontSize: 14, boxSizing: "border-box" }}
              />
              {!durationValid && (
                <p id="duration-error" role="alert" style={{ color: "#b91c1c", margin: "8px 0", fontSize: 13 }}>
                  Enter a positive, finite duration in seconds.
                </p>
              )}
            </div>
          )}
          <p id="duration-guidance" style={{ margin: "8px 0 0", color: "#666", fontSize: 13 }}>
            Aim for approximately 3 minutes or less for a short. This is guidance, not a duration limit.
          </p>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <label htmlFor="content-goal" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
            Content Goal
          </label>
          <input
            id="content-goal"
            type="text"
            value={contentGoal}
            onChange={(e) => setContentGoal(e.target.value)}
            disabled={submitting}
            placeholder="e.g., educational, entertainment"
            style={{ width: "100%", padding: "8px 12px", border: "1px solid #ccc", borderRadius: 4, fontSize: 14, boxSizing: "border-box" }}
          />
        </div>
      </div>
    </form>
  );
}
