"""Device identifiers, and the property that makes storing them safe."""

from __future__ import annotations

import pytest

from hawkeye_backend.household.identity import MalformedAddress, fingerprint, hash_identifier

MAC = "a4:83:e7:2c:19:91"
SALT = "site-demo-01-salt"


def test_the_same_address_hashes_the_same_way():
    """Matching an observed device is hashing it and comparing."""
    assert hash_identifier(MAC, SALT) == hash_identifier(MAC, SALT)


def test_case_and_separator_do_not_change_the_hash():
    """Routers report MACs in several shapes and they are the same device."""
    assert hash_identifier("A4:83:E7:2C:19:91", SALT) == hash_identifier("a4-83-e7-2c-19-91", SALT)
    assert hash_identifier("a483e72c1991", SALT) == hash_identifier(MAC, SALT)


def test_a_different_salt_gives_a_different_hash():
    """A roster leaked from one house does not identify devices in another."""
    assert hash_identifier(MAC, SALT) != hash_identifier(MAC, "some-other-house")


def test_the_hash_is_sixty_four_hex_characters():
    h = hash_identifier(MAC, SALT)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_the_raw_address_is_not_recoverable_from_the_hash():
    """Stated as a test so nobody later stores the address 'just for debugging'."""
    h = hash_identifier(MAC, SALT)
    assert MAC.replace(":", "") not in h


def test_the_fingerprint_is_short_and_stable():
    """Enough to tell two phones apart in one room, not enough to track one."""
    f = fingerprint(MAC, SALT)
    assert f == fingerprint(MAC, SALT)
    assert len(f) <= 12
    assert f.startswith("a4")


def test_different_devices_get_different_fingerprints():
    assert fingerprint(MAC, SALT) != fingerprint("b8:27:eb:11:22:33", SALT)


def test_a_malformed_address_is_refused_rather_than_hashed():
    """A digest from garbage is a device that can never match, and nothing
    downstream can tell. This is the only place the real input still exists."""
    with pytest.raises(MalformedAddress):
        hash_identifier("hello", SALT)


def test_a_truncated_address_is_refused():
    with pytest.raises(MalformedAddress):
        hash_identifier("a4:83:e7", SALT)


def test_an_overlong_address_is_refused():
    with pytest.raises(MalformedAddress):
        hash_identifier("a4:83:e7:2c:19:91:ab", SALT)
