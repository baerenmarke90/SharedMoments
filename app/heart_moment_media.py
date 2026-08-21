from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError


MEDIA_DIR = (
    Path(__file__).resolve().parent
    / 'uploads'
    / 'heart-moments'
)

MAX_IMAGE_SIZE = 20 * 1024 * 1024

ALLOWED_FORMATS = {
    'JPEG': ('.jpg', 'image/jpeg'),
    'PNG': ('.png', 'image/png'),
    'WEBP': ('.webp', 'image/webp'),
    'GIF': ('.gif', 'image/gif'),
}


def _ensure_media_dir():
    MEDIA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


def heart_moment_image_path(filename):
    if not filename:
        return None

    # Never allow paths such as ../../something.
    if Path(filename).name != filename:
        raise ValueError('Invalid Heart Moment media filename')

    return MEDIA_DIR / filename


def heart_moment_image_mimetype(filename):
    suffix = Path(filename).suffix.lower()

    mime_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.webp': 'image/webp',
        '.gif': 'image/gif',
    }

    return mime_types.get(
        suffix,
        'application/octet-stream',
    )


def save_heart_moment_image(file_storage):
    if not file_storage:
        raise ValueError('No image provided')

    data = file_storage.read(
        MAX_IMAGE_SIZE + 1
    )

    if not data:
        raise ValueError('Image is empty')

    if len(data) > MAX_IMAGE_SIZE:
        raise ValueError(
            'Image is too large. Maximum size is 20 MB.'
        )

    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
            image_format = (
                image.format or ''
            ).upper()

    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
    ) as exc:
        raise ValueError(
            'Unsupported or invalid image'
        ) from exc

    if image_format not in ALLOWED_FORMATS:
        raise ValueError(
            'Unsupported image format. '
            'Allowed: JPEG, PNG, WebP and GIF.'
        )

    extension, _ = ALLOWED_FORMATS[
        image_format
    ]

    filename = (
        f'{uuid4().hex}{extension}'
    )

    _ensure_media_dir()

    path = heart_moment_image_path(
        filename
    )

    path.write_bytes(data)

    return filename


def delete_heart_moment_image(filename):
    if not filename:
        return False

    path = heart_moment_image_path(
        filename
    )

    if not path.exists():
        return False

    path.unlink()

    return True
