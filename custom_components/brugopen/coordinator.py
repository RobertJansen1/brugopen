"""Data coordinator for the Brugopeningen integration.

Fetches the NDW actueel_beeld.xml.gz feed (DATEX II v3 SituationPublication).

How the NDW v3 feed works
-------------------------
The actueel_beeld feed is a combined snapshot of all active traffic situations
in the Netherlands.  Bridge openings are encoded as situations whose
situationRecord has xsi:type="sit:GeneralNetworkManagement" and contains a
<generalNetworkManagementType>bridgeSwingInOperation</generalNetworkManagementType>
element.

Situation IDs follow the same pattern as the retired v2.3 brugopeningen feed:
    <prefix>_<locationCode>_<eventId>
e.g. MOS01_NLGRQ000600502900272_97024779

We strip the trailing event segment to get a stable per-bridge key.

Conditional GETs
----------------
The coordinator sends If-None-Match / If-Modified-Since headers so that the
full XML is only downloaded when the feed has actually changed.
"""

from __future__ import annotations

import gzip
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from xml.etree import ElementTree

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .bridge_names import BRIDGE_NAMES
from .const import (
    BRIDGE_MANAGEMENT_TYPE,
    CONF_SCAN_INTERVAL,
    DATA_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    NS_COMMON,
    NS_LOC,
    NS_SITUATION,
)

_LOGGER = logging.getLogger(__name__)

_STORAGE_KEY = f"{DOMAIN}.bridges"
_STORAGE_VERSION = 1

_XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"


@dataclass
class BridgeData:
    """State for a single bridge."""

    bridge_id: str
    name: str
    is_open: bool
    last_opened: datetime | None = None
    latitude: float | None = None
    longitude: float | None = None
    situation_version_time: datetime | None = None


def _location_code(bridge_id: str) -> str:
    """Return the bare location code from a bridge_id.

    bridge_id is already stripped of the event suffix, but still has a
    prefix segment separated by an underscore:
        MOS01_NLGRQ000600502900272  →  NLGRQ000600502900272

    If there is no underscore the full id is returned as-is.
    """
    _, _, code = bridge_id.partition("_")
    return code if code else bridge_id


