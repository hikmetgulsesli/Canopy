"""Integration-adjacent checks for identity portability feature gating."""

import os
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

# Ensure repository root is importable when running tests directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Provide lightweight zeroconf stub for environments without optional deps.
if 'zeroconf' not in sys.modules:
    zeroconf_stub = types.ModuleType('zeroconf')

    class _Dummy:
        def __init__(self, *args, **kwargs):
            pass

    zeroconf_stub.ServiceBrowser = _Dummy
    zeroconf_stub.ServiceInfo = _Dummy
    zeroconf_stub.Zeroconf = _Dummy
    zeroconf_stub.ServiceStateChange = _Dummy
    sys.modules['zeroconf'] = zeroconf_stub

from canopy.core.config import Config
from canopy.core.identity_portability import IdentityPortabilityManager
from canopy.network.manager import P2PNetworkManager
from canopy.network.routing import MessageRouter, MessageType


class _FakeDb:
    def get_connection(self):
        raise RuntimeError("Not used in this test")


class TestIdentityPortabilityIntegration(unittest.TestCase):
    def test_config_parses_identity_portability_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            old_env = dict(os.environ)
            try:
                os.environ['CANOPY_IDENTITY_PORTABILITY_ENABLED'] = 'true'
                os.environ['CANOPY_DATA_DIR'] = tmpdir
                cfg = Config.from_env()
                self.assertTrue(cfg.security.identity_portability_enabled)
            finally:
                os.environ.clear()
                os.environ.update(old_env)

    def test_p2p_capability_advertises_identity_portability(self) -> None:
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            with tempfile.TemporaryDirectory() as tmpdir:
                config = SimpleNamespace(
                    storage=SimpleNamespace(database_path=os.path.join(tmpdir, 'db.sqlite3')),
                    security=SimpleNamespace(
                        allow_unverified_relay_messages=False,
                        e2e_private_channels=False,
                        e2e_private_channels_enforce=False,
                        sync_digest_enabled=False,
                        sync_digest_require_capability=True,
                        sync_digest_max_channels_per_request=200,
                        identity_portability_enabled=True,
                    ),
                    network=SimpleNamespace(
                        mesh_port=7771,
                        enable_tls=False,
                        tls_cert_path='',
                        tls_key_path='',
                    ),
                )
                mgr = P2PNetworkManager(config, MagicMock())
                self.assertIn('identity_portability_v1', mgr.get_local_capabilities())
        finally:
            loop.close()

    def test_targeted_relay_types_include_identity_portability_messages(self) -> None:
        targeted = MessageRouter._TARGETED_MESH_RELAY_TYPES
        self.assertIn(MessageType.PRINCIPAL_ANNOUNCE, targeted)
        self.assertIn(MessageType.PRINCIPAL_KEY_UPDATE, targeted)
        self.assertIn(MessageType.BOOTSTRAP_GRANT_SYNC, targeted)
        self.assertIn(MessageType.BOOTSTRAP_GRANT_REVOKE, targeted)

    def test_manager_disabled_status_is_safe(self) -> None:
        cfg = SimpleNamespace(security=SimpleNamespace(identity_portability_enabled=False))
        mgr = IdentityPortabilityManager(_FakeDb(), cfg, p2p_manager=None)
        status = mgr.get_status_snapshot()
        self.assertFalse(status.get('enabled'))
        self.assertEqual(status.get('capability'), 'identity_portability_v1')


if __name__ == '__main__':
    unittest.main()
