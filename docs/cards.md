# Cards

YAML for the interactive map card and the standard cards that pair with it.

## Contents

- [The map card](#the-map-card)
- [Options](#options)
- [Stacking with other cards](#stacking-with-other-cards)
- [A minimal dashboard](#a-minimal-dashboard)
- [A full dashboard](#a-full-dashboard)
- [Floorplan and picture cards](#floorplan-and-picture-cards)
- [Manual driving](#manual-driving)
- [Blueprints](#blueprints)

## The map card

```yaml
type: custom:dreame-robot-map
entity: lawn_mower.back_garden
```

Registration is the one-time setup in
[installation.md → Set up the map card](installation.md#set-up-the-map-card).

### What it draws

| Element | Meaning | Tappable |
| --- | --- | --- |
| Green | A lawn zone | Yes — mows that zone |
| Blue | A spot area | Yes — mows that spot |
| Dark red | A no-go area | No |
| Orange dashed | A map edge | Yes — mows that edge |
| Yellow dashed | A navigation path | No |
| Yellow solid | The travel trail | No |
| Grey dots | Cruise points | No |
| White triangle | The mower, pointing where it faces | No |

Tapping a zone, spot or edge selects it and swaps the action row for
"Mow *that*". Tapping bare lawn selects a coordinate and offers both "Mow here"
and "Drive here".

The mower marker only appears when the device is publishing live position. A
mower on A1-generation firmware, or one whose firmware omits the runtime frame,
still draws everything else.

### Action row

Always present:

| Button | Service |
| --- | --- |
| Start mowing | `lawn_mower.start_mowing` |
| Pause | `lawn_mower.pause` |
| Dock | `lawn_mower.dock` |
| Stop | `dreame_robot.stop_mowing` |

Added when something is selected:

| Selection | Buttons |
| --- | --- |
| A zone | `Mow Zone A` |
| A spot area | `Mow Under tree` |
| An edge | `Mow Edge 1.0` |
| Bare lawn | `Mow here (x, y)` and `Drive here` |

"Stop" uses the integration's own service rather than a button entity, so it works
even if the button is not created.

## Options

| Option | Type | Default | Notes |
| --- | --- | --- | --- |
| `entity` | string | — | **Required.** The `lawn_mower` entity. Alternatively pass `entry_id` |
| `title` | string | `Dreame mower` | Heading |
| `refresh_interval` | number | `3` | Seconds between map refreshes |

A complete example:

```yaml
type: custom:dreame-robot-map
entity: lawn_mower.back_garden
title: Back garden
refresh_interval: 5
```

Refresh interval trades freshness against cloud requests. Three seconds is
responsive and cheap — the endpoint reads cached geometry and only re-renders
when the mower's pose changed. Ten seconds is plenty for a parked mower.

## Stacking with other cards

The card reads the map geometry from `map.json` and mower state from the entity,
so it shows current values without extra configuration. Pair it with the standard
entities for detail.

### Status at a glance

```yaml
type: entities
title: Back garden
entities:
  - entity: lawn_mower.back_garden
  - entity: sensor.back_garden_battery
  - entity: sensor.back_garden_session_area
  - entity: sensor.back_garden_task_progress
  - entity: binary_sensor.back_garden_problem
```

### Primary controls as buttons

```yaml
type: horizontal-stack
cards:
  - show_icon: true
    show_name: false
    type: button
    entity: lawn_mower.back_garden
    icon: mdi:play
    tap_action:
      action: call-service
      service: lawn_mower.start_mowing
  - show_icon: true
    show_name: false
    type: button
    entity: lawn_mower.back_garden
    icon: mdi:pause
    tap_action:
      action: call-service
      service: lawn_mower.pause
  - show_icon: true
    show_name: false
    type: button
    entity: lawn_mower.back_garden
    icon: mdi:home-import-outline
    tap_action:
      action: call-service
      service: lawn_mower.dock
  - show_icon: true
    show_name: false
    type: button
    entity: button.back_garden_stop_task
    icon: mdi:stop
```

### Settings

```yaml
type: entities
title: Back garden settings
show_header_toggle: false
entities:
  - entity: number.back_garden_voice_volume
  - entity: number.back_garden_after_rain_delay
  - entity: switch.back_garden_rain_protection
  - entity: switch.back_garden_charging_window
  - type: divider
  - entity: switch.back_garden_general_voice_prompts
  - entity: switch.back_garden_working_voice_prompts
  - entity: switch.back_garden_status_voice_prompts
  - entity: switch.back_garden_fault_voice_prompts
```

### Errors and maintenance

```yaml
type: entities
title: Back garden health
show_header_toggle: false
entities:
  - entity: binary_sensor.back_garden_problem
  - entity: sensor.back_garden_error
  - entity: sensor.back_garden_status_notice
  - type: divider
  - entity: binary_sensor.back_garden_maintenance_due
  - entity: binary_sensor.back_garden_maintenance_due_soon
  - entity: binary_sensor.back_garden_live_updates
```

## A minimal dashboard

Enough to control the mower and see what it is doing.

```yaml
views:
  - title: Mower
    path: mower
    cards:
      - type: custom:dreame-robot-map
        entity: lawn_mower.back_garden
        title: Back garden

      - type: entities
        entities:
          - entity: sensor.back_garden_battery
          - entity: sensor.back_garden_task_progress
          - entity: sensor.back_garden_session_area
```

## A full dashboard

```yaml
views:
  - title: Mower
    path: mower
    cards:
      - type: custom:dreame-robot-map
        entity: lawn_mower.back_garden
        title: Back garden
        refresh_interval: 3

      - type: horizontal-stack
        cards:
          - show_icon: true
            show_name: false
            type: button
            entity: lawn_mower.back_garden
            icon: mdi:play
            tap_action:
              action: call-service
              service: lawn_mower.start_mowing
          - show_icon: true
            show_name: false
            type: button
            entity: lawn_mower.back_garden
            icon: mdi:pause
            tap_action:
              action: call-service
              service: lawn_mower.pause
          - show_icon: true
            show_name: false
            type: button
            entity: lawn_mower.back_garden
            icon: mdi:home-import-outline
            tap_action:
              action: call-service
              service: lawn_mower.dock
          - show_icon: true
            show_name: false
            type: button
            entity: button.back_garden_stop_task
            icon: mdi:stop

      - type: entities
        title: This run
        show_header_toggle: false
        entities:
          - entity: sensor.back_garden_state
          - entity: sensor.back_garden_mowing_mode
          - entity: sensor.back_garden_session_mowing_time
          - entity: sensor.back_garden_session_area
          - entity: sensor.back_garden_task_progress
          - entity: sensor.back_garden_task_status

      - type: entities
        title: Lifetime
        show_header_toggle: false
        entities:
          - entity: sensor.back_garden_total_mowing_time
          - entity: sensor.back_garden_total_mowed_area
          - entity: sensor.back_garden_stored_maps
          - entity: sensor.back_garden_zones_on_current_map

      - type: entities
        title: Health
        show_header_toggle: false
        entities:
          - entity: binary_sensor.back_garden_problem
          - entity: sensor.back_garden_error
          - entity: binary_sensor.back_garden_maintenance_due
          - entity: binary_sensor.back_garden_maintenance_due_soon
          - entity: binary_sensor.back_garden_live_updates

      - type: entities
        title: Settings
        show_header_toggle: false
        entities:
          - entity: select.back_garden_map
          - entity: select.back_garden_map_rotation
          - entity: number.back_garden_after_rain_delay
          - entity: switch.back_garden_rain_protection
          - entity: switch.back_garden_charging_window
          - entity: number.back_garden_voice_volume

  - title: Automation
    path: automation
    cards:
      - type: entities
        title: Schedules
        entities:
          - entity: automation.mow_on_weekday_mornings
```

## Floorplan and picture cards

If you would rather not install the custom card, the `image` entity works
anywhere an image is accepted.

### Picture entity

```yaml
type: picture-entity
entity: image.back_garden
name: Back garden
```

### Floorplan

The image entity has no camera or device tracker to attach, so it will not place
itself. Point at it explicitly:

```yaml
type: floorplan
entities:
  - entity: image.back_garden
    height: 60%
```

The PNG is redrawn when the mower's pose changes, so it works like a static map
with a live marker — but it is not interactive. For tap-to-mow, install the custom
card.

## Manual driving

The `remote_control` service is a single step, not a hold. Each call nudges the
mower once, and the last command is all it keeps — so there is nothing to release.

```yaml
type: horizontal-stack
cards:
  - type: button
    icon: mdi:arrow-left
    tap_action:
      action: call-service
      service: dreame_robot.remote_control
      data:
        velocity: 0
        rotation: -400
  - type: button
    icon: mdi:arrow-up
    tap_action:
      action: call-service
      service: dreame_robot.remote_control
      data:
        velocity: 400
        rotation: 0
  - type: button
    icon: mdi:arrow-down
    tap_action:
      action: call-service
      service: dreame_robot.remote_control
      data:
        velocity: -400
        rotation: 0
  - type: button
    icon: mdi:arrow-right
    tap_action:
      action: call-service
      service: dreame_robot.remote_control
      data:
        velocity: 0
        rotation: 400
```

Switch `tap_action` to `hold_action` with `action: repeat` if you want a
continuous turn, but weigh that first: a mower's obstacle avoidance assumes
nobody is steering it, and the vendor app does not expose manual driving as a
supported feature either. `dreame_robot.stop_mowing` is the reliable stop.

## Blueprints

Two automations worth having from day one. Both live in
**Settings → Automations & Scenes → Blueprints**.

### Guarded scheduled mowing

```yaml
blueprint:
  name: Mower - scheduled mowing with guards
  description: >-
    Start mowing on a schedule only if nobody is home, the mower is docked and
    there is no active fault.
  domain: automation
  input:
    time:
      name: Time
      default: "07:30:00"
      selector:
        time:
    days:
      name: Days
      default: [mon, tue, wed, thu, fri]
      selector:
        select:
          multiple: true
          options: [mon, tue, wed, thu, fri, sat, sun]
    mower_entity:
      name: Mower entity
      default: lawn_mower.mower
      selector:
        entity:
          domain: lawn_mower
    problem_entity:
      name: Problem sensor
      default: binary_sensor.mower_problem
      selector:
        entity:
          domain: binary_sensor
    zone_ids:
      name: Zone ids to mow (blank means the whole lawn)
      default: []
      selector:
        object:

mode: single

trigger:
  - platform: time
    at: !input time

condition:
  - condition: day
    weekday: !input days
  - condition: state
    entity_id: !input mower_entity
    state: docked
  # Worth the line: a blocked lidar or a lifted mower accepts a start command
  # and then refuses to move, so without this the run silently never happens.
  - condition: state
    entity_id: !input problem_entity
    state: "off"
  - condition: numeric_state
    entity_id: sensor.mower_battery
    above: 20
  - condition: state
    entity_id: zone.home
    state: "off"

action:
  - choose:
      - conditions:
          - condition: template
            value_template: "{{ zone_ids | count > 0 }}"
        sequence:
          - service: dreame_robot.mow_zones
            data:
              zone_ids: !input zone_ids
    default:
      - service: lawn_mower.start_mowing
        target:
          entity_id: !input mower_entity
```

Set **Zone ids** to `[1, 2]` for a targeted run, or leave it empty for the whole
lawn. Take the ids from the `zone_ids` attribute on the lawn mower entity, or
from the map card.


### Fault notifications

```yaml
blueprint:
  name: Mower - fault notification
  description: Notify when the mower reports a fault, and again when it clears.
  domain: automation
  input:
    notify_service:
      name: Notify service
      default: notify.persistent_notification
      selector:
        text:

mode: triggered

trigger:
  - platform: state
    entity_id: binary_sensor.mower_problem
    to: "on"
    id: raised
  - platform: state
    entity_id: binary_sensor.mower_problem
    to: "off"
    id: cleared

action:
  - choose:
      - conditions: "{{ trigger.id == 'raised' }}"
        sequence:
          - service: !input notify_service
            data:
              title: Mower needs attention
              message: >-
                {{ states('sensor.mower_error') }}
                (code {{ state_attr('lawn_mower.mower', 'error_code') }}).
                Clear the fault with button.mower_clear_warning.
      - conditions: "{{ trigger.id == 'cleared' }}"
        sequence:
          - service: !input notify_service
            data:
              title: Mower fault cleared
              message: The mower is running normally again.
```

`button.mower_clear_warning` is disabled by default. Enable it in the entity
settings if you want to clear faults from a dashboard.
