from io import BytesIO

from creator_service import sample_project
from PIL import Image


def test_sample_image_bytes_are_reproducible_decodable_and_distinct() -> None:
    # Given two scene colors.
    navy, cyan = (32, 48, 80), (24, 192, 208)
    # When generating sample PNG bytes locally.
    images = [sample_project.sample_image_bytes(color) for color in (navy, cyan, navy)]
    # Then content is deterministic, distinct and decodable at a tiny vertical size.
    assert images[0] == images[2] and images[0] != images[1]
    for data, color in zip(images, (navy, cyan, navy), strict=True):
        assert len(data) < 1024
        with BytesIO(data) as buffer, Image.open(buffer) as image:
            assert image.format == "PNG"
            assert image.size == (90, 160)
            assert image.getpixel((45, 80)) == color
