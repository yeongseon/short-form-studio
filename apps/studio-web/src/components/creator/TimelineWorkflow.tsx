const STEPS = [
  { stage: "TIMELINE_REVIEW", label: "Timeline review" },
  { stage: "RENDER_GENERATING", label: "Render" },
  { stage: "FINAL_REVIEW", label: "Final review" },
  { stage: "PUBLISHED", label: "Published" },
] as const;

export function TimelineWorkflow({ currentStage }: { readonly currentStage: string }) {
  return <ol aria-label="Timeline workflow" style={{ display: "flex", flexWrap: "wrap", gap: 24, paddingLeft: 20, fontSize: 13 }}>
    {STEPS.map((step) => <li key={step.stage}>
      <span aria-current={currentStage === step.stage ? "step" : undefined}
        style={{ fontWeight: currentStage === step.stage ? 600 : 400 }}>{step.label}</span>
    </li>)}
  </ol>;
}
