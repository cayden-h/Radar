"""The package imports and declares a version. The cheapest possible smoke test."""

import hawkeye_vision


def test_package_declares_a_version():
    assert hawkeye_vision.__version__ == "0.1.0"
