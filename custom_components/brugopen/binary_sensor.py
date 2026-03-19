"""Binary sensor platform – bridge open / closed status.

Each bridge gets ONE binary sensor:
  - state ON  → bridge is open (lifted for boat traffic, road is blocked)
  - state OFF → bridge is closed (passable for road traffic)

Dynamic discovery
-----------------
Bridges are not known in advance; they are discovered as they appear in the
NDW feed.  Whenever the coordinator delivers new data this platform checks
for bridge IDs that it has not yet created an entity for and adds them via
``async_add_entities``.  The listener is cleaned up automatically when the
config entry is unloaded.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    """Set up bridge binary sensors for a config entry."""
    coordinator: BrugOpenCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_ids: set[str] = set()
    watched: set[str] = set(entry.options.get(CONF_WATCHED_BRIDGES, []))

    # Remove entities from the registry that are no longer in the watched set.
    # This runs once on (re)load so that deselected bridges are cleaned up.
    if watched:
        registry = er.async_get(hass)
        for entity_entry in er.async_entries_for_config_entry(
            registry, entry.entry_id
        ):
            # unique_id format: brugopen_<bridge_id>_open
            if not entity_entry.unique_id.endswith("_open"):
                continue
            bridge_id = entity_entry.unique_id[
                len(DOMAIN) + 1 : -len("_open")
            ]
            if bridge_id not in watched:
                registry.async_remove(entity_entry.entity_id)

    @callback
    def _discover() -> None:
        """Create entities for any bridge IDs not yet known."""
        new_entities = [
            BridgeOpenBinarySensor(coordinator, bridge_id)
            for bridge_id in coordinator.data
            if bridge_id not in known_ids
            and (not watched or bridge_id in watched)
        ]
        if new_entities:
            known_ids.update(e._bridge_id for e in new_entities)
            async_add_entities(new_entities)

    # Register the discovery callback; unregister it on integration unload
    remove_listener = coordinator.async_add_listener(_discover)
    entry.async_on_unload(remove_listener)

    # Run once immediately to pick up any bridges already in coordinator.data
    _discover()


class BridgeOpenBinarySensor(BridgeEntity, BinarySensorEntity):
    """Binary sensor: is the bridge currently open (lifted)?

    device_class ``opening`` maps the boolean to meaningful icons and
    translatable state strings ("Open" / "Closed") in the HA frontend.
    """

    _attr_device_class = BinarySensorDeviceClass.OPENING
    _attr_translation_key = "bridge_open"

    def __init__(self, coordinator: BrugOpenCoordinator, bridge_id: str) -> None:
        super().__init__(coordinator, bridge_id)
        self._attr_unique_id = f"{DOMAIN}_{bridge_id}_open"

    @property
    def is_on(self) -> bool | None:
        """Return True when the bridge is open (lifted)."""
        if self.bridge_data is None:
            return None
        return self.bridge_data.is_open
