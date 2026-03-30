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
  const [targetDuration, setTargetDuration] = useState(60);
  const [contentGoal, setContentGoal] = useState("");

  const canSubmit = title.trim() !== "" && ideaBrief.trim() !== "" && !submitting;

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

      <div style={{ display: "flex", gap: 16, marginBottom: 16 }}>
        <div style={{ flex: 1 }}>
          <label htmlFor="target-duration" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
            Target Duration (seconds)
          </label>
          <input
            id="target-duration"
            type="number"
            min={10}
            max={180}
            value={targetDuration}
            onChange={(e) => setTargetDuration(Number(e.target.value))}
            disabled={submitting}
            style={{ width: "100%", padding: "8px 12px", border: "1px solid #ccc", borderRadius: 4, fontSize: 14, boxSizing: "border-box" }}
          />
        </div>
        <div style={{ flex: 1 }}>
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
