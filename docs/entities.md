# Entity and service reference

Every entity and service this integration creates, what it reads, and what you
can do with it.

Entity ids depend on the name you gave the mower. The tables below use
`back_garden` as the example, so `sensor.back_garden_battery` corresponds to a
mower called *Back garden*. If you named it something else, the prefix changes.

## Contents

- [lawn_mower](#lawn_mower)
- [image](#image)
- [sensor](#sensor)
- [binary_sensor](#binary_sensor)
- [switch](#switch)
- [number](#number)
- [select](#select)
- [button](#button)
- [update](#update)
- [Services](#services)
- [Automations](#automations)

## lawn_mower

The primary control surface. Entity id is `lawn_mower.<name>`.

### States

Home Assistant has five lawn mower states, so the mower's richer states collapse
onto them:

| Home Assistant state | Mower states that map to it |
| --- | --- |
| `mowing` | mowing, mapping, remote control, second mowing, spot mowing, shortcut, monitoring, repositioning, human following |
| `paused` | paused, monitoring paused, paused at a maintenance point |
| `returning` | returning to dock |
| `docked` | idle, charging, smart charging, charging complete, charging paused (hot or cold), waiting for task, station cleaning, upgrading |
| `error` | any state, when the device reports a fault-tier code |

An unrecognised state falls back to `docked` rather than claiming the mower is
working.

### Services

| Service | What it does on the device |
| --- | --- |
| `lawn_mower.start_mowing` | Start or resume mowing the whole lawn |
| `lawn_mower.pause` | Pause the current task |
| `lawn_mower.dock` | Return to the station |

### Attributes

| Attribute | Example | Notes |
| --- | --- | --- |
| `entry_id` | `01JABC…` | The map card uses this to find its endpoint |
| `state` | `mowing` | The decoded device state name |
| `state_code` | `1` | The raw `2.1` value, for debugging |
| `task_status` | `mowing` | The mower's own task status |
| `mowing_mode` | `standard` | From `4.23` |
| `battery_level` | `82` | |
| `charging` | `false` | |
| `docked` | `true` | |
| `error_code` | `4` | `null` when healthy |
| `error_name` | `left_drive_wheel_error` | |
| `error_tier` | `error` | `error`, `alert`, `attention`, `info` or `null` |
| `session_minutes` | `42` | Current run |
| `session_area_sqm` | `61.5` | |
| `progress_percent` | `35.0` | |
| `total_minutes` | `5120` | Lifetime |
| `total_area_sqm` | `2310.5` | |
| `push_connected` | `true` | MQTT channel health |
| `last_failure` | `null` | Last poll error, if the cloud is struggling |
| `position_x`, `position_y` | `900`, `500` | Live pose in centimetres, when known |
| `heading` | `45.0` | Degrees |
| `task_region_id`, `task_total_area_sqm`, `task_current_area_sqm` | | Mission detail from the runtime frame |
| `map_name`, `map_total_area` | `Front lawn`, `128.4` | Active map |
| `zone_ids`, `spot_ids` | `[1, 2]` | What the `mow_zones` / `mow_spots` services expect |
| `map_ids` | `[1, 2]` | Stored maps |

The `zone_ids` and `spot_ids` attributes are the bridge between the map and the
services — read them to build a picker, or take them from the card.

## image

`image.<name>`. A PNG render of the active map, with the mower drawn on it.

Works in a `picture-entity` card, a floorplan, or anywhere that takes an image
entity. Useful if you do not want to install the custom card.

Attributes: `map_name`, `map_id`, `map_total_area`, `zone_count`,
`forbidden_count`, `spot_count`, `rotation`, `canvas_width`, `canvas_height`,
`map_json_url`.

Unavailable when no map has been downloaded.

## sensor

18 sensors, 13 enabled by default.

| Entity | Device class | Unit | Category | Default | Reads |
| --- | --- | --- | --- | --- | --- |
| `sensor.*_battery` | battery | % | — | on | `3.1`, falling back to the heartbeat |
| `sensor.*_state` | enum | — | diagnostic | on | `2.1` decoded |
| `sensor.*_task_status` | — | — | diagnostic | on | `2.50` or the heartbeat |
| `sensor.*_mowing_mode` | — | — | diagnostic | on | `4.23` |
| `sensor.*_session_mowing_time` | duration | min | — | on | `4.2` |
| `sensor.*_session_area` | area | m² | — | on | `4.3` |
| `sensor.*_task_progress` | — | % | — | on | `4.63`, or the runtime frame |
| `sensor.*_total_mowing_time` | duration | min | diagnostic | on | `12.2` |
| `sensor.*_total_mowed_area` | area | m² | diagnostic | on | `12.4` |
| `sensor.*_error` | — | — | diagnostic | on | `2.2` when the tier is `error`, else `none` |
| `sensor.*_status_notice` | — | — | diagnostic | on | `2.2` when the tier is not `error`, else `none` |
| `sensor.*_stored_maps` | — | — | diagnostic | on | Map count |
| `sensor.*_zones_on_current_map` | — | — | diagnostic | on | Zone count |
| `sensor.*_position_x` | — | cm | diagnostic | **off** | Live pose |
| `sensor.*_position_y` | — | cm | diagnostic | **off** | Live pose |
| `sensor.*_heading` | — | ° | diagnostic | **off** | Live pose |
| `sensor.*_serial_number` | — | — | diagnostic | **off** | `4.14` |
| `sensor.*_firmware_version` | — | — | diagnostic | **off** | Model record |

Error and notice are split on purpose: a fault turns the mower into `error` and
lights `binary_sensor.*_problem`, while an informational code like "task
completed" is just a notice.

The four disabled sensors are useful for debugging and automations but clutter a
dashboard, so they ship off. Enable them in the entity settings.

## binary_sensor

12 sensors, 11 enabled by default.

| Entity | Device class | Category | Default | On when |
| --- | --- | --- | --- | --- |
| `binary_sensor.*_problem` | problem | — | on | The mower is in `error` |
| `binary_sensor.*_maintenance_due` | problem | — | on | A maintenance counter is exhausted |
| `binary_sensor.*_maintenance_due_soon` | — | diagnostic | on | A counter is under 20% remaining |
| `binary_sensor.*_connectivity` | connectivity | — | on | The last read or push succeeded |
| `binary_sensor.*_live_updates` | connectivity | diagnostic | on | The MQTT channel is connected |
| `binary_sensor.*_charging` | battery charging | — | on | Charging |
| `binary_sensor.*_on_the_dock` | — | — | on | On the station |
| `binary_sensor.*_mowing` | — | — | on | Activity is `mowing` |
| `binary_sensor.*_paused` | — | — | on | Activity is `paused` |
| `binary_sensor.*_returning` | — | — | on | Activity is `returning` |
| `binary_sensor.*_task_active` | running | — | on | Mowing or returning |
| `binary_sensor.*_firmware_update_available` | update | diagnostic | **off** | The cloud offers newer firmware |

The two connectivity sensors answer different questions. `connectivity` means
Home Assistant can see the mower at all. `live_updates` means instant updates are
arriving over MQTT. If the first is on and the second is off, polling is carrying
the integration and you may want a longer interval.

## switch

6 switches, covering the settings the device actually reported. A switch whose
setting the mower does not publish goes `unavailable` rather than appearing and
failing.

| Entity | Writes | Notes |
| --- | --- | --- |
| `switch.*_rain_protection` | `{"m":"s","t":"WRP",…}` | Preserves the configured delay and sensitivity |
| `switch.*_charging_window` | `{"m":"s","t":"BAT",…}` | Preserves the configured hours |
| `switch.*_general_voice_prompts` | `{"m":"s","t":"VOICE",…}` | One of four groups |
| `switch.*_working_voice_prompts` | | |
| `switch.*_status_voice_prompts` | | |
| `switch.*_fault_voice_prompts` | | |

Every write is a read-modify-write of the whole record, because the device has no
partial update. Turning one voice group off leaves the other three alone.

## number

| Entity | Range | Unit | Notes |
| --- | --- | --- | --- |
| `number.*_voice_volume` | 0–100 | % | `VOL` setting |
| `number.*_after_rain_delay` | 0–24 | h | `WRP` delay; 0 means "until started manually" |

Both unavailable if the mower does not report the setting.

Cutting height is **not** exposed — see
[protocol.md → Limitations](protocol.md#limitations).

## select

| Entity | Options | Notes |
| --- | --- | --- |
| `select.*_map` | One per stored map | Only offered when there is more than one. Writes a map-switch command to the device |
| `select.*_map_rotation` | `0°`, `90°`, `180°`, `270°` | Display only. Writes an entry option, not a device command |

The active map defaults to the newest one the mower stores. Use the select to
change it.

## button

| Entity | Default | Does |
| --- | --- | --- |
| `button.*_stop_task` | on | Stop without sending the mower home |
| `button.*_locate` | on | Make it beep so you can find it |
| `button.*_clear_warning` | **off** | Acknowledge a latched warning |
| `button.*_reset_blade_counter` | **off** | Zero the blade maintenance counter |
| `button.*_reset_brush_counter` | **off** | Zero the brush counter |
| `button.*_reset_maintenance_counter` | **off** | Zero the robot counter |

Reset buttons ship disabled because zeroing a counter you have not actually
replaced a part for throws away real information. Enable the one you need.

## update

| Entity | Device class | Notes |
| --- | --- | --- |
| `update.*` | firmware | Install support |

The mower reports no progress, so an install is assumed to take up to a day before
the UI offers a retry. Unavailable until the cloud reports a version.

## Services

All nine take an optional `entry_id`. Omit it to target every configured mower —
handy for a one-mower account, and worth being explicit about when you have
several.

### `dreame_robot.mow_zones`

Mow saved lawn zones.

| Field | Required | Meaning |
| --- | --- | --- |
| `zone_ids` | yes | Zone identifiers, from the `zone_ids` attribute |
| `entry_id` | no | Limit to one mower |

```yaml
action: dreame_robot.mow_zones
data:
  zone_ids: [1, 2]
```

### `dreame_robot.mow_spots`

Mow saved spot areas. Same shape, with `spot_ids`.

### `dreame_robot.mow_edges`

Mow saved map edges. Each id is a `[edge, contour_index]` pair.

| Field | Required | Meaning |
| --- | --- | --- |
| `contour_ids` | yes | List of two-item integer lists |

```yaml
action: dreame_robot.mow_edges
data:
  contour_ids:
    - [1, 0]
    - [1, 1]
```

A single number is rejected — the contour index is required to identify the edge.

### `dreame_robot.mow_point`

Mow a patch at a coordinate. About 1.5 m².

| Field | Required | Default | Meaning |
| --- | --- | --- | --- |
| `x` | yes | — | Centimetres from the map origin |
| `y` | yes | — | Centimetres from the map origin |
| `passes` | no | `1` | 1–5 passes |

Coordinates come from the map card, or from `native_center` on any map polygon in
`map.json`.

### `dreame_robot.go_to`

Drive to a coordinate without mowing. `x` and `y` as above.

### `dreame_robot.switch_map`

Make the mower work on a different stored map. `map_index` is zero-based.

### `dreame_robot.remote_control`

Drive manually for one step. Both axes run `-1000` to `1000`.

| Field | Required | Meaning |
| --- | --- | --- |
| `velocity` | yes | Forward positive, back negative |
| `rotation` | yes | Left negative, right positive |

The command is a single step, not a hold. Call it repeatedly from a script or a
`repeat` loop to keep moving; anything out of range is rejected before it reaches
the device.

### `dreame_robot.stop_mowing`

Stop the current task without returning to the dock. No fields beyond
`entry_id`.

### `dreame_robot.reset_maintenance`

Zero a maintenance counter after replacing the part. `item` is `blade`, `brush`
or `robot`.

## Automations

### Only mow when nobody is home

```yaml
automation:
  - alias: Mow on weekday mornings when away
    triggers:
      - trigger: time
        at: "07:30:00"
    conditions:
      - condition: state
        entity_id: zone.home
        state: "off"
      - condition: state
        entity_id: binary_sensor.back_garden_problem
        state: "off"
      - condition: state
        entity_id: lawn_mower.back_garden
        state: "docked"
    actions:
      - action: lawn_mower.start_mowing
        target:
          entity_id: lawn_mower.back_garden
```

Checking `problem` first matters. A blocked lidar or a lifted mower will accept
the start command and then refuse to move.

### Notify when a fault appears

```yaml
automation:
  - alias: Alert on mower fault
    triggers:
      - trigger: state
        entity_id: binary_sensor.back_garden_problem
        to: "on"
    actions:
      - action: notify.mobile_app_phone
        data:
          title: Mower fault
          message: >-
            {{ states('sensor.back_garden_error') }}
            (code {{ state_attr('lawn_mower.back_garden', 'error_code') }})
```

### Mow specific zones on a schedule

```yaml
automation:
  - alias: Mow only the front zones on Sunday
    triggers:
      - trigger: time
        at: "09:00:00"
    conditions:
      - condition: day
        weekday: sun
    actions:
      - action: dreame_robot.mow_zones
        data:
          zone_ids: [1]
```

### Return before a storm

```yaml
automation:
  - alias: Come home when it starts raining
    triggers:
      - trigger: state
        entity_id: weather.home
        attribute: condition
        to: rainy
    actions:
      - action: lawn_mower.dock
        target:
          entity_id: lawn_mower.back_garden
```

### Send it to a spot when the lawn is walked on

```yaml
automation:
  - alias: Mow where the dog ran
    triggers:
      - trigger: state
        entity_id: binary_sensor.back_garden_task_active
        to: "off"
    actions:
      - action: dreame_robot.mow_point
        data:
          x: 1447
          y: 311
          passes: 2
```

### Notify when maintenance is due

```yaml
automation:
  - alias: Mower maintenance due
    triggers:
      - trigger: state
        entity_id: binary_sensor.back_garden_maintenance_due
        to: "on"
    actions:
      - action: persistent_notification.create
        data:
          message: >-
            The {{ state_attr('lawn_mower.back_garden', 'name') }} needs
            maintenance before its next full mow.
```
