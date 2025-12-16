import pytest
from unittest.mock import MagicMock, patch


class TestIsUserAllowed:
    """Tests for is_user_allowed function"""

    @pytest.mark.parametrize(
        "user_id,admin_ids,expected",
        [
            (123, [123, 456], True),
            (456, [123, 456], True),
            (789, [123, 456], False),
            (123, [], False),
            (0, [0], True),
        ],
        ids=[
            "user_in_admin_ids_first",
            "user_in_admin_ids_second",
            "user_not_in_admin_ids",
            "empty_admin_ids",
            "zero_id",
        ],
    )
    def test_is_user_allowed_by_id(self, user_id, admin_ids, expected):
        with patch("bot.check_permissions.config") as mock_config:
            mock_config.ADMIN_IDS = admin_ids
            mock_config.ADMIN_USERNAMES = []

            from bot.check_permissions import is_user_allowed

            user = MagicMock()
            user.id = user_id
            user.username = None

            assert is_user_allowed(user) == expected

    @pytest.mark.parametrize(
        "username,admin_usernames,expected",
        [
            ("admin", ["admin", "moderator"], True),
            ("moderator", ["admin", "moderator"], True),
            ("user", ["admin", "moderator"], False),
            ("Admin", ["admin"], True),  # case insensitive
            ("ADMIN", ["admin"], True),  # case insensitive
            ("admin", ["ADMIN"], True),  # case insensitive both ways
            (None, ["admin"], False),
            ("admin", [], False),
        ],
        ids=[
            "username_in_list_first",
            "username_in_list_second",
            "username_not_in_list",
            "case_insensitive_user_upper",
            "case_insensitive_user_allcaps",
            "case_insensitive_config_upper",
            "username_none",
            "empty_admin_usernames",
        ],
    )
    def test_is_user_allowed_by_username(self, username, admin_usernames, expected):
        with patch("bot.check_permissions.config") as mock_config:
            mock_config.ADMIN_IDS = []
            mock_config.ADMIN_USERNAMES = admin_usernames

            from bot.check_permissions import is_user_allowed

            user = MagicMock()
            user.id = 999  # Not in admin IDs
            user.username = username

            assert is_user_allowed(user) == expected

    def test_is_user_allowed_id_takes_priority(self):
        """User with matching ID is allowed even if username doesn't match"""
        with patch("bot.check_permissions.config") as mock_config:
            mock_config.ADMIN_IDS = [123]
            mock_config.ADMIN_USERNAMES = ["other_user"]

            from bot.check_permissions import is_user_allowed

            user = MagicMock()
            user.id = 123
            user.username = "not_matching"

            assert is_user_allowed(user) is True

    def test_is_user_allowed_username_fallback(self):
        """User without matching ID but with matching username is allowed"""
        with patch("bot.check_permissions.config") as mock_config:
            mock_config.ADMIN_IDS = [111]
            mock_config.ADMIN_USERNAMES = ["admin"]

            from bot.check_permissions import is_user_allowed

            user = MagicMock()
            user.id = 999
            user.username = "admin"

            assert is_user_allowed(user) is True

    def test_is_user_allowed_neither_matches(self):
        """User with neither matching ID nor username is denied"""
        with patch("bot.check_permissions.config") as mock_config:
            mock_config.ADMIN_IDS = [111]
            mock_config.ADMIN_USERNAMES = ["admin"]

            from bot.check_permissions import is_user_allowed

            user = MagicMock()
            user.id = 999
            user.username = "random_user"

            assert is_user_allowed(user) is False
