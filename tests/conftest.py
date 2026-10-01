"""Shared fixtures for the Home Assistant level tests."""

from __future__ import annotations

import copy
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vnish.const import DOMAIN

from .fake_vnish import INFO, PRESETS, RPC_POOLS, SETTINGS, SUMMARY

HOST = "192.168.1.50"


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def client():
    """A VnishClient double that serves realistic payloads."""
    with (
        patch("custom_components.vnish.VnishClient", autospec=True) as cls,
        patch("custom_components.vnish.config_flow.VnishClient", new=cls),
    ):
        mock = cls.return_value
        mock.host = HOST
        mock.info.return_value = copy.deepcopy(INFO)
        mock.summary.return_value = copy.deepcopy(SUMMARY)
        mock.settings.return_value = copy.deepcopy(SETTINGS)
        mock.presets.return_value = copy.deepcopy(PRESETS)
        mock.rpc_summary.return_value = {"GHS 5s": 110500.0}
        mock.rpc_pools.return_value = copy.deepcopy(RPC_POOLS)
        yield mock


@pytest.fixture
def entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="AA:BB:CC:DD:EE:FF",
        title="antminer-s19",
        data={CONF_HOST: HOST, CONF_PASSWORD: "admin"},
    )
