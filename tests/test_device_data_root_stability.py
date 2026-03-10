"""Regression tests for stable per-device data path resolution."""

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure repository root is importable when running tests directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Provide a lightweight zeroconf stub for environments without optional deps.
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

from canopy.core import device as device_mod


class TestDeviceDataRootStability(unittest.TestCase):
    def test_data_root_persists_and_is_cwd_independent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            device_home = root / 'device-home'
            module_data_root = root / 'project-data'
            cwd_a = root / 'cwd-a'
            cwd_b = root / 'cwd-b'
            cwd_a.mkdir(parents=True, exist_ok=True)
            cwd_b.mkdir(parents=True, exist_ok=True)

            device_file = device_home / 'device_identity.json'
            original_cwd = Path.cwd()
            try:
                with patch.object(device_mod, '_DEVICE_DIR', device_home), \
                     patch.object(device_mod, '_DEVICE_FILE', device_file), \
                     patch.object(device_mod, '_default_project_data_root', return_value=module_data_root), \
                     patch.dict(os.environ, {'CANOPY_DATA_ROOT': ''}, clear=False):

                    # First call from cwd-a chooses module-derived root and persists it.
                    os.chdir(cwd_a)
                    first_dir = device_mod.get_device_data_dir(Path('./data'))
                    identity_data = json.loads(device_file.read_text())
                    self.assertEqual(
                        Path(identity_data.get('data_root', '')),
                        module_data_root.resolve(),
                    )

                    # Second call from cwd-b must resolve to the same persisted root.
                    os.chdir(cwd_b)
                    second_dir = device_mod.get_device_data_dir(Path('./data'))

                    self.assertEqual(first_dir, second_dir)
                    self.assertEqual(second_dir.parent.parent, module_data_root.resolve())
                    self.assertTrue((second_dir / '.').exists())
            finally:
                os.chdir(original_cwd)

    def test_env_data_root_override_takes_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            device_home = root / 'device-home'
            override_root = root / 'override-root'
            device_file = device_home / 'device_identity.json'

            with patch.object(device_mod, '_DEVICE_DIR', device_home), \
                 patch.object(device_mod, '_DEVICE_FILE', device_file), \
                 patch.dict(os.environ, {'CANOPY_DATA_ROOT': str(override_root)}, clear=False):
                device_dir = device_mod.get_device_data_dir(Path('./data'))
                self.assertEqual(device_dir.parent.parent, override_root.resolve())


if __name__ == '__main__':
    unittest.main()
