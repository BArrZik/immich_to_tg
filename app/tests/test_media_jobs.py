import pytest
from cron_jobs.post_media_to_channel_job import MediaJobs


@pytest.fixture
def media_jobs():
    return MediaJobs()


class TestDetermineMediaType:
    """Tests for _determine_media_type method"""

    @pytest.mark.parametrize(
        "mime_type,path,asset_type,expected",
        [
            # By MIME type (highest priority)
            ("image/gif", "/photo.jpg", "IMAGE", "gif"),
            ("video/mp4", "/file.mp4", "VIDEO", "video"),
            ("video/quicktime", "/file.mov", "VIDEO", "video"),
            ("video/webm", "/file.webm", "VIDEO", "video"),
            ("image/jpeg", "/photo.jpg", "IMAGE", "image"),
            ("image/png", "/photo.png", "IMAGE", "image"),
            ("image/heic", "/photo.heic", "IMAGE", "image"),
            ("IMAGE/JPEG", "/photo.jpg", "IMAGE", "image"),  # case insensitive
            # By extension (when no MIME)
            ("", "/animation.gif", "IMAGE", "gif"),
            ("", "/video.mp4", "VIDEO", "video"),
            ("", "/video.mov", "VIDEO", "video"),
            ("", "/video.webm", "VIDEO", "video"),
            ("", "/photo.jpg", "IMAGE", "image"),
            ("", "/photo.jpeg", "IMAGE", "image"),
            ("", "/photo.png", "IMAGE", "image"),
            ("", "/photo.heic", "IMAGE", "image"),
            ("", "/photo.heif", "IMAGE", "image"),
            ("", "/PHOTO.JPG", "IMAGE", "image"),  # case insensitive
            # Fallback to asset type
            ("", "/file.unknown", "IMAGE", "image"),
            ("", "/file.unknown", "VIDEO", "video"),
        ],
        ids=[
            "gif_mime",
            "video_mp4_mime",
            "video_quicktime_mime",
            "video_webm_mime",
            "image_jpeg_mime",
            "image_png_mime",
            "image_heic_mime",
            "image_mime_case_insensitive",
            "gif_extension",
            "video_mp4_ext",
            "video_mov_ext",
            "video_webm_ext",
            "image_jpg_ext",
            "image_jpeg_ext",
            "image_png_ext",
            "image_heic_ext",
            "image_heif_ext",
            "image_ext_case_insensitive",
            "fallback_image",
            "fallback_video",
        ],
    )
    def test_determine_media_type(self, media_jobs, mime_type, path, asset_type, expected):
        asset = {"originalMimeType": mime_type, "originalPath": path, "type": asset_type}
        assert media_jobs._determine_media_type(asset) == expected

    def test_uses_original_url_when_path_missing(self, media_jobs):
        asset = {"originalMimeType": "", "originalUrl": "/photo.jpg", "type": "IMAGE"}
        assert media_jobs._determine_media_type(asset) == "image"


class TestGetFileSize:
    """Tests for _get_file_size method"""

    @pytest.mark.parametrize(
        "exif_info,expected",
        [
            ({"fileSize": 1024}, 1024),
            ({"size": 2048}, 2048),
            ({"fileSizeInByte": 4096}, 4096),
            ({"originalFileSize": 8192}, 8192),
            # Priority order: fileSize > size > fileSizeInByte
            ({"fileSize": 100, "size": 200, "fileSizeInByte": 300}, 100),
            ({"size": 200, "fileSizeInByte": 300}, 200),
            # No size fields
            ({}, None),
            ({"make": "Canon", "model": "EOS R5"}, None),
        ],
        ids=[
            "fileSize_field",
            "size_field",
            "fileSizeInByte_field",
            "originalFileSize_field",
            "priority_fileSize_first",
            "priority_size_second",
            "empty_exif",
            "no_size_fields",
        ],
    )
    def test_get_file_size(self, media_jobs, exif_info, expected):
        asset = {"exifInfo": exif_info}
        assert media_jobs._get_file_size(asset) == expected

    @pytest.mark.parametrize(
        "asset",
        [
            {},
            {"other_field": "value"},
        ],
        ids=["empty_asset", "no_exif_info"],
    )
    def test_get_file_size_no_exif(self, media_jobs, asset):
        assert media_jobs._get_file_size(asset) is None


