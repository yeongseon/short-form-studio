from __future__ import annotations

import sys
from enum import Enum

if sys.version_info >= (3, 11):  # noqa: UP036
    from enum import StrEnum
else:

    class StrEnum(str, Enum):  # noqa: UP042
        def __str__(self) -> str:
            return self.value


class MediaType(StrEnum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    AUDIO = "AUDIO"
    LOGO = "LOGO"
    GRAPHIC = "GRAPHIC"


class MediaOrigin(StrEnum):
    GENERATED = "GENERATED"
    UPLOADED = "UPLOADED"
    EXTERNAL_URL = "EXTERNAL_URL"
    STOCK = "STOCK"
    IMPORTED = "IMPORTED"
