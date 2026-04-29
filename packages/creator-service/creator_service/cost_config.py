"""Versioned cost estimates for provider usage tracking.

These are static estimates used by workers when recording usage events.
"""

COST_CONFIG_VERSION = "2024.1"

# Update these when provider pricing changes. Bump COST_CONFIG_VERSION on any change.
# Future: load from DB or remote config for runtime updates
COST_SCRIPT_GENERATION = 0.002
COST_VISUAL_PLAN = 0.002
COST_SCENE_IMAGE = 0.04
COST_AUDIO_GENERATION = 0.005
COST_SUBTITLE_GENERATION = 0.001
COST_RENDER_VIDEO = 0.001
COST_PARAGRAPH_AUDIO = 0.005
COST_PARAGRAPH_SUBTITLE = 0.001