class TestGetFileFormat:
    """Tests for _get_file_format method"""

    @pytest.mark.parametrize(
        "asset,expected",
        [
            # From MIME type (priority)
            ({"originalMimeType": "image/jpeg", "originalPath": "/photo.jpg"}, "image/jpeg"),
            ({"originalMimeType": "video/mp4", "originalPath": "/video.mp4"}, "video/mp4"),
            ({"originalMimeType": "IMAGE/HEIC", "originalPath": "/photo.heic"}, "image/heic"),
            # From extension when no MIME
            ({"originalMimeType": "", "originalPath": "/photo.jpg"}, "jpg"),
            ({"originalMimeType": "", "originalPath": "/photo.heic"}, "heic"),
            ({"originalMimeType": "", "originalPath": "/video.mp4"}, "mp4"),
            # From originalUrl
            ({"originalMimeType": "", "originalUrl": "/photo.png"}, "png"),
            # No info
            ({"originalMimeType": ""}, None),
        ],
        ids=[
            "mime_jpeg",
            "mime_video",
            "mime_heic_uppercase",
            "ext_jpg",
            "ext_heic",
            "ext_mp4",
            "url_png",
            "no_info",
        ],
    )
    def test_get_file_format(self, media_jobs, asset, expected):
        assert media_jobs._get_file_format(asset) == expected


class TestGetLocationInfo:
    """Tests for _get_location_info method"""

    @pytest.mark.parametrize(
        "exif_info,expected_name,expected_lat,expected_lon",
        [
            # Full location
            (
                {"city": "Moscow", "state": "Moscow Oblast", "country": "Russia", "latitude": 55.7558, "longitude": 37.6173},
                "Moscow, Moscow Oblast, Russia",
                55.7558,
                37.6173,
            ),
            # Partial location names
            ({"city": "Paris"}, "Paris", None, None),
            ({"country": "Japan"}, "Japan", None, None),
            ({"city": "Berlin", "country": "Germany"}, "Berlin, Germany", None, None),
            ({"state": "California", "country": "USA"}, "California, USA", None, None),
            # Coords only
            ({"latitude": 35.6762, "longitude": 139.6503}, None, 35.6762, 139.6503),
            # Partial coords ignored
            ({"latitude": 35.6762}, None, None, None),
            ({"longitude": 139.6503}, None, None, None),
            # Empty/None
            ({}, None, None, None),
        ],
        ids=[
            "full_location",
            "city_only",
            "country_only",
            "city_country",
            "state_country",
            "coords_only",
            "partial_coords_lat",
            "partial_coords_lon",
            "empty",
        ],
    )
    def test_get_location_info(self, media_jobs, exif_info, expected_name, expected_lat, expected_lon):
        result = media_jobs._get_location_info(exif_info)
        assert result["location_name"] == expected_name
        assert result["latitude"] == expected_lat
        assert result["longitude"] == expected_lon

    def test_get_location_info_none_input(self, media_jobs):
        result = media_jobs._get_location_info(None)
        assert result == {"location_name": None, "latitude": None, "longitude": None}


