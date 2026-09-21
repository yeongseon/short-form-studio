from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class CreativeProfile(BaseModel):
    """Creative look and feel: 'how it feels', not 'what to make'.

    Separate from ContentRecipe (structure/pacing) and OutputSpec (geometry).
    Selectable via named presets; unknown ids raise rather than silently
    falling back to a niche default.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    transition: str = Field(max_length=50)
    color_grade: str = Field(max_length=50)
    motion: str = Field(max_length=50)
    subtitle_emphasis: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> CreativeProfile:
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()

    # -- named presets ------------------------------------------------------

    @classmethod
    def default(cls) -> CreativeProfile:
        return cls(
            id="default",
            transition="cut",
            color_grade="neutral",
            motion="none",
            subtitle_emphasis=False,
        )

    @classmethod
    def cinematic(cls) -> CreativeProfile:
        return cls(
            id="cinematic",
            transition="fade",
            color_grade="warm",
            motion="ken_burns",
            subtitle_emphasis=True,
        )

    @classmethod
    def minimal(cls) -> CreativeProfile:
        return cls(
            id="minimal",
            transition="cut",
            color_grade="neutral",
            motion="none",
            subtitle_emphasis=False,
        )

    @classmethod
    def energetic(cls) -> CreativeProfile:
        return cls(
            id="energetic",
            transition="whip",
            color_grade="vivid",
            motion="fast_zoom",
            subtitle_emphasis=True,
        )

    @classmethod
    def story(cls) -> CreativeProfile:
        return cls(
            id="story",
            transition="ken_burns_lite",
            color_grade="moody",
            motion="ken_burns",
            subtitle_emphasis=True,
        )

    @classmethod
    def product(cls) -> CreativeProfile:
        return cls(
            id="product",
            transition="fade",
            color_grade="clean",
            motion="slow_pan",
            subtitle_emphasis=True,
        )

    @classmethod
    def preset_ids(cls) -> list[str]:
        return sorted(_PRESETS)

    @classmethod
    def preset(cls, profile_id: str) -> CreativeProfile:
        """Resolve a named creative profile; unknown ids raise (no fallback)."""
        factory = _PRESETS.get(profile_id)
        if factory is None:
            raise ValueError(f"Unknown creative profile: {profile_id!r}")
        return factory()


_PRESETS = {
    "default": CreativeProfile.default,
    "cinematic": CreativeProfile.cinematic,
    "minimal": CreativeProfile.minimal,
    "energetic": CreativeProfile.energetic,
    "story": CreativeProfile.story,
    "product": CreativeProfile.product,
}
