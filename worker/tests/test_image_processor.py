from io import BytesIO
import unittest

from PIL import Image

from processors.image_processor import InvalidImageError, create_thumbnails


class ImageProcessorTests(unittest.TestCase):
    @staticmethod
    def make_image(size=(1200, 900), image_format="JPEG", mode="RGB"):
        stream = BytesIO()
        color = (120, 80, 200, 100) if mode == "RGBA" else (120, 80, 200)
        Image.new(mode, size, color).save(stream, format=image_format)
        return stream.getvalue()

    def test_creates_two_webp_thumbnails_within_limits(self):
        small, large = create_thumbnails(
            self.make_image(), expected_mime_type="image/jpeg"
        )
        self.assertEqual(small.name, "small")
        self.assertEqual(large.name, "large")
        self.assertLessEqual(small.width, 200)
        self.assertLessEqual(small.height, 200)
        self.assertLessEqual(large.width, 800)
        self.assertLessEqual(large.height, 800)
        self.assertEqual(small.content_type, "image/webp")
        self.assertTrue(small.data.startswith(b"RIFF"))
        self.assertTrue(large.data.startswith(b"RIFF"))

    def test_png_transparency_is_preserved(self):
        small, _ = create_thumbnails(
            self.make_image((300, 200), "PNG", "RGBA"),
            expected_mime_type="image/png",
        )
        with Image.open(BytesIO(small.data)) as decoded:
            self.assertEqual(decoded.mode, "RGBA")

    def test_accepts_webp(self):
        small, large = create_thumbnails(
            self.make_image((300, 200), "WEBP"), expected_mime_type="image/webp"
        )
        self.assertGreater(len(small.data), 0)
        self.assertGreater(len(large.data), 0)

    def test_rejects_mime_content_mismatch(self):
        with self.assertRaises(InvalidImageError):
            create_thumbnails(
                self.make_image(image_format="JPEG"),
                expected_mime_type="image/png",
            )

    def test_rejects_corrupt_image(self):
        with self.assertRaises(InvalidImageError):
            create_thumbnails(b"not an image")

    def test_rejects_empty_image(self):
        with self.assertRaises(InvalidImageError):
            create_thumbnails(b"")

    def test_rejects_image_over_pixel_limit(self):
        with self.assertRaises(InvalidImageError):
            create_thumbnails(
                self.make_image((1100, 1000)),
                expected_mime_type="image/jpeg",
                max_pixels=1_000_000,
            )

    def test_applies_exif_orientation(self):
        stream = BytesIO()
        image = Image.new("RGB", (80, 160), (20, 100, 200))
        exif = Image.Exif()
        exif[274] = 6  # Rotate 90 degrees clockwise when displayed.
        image.save(stream, format="JPEG", exif=exif)
        small, _ = create_thumbnails(
            stream.getvalue(), expected_mime_type="image/jpeg"
        )
        self.assertEqual((small.width, small.height), (160, 80))

    def test_does_not_upscale_small_image(self):
        small, large = create_thumbnails(
            self.make_image((40, 30)), expected_mime_type="image/jpeg"
        )
        self.assertEqual((small.width, small.height), (40, 30))
        self.assertEqual((large.width, large.height), (40, 30))


if __name__ == "__main__":
    unittest.main()
