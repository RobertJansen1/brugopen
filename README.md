# Brugopeningen

Custom HACS integration to monitor Dutch bridge (drawbridge) status in real time
using the [NDW open data feed](https://opendata.ndw.nu/).

## Features

- Fetches `actueel_beeld.xml.gz` (DATEX II v3) every 5–300 seconds (default 30 s) —
  conditional GET, only downloads new data when the feed has actually changed
- Creates a **device** per discovered bridge (manufacturer: Rijkswaterstaat / NDW)
- Creates multiple entities per device:
  - **Status** (`binary_sensor`) – `Open` when the bridge is raised for boat traffic,
    `Closed` when passable for road traffic; includes `latitude`, `longitude` and
    `location_code` as state attributes for the **HA Map card**
  - **Laatste opening** (`sensor`, device class `timestamp`) – when the bridge was last raised
  - **Laatste update NDW** (`sensor`, device class `timestamp`, disabled by default) –
    when NDW last updated the situation in the feed
- Bridge coordinates (lat/lon) are stored persistently so they are available immediately after a restart
- By default all bridges are monitored; use the options flow to limit to a selection
- Dutch (`nl`) and English (`en`) translations included
- Custom integration icon (requires HA 2026.3+)

## Installation via HACS

1. Open HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/RobertJansen1/brugopen` as category **Integration**
3. Search for "Brugopeningen" and install
4. Restart Home Assistant
5. Go to _Settings → Devices & Services → Add integration_ and search for
   **Brugopeningen**

## Manual installation

Copy the `custom_components/brugopen` folder to your
`<config>/custom_components/` directory and restart Home Assistant.

## Configuration

After setup, click the **⚙️** icon on the integration card to open the options flow:

1. **Instellingen** – adjust the refresh interval (5–300 s, default 30 s)
2. **Bruggen** – optionally select a subset of bridges to follow; leave empty to follow all

Bridge names can be customised via _Settings → Devices & Services → Brugopeningen → the device_.

## How it works

The NDW `actueel_beeld.xml.gz` feed is a combined DATEX II v3 `SituationPublication`
containing all active traffic situations in the Netherlands.  Bridge openings are
identified by situations with `generalNetworkManagementType = bridgeSwingInOperation`.

A bridge absent from the feed is implicitly **closed**.  The integration keeps a
persistent record of every bridge ever seen (`.storage/brugopen.bridges`) so that
devices and their history survive restarts even before the bridge opens again.

If a bridge has never opened, wait for it to appear in the feed — after that it will
show up as a device automatically (or add it manually via the options flow).

## Goals / roadmap

- [x] Fetch bridge status from NDW open data (conditional GET)
- [x] DATEX II v3 feed (`actueel_beeld.xml.gz`)
- [x] Create a device per bridge
- [x] `binary_sensor` (Open / Closed) + `sensor` (Last opened) per device
- [x] `sensor` (Last updated by NDW) per device (disabled by default)
- [x] Lat/lon coordinates as state attributes (Map card support)
- [x] Options flow – refresh interval + bridge selection
- [x] Persistent bridge storage (survives restarts)
- [x] Dutch and English translations
- [x] Custom integration icon
- [ ] Support for additional NDW datasets (e.g. road works)