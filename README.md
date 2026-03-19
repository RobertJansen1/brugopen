# Brugopeningen

Custom HACS integration to monitor Dutch bridge (drawbridge) status in real time
using the [NDW open data feed](https://opendata.ndw.nu/).

## Features

- Fetches `brugopeningen.xml.gz` every 5-300 seconds (default 30) (conditional GET – only
  downloads new data when the file has actually changed on the server)
- Creates a **device** per discovered bridge (manufacturer: Rijkswaterstaat / NDW)
- Creates multiple entities per device:
  - **Status** (`binary_sensor`) – `Open` when the bridge is raised for boat
    traffic, `Closed` when passable for road traffic
  - **Laatste opening** (`sensor`, device class `timestamp`) – when the bridge
    was last raised
- By default all bridges are enabled, if you want to limit, select the bridges you are interrested in
- Dutch (`nl`) and English (`en`) translations included

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

## How it works

The NDW feed is a DATEX II `SituationPublication`.  Every `<situation>` element
in the feed represents a bridge that is **currently open** (being lifted for
boat traffic).  A bridge that is absent from the feed is implicitly **closed**.
The integration maintains the complete set of ever-seen bridges in memory and on storage;
their `is_open` flag is updated on every poll cycle. If your bridge is not in the list, 
wait for it to open the first time, after that you can add it (or it will be done if you 
don't select any bridge)

## Goals / roadmap

 - [x] Fetch bridge status from NDW open data (conditional GET)
 - [x] Create a device per bridge
 - [x] Create binary_sensor (Open / Closed) and sensor (Last opened) per device
 - [ ] Options flow to filter bridges by name or region
 - [ ] Support for additional NDW datasets (e.g. road works)