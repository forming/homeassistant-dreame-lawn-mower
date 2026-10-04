# Dreame Robot for Home Assistant

A community Home Assistant custom integration for **Dreame** and **MOVA** robotic
lawn mowers, with an **interactive map**.

Unlike a vacuum integration, a mower needs a map you can actually read: which
lawn is loaded, where the zones are, where the mower is right now, and a way to
send it to any of them. This integration gives you all four — a live SVG map you
can tap, per-zone mowing, live position, and the full control surface Home
Assistant's `lawn_mower` domain expects.

```
┌─────────────────────────────────────────────┐
│  Back garden              mowing · 82% · 14m²│
│                                             │
│        ╭─────────────╮                      │
│        │▒▒▒▒▒▒▒▒▒▒▒▒▒│   ┌───────────┐        │
│        │▒▒▒▒▒▒▲▒▒▒▒▒▒▒│   │░░░░░░░░░░░│        │
│        │▒▒▒▒▒▒▒▒▒▒▒▒▒│   └───────────┘        │
│        ╰─────────────╯                      │
│                                             │
│  Selected zone: Zone A                      │
│  [Mow Zone A] [Drive here] [Start] [Pause] …│
└─────────────────────────────────────────────┘
```

## Features

- **Interactive map card** — tap a lawn zone, a spot area, a map edge or a bare
  spot on the map and send the mower there. Shows live position, heading and the
  travel trail.
- **Standard entities** — `lawn_mower`, `image` (PNG map), `sensor`,
  `binary_sensor`, `switch`, `number`, `select`, `button`, `update`.
- **Targeted mowing** — all-area, per-zone, spot areas, map edges, ad-hoc
  patches, and drive-to-point.
- **Live updates over MQTT** — battery, state and position arrive as push
  messages; polling is only a fallback.
- **Settings** — rain protection, charging window, voice volume and the four
  voice prompt groups.
- **Diagnostics** — maintenance counters, device-code error messages with
  severity, task progress, firmware updates.

## Requirements

- Home Assistant 2024.12 or newer
- A Dreamehome or MOVAhome account with a mower bound to it
- The mower must have completed at least one mapping run, so the map exists

## Installation

### HACS (recommended)

1. Add this repository as a custom repository in HACS (category: *Integration*).
2. Install **Dreame Robot**.
3. Restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration → Dreame Robot**.

### Manual

1. Copy `custom_components/dreame_robot` into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

Then install the map card (below).

### Setting up the map card

The interactive card ships with the integration but must be registered as a
Lovelace resource:

1. Copy `custom_components/dreame_robot/www/dreame-robot-map-card.js` to
   `config/www/dreame-robot-map-card.js`.
2. **Settings → Dashboards → Resources → Add resource**
   - URL: `/local/dreame-robot-map-card.js`
   - Type: **JavaScript module**
3. Add the card to a view:

```yaml
type: custom:dreame-robot-map
entity: lawn_mower.back_garden
title: Back garden
refresh_interval: 3   # seconds, optional
```

The card polls `/api/dreame_robot/<entry_id>/map.json`, so it also works from a
remote dashboard as long as your Home Assistant URL is reachable.

## Entities

| Platform | Entity | Notes |
| --- | --- | --- |
| `lawn_mower` | `<name>` | start mowing, pause, dock. Carries state, battery, error, position and map details as attributes. |
| `image` | `<name>` | PNG render of the current map, usable in a `picture-entity` or `floorplan` card. |
| `sensor` | Battery | Battery device class |
| | State, Task status | Enumerated device state |
| | Session mowing time, Session area, Task progress | Current run |
| | Total mowing time, Total mowed area | Lifetime totals |
| | Error, Status notice | Decoded device code with severity |
| | Position X, Position Y, Heading | Live pose, disabled by default |
| | Stored maps, Zones on current map | Map inventory |
| `binary_sensor` | Problem | Active fault |
| | Connectivity, Live updates | Push channel health |
| | Charging, On the dock, Mowing, Paused, Returning, Task active | Current state |
| | After-rain delay active, Maintenance due / due soon, Firmware update available | Status |
| `switch` | Rain protection, Charging window | Verified settings |
| | General / Working / Status / Fault voice prompts | Verified settings |
| `number` | Voice volume, After-rain delay | Verified settings |
| `select` | Map, Map rotation | Multi-lawn support |
| `button` | Stop task, Locate | Always available |
| | Clear warning, Reset blade / brush / maintenance counter | Disabled by default |
| `update` | Firmware | Install support |

## Services

All services accept an optional `entry_id`. Omit it to target every configured
mower.

