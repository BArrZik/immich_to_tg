import pytest
from unittest.mock import MagicMock
from bot.post_to_channel import MediaPoster


@pytest.fixture
def media_poster():
    mock_app = MagicMock()
    return MediaPoster(mock_app)


class TestFormatExifInfo:
    """Tests for _format_exif_info method"""

    @pytest.mark.parametrize(
        "info,expected_contains",
        [
            # Camera info
            ({"camera": "Canon EOS R5"}, ["Снято на Canon EOS R5"]),
            ({"camera": "Sony A7III"}, ["Снято на Sony A7III"]),
            # Camera filtered out for invalid values
            ({"camera": "none"}, []),
            ({"camera": "None"}, []),
            ({"camera": "null"}, []),
            ({"camera": "unknown"}, []),
            ({"camera": "undefined"}, []),
            ({"camera": "NONE"}, []),  # case insensitive
            # Photo details
            ({"aperture": 2.8}, ["ƒ/2.8"]),
            ({"shutter": "1/250"}, ["1/250"]),
            ({"focal": 50}, ["50 мм"]),
            ({"iso": 100}, ["ISO 100"]),
            # Combined photo details
            (
                {"aperture": 2.8, "shutter": "1/250", "focal": 50, "iso": 100},
                ["ƒ/2.8", "1/250", "50 мм", "ISO 100"],
            ),
            # Empty info
            ({}, []),
        ],
        ids=[
            "camera_canon",
            "camera_sony",
            "camera_none_lowercase",
            "camera_none_titlecase",
            "camera_null",
            "camera_unknown",
            "camera_undefined",
            "camera_none_uppercase",
            "aperture",
            "shutter",
            "focal",
            "iso",
            "combined_photo_details",
            "empty_info",
        ],
    )
    def test_format_exif_info_parts(self, media_poster, info, expected_contains):
        result = media_poster._format_exif_info(info)
        for expected in expected_contains:
            assert expected in result

    def test_format_exif_info_date_valid(self, media_poster):
        info = {"date": "2024-01-15T10:30:00"}
        result = media_poster._format_exif_info(info)
        assert "📅:" in result
        assert "2024" in result

    def test_format_exif_info_date_invalid(self, media_poster):
        info = {"date": "invalid-date"}
        result = media_poster._format_exif_info(info)
        assert "📅:" not in result

    def test_format_exif_info_full(self, media_poster):
        info = {
            "camera": "Canon EOS R5",
            "date": "2024-01-15T10:30:00",
            "aperture": 2.8,
            "shutter": "1/250",
            "focal": 50,
            "iso": 100,
        }
        result = media_poster._format_exif_info(info)
        assert "Снято на Canon EOS R5" in result
        assert "📅:" in result
        assert "ƒ/2.8" in result
        assert "1/250" in result
        assert "50 мм" in result
        assert "ISO 100" in result


class TestGetAndroidOrientationParams:
    """Tests for _get_android_orientation_params method"""

    @pytest.mark.parametrize(
        "orientation,expected_params,expected_swap",
        [
            (1, [], False),  # Normal
            (2, ["-vf", "hflip"], False),  # Horizontal flip
            (3, ["-vf", "hflip,vflip"], False),  # 180° rotation
            (4, ["-vf", "vflip"], False),  # Vertical flip
            (5, ["-vf", "transpose=2"], True),  # Vertical flip + 90° CCW
            (6, [], True),  # 90° CW
            (7, ["-vf", "transpose=0"], True),  # Vertical flip + 90° CW
            (8, ["-vf", "transpose=2"], True),  # 90° CCW
            (0, [], False),  # Unknown - defaults
            (99, [], False),  # Unknown - defaults
        ],
        ids=[
            "orientation_1_normal",
            "orientation_2_hflip",
            "orientation_3_180deg",
            "orientation_4_vflip",
            "orientation_5_vflip_90ccw",
            "orientation_6_90cw",
            "orientation_7_vflip_90cw",
            "orientation_8_90ccw",
            "orientation_0_unknown",
            "orientation_99_unknown",
        ],
    )
    def test_get_android_orientation_params(self, media_poster, orientation, expected_params, expected_swap):
        params, swap = media_poster._get_android_orientation_params(orientation)
        assert params == expected_params
        assert swap == expected_swap


class TestFormatLocation:
    """Tests for _format_location method"""

    @pytest.mark.parametrize(
        "info,expected_result",
        [
            # With location name
            (
                {"location": {"location_name": "Tokyo, Japan", "latitude": 35.6762, "longitude": 139.6503}},
                ("[Tokyo, Japan](https://maps.google.com/?q=35.6762,139.6503)", "https://maps.google.com/?q=35.6762,139.6503"),
            ),
            # Without location name - coords only
            (
                {"location": {"location_name": None, "latitude": 35.6762, "longitude": 139.6503}},
                ("[35.67620, 139.65030](https://maps.google.com/?q=35.6762,139.6503)", "https://maps.google.com/?q=35.6762,139.6503"),
            ),
            # Missing latitude
            (
                {"location": {"location_name": "Test", "latitude": None, "longitude": 139.6503}},
                None,
            ),
            # Missing longitude
            (
                {"location": {"location_name": "Test", "latitude": 35.6762, "longitude": None}},
                None,
            ),
        ],
        ids=[
            "with_location_name",
            "coords_only",
            "missing_lat",
            "missing_lon",
        ],
    )
    @pytest.mark.asyncio
    async def test_format_location(self, media_poster, info, expected_result):
        result = await media_poster._format_location(info)
        assert result == expected_result
