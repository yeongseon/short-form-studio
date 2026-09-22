from creator_domain.task_dispatch import TaskName, TaskSubmission
from pydantic import JsonValue

from creator_service.dispatch_runtime import DispatchRuntime


class DispatchCalls(DispatchRuntime):
    def _dispatch_task(
        self, *, task_attr: TaskName, run_id: int,
        args: list[JsonValue] | None = None, kwargs: dict[str, JsonValue] | None = None,
        task_id: str | None = None,
    ) -> str:
        return self.dispatcher.dispatch(TaskSubmission(
            task_name=task_attr, run_id=run_id, args=tuple(args or ()),
            kwargs=kwargs or {}, task_id=task_id,
        ))

    def dispatch_generate_script(
        self, run_id: int, idea_brief: str, model_key: str, instructions: str | None,
        niche: str | None = None, language: str = "ko", task_id: str | None = None,
    ) -> str:
        return self._dispatch_task(
            task_attr="generate_script", run_id=run_id,
            kwargs={"run_id": run_id, "idea_brief": idea_brief, "model_key": model_key,
                    "instructions": instructions, "niche": niche, "language": language},
            task_id=task_id,
        )

    def dispatch_generate_visual_plan(
        self, run_id: int, model_key: str, style_preset: str | None,
        niche: str | None = None, task_id: str | None = None,
    ) -> str:
        return self._dispatch_task(
            task_attr="generate_visual_plan", run_id=run_id,
            kwargs={"run_id": run_id, "model_key": model_key, "style_preset": style_preset, "niche": niche},
            task_id=task_id,
        )

    def dispatch_generate_audio(
        self, run_id: int, tts_model: str, voice: str, task_id: str | None = None,
    ) -> str:
        return self._dispatch_task(
            task_attr="generate_audio", run_id=run_id, args=[run_id],
            kwargs={"tts_model": tts_model, "voice": voice}, task_id=task_id,
        )

    def dispatch_generate_subtitles(
        self, run_id: int, subtitle_model: str, subtitle_format: str, task_id: str | None = None,
    ) -> str:
        return self._dispatch_task(
            task_attr="generate_subtitles", run_id=run_id, args=[run_id],
            kwargs={"subtitle_model": subtitle_model, "subtitle_format": subtitle_format}, task_id=task_id,
        )

    def dispatch_render_video(self, run_id: int, render_profile: str, task_id: str | None = None) -> str:
        return self._dispatch_task(
            task_attr="render_video", run_id=run_id, args=[run_id],
            kwargs={"render_profile": render_profile}, task_id=task_id,
        )

    def dispatch_generate_scene_image(
        self, run_id: int, model_key: str, scene_id: str | None, prompt_override: str | None,
        is_active: bool, image_params: dict[str, JsonValue] | None = None, task_id: str | None = None,
    ) -> str:
        return self._dispatch_task(
            task_attr="generate_scene_image", run_id=run_id, args=[run_id],
            kwargs={"scene_id": scene_id, "model_key": model_key, "prompt_override": prompt_override,
                    "is_active": is_active, "image_params": image_params}, task_id=task_id,
        )

    def dispatch_paragraph_audio(
        self, run_id: int, section_id: str, tts_model: str, voice: str, task_id: str | None = None,
    ) -> str:
        return self._dispatch_task(
            task_attr="generate_paragraph_audio", run_id=run_id, args=[run_id],
            kwargs={"section_id": section_id, "tts_model": tts_model, "voice": voice}, task_id=task_id,
        )

    def dispatch_paragraph_subtitles(
        self, run_id: int, section_id: str, subtitle_model: str, subtitle_format: str,
        task_id: str | None = None,
    ) -> str:
        return self._dispatch_task(
            task_attr="generate_paragraph_subtitles", run_id=run_id, args=[run_id],
            kwargs={"section_id": section_id, "subtitle_model": subtitle_model,
                    "subtitle_format": subtitle_format}, task_id=task_id,
        )