| Service | Fields | What it does |
| --- | --- | --- |
| `dreame_robot.mow_zones` | `zone_ids` | Mow saved lawn zones |
| `dreame_robot.mow_spots` | `spot_ids` | Mow saved spot areas |
| `dreame_robot.mow_edges` | `contour_ids` — list of `[edge, index]` pairs | Mow saved map edges |
| `dreame_robot.mow_point` | `x`, `y`, `passes` | Mow a patch at a map coordinate |
| `dreame_robot.go_to` | `x`, `y` | Drive to a coordinate without mowing |
| `dreame_robot.switch_map` | `map_index` | Work on a different stored map |
| `dreame_robot.remote_control` | `velocity`, `rotation` | Drive manually one step, `-1000`…`1000` |
| `dreame_robot.stop_mowing` | — | Stop the task without going home |
| `dreame_robot.reset_maintenance` | `item` — `blade`, `brush`, `robot` | Zero a maintenance counter |

Example — mow two zones only when nobody is home on a weekday morning:

```yaml
automation:
  - alias: Mow the back zones on weekday mornings
    triggers:
      - trigger: time
        at: "07:30:00"
    conditions:
      - condition: state
        entity_id: zone.home
        state: "off"
      - condition: state
        entity_id: lawn_mower.back_garden
        state: "docked"
    actions:
      - action: dreame_robot.mow_zones
        data:
          zone_ids: [1, 2]
```

## Supported models

Anything the vendor cloud reports with `.mower.` in its model id is accepted.
Confirmed working:

| Model | Name | Notes |
| --- | --- | --- |
| `dreame.mower.g2408` | Dreame A2 | Primary development target |
| `dreame.mower.q2501a` | Dreame A3 AWD 1000 | |
| `dreame.mower.g2568d` | Dreame A2 3000 | |
| `dreame.mower.g2541e` | Dreame A3 AWD Pro 3500 | |
| `dreame.mower.g2540d` | Dreame A1 Pro 2000 | |
| `dreame.mower.p2255` | Dreame A1 | |
| `dreame.mower.g2422` | Dreame A1 Pro | |
| `mova.mower.g2583` | VIAX 500 | Firmware reuses state codes 15/16/19; handled |
| `mova.mower.g2420a`, `g2552` | VIAX 250 | |
| `mova.mower.g2420b` | VIAX 300 | |
| `mova.mower.g2529b` | LiDAX Ultra 800 | |
| `mova.mower.g2529c`, `g2529f`, `g2584a` | LiDAX Ultra 1000/2000/2000 AWD | |

If your model is missing, open an issue with its `model` id from
**Settings → Devices & Services → Dreame Robot → the device**.

## Not supported

Deliberately out of scope, and honest about it rather than half-working:

- **Live video.** The vendor streams over a proprietary peer-to-peer transport
  that needs a native helper binary. Nothing here pretends to stream video.
- **Cutting-height adjustment.** Models with an electronic height actuator
  report it, but the write path uses an encoded preference blob this project
  does not decode. Use the app for height changes.
- **Schedule editing.** Schedules are read from the device but not written, to
  avoid corrupting them.
- **The legacy binary map format** used by A1-generation firmware. Those mowers
  get state, battery and commands, but no map.
- **LAN-only control.** Everything goes through the vendor cloud.

## How it works

Dreame mowers speak an undocumented JSON-over-HTTPS and JSON-over-MQTT(TLS)
protocol. The client lives in `custom_components/dreame_robot/client/` and has no
Home Assistant imports, so it can be tested and reused on its own.

- `cloud.py` — login, device discovery, the `sendCommand` envelope
- `mqtt.py` — subscribe-only push channel
- `device.py` — polling, commands, settings, map access
- `models.py` — state and device-code tables, map parsing, binary frame decoding
- `render.py` — the PNG renderer and the projection the map card inverts

The design decisions worth knowing are documented as comments where they matter:
mutations are never retried (a duplicated write can apply twice on the device),
a `401` is always safe to retry because the command never left the cloud, and
unknown device codes are reported rather than guessed at.

## Development

```bash
uv venv --python 3.13
uv pip install -r requirements-test.txt
uv run ruff check .
uv run pytest
```

## Contributing

Issues and pull requests are welcome. If you have a mower this integration does
not fully support, please include:

- your model id and firmware version
- a diagnostics download (Settings → Devices & Services → ⋮ → Download diagnostics)
- what you expected to happen

Please do not include your account password or access token.

## License

MIT. See [LICENSE](LICENSE).

This project is not affiliated with, endorsed by, or supported by Dreame or
MOVA.
