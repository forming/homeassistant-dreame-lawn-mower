# Installation

Everything from a fresh Home Assistant install to a working mower with an
interactive map on a dashboard.

## Contents

- [Before you start](#before-you-start)
- [Install the integration](#install-the-integration)
- [Set up the map card](#set-up-the-map-card)
- [First-run walkthrough](#first-run-walkthrough)
- [Regions and accounts](#regions-and-accounts)
- [Options](#options)
- [Verifying it works](#verifying-it-works)
- [Troubleshooting](#troubleshooting)
- [Upgrading](#upgrading)
- [Uninstalling](#uninstalling)

## Before you start

You need:

| Requirement | Notes |
| --- | --- |
| Home Assistant 2024.12 or newer | Config-entry based; no YAML required |
| A Dreamehome or MOVAhome account | The one you sign into on your phone |
| A mower bound to that account | Bound in the vendor app, not here |
| A completed mapping run | The mower must have drawn its map at least once |

Check the last one first. Open the vendor app and look at the map tab. If it is
blank, the mower has never finished mapping, and this integration has nothing to
draw. Run a mapping job in the app before continuing.

The integration talks to the vendor's cloud, so it needs outbound HTTPS on port
443 and, for live updates, outbound TCP 8883.

```
Home Assistant ──HTTPS 443──▶ <region>.iot.dreame.tech:13267   (commands, state)
Home Assistant ──TLS  8883──▶ the broker named in the device record   (live push)
```

## Install the integration

### Option A — HACS (recommended)

1. Open HACS in Home Assistant.
2. Go to the ⋮ menu at the top of the HACS sidebar and choose **Custom
   repositories**.
3. Add this repository:
   - **Repository**: `https://github.com/dreame-robot/homeassistant-dreame-robot`
   - **Category**: *Integration*
4. Close and reopen HACS, search for **Dreame Robot**, and install it.
5. Restart Home Assistant. **This step is required** — HACS does not always load
   a newly installed integration without one.
6. Go to **Settings → Devices & Services → Add Integration** and pick **Dreame
   Robot**.

Home Assistant will download `paho-mqtt`, `pillow` and `requests` on first
setup. Watch the log the first time; it takes a few seconds.

### Option B — manual

1. Download this repository as a zip and unpack it, or clone it:

   ```bash
   git clone https://github.com/dreame-robot/homeassistant-dreame-robot.git
   ```

2. Copy the integration directory into your Home Assistant config directory:

   ```bash
   cp -r homeassistant-dreame-robot/custom_components/dreame_robot \
         /path/to/homeassistant/config/custom_components/
   ```

   You want this layout:

   ```
   config/
     custom_components/
       dreame_robot/
         __init__.py
         manifest.json
         ...
   ```

   Do **not** copy it as `custom_components/homeassistant-dreame-robot`. The
   directory name must be `dreame_robot`, because that is the integration
   domain.

3. Restart Home Assistant.
4. **Settings → Devices & Services → Add Integration → Dreame Robot**.

### Option C — configuration directory override

If you run Home Assistant with a non-default config directory, the path is
whatever you passed to `hass --config`. Put `dreame_robot` inside *that*
directory's `custom_components/`.

## Set up the map card

The interactive map card is a Lovelace custom card. It ships inside the
integration but must be registered as a resource before Lovelace will load it.
This is a one-time step; do it once per Home Assistant install.

1. Copy the card to your `www/` folder:

   ```bash
   mkdir -p /path/to/homeassistant/config/www
   cp custom_components/dreame_robot/www/dreame-robot-map-card.js \
      /path/to/homeassistant/config/www/dreame-robot-map-card.js
   ```

   Or, if you used HACS, find the file under
   `/config/www/` and check **File Editor → Show hidden files** if it does not
   appear.

2. Register the resource:

   **Settings → Dashboards → ⚙️ (three dots) → Resources → Add resource**

   | Field | Value |
   | --- | --- |
   | URL | `/local/dreame-robot-map-card.js` |
   | Type | **JavaScript module** |

   The URL must start with `/local/`. Home Assistant serves `config/www/` under
   that prefix, and browsers block Lovelace from loading resources from other
   origins.

3. Hard-reload your dashboard (⌘⇧R on macOS, Ctrl⇧R elsewhere). Browsers cache
   resource scripts aggressively, and a stale copy is the most common reason the
   card renders as an unknown element.

4. Add the card to a view:

   ```yaml
   type: custom:dreame-robot-map
   entity: lawn_mower.back_garden
   ```

   The `entity` is your lawn mower entity. Find it under
   **Settings → Devices & Services → Dreame Robot**, or in the developer tools
   state list.

### Card options

| Option | Type | Default | Meaning |
| --- | --- | --- | --- |
| `entity` | string | — | **Required.** The `lawn_mower` entity, or an `entry_id` via that option instead. |
| `title` | string | `Dreame mower` | Heading shown at the top left. |
| `refresh_interval` | number | `3` | Seconds between map refreshes. |

### If the card shows as unknown

| Symptom | Cause | Fix |
| --- | --- | --- |
| Card renders as a blank yellow box | Resource not registered, or wrong type | Check the URL starts with `/local/` and the type is **JavaScript module** |
| Card shows "No map stored on this mower yet" | Mower has never mapped | Run a mapping job in the vendor app |
| Card loads but the map is stale | Old script cached | Hard-reload the browser |
| `dreame-robot-map requires an 'entity' or 'entry_id'` | Missing `entity:` | Add it to the card YAML |

To see the real error, open the browser console (F12) and look for messages from
`dreame-robot-map-card.js`.

## First-run walkthrough

**Settings → Devices & Services → Add Integration → Dreame Robot**

The form has four fields:

| Field | Notes |
| --- | --- |
| **Brand** | `Dreamehome` for Dreame mowers, `MOVAhome` for MOVA-branded ones. |
| **Region** | The region your account was created in. See below. |
| **Email address** | Your Dreamehome/MOVAhome login. |
| **Password** | Sent to the vendor cloud to authenticate. Stored in your Home Assistant config entry, which lives in `.storage/core.config_entries`. |

If your account has several mowers, the next step asks which one to add. Add the
others by repeating the flow — each mower gets its own config entry, its own
entities and its own map endpoint.

When setup succeeds you should see a device named after your mower, containing
a `lawn_mower` entity and roughly thirty more.

## Regions and accounts

Region is part of the hostname, so a wrong value fails at DNS:

| Region | Host |
| --- | --- |
| `eu` | `eu.iot.dreame.tech` |
| `us` | `us.iot.dreame.tech` |
| `cn` | `cn.iot.dreame.tech` |
| `ru` | `ru.iot.dreame.tech` |
| `sg` | `sg.iot.dreame.tech` |

MOVA accounts use `*.iot.mova-tech.com` with the same region prefix.

**Which region?** The one your account was created in — the region you selected
when you first signed up to the vendor app. If you are unsure, try `eu`, then
`us`. If login fails with `cannot_connect` and you have not changed anything
else, region is the most likely cause.

Only the Chinese region sends the extra `Dreame-Rlc` routing header; the
integration adds it automatically.

**Account sharing.** If a second person has shared a mower with your account, it
appears in the device list like any other and can be added as its own entry.

**Two-factor authentication.** Not supported. If your account has 2FA enabled,
password login returns an error and there is no way to complete the flow. There
is nothing to configure here; disable 2FA on the account to use this
integration.

## Options

**Settings → Devices & Services → Dreame Robot → ⚙️ Configure**

| Option | Range | Default | Effect |
| --- | --- | --- | --- |
| **Polling interval** | 15–300 seconds | 60 | How often to re-read state from the cloud when no push messages arrive. |
| **Map rotation** | 0°, 90°, 180°, 270° | 0 | Display rotation of the rendered map. Does not affect the mower. |

You rarely need to change these. Live updates arrive over MQTT push, so polling
is a fallback; a 60-second interval with working push feels instant. Lower it if
push is unreliable, raise it if you want fewer cloud requests.

Map rotation is useful when the vendor app's north is not your north — common
when a map was drawn after the mower was moved. There is also a
`select.back_garden_map_rotation` entity if you would rather change it from a
dashboard.

Both options apply immediately, without reloading the integration.

## Verifying it works

Check these in order:

1. **The lawn mower entity exists and has a state.** If it is `unavailable`, the
   cloud is not answering — see [Troubleshooting](#troubleshooting).
2. **`sensor.*_battery` has a number.** This proves the property read worked.
3. **`image.<mower name>` renders a map.** Use it in a picture-entity card to
   check. If it renders, the map download and PNG renderer both work.
4. **The interactive card renders.** This proves the Lovelace resource is
   registered correctly.
5. **Live position moves.** Watch `sensor.*_position_x` while the mower runs.
   These are disabled by default — enable them in the entity settings first.

To enable a disabled entity: find it under
**Settings → Devices & Services → Dreame Robot → your mower → Entities**, click
it, and toggle it on. Or add this to `configuration.yaml`:

```yaml
homeassistant:
  entity:
    enabled:
      - integration: dreame_robot
        entity_id: sensor.back_garden_position_x
        disabled: false
```

## Troubleshooting

### Setup fails

| Error in the form | Meaning | Fix |
| --- | --- | --- |
| `cannot_auth` | Cloud rejected the email or password | Check you can sign into the vendor app. If your account uses 2FA, this integration cannot use it. |
| `cannot_connect` | Could not reach the cloud | Check internet access and try another region. |
| `invalid_region` | Unsupported region value | Should not happen; report it. |
| `no_devices` | Signed in, but no mower on the account | Bind the mower in the vendor app first, then retry. |
| Setup never finishes | Slow network to the vendor cloud | Wait; the login plus device list can take 30 seconds. |

### After setup, entities are unavailable

The integration logs the reason. Watch it with the
[Logger integration](https://www.home-assistant.io/integrations/logger/):

```yaml
logger:
  default: warning
  logs:
    custom_components.dreame_robot: debug
```

Common causes:

- **The access token expired and refresh failed.** Usually a password change or
  a revoked session. Re-authenticate:
  **Settings → Devices & Services → Dreame Robot → ⋮ → Reconfigure**, or the
  integration will ask for the password on its own.
- **The vendor cloud is down.** Nothing to do but wait. The integration keeps the
  last good state readable for five minutes before entities go unavailable, so
  brief outages are invisible.
- **The mower is offline.** A mower that has lost Wi-Fi stops publishing state.

### Live updates do not arrive

Live updates come over MQTT, separate from the HTTPS polling path. If state
updates every minute but nothing is instant, push is not connected.

- `binary_sensor.*_live_updates` tells you directly whether the push channel is
  up.
- Push needs outbound TCP 8883 to whatever host is in the device's
  `bindDomain`. Some networks block that. Polling still works.
- The broker presents a chain rooted in GlobalSign Root CA, which is bundled with
  the integration, so no system CA install is needed.

### No map

| Symptom | Cause |
| --- | --- |
| `No map stored on this mower yet` | The mower has never finished mapping |
| `image.*` renders but is blank | The mower has a map with no drawable geometry |
| The map is from a different lawn | The integration defaults to the newest stored map; use the `map` select entity to switch |
| Zones have no names | The zones were drawn without names in the vendor app; the card falls back to `Zone <id>` |

### Commands do nothing

- Check `sensor.*_error`. A fault-tier device code blocks mowing until it is
  resolved — a blocked lidar, a lifted mower or a battery that is too hot.
- The log records the device's response. `r != 0` means the mower rejected the
  command; the code is in the log line.
- Zone and edge mowing need identifiers from the current map. Read them from the
  `zone_ids` and `spot_ids` attributes on the lawn mower entity, or from the card.

### The mower reports the wrong state

The state comes from the vendor's own `2.1` property, decoded through a table in
`client/models.py`. Some firmware families renumber codes. If your model is
wrong, add it to `STATE_OVERRIDES` and open a pull request — see
[CONTRIBUTING.md](../CONTRIBUTING.md).

Check `sensor.*_state` for the decoded name and the `state_code` attribute on the
lawn mower entity for the raw value. Report the pair if they disagree.

## Upgrading

Through HACS: **HACS → Dreame Robot → Update**, then restart Home Assistant.

Manually: pull the repository, copy `custom_components/dreame_robot` over the
existing one, and restart.

Entity ids and unique ids are stable across upgrades. Renaming or recreating a
config entry will orphan entities and leave stale ones behind — use **Reload**
(**⋮ → Reload**) instead of delete-and-re-add when you only need to re-run setup.

## Uninstalling

1. **Settings → Devices & Services → Dreame Robot**, select the entry,
   **⋮ → Delete**.
2. Restart Home Assistant.

That removes the entities, the config entry and the stored credentials.

You can also remove the card, but it is harmless on its own — it shows a
"waiting for the mower" placeholder once the integration is gone. Delete
`config/www/dreame-robot-map-card.js` and remove the Lovelace resource to
tidy up.

Nothing uninstalls on the vendor side. The integration never writes to the
account except the settings you change here.
