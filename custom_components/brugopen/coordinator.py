"""Data coordinator for the Brugopeningen integration.

Fetches the NDW brugopeningen.xml.gz feed (DATEX II SituationPublication format).

How the NDW feed works
----------------------
The feed contains only bridges that are **currently open** (being lifted for
boat traffic).  A bridge that does not appear in the feed is implicitly closed.
Each <situation> element represents one active bridge opening event and
contains:
  - situation/@id       – unique event ID; the stable bridge location code is
                         derived from it by stripping the trailing _<eventId>
                         segment (e.g. MOS01_NLGRQ000600502900272_97024779
                         → MOS01_NLGRQ000600502900272)
  - overallStartTime    – when the bridge was last opened
  - locationForDisplay  – WGS84 coordinates (latitude / longitude)
  - descriptor element  – human-readable bridge name (TPEG location descriptor)

Conditional GETs
----------------
The coordinator sends If-None-Match / If-Modified-Since headers so that the
full XML is only downloaded when the feed has actually changed.  This allows
a short polling interval (30 s) without generating unnecessary traffic.
"""

from __future__ import annotations

import gzip
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from xml.etree import ElementTree

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from homeassistant.config_entries import ConfigEntry

from .bridge_names import BRIDGE_NAMES
from .const import CONF_SCAN_INTERVAL, DATA_URL, DATEX_NAMESPACE, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

_STORAGE_KEY = f"{DOMAIN}.bridges"
_STORAGE_VERSION = 1


