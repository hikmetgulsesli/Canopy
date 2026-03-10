import copy
import time
import unittest

from traffic_tool.collector import CanopyTrafficCollector


class TrafficToolCollectorTests(unittest.TestCase):
    def test_collect_once_applies_deltas_and_series(self):
        collector = CanopyTrafficCollector(
            target_base_url='http://127.0.0.1:7770',
            poll_seconds=5,
            retention_minutes=60,
        )
        base_ts = time.time()

        seq = [
            {
                'timestamp': base_ts,
                'timestamp_iso': '1970-01-01T00:16:40+00:00',
                'target_base_url': 'http://127.0.0.1:7770',
                'poll_seconds': 5,
                'probes': {
                    'health': {'ok': True, 'latency_ms': 5.0, 'response_bytes': 20, 'status_code': 200, 'data': {}, 'error': ''},
                    'p2p_status': {'ok': True, 'latency_ms': 6.0, 'response_bytes': 80, 'status_code': 200, 'data': {}, 'error': ''},
                    'system_info': {'ok': True, 'latency_ms': 9.0, 'response_bytes': 120, 'status_code': 200, 'data': {}, 'error': ''},
                    'relay_status': {'ok': True, 'latency_ms': 7.0, 'response_bytes': 90, 'status_code': 200, 'data': {'active_relays': {}}, 'error': ''},
                },
                'database_stats': {'messages': 10, 'feed_posts': 3},
                'p2p': {'running': True, 'connected_peers': 2, 'discovered_peers': 4, 'relay_policy': 'broker_only', 'active_relays': {}},
                'derived': {'probe_error_count': 0, 'relay_route_count': 0, 'messages_delta': 0, 'feed_posts_delta': 0, 'peers_delta': 0, 'traffic_score': 0.0},
            },
            {
                'timestamp': base_ts + 5.0,
                'timestamp_iso': '1970-01-01T00:16:45+00:00',
                'target_base_url': 'http://127.0.0.1:7770',
                'poll_seconds': 5,
                'probes': {
                    'health': {'ok': True, 'latency_ms': 5.5, 'response_bytes': 20, 'status_code': 200, 'data': {}, 'error': ''},
                    'p2p_status': {'ok': True, 'latency_ms': 6.5, 'response_bytes': 80, 'status_code': 200, 'data': {}, 'error': ''},
                    'system_info': {'ok': True, 'latency_ms': 10.0, 'response_bytes': 130, 'status_code': 200, 'data': {}, 'error': ''},
                    'relay_status': {'ok': True, 'latency_ms': 7.0, 'response_bytes': 95, 'status_code': 200, 'data': {'active_relays': {'peerB': 'peerA'}}, 'error': ''},
                },
                'database_stats': {'messages': 16, 'feed_posts': 5},
                'p2p': {'running': True, 'connected_peers': 3, 'discovered_peers': 5, 'relay_policy': 'broker_only', 'active_relays': {'peerB': 'peerA'}},
                'derived': {'probe_error_count': 0, 'relay_route_count': 1, 'messages_delta': 0, 'feed_posts_delta': 0, 'peers_delta': 0, 'traffic_score': 0.0},
            },
        ]

        def fake_build_sample():
            return copy.deepcopy(seq.pop(0))

        collector._build_sample = fake_build_sample  # type: ignore[method-assign]

        first = collector.collect_once()
        second = collector.collect_once()

        self.assertEqual(first['derived']['messages_delta'], 0)
        self.assertEqual(second['derived']['messages_delta'], 6)
        self.assertEqual(second['derived']['feed_posts_delta'], 2)
        self.assertEqual(second['derived']['peers_delta'], 1)
        self.assertGreater(second['derived']['traffic_score'], 0)

        series = collector.timeseries(metric='message_delta', window_seconds=120, bucket_seconds=5)
        self.assertTrue(series)
        self.assertEqual(series[-1]['value'], 6.0)

        breakdown = collector.endpoint_breakdown(window_seconds=120)
        self.assertTrue(any(row['endpoint'] == 'system_info' for row in breakdown))


if __name__ == '__main__':
    unittest.main()
