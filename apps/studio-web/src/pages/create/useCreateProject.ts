import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiJson, apiVoid, API_BASE } from "../../api/client";
import type { IdeaFormData } from "../../components/creator/IdeaForm";

type ProjectSource =
  | { readonly source_type: "idea"; readonly title: string; readonly idea_brief: string }
  | { readonly source_type: "pasted_json"; readonly title: string; readonly json_script: string };

export function useCreateProject(settings: { readonly models: Record<string, string>; readonly style: string }) {
  const navigate = useNavigate();
  const lock = useRef(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = useCallback(async (source: ProjectSource, metadata?: { content_goal?: string; target_duration: number }) => {
    if (lock.current) return;
    lock.current = true;
    setSubmitting(true);
    setError(null);
    let projectId: number | null = null;
    try {
      const project = await apiJson<{ id: number }>(`${API_BASE}/projects`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(source),
      });
      projectId = project.id;
      const shared = { model_defaults: settings.models, style_preset: settings.style };
      switch (source.source_type) {
        case "idea":
          await apiVoid(`${API_BASE}/projects/${project.id}/runs`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...shared, metadata }),
          });
          break;
        case "pasted_json":
          await apiVoid(`${API_BASE}/projects/${project.id}/script/import-json`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...shared, json_script: source.json_script }),
          });
          break;
        default: {
          const exhaustive: never = source;
          return exhaustive;
        }
      }
      navigate(`/projects/${project.id}`);
    } catch (err: unknown) {
      let message = err instanceof Error ? err.message : "An unexpected error occurred";
      if (projectId !== null) {
        try {
          await apiVoid(`${API_BASE}/projects/${projectId}`, { method: "DELETE" });
        } catch (cleanupError: unknown) {
          message += cleanupError instanceof Error
            ? ` — Project cleanup failed: ${cleanupError.message}`
            : " — Project cleanup failed";
        }
      }
      setError(message);
    } finally {
      lock.current = false;
      setSubmitting(false);
    }
  }, [navigate, settings.models, settings.style]);

  const handleIdeaSubmit = useCallback((data: IdeaFormData) => create({
    title: data.title, source_type: "idea", idea_brief: data.ideaBrief,
  }, { content_goal: data.contentGoal || undefined, target_duration: data.targetDuration }), [create]);

  const handleJsonSubmit = async (form: { title: string; jsonScript: string }) => {
    const jsonScript = form.jsonScript.trim();
    if (!jsonScript) return;
    try {
      JSON.parse(jsonScript);
    } catch (err: unknown) {
      if (!(err instanceof SyntaxError)) throw err;
      setError("Invalid JSON — please check the syntax.");
      return;
    }
    await create({ title: form.title.trim() || "Untitled", source_type: "pasted_json", json_script: jsonScript });
  };
  return { submitting, error, handleIdeaSubmit, handleJsonSubmit };
}