@dataclass
class BridgeData:
    """State for a single bridge."""

    bridge_id: str
    name: str
    is_open: bool
    last_opened: datetime | None = None
    latitude: float | None = None
    longitude: float | None = None


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
        # HTTP cache-control headers from the previous successful response
        self._etag: str | None = None
        self._last_modified: str | None = None
        # All bridges ever seen, keyed by stable bridge location code
        # (situation ID with trailing _<eventId> stripped)
        self._bridges: dict[str, BridgeData] = {}
        self._store: Store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)

    # ------------------------------------------------------------------
    # DataUpdateCoordinator interface
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, BridgeData]:
        """Fetch and parse the NDW data feed."""
        raw = await self._fetch()
        if raw is None:
            # 304 Not Modified – return cached state
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
            # BRIDGE_NAMES always wins – it is an explicit user override.
            # Fall back to the stored name, then the bare ID.
            name = BRIDGE_NAMES.get(_location_code(bid)) or item.get("name") or bid
            # Always restore as closed – the next XML fetch will update open bridges
            self._bridges[bid] = BridgeData(
                bridge_id=bid,
                name=name,
                is_open=False,
                last_opened=last_opened,
                latitude=item.get("latitude"),
                longitude=item.get("longitude"),
            )
        _LOGGER.debug("Restored %d bridges from storage", len(self._bridges))

    async def _async_save(self) -> None:
        """Persist current bridge state to .storage."""
        payload = []
        for bridge in self._bridges.values():
            payload.append({
                "bridge_id": bridge.bridge_id,
                "name": bridge.name,
                "last_opened": bridge.last_opened.isoformat() if bridge.last_opened else None,
                "latitude": bridge.latitude,
                "longitude": bridge.longitude,
            })
        await self._store.async_save({"bridges": payload})

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _fetch(self) -> bytes | None:
        """Download the gzipped XML.  Returns None when not modified."""
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
                # Save caching headers for the next request
                self._etag = resp.headers.get("ETag")
                self._last_modified = resp.headers.get("Last-Modified")
                return await resp.read()
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Network error reaching NDW API: {err}") from err

    # ------------------------------------------------------------------
    # XML parsing
    # ------------------------------------------------------------------

    def _parse(self, root: ElementTree.Element) -> dict[str, BridgeData]:
        """Parse a DATEX II SituationPublication and update _bridges."""
        ns = DATEX_NAMESPACE
        open_ids: set[str] = set()

        for situation in root.iter(f"{{{ns}}}situation"):
            situation_id = situation.get("id", "").strip()
            if not situation_id:
                continue

            # Derive the stable bridge location code by stripping the
            # trailing _<eventId> segment from the DATEX II situation ID.
            # Example: MOS01_NLGRQ000600502900272_97024779
            #        → MOS01_NLGRQ000600502900272
            bridge_id = self._bridge_id_from_situation(situation_id)

            open_ids.add(bridge_id)

            last_opened = self._parse_start_time(situation, ns)
            name = (
                self._extract_name(situation, ns)
                or BRIDGE_NAMES.get(_location_code(bridge_id))
                or bridge_id
            )
            latitude = self._find_float(situation, ns, "latitude")
            longitude = self._find_float(situation, ns, "longitude")

            if bridge_id in self._bridges:
                bridge = self._bridges[bridge_id]
                bridge.is_open = True
                bridge.name = name
                if last_opened:
                    bridge.last_opened = last_opened
                if latitude is not None:
                    bridge.latitude = latitude
                if longitude is not None:
                    bridge.longitude = longitude
            else:
                self._bridges[bridge_id] = BridgeData(
                    bridge_id=bridge_id,
                    name=name,
                    is_open=True,
                    last_opened=last_opened,
                    latitude=latitude,
                    longitude=longitude,
                )
                _LOGGER.debug("Discovered new bridge: %s (%s)", name, bridge_id)

        # Bridges absent from this update have been closed
        for bid, bridge in self._bridges.items():
            if bid not in open_ids:
                bridge.is_open = False

        return dict(self._bridges)

    # ------------------------------------------------------------------
    # XML element helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _bridge_id_from_situation(situation_id: str) -> str:
        """Return the stable bridge location code from a DATEX II situation ID.

        DATEX II situation IDs used by NDW follow the pattern:
            <prefix>_<locationCode>_<eventId>
        e.g. MOS01_NLGRQ000600502900272_97024779

        The last segment (_97024779) is a unique event counter that changes
        with every new opening event.  We strip it so that the same physical
        bridge always maps to the same key.

        If the ID contains fewer than two underscores we return it as-is.
        """
        parts = situation_id.rsplit("_", 1)
        return parts[0] if len(parts) == 2 else situation_id

    @staticmethod
    def _parse_start_time(
        situation: ElementTree.Element, ns: str
    ) -> datetime | None:
        """Extract the overallStartTime from a situation element."""
        el = situation.find(
            f".//{{{ns}}}validityTimeSpecification/{{{ns}}}overallStartTime"
        )
        if el is None or not el.text:
            return None
        try:
            # ISO 8601 with optional trailing Z or +HH:MM offset
            return datetime.fromisoformat(el.text.replace("Z", "+00:00"))
        except ValueError:
            _LOGGER.debug("Could not parse time: %s", el.text)
            return None

    @classmethod
    def _extract_name(cls, situation: ElementTree.Element, ns: str) -> str | None:
        """Return a human-readable bridge name from the situation element.

        DATEX II v2 descriptor elements can contain the text either:
          a) as a direct text node  (older feeds)
          b) inside a child <value> element  (most NDW feeds)

        We try both and skip short strings that are likely enum codes
        (e.g. "other", "nl").
        """
        for desc in situation.iter(f"{{{ns}}}descriptor"):
            # (b) DATEX II v2: text is in a <value> child
            value_el = desc.find(f"{{{ns}}}value")
            if value_el is not None and value_el.text:
                text = value_el.text.strip()
                if len(text) > 4:
                    return text
            # (a) older flat format: text directly in <descriptor>
            if len(desc) == 0 and desc.text:
                text = desc.text.strip()
                if len(text) > 4:
                    return text

        # Nothing found – log the raw XML once so the structure can be inspected
        _LOGGER.debug(
            "Could not extract name for situation %s; raw XML: %s",
            situation.get("id"),
            ElementTree.tostring(situation, encoding="unicode")[:800],
        )
        return None

    @staticmethod
    def _find_float(
        situation: ElementTree.Element, ns: str, tag: str
    ) -> float | None:
        el = situation.find(f".//{{{ns}}}locationForDisplay/{{{ns}}}{tag}")
        if el is not None and el.text:
            try:
                return float(el.text)
            except ValueError:
                pass
        return None
