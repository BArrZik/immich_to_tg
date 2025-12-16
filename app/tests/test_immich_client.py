import pytest
from datetime import datetime, timedelta
from collections import deque
from immich.immich_client import ImmichClient, ImmichService


class TestNormalizeUrl:
    """Tests for ImmichClient.normalize_url static method"""

    @pytest.mark.parametrize(
        "input_url,expected",
        [
            # Basic URLs with protocol
            ("https://immich.example.com", "https://immich.example.com"),
            ("http://immich.example.com", "http://immich.example.com"),
            # URLs without protocol - domain names get https
            ("immich.example.com", "https://immich.example.com"),
            ("example.com", "https://example.com"),
            # URLs without protocol - with port get http
            ("immich.example.com:2283", "http://immich.example.com:2283"),
            ("example.com:8080", "http://example.com:8080"),
            # IP addresses
            ("192.168.1.100", "https://192.168.1.100"),
            ("192.168.1.100:2283", "http://192.168.1.100:2283"),
            ("10.0.0.1:8080", "http://10.0.0.1:8080"),
            # Localhost variants
            ("localhost:2283", "http://localhost:2283"),
            ("localhost:8080", "http://localhost:8080"),
            ("http://localhost:2283", "http://localhost:2283"),
            pytest.param("localhost://something", "http://localhost/something", marks=pytest.mark.xfail(reason="Такой тип url не планируется поддерживать", strict=True)),
            # With explicit protocols
            ("http://192.168.1.100:2283", "http://192.168.1.100:2283"),
            ("https://192.168.1.100:2283", "https://192.168.1.100:2283"),
            # Whitespace handling
            ("  https://immich.example.com  ", "https://immich.example.com"),
            ("  192.168.1.100:2283  ", "http://192.168.1.100:2283"),
            # Duplicate slashes
            ("http:///example.com", "http://example.com"),
            ("https:///immich.local", "https://immich.local"),
            # Complex paths
            ("immich.example.com/api/v1", "https://immich.example.com/api/v1"),
            ("192.168.1.100:2283/api", "http://192.168.1.100:2283/api"),
        ],
        ids=[
            "https_domain",
            "http_domain",
            "domain_no_protocol_https",
            "simple_domain_https",
            "domain_with_port_http",
            "domain_with_port_8080",
            "ip_no_port_https",
            "ip_with_port_2283",
            "ip_with_port_8080",
            "localhost_2283",
            "localhost_8080",
            "localhost_http_explicit",
            "localhost_triple_slash",
            "ip_port_http_explicit",
            "ip_port_https_explicit",
            "whitespace_https",
            "whitespace_ip_port",
            "triple_slash_http",
            "triple_slash_https",
            "domain_with_path",
            "ip_port_with_path",
        ],
    )
    def test_normalize_url(self, input_url, expected):
        assert ImmichClient.normalize_url(input_url) == expected


class TestImmichClientIsValid:
    """Tests for ImmichClient.is_valid method"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "last_used_delta,ttl_seconds,expected",
        [
            (timedelta(seconds=30), 60, True),  # Fresh - used 30s ago, ttl 60s
            (timedelta(seconds=60), 60, False),  # Exactly at TTL boundary
            (timedelta(seconds=90), 60, False),  # Expired - used 90s ago, ttl 60s
            (timedelta(hours=1), 7200, True),  # Fresh - used 1h ago, ttl 2h
            (timedelta(hours=3), 7200, False),  # Expired - used 3h ago, ttl 2h
            (timedelta(seconds=0), 60, True),  # Just used
        ],
        ids=[
            "fresh_30s",
            "at_boundary_60s",
            "expired_90s",
            "fresh_1h_ttl_2h",
            "expired_3h_ttl_2h",
            "just_used",
        ],
    )
    async def test_is_valid(self, last_used_delta, ttl_seconds, expected):
        client = ImmichClient("http://test.local", "api_key")
        client.last_used = datetime.now() - last_used_delta

        result = await client.is_valid(timedelta(seconds=ttl_seconds))

        assert result == expected
        await client.close()


class TestImmichClientRefresh:
    """Tests for ImmichClient.refresh method"""

    @pytest.mark.asyncio
    async def test_refresh_updates_last_used(self):
        client = ImmichClient("http://test.local", "api_key")
        old_time = client.last_used
        client.last_used = datetime.now() - timedelta(hours=1)

        await client.refresh()

        assert client.last_used > old_time - timedelta(hours=1)
        assert (datetime.now() - client.last_used).total_seconds() < 1
        await client.close()


class TestImmichServiceLRU:
    """Tests for ImmichService LRU functionality"""

    def test_update_lru_moves_to_end(self):
        service = ImmichService()
        service._lru_queue = deque([1, 2, 3])

        service._update_lru(1)

        assert list(service._lru_queue) == [2, 3, 1]

    def test_update_lru_new_item(self):
        service = ImmichService()
        service._lru_queue = deque([1, 2, 3])

        service._update_lru(4)

        assert list(service._lru_queue) == [1, 2, 3, 4]

    def test_update_lru_empty_queue(self):
        service = ImmichService()
        service._lru_queue = deque()

        service._update_lru(1)

        assert list(service._lru_queue) == [1]

    @pytest.mark.parametrize(
        "initial_queue,update_id,expected_queue",
        [
            ([1, 2, 3], 2, [1, 3, 2]),
            ([1, 2, 3], 3, [1, 2, 3]),  # Already at end
            ([1], 1, [1]),
            ([1, 2, 3, 4, 5], 1, [2, 3, 4, 5, 1]),
        ],
        ids=[
            "move_middle_to_end",
            "already_at_end",
            "single_element",
            "move_first_to_end",
        ],
    )
    def test_update_lru_scenarios(self, initial_queue, update_id, expected_queue):
        service = ImmichService()
        service._lru_queue = deque(initial_queue)

        service._update_lru(update_id)

        assert list(service._lru_queue) == expected_queue


class TestImmichServiceConfig:
    """Tests for ImmichService configuration"""

    @pytest.mark.parametrize(
        "ttl_hours,max_clients",
        [
            (1, 100),
            (2, 1000),
            (24, 500),
            (0.5, 50),
        ],
        ids=[
            "1h_100clients",
            "2h_1000clients",
            "24h_500clients",
            "30min_50clients",
        ],
    )
    def test_service_initialization(self, ttl_hours, max_clients):
        service = ImmichService(
            client_ttl=timedelta(hours=ttl_hours),
            max_clients=max_clients,
        )

        assert service.client_ttl == timedelta(hours=ttl_hours)
        assert service.max_clients == max_clients
        assert len(service.active_clients) == 0
        assert len(service._lru_queue) == 0

    def test_default_initialization(self):
        service = ImmichService()

        assert service.client_ttl == timedelta(hours=2)
        assert service.max_clients == 1000