class TestProcessAssets:
    """Tests for _process_assets method"""

    def test_process_empty_assets(self, media_jobs):
        assert media_jobs._process_assets([]) == []

    @pytest.mark.parametrize(
        "asset,expected_type,expected_format",
        [
            (
                {"id": "1", "originalPath": "/p.jpg", "originalMimeType": "image/jpeg", "type": "IMAGE", "exifInfo": {}},
                "image",
                "image/jpeg",
            ),
            (
                {"id": "2", "originalPath": "/v.mp4", "originalMimeType": "video/mp4", "type": "VIDEO", "exifInfo": {}},
                "video",
                "video/mp4",
            ),
            (
                {"id": "3", "originalPath": "/a.gif", "originalMimeType": "image/gif", "type": "IMAGE", "exifInfo": {}},
                "gif",
                "image/gif",
            ),
        ],
        ids=["image", "video", "gif"],
    )
    def test_process_asset_media_types(self, media_jobs, asset, expected_type, expected_format):
        result = media_jobs._process_assets([asset])
        assert len(result) == 1
        assert result[0]["media_type"] == expected_type
        assert result[0]["file_format"] == expected_format

    def test_process_asset_full_exif(self, media_jobs):
        asset = {
            "id": "uuid-123",
            "originalPath": "/photos/photo.jpg",
            "originalMimeType": "image/jpeg",
            "type": "IMAGE",
            "exifInfo": {
                "fileSizeInByte": 1024000,
                "exifImageWidth": 4000,
                "exifImageHeight": 3000,
                "orientation": "6",
                "make": "Canon",
                "model": "EOS R5",
                "lensModel": "RF 24-70mm",
                "iso": 100,
                "fNumber": 2.8,
                "exposureTime": "1/250",
                "focalLength": 50,
                "dateTimeOriginal": "2024-01-15T10:30:00",
                "city": "Tokyo",
                "country": "Japan",
                "latitude": 35.6762,
                "longitude": 139.6503,
            },
        }
        result = media_jobs._process_assets([asset])[0]

        assert result["media_uuid"] == "uuid-123"
        assert result["media_url"] == "/photos/photo.jpg"
        assert result["file_size"] == 1024000
        assert result["processed"] is False
        assert result["error"] is None
        assert result["info"]["width"] == 4000
        assert result["info"]["height"] == 3000
        assert result["info"]["orientation"] == 6
        assert result["info"]["camera"] == "Canon EOS R5"
        assert result["info"]["lens"] == "RF 24-70mm"
        assert result["info"]["iso"] == 100
        assert result["info"]["aperture"] == 2.8
        assert result["info"]["shutter"] == "1/250"
        assert result["info"]["focal"] == 50
        assert result["info"]["date"] == "2024-01-15T10:30:00"
        assert result["info"]["location"]["location_name"] == "Tokyo, Japan"
        assert result["info"]["location"]["latitude"] == 35.6762

    @pytest.mark.parametrize(
        "exif_info,expected_orientation",
        [
            ({"orientation": "1"}, 1),
            ({"orientation": "6"}, 6),
            ({"orientation": "8"}, 8),
            ({"orientation": 1}, 1),
            ({"orientation": 6}, 6),
            ({}, 1),  # default when missing
        ],
        ids=["str_1", "str_6", "str_8", "int_1", "int_6", "default_when_missing"],
    )
    def test_process_asset_orientation(self, media_jobs, exif_info, expected_orientation):
        asset = {
            "id": "test",
            "originalPath": "/p.jpg",
            "originalMimeType": "image/jpeg",
            "type": "IMAGE",
            "exifInfo": exif_info,
        }
        result = media_jobs._process_assets([asset])[0]
        assert result["info"]["orientation"] == expected_orientation

    def test_process_asset_uses_original_url(self, media_jobs):
        asset = {
            "id": "uuid",
            "originalUrl": "https://immich.local/photo.jpg",
            "originalMimeType": "image/jpeg",
            "type": "IMAGE",
            "exifInfo": {},
        }
        result = media_jobs._process_assets([asset])[0]
        assert result["media_url"] == "https://immich.local/photo.jpg"

    def test_process_asset_no_exif(self, media_jobs):
        asset = {
            "id": "uuid",
            "originalPath": "/photo.jpg",
            "originalMimeType": "image/jpeg",
            "type": "IMAGE",
        }
        result = media_jobs._process_assets([asset])[0]
        assert result["file_size"] is None
        assert result["info"]["width"] is None

    def test_process_multiple_assets(self, media_jobs):
        assets = [
            {"id": f"uuid-{i}", "originalPath": f"/photo{i}.jpg", "originalMimeType": "image/jpeg", "type": "IMAGE", "exifInfo": {}}
            for i in range(3)
        ]
        result = media_jobs._process_assets(assets)
        assert len(result) == 3
        assert [r["media_uuid"] for r in result] == ["uuid-0", "uuid-1", "uuid-2"]

    def test_process_asset_skips_invalid(self, media_jobs):
        """Assets that cause errors should be skipped"""
        assets = [
            {"id": "good1", "originalPath": "/p1.jpg", "originalMimeType": "image/jpeg", "type": "IMAGE", "exifInfo": {}},
            {"id": "bad", "originalPath": "/file.unknown", "originalMimeType": ""},  # missing 'type'
            {"id": "good2", "originalPath": "/p2.jpg", "originalMimeType": "image/jpeg", "type": "IMAGE", "exifInfo": {}},
        ]
        result = media_jobs._process_assets(assets)
        assert len(result) == 2
        assert result[0]["media_uuid"] == "good1"
        assert result[1]["media_uuid"] == "good2"

    def test_process_asset_minimal_info_defaults(self, media_jobs):
        asset = {
            "id": "minimal",
            "originalPath": "/photo.jpg",
            "originalMimeType": "image/jpeg",
            "type": "IMAGE",
            "exifInfo": {},
        }
        result = media_jobs._process_assets([asset])[0]

        assert result["info"]["width"] is None
        assert result["info"]["height"] is None
        assert result["info"]["orientation"] == 1
        assert result["info"]["camera"] == "None None"
        assert result["info"]["lens"] is None
        assert result["info"]["iso"] is None
        assert result["info"]["aperture"] is None
        assert result["info"]["shutter"] is None
        assert result["info"]["focal"] is None
        assert result["info"]["date"] is None
        assert result["info"]["location"]["location_name"] is None
