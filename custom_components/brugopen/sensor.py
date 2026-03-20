"""Sensor platform – bridge metadata sensors.

Each bridge gets two sensors:
  - Last opened          (device_class: timestamp) – when the bridge was last raised
  - Last updated by NDW  (device_class: timestamp) – when NDW last changed the situation

The bridge name and identifier live in the device registry (see entity.py)
rather than as separate sensor entities.
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_WATCHED_BRIDGES, DOMAIN
from .coordinator import BrugOpenCoordinator
from .entity import BridgeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up bridge sensors for a config entry."""
    coordinator: BrugOpenCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_ids: set[str] = set()
    watched: set[str] = set(entry.options.get(CONF_WATCHED_BRIDGES, []))

    # Remove entities from the registry that are no longer in the watched set.
    _SENSOR_SUFFIXES = ("_last_opened", "_situation_version_time")
    if watched:
        registry = er.async_get(hass)
        for entity_entry in er.async_entries_for_config_entry(
            registry, entry.entry_id
        ):
            uid = entity_entry.unique_id
            suffix = next((s for s in _SENSOR_SUFFIXES if uid.endswith(s)), None)
            if suffix is None:
                continue
            bridge_id = uid[len(DOMAIN) + 1 : -len(suffix)]
            if bridge_id not in watched:
                registry.async_remove(entity_entry.entity_id)

    @callback
    def _discover() -> None:
        new_entities: list = []
        for bridge_id in coordinator.data:
            if bridge_id in known_ids or (watched and bridge_id not in watched):
                continue
            new_entities.append(BridgeLastOpenedSensor(coordinator, bridge_id))
            new_entities.append(BridgeSituationVersionTimeSensor(coordinator, bridge_id))
        if new_entities:
            known_ids.update(e._bridge_id for e in new_entities)
            async_add_entities(new_entities)

    remove_listener = coordinator.async_add_listener(_discover)
    entry.async_on_unload(remove_listener)
    _discover()


class BridgeLastOpenedSensor(BridgeEntity, SensorEntity):
    """Sensor showing when the bridge was last raised.

    The value is a timezone-aware datetime.  HA automatically formats it in
    the user's local timezone.  The state is ``unknown`` until the bridge has
    been observed as open at least once.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_opened"

    def __init__(self, coordinator: BrugOpenCoordinator, bridge_id: str) -> None:
        super().__init__(coordinator, bridge_id)
        self._attr_unique_id = f"{DOMAIN}_{bridge_id}_last_opened"

    @property
    def native_value(self) -> datetime | None:
        """Return the datetime when the bridge was last opened."""
        if self.bridge_data is None:
            return None
        return self.bridge_data.last_opened


class BridgeSituationVersionTimeSensor(BridgeEntity, SensorEntity):
    """Sensor showing when NDW last updated this bridge situation.

    Useful to see how fresh the data is.  Disabled by default to keep
    the device card uncluttered.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "situation_version_time"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: BrugOpenCoordinator, bridge_id: str) -> None:
        super().__init__(coordinator, bridge_id)
        self._attr_unique_id = f"{DOMAIN}_{bridge_id}_situation_version_time"

    @property
    def native_value(self) -> datetime | None:
        """Return the datetime when NDW last updated this situation."""
        if self.bridge_data is None:
            return None
        return self.bridge_data.situation_version_time
