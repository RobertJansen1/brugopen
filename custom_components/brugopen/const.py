"""Constants for the Brugopeningen integration."""

from datetime import timedelta

DOMAIN = "brugopen"

# NDW open data URL – gzipped DATEX II v3 SituationPublication (actueel beeld)
# Replaces brugopeningen.xml.gz (v2.3 feed retired 2 April 2026)
DATA_URL = "https://opendata.ndw.nu/actueel_beeld.xml.gz"

# Default poll interval (seconds). Can be changed via the options flow.
DEFAULT_SCAN_INTERVAL = 30
SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

# DATEX II v3 XML namespaces used in the NDW actueel_beeld feed
NS_SITUATION = "http://datex2.eu/schema/3/situation"
NS_COMMON = "http://datex2.eu/schema/3/common"
NS_LOC = "http://datex2.eu/schema/3/locationReferencing"

# Value of generalNetworkManagementType that identifies bridge openings
BRIDGE_MANAGEMENT_TYPE = "bridgeSwingInOperation"

# Options keys
CONF_WATCHED_BRIDGES = "watched_bridges"
CONF_SCAN_INTERVAL = "scan_interval"
