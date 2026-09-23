from io import BytesIO

from PIL import Image


def sample_image_bytes(color: tuple[int, int, int]) -> bytes:
    with BytesIO() as buffer, Image.new("RGB", (90, 160), color) as image:
        image.save(buffer, format="PNG")
        return buffer.getvalue()
