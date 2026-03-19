"""Brugopeningen – Home Assistant integration entry point.

Lifecycle
---------
async_setup_entry  – called when the config entry is loaded.
                     Creates the coordinator, does the first refresh, then
                     forwards setup to the individual platforms.
async_unload_entry – called when the user removes the integration or HA
                     restarts.  Cleans up platforms and stored data.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_WATCHED_BRIDGES, DOMAIN
from .coordinator import BrugOpenCoordinator
from .bridge_names import BRIDGE_NAMES
from .coordinator import _location_code

# The platforms (entity types) that this integration provides
PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Brugopeningen from a config entry."""
    session = async_get_clientsession(hass)
    coordinator = BrugOpenCoordinator(hass, session, entry)

    # Restore previously seen bridges from storage so devices survive restarts
    # even when those bridges are currently closed (absent from the XML feed).
    await coordinator.async_load()

    # Perform the first data fetch.  If this fails, HA raises ConfigEntryNotReady
    # and will automatically retry later – no manual error handling needed here.
    await coordinator.async_config_entry_first_refresh()

    # Store the coordinator so that the platform modules can access it via
    # hass.data[DOMAIN][entry.entry_id]
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Delegate entity setup to binary_sensor.py and sensor.py
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Sync device names from BRIDGE_NAMES into the device registry.
    # This ensures that adding an entry to bridge_names.py + reloading
    # immediately renames the device in HA (as long as the user hasn't
    # manually renamed it, in which case name_by_user is set and we skip it).
    dev_registry = dr.async_get(hass)
    for device_entry in dr.async_entries_for_config_entry(dev_registry, entry.entry_id):
        if device_entry.name_by_user:
            continue  # user explicitly renamed this device – don't touch it
        for i_domain, bridge_id in device_entry.identifiers:
            if i_domain != DOMAIN:
                continue
            friendly = BRIDGE_NAMES.get(_location_code(bridge_id))
            if friendly and friendly != device_entry.name:
                dev_registry.async_update_device(device_entry.id, name=friendly)
            break

    # Remove devices for bridges that are no longer in the watched set.
    # Must run after platforms are set up (so entity cleanup already ran).
    watched: set[str] = set(entry.options.get(CONF_WATCHED_BRIDGES, []))
    if watched:
        registry = dr.async_get(hass)
        for device_entry in dr.async_entries_for_config_entry(
            registry, entry.entry_id
        ):
            for domain, bridge_id in device_entry.identifiers:
                if domain == DOMAIN and bridge_id not in watched:
                    registry.async_remove_device(device_entry.id)
                    break

    # Reload the integration whenever the user saves new options so that
    # the bridge selection takes effect immediately.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload after options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
