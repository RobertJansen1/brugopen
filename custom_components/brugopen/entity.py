"""Shared base entity class for Brugopeningen entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BridgeData, BrugOpenCoordinator


class BridgeEntity(CoordinatorEntity[BrugOpenCoordinator]):
    """Base class for all Brugopeningen entities.

    Provides:
    - A reference to the coordinator and the bridge's unique ID
    - A ``bridge_data`` property for convenience
    - A shared ``device_info`` so all entities for one bridge are grouped
      under the same HA device
    - Entity names via translation keys (``_attr_has_entity_name = True``)
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: BrugOpenCoordinator, bridge_id: str) -> None:
        super().__init__(coordinator)
        self._bridge_id = bridge_id

    _attr_entity_registry_enabled_default = True

    @property
    def bridge_data(self) -> BridgeData | None:
        """Return the current data for this bridge, or None if not found."""
        return self.coordinator.data.get(self._bridge_id)

    @property
    def device_info(self) -> DeviceInfo:
        """Group all entities for this bridge under one HA device."""
        bridge = self.bridge_data
        return DeviceInfo(
            identifiers={(DOMAIN, self._bridge_id)},
            name=bridge.name if bridge else self._bridge_id,
            manufacturer="Rijkswaterstaat / NDW",
            model="Beweegbare brug",
            configuration_url="https://opendata.ndw.nu/",
        )