class BrugOpenCoordinator(DataUpdateCoordinator[dict[str, BridgeData]]):
    """Manages fetching and parsing of the NDW bridge opening feed."""

    def __init__(self, hass: HomeAssistant, session: aiohttp.ClientSession, entry: ConfigEntry) -> None:
        interval_seconds: int = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval_seconds),
        )
        self._session = session
        self._etag: str | None = None
        self._last_modified: str | None = None
        # All bridges ever seen, keyed by stable bridge_id (prefix_locationCode)
        self._bridges: dict[str, BridgeData] = {}
        self._store: Store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)

    # ------------------------------------------------------------------
    # DataUpdateCoordinator interface
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, BridgeData]:
        raw = await self._fetch()
        if raw is None:
            return self._bridges

        try:
            xml_bytes = gzip.decompress(raw)
            root = ElementTree.fromstring(xml_bytes)
        except Exception as err:
            raise UpdateFailed(f"Could not decompress / parse NDW XML: {err}") from err

        result = self._parse(root)
        await self._async_save()
        return result

    async def async_load(self) -> None:
        """Restore previously persisted bridge state from .storage."""
        stored = await self._store.async_load()
        if not stored:
            return
        for item in stored.get("bridges", []):
            bid = item.get("bridge_id")
            if not bid:
                continue
            last_opened: datetime | None = None
            if item.get("last_opened"):
                try:
                    last_opened = datetime.fromisoformat(item["last_opened"])
                except ValueError:
                    pass
            name = BRIDGE_NAMES.get(_location_code(bid)) or item.get("name") or bid
            svt: datetime | None = None
            if item.get("situation_version_time"):
                try:
                    svt = datetime.fromisoformat(item["situation_version_time"])
                except ValueError:
                    pass
            self._bridges[bid] = BridgeData(
                bridge_id=bid,
                name=name,
                is_open=False,
                last_opened=last_opened,
                latitude=item.get("latitude"),
                longitude=item.get("longitude"),
                situation_version_time=svt,
            )
        _LOGGER.debug("Restored %d bridges from storage", len(self._bridges))

    async def _async_save(self) -> None:
        payload = [
            {
                "bridge_id": b.bridge_id,
                "name": b.name,
                "last_opened": b.last_opened.isoformat() if b.last_opened else None,
                "latitude": b.latitude,
                "longitude": b.longitude,
                "situation_version_time": b.situation_version_time.isoformat() if b.situation_version_time else None,
            }
            for b in self._bridges.values()
        ]
        await self._store.async_save({"bridges": payload})

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _fetch(self) -> bytes | None:
        headers: dict[str, str] = {}
        if self._etag:
            headers["If-None-Match"] = self._etag
        elif self._last_modified:
            headers["If-Modified-Since"] = self._last_modified

        try:
            async with self._session.get(
                DATA_URL,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 304:
                    return None
                if resp.status != 200:
                    raise UpdateFailed(f"NDW API returned HTTP {resp.status}")
                self._etag = resp.headers.get("ETag")
                self._last_modified = resp.headers.get("Last-Modified")
                return await resp.read()
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Network error reaching NDW API: {err}") from err

    # ------------------------------------------------------------------
    # XML parsing – DATEX II v3
    # ------------------------------------------------------------------

    def _parse(self, root: ElementTree.Element) -> dict[str, BridgeData]:
        """Parse a DATEX II v3 SituationPublication and update _bridges."""
        sit_ns = NS_SITUATION
        open_ids: set[str] = set()

        for situation in root.iter(f"{{{sit_ns}}}situation"):
            situation_id = situation.get("id", "").strip()
            if not situation_id:
                continue

            # Only process if at least one record is a bridge opening
            if not self._is_bridge_situation(situation):
                continue

            bridge_id = self._bridge_id_from_situation(situation_id)
            open_ids.add(bridge_id)

            last_opened = self._parse_start_time(situation)
            situation_version_time = self._parse_situation_version_time(situation)
            name = BRIDGE_NAMES.get(_location_code(bridge_id)) or bridge_id
            latitude, longitude = self._parse_coords(situation)

            if bridge_id in self._bridges:
                bridge = self._bridges[bridge_id]
                bridge.is_open = True
                if last_opened:
                    bridge.last_opened = last_opened
                if situation_version_time:
                    bridge.situation_version_time = situation_version_time
                if latitude is not None:
                    bridge.latitude = latitude
                if longitude is not None:
                    bridge.longitude = longitude
                # Refresh name in case bridge_names.py was updated
                bridge.name = BRIDGE_NAMES.get(_location_code(bridge_id)) or bridge.name
            else:
                self._bridges[bridge_id] = BridgeData(
                    bridge_id=bridge_id,
                    name=name,
                    is_open=True,
                    last_opened=last_opened,
                    latitude=latitude,
                    longitude=longitude,
                    situation_version_time=situation_version_time,
                )
                _LOGGER.debug("Discovered new bridge: %s (%s)", name, bridge_id)

        # Bridges not in this update are closed
        for bid, bridge in self._bridges.items():
            if bid not in open_ids:
                bridge.is_open = False

        return dict(self._bridges)

    # ------------------------------------------------------------------
    # XML element helpers – DATEX II v3
    # ------------------------------------------------------------------

    @staticmethod
    def _is_bridge_situation(situation: ElementTree.Element) -> bool:
        """Return True if the situation contains a bridge opening record.

        In v3 the marker is:
          <generalNetworkManagementType>bridgeSwingInOperation</generalNetworkManagementType>
        inside a situationRecord of xsi:type="sit:GeneralNetworkManagement".
        """
        mgmt_tag = f"{{{NS_SITUATION}}}generalNetworkManagementType"
        for el in situation.iter(mgmt_tag):
            if (el.text or "").strip() == BRIDGE_MANAGEMENT_TYPE:
                return True
        return False

    @staticmethod
    def _bridge_id_from_situation(situation_id: str) -> str:
        """Strip trailing event-ID segment from the situation ID.

        MOS01_NLGRQ000600502900272_97024779  →  MOS01_NLGRQ000600502900272
        """
        parts = situation_id.rsplit("_", 1)
        return parts[0] if len(parts) == 2 else situation_id

    @staticmethod
    def _parse_start_time(situation: ElementTree.Element) -> datetime | None:
        """Extract overallStartTime from a v3 situation."""
        el = situation.find(
            f".//{{{NS_COMMON}}}validityTimeSpecification/{{{NS_COMMON}}}overallStartTime"
        )
        if el is None or not el.text:
            return None
        try:
            return datetime.fromisoformat(el.text.replace("Z", "+00:00"))
        except ValueError:
            _LOGGER.debug("Could not parse time: %s", el.text)
            return None

    @staticmethod
    def _parse_situation_version_time(situation: ElementTree.Element) -> datetime | None:
        """Extract situationVersionTime (NDW last-update timestamp) from a v3 situation."""
        el = situation.find(f"{{{NS_SITUATION}}}situationVersionTime")
        if el is None or not el.text:
            return None
        try:
            return datetime.fromisoformat(el.text.replace("Z", "+00:00"))
        except ValueError:
            _LOGGER.debug("Could not parse situationVersionTime: %s", el.text)
            return None

    @staticmethod
    def _parse_coords(situation: ElementTree.Element) -> tuple[float | None, float | None]:
        """Extract WGS84 coordinates from a v3 situation."""
        lat_el = situation.find(
            f".//{{{NS_LOC}}}pointCoordinates/{{{NS_LOC}}}latitude"
        )
        lon_el = situation.find(
            f".//{{{NS_LOC}}}pointCoordinates/{{{NS_LOC}}}longitude"
        )
        try:
            lat = float(lat_el.text) if lat_el is not None and lat_el.text else None
            lon = float(lon_el.text) if lon_el is not None and lon_el.text else None
            return lat, lon
        except ValueError:
            return None, None


