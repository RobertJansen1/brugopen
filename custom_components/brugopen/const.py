"""Constants for the Brugopeningen integration."""

from datetime import timedelta

DOMAIN = "brugopen"

# NDW open data URL – gzipped DATEX II SituationPublication
DATA_URL = "https://opendata.ndw.nu/brugopeningen.xml.gz"

# Default poll interval (seconds). Can be changed via the options flow.
DEFAULT_SCAN_INTERVAL = 30
SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

# DATEX II v2 XML namespace used in the NDW data feed
DATEX_NAMESPACE = "http://datex2.eu/schema/2/2_0"

# Options keys
CONF_WATCHED_BRIDGES = "watched_bridges"
CONF_SCAN_INTERVAL = "scan_interval"
