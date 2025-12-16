import pytest
import asyncio
from datetime import datetime, timedelta
from bot.handlers.discussion_forward_tracker_handler import DiscussionForwardTracker


@pytest.fixture
def tracker():
    return DiscussionForwardTracker(ttl_seconds=60)


class TestDiscussionForwardTrackerStore:
    """Tests for store method"""

    @pytest.mark.asyncio
    async def test_store_creates_mapping(self, tracker):
        await tracker.store(channel_id=123, channel_msg_id=456, discussion_msg_id=789)

        key = (123, 456)
        assert key in tracker._mapping
        assert tracker._mapping[key][0] == 789

    @pytest.mark.asyncio
    async def test_store_sets_event(self, tracker):
        key = (123, 456)
        # Access waiter to create event
        _ = tracker._waiters[key]

        await tracker.store(channel_id=123, channel_msg_id=456, discussion_msg_id=789)

        assert tracker._waiters[key].is_set()

    @pytest.mark.asyncio
    async def test_store_overwrites_existing(self, tracker):
        await tracker.store(channel_id=123, channel_msg_id=456, discussion_msg_id=100)
        await tracker.store(channel_id=123, channel_msg_id=456, discussion_msg_id=200)

        key = (123, 456)
        assert tracker._mapping[key][0] == 200


class TestDiscussionForwardTrackerGet:
    """Tests for get method"""

    @pytest.mark.asyncio
    async def test_get_existing_mapping(self, tracker):
        await tracker.store(channel_id=123, channel_msg_id=456, discussion_msg_id=789)

        result = await tracker.get(channel_id=123, channel_msg_id=456, timeout=1.0)

        assert result == 789

    @pytest.mark.asyncio
    async def test_get_nonexistent_mapping_timeout(self, tracker):
        result = await tracker.get(channel_id=999, channel_msg_id=999, timeout=0.1)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_waits_for_store(self, tracker):
        async def delayed_store():
            await asyncio.sleep(0.1)
            await tracker.store(channel_id=123, channel_msg_id=456, discussion_msg_id=789)

        asyncio.create_task(delayed_store())
        result = await tracker.get(channel_id=123, channel_msg_id=456, timeout=1.0)

        assert result == 789

    @pytest.mark.asyncio
    async def test_get_expired_mapping_returns_none(self, tracker):
        # Store with past timestamp
        key = (123, 456)
        expired_time = datetime.now() - timedelta(seconds=120)  # Expired 2 minutes ago
        tracker._mapping[key] = (789, expired_time)

        result = await tracker.get(channel_id=123, channel_msg_id=456, timeout=0.1)

        assert result is None


class TestDiscussionForwardTrackerCleanup:
    """Tests for cleanup_expired method"""

    @pytest.mark.asyncio
    async def test_cleanup_removes_expired(self, tracker):
        # Add expired entry
        key_expired = (111, 222)
        expired_time = datetime.now() - timedelta(seconds=120)
        tracker._mapping[key_expired] = (333, expired_time)

        # Add fresh entry
        await tracker.store(channel_id=444, channel_msg_id=555, discussion_msg_id=666)

        await tracker.cleanup_expired()

        assert key_expired not in tracker._mapping
        assert (444, 555) in tracker._mapping

    @pytest.mark.asyncio
    async def test_cleanup_removes_waiters(self, tracker):
        key = (111, 222)
        expired_time = datetime.now() - timedelta(seconds=120)
        tracker._mapping[key] = (333, expired_time)
        _ = tracker._waiters[key]  # Create waiter

        await tracker.cleanup_expired()

        assert key not in tracker._waiters

    @pytest.mark.asyncio
    async def test_cleanup_empty_mapping(self, tracker):
        await tracker.cleanup_expired()
        assert tracker._mapping == {}

    @pytest.mark.asyncio
    async def test_cleanup_keeps_fresh_entries(self, tracker):
        await tracker.store(channel_id=123, channel_msg_id=456, discussion_msg_id=789)

        await tracker.cleanup_expired()

        assert (123, 456) in tracker._mapping


class TestDiscussionForwardTrackerTTL:
    """Tests for TTL configuration"""

    @pytest.mark.asyncio
    async def test_custom_ttl(self):
        tracker = DiscussionForwardTracker(ttl_seconds=1)

        await tracker.store(channel_id=123, channel_msg_id=456, discussion_msg_id=789)
        result_fresh = await tracker.get(channel_id=123, channel_msg_id=456, timeout=0.1)
        assert result_fresh == 789

        await asyncio.sleep(1.1)

        result_expired = await tracker.get(channel_id=123, channel_msg_id=456, timeout=0.1)
        assert result_expired is None


class TestDiscussionForwardTrackerConcurrency:
    """Tests for concurrent access"""

    @pytest.mark.asyncio
    async def test_multiple_channels(self, tracker):
        channels = [(i, i * 10, i * 100) for i in range(1, 6)]

        for channel_id, msg_id, disc_id in channels:
            await tracker.store(channel_id, msg_id, disc_id)

        for channel_id, msg_id, disc_id in channels:
            result = await tracker.get(channel_id, msg_id, timeout=0.1)
            assert result == disc_id

    @pytest.mark.asyncio
    async def test_concurrent_store_and_get(self, tracker):
        async def store_task(n):
            await tracker.store(channel_id=n, channel_msg_id=n, discussion_msg_id=n * 10)

        async def get_task(n):
            return await tracker.get(channel_id=n, channel_msg_id=n, timeout=1.0)

        # Store concurrently
        await asyncio.gather(*[store_task(i) for i in range(10)])

        # Get concurrently
        results = await asyncio.gather(*[get_task(i) for i in range(10)])

        assert results == [i * 10 for i in range(10)]
