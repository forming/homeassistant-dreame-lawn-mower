# How the protocol works

An in-depth description of the Dreame/MOVA cloud protocol this integration
speaks, and how the integration is built around it.

This is reverse-engineered from the vendor's mobile app and firmware. Nothing
here is documented by the vendor. Treat it as a working model that may be
incomplete — see [Limitations](#limitations).

Everything described below is implemented in `custom_components/dreame_robot/client/`,
which imports nothing from Home Assistant and is tested on its own.

## Contents

- [The big picture](#the-big-picture)
- [Authentication](#authentication)
- [Reading device state](#reading-device-state)
- [Live updates over MQTT](#live-updates-over-mqtt)
- [Sending commands](#sending-commands)
- [Two command planes](#two-command-planes)
- [The map subsystem](#the-map-subsystem)
- [Framed binary payloads](#framed-binary-payloads)
- [State and error decoding](#state-and-error-decoding)
- [Settings and maintenance](#settings-and-maintenance)
- [Design decisions](#design-decisions)
- [Limitations](#limitations)

## The big picture

Everything goes through the vendor's cloud. There is no local/LAN control path —
the earlier `python-miio` LAN protocol these products inherited from their vacuum
lineage is dead code in the firmware.

Two transports:

| Transport | Direction | Used for |
| --- | --- | --- |
| HTTPS + JSON | both | Login, device discovery, property reads, every command |
| MQTT over TLS, subscribe only | vendor → us | Live state, battery, position, task progress |

Commands are never published to MQTT. That keeps the write path in one place, so
there is a single retry and error-handling policy.

```
                        ┌──────────────────────────────────┐
                        │  <region>.iot.dreame.tech:13267  │
  Home Assistant  ──────▶│  /dreame-auth/oauth/token        │
       │                │  /dreame-user-iot/iotstatus/props│
       │                │  /dreame-user-iot/iotuserdata/…  │◀── commands
       │                │  /dreame-iot-com-<label>/…       │
       │                └──────────────────────────────────┘
       │
       │  subscribe only
       ▼
  mqtt.<host from device record>:8883
  topic /status/<did>/<masterUid>/<model>/<region>/
```

## Authentication

`client/cloud.py`. Two endpoints, both `POST`.

### Step 1 — sign in

```
POST https://<region>.iot.dreame.tech:13267/dreame-auth/oauth/token
Content-Type: application/x-www-form-urlencoded
```

The body is a hand-assembled form string:

```
platform=IOS&scope=all&grant_type=password&username=<EMAIL>&password=<HASH>&type=account
```

`HASH` is the account password with a fixed vendor salt appended, hashed with
MD5, hex-encoded:

```python
md5(password + "RAylYC%fmSKp7%Tq").hexdigest()
```

MD5 here is not a choice — it is what the app does. The integration does the same
rather than trying to be smarter, because the cloud compares the hex digest.

Headers matter too:

| Header | Value | Why |
| --- | --- | --- |
| `Authorization` | `Basic ZHJlYW1lX2FwcHYxOkFQXmR2QHpAU1FZVnhOODg=` | Public app credentials the cloud expects |
| `User-Agent` | `Dreame_Smarthome/1.5.59 (iPhone; iOS 16.0; Scale/3.00)` | The cloud gates features on this |
| `Tenant-Id` | `000000` (Dreame) or `000002` (MOVA) | Account tenancy |
| `Dreame-Rlc` | a fixed token | **Only** for the `cn` region |

The response yields:

| Field | Used as |
| --- | --- |
| `access_token` | `Dreame-Auth` header on later calls, **and** the MQTT password |
| `refresh_token` | The body of the next login, and the way back after a `401` |
| `expires_in` | Token lifetime; refresh 120 seconds early |
| `uid` | The MQTT username, and the object path segment |
| `tenant_id` | Overrides the default tenant header |

### Step 2 — refresh

```
platform=IOS&scope=all&grant_type=refresh_token&refresh_token=<REFRESH_TOKEN>
```

If the refresh token has been revoked, the cloud returns an
`error_description` mentioning it. The integration then discards it and repeats
the login with the password, rather than stranding the account.

There is no 2FA path. A 2FA-protected account cannot be used.

## Reading device state

`POST /dreame-user-iot/iotstatus/props`

```json
{"did": "<device id>", "keys": ["2.1", "3.1", "4.1", "…"]}
```

Properties are addressed as `siid.piid` (MIoT-style service/interface/property
triples, inherited from the vacuum platform). One request reads many keys; the
response is a list of `{key, value, updateDate}` records.

The polled set is `POLL_PROPERTIES` in `client/const.py`:

| Key | Meaning |
| --- | --- |
| `2.1` | Mower state |
| `2.2` | Device code (the error/notice code) |
| `3.1` | Battery level |
| `3.2` | Charging |
| `4.1` | Task started |
| `4.17` | Paused |
| `4.23` | Mowing mode |
| `4.2` | Session mowing time |
| `4.3` | Session mowed area |
| `4.63` | Task progress |
| `2.50` | Task status, as a small JSON string |
| `12.2` | Lifetime mowing time |
| `12.4` | Lifetime mowed area |

Deliberately short. Each extra key is extra bytes on every poll, and the keys
above are the ones that change often enough to matter. Everything else — model,
serial, capabilities — is stable and is read once at setup.

`POST /dreame-user-iot/iotuserbind/device/listV2` returns the account's devices.
The integration filters to models containing `.mower.`, which excludes the vacuums,
air purifiers and fans that share the same cloud and the same account.

## Live updates over MQTT

`client/mqtt.py`. The channel is subscribe-only.

| Setting | Value | Notes |
| --- | --- | --- |
| Broker | from the device record's `bindDomain` | e.g. `mqtt.eu.dreame.tech:8883` |
| Username | `uid` from login | |
| Password | `access_token` from login | Rotates with the token |
| Client id | `p_<masterUid>_<13 random A–F>_<first host label>` | |
| Keepalive | 50 s | |
| QoS | 0 | Matches the app |
| Clean session | yes | |
| Topic | `/status/<did>/<masterUid>/<model>/<region>/` | One subscription |

The broker serves a chain rooted in GlobalSign Root CA, which is not in most
system trust stores. The integration bundles that certificate
(`client/certs/vendor_root_ca.pem`) and builds an SSL context from it, so no
system-wide CA install is needed. `VERIFY_X509_STRICT` is cleared because the
vendor's leaf certificate omits the Authority Key Identifier — chain and hostname
verification stay on.

Payloads are plain UTF-8 JSON. No encryption, no base64:

```json
{
  "method": "properties_changed",
  "params": [
    {"siid": 2,  "piid": 1,  "value": 1},
    {"siid": 3,  "piid": 1,  "value": 77},
    {"siid": 1,  "piid": 4,  "value": [206, 0, 206, "…"]},
    {"siid": 2,  "piid": 50, "value": "{\"d\":{\"exe\":true,\"o\":6},\"t\":\"TASK\"}"}
  ]
}
```

The handler matches `(siid, piid)` against known keys, folds values into a local
cache and fires an update callback. That callback is bridged onto the Home
Assistant event loop, and the coordinator publishes a snapshot built purely from
cache — no network call, so a push costs nothing but a dict copy.

The two keys worth singling out:

| Key | Content |
| --- | --- |
| `1.4` | Framed runtime payload: live pose, heading, travel trail, mission progress |
| `2.2` | Device code — how the vendor reports faults |

Because push arrives whenever the mower has something to say, polling is only a
fallback for when the channel is blocked. That is why the default polling
interval is a relaxed 60 seconds.

## Sending commands

`POST /dreame-iot-com-<label>/device/sendCommand`

`<label>` is the first dot-separated label of the device's `bindDomain`, e.g.
`bindDomain: mqtt.eu.dreame.tech` gives `/dreame-iot-com-mqtt/device/sendCommand`.

Every command is wrapped in a doubled-id envelope:

```json
{
  "did": "1234567890",
  "id": 42,
  "data": {
    "did": "1234567890",
    "id": 42,
    "method": "action",
    "params": {"did": "1234567890", "siid": 5, "aiid": 1, "in": []}
  }
}
```

`id` is a counter seeded from `random.randint(1, 100)` and incremented per
command, repeated at both nesting levels. There is no client-side request
correlation and no pending-response table — correlation is the cloud's job and the
HTTP response *is* the device's answer:

```json
{"code": 0, "success": true, "data": {"result": {…}}}
```

Error codes seen in the wild:

| Code | Meaning | Handling |
| --- | --- | --- |
| `0` | Success | |
| `80001` | Cloud accepted it, the device did not answer in time | Raised as a rejection — never treated as success |
| `10007` | Interim/OSS file not ready | Raised with the code preserved |

## Two command planes

The generation matters, because it decides how a command is encoded.

### Legacy MIoT actions (A1 generation)

Plain `siid`/`aiid` pairs:

| Command | `siid` | `aiid` |
| --- | --- | --- |
| Start mowing | 5 | 1 |
| Stop | 5 | 2 |
| Return to dock | 5 | 3 |
| Pause | 5 | 4 |
| Clear warning | 4 | 3 |
| Locate | 7 | 1 |

### App bridge (A2, A3, MOVA, VIAX, LiDAX)

Everything goes through one action — `siid=2`, `aiid=50` — carrying a payload
that names a verb:

| Verb | Meaning | Shape |
| --- | --- | --- |
| `m: "g"` | read | `{"m":"g","t":"TYPE","d":{…}}` |
| `m: "s"` | write | `{"m":"s","t":"TYPE","d":{…}}` |
| `m: "a"` | action | `{"m":"a","p":0,"o":<opcode>,"d":{…}}` |

Responses use `r` for the result code and `d` for the payload, and `d` may nest
another `r`/`d` pair.

Mowing opcodes:

| Opc | Target key | Meaning |
| --- | --- | --- |
| `101` | `edge` | Mow map edges, as `[edge, contour]` pairs |
| `102` | `region` | Mow saved lawn zones |
| `103` | `area` | Mow saved spot areas |
| `109` | `point` | Drive through maintenance points (max 5) |

So a zone-mowing command is:

```json
{"m": "a", "p": 0, "o": 102, "d": {"region": [1, 2]}}
```

### Custom tasks (start custom)

Ad-hoc spots and drive-to-point use the legacy action `siid=4, aiid=1` with two
`piid` slots:

```json
{"siid": 4, "aiid": 1, "in": [
  {"piid": 1,  "value": 20},
  {"piid": 10, "value": "{\"points\":[[400,250,2]]}"}
]}
```

The status code says which task: `20` is spot mowing, `23` is drive-to-point.

### Manual drive

Not an action — a property write on `4.15` carrying a JSON string, where both
axes run from `-1000` to `1000`:

```json
{"spdv": 400, "spdw": -300, "audio": "false", "random": 0}
```

## The map subsystem

`client/device.py` and `client/models.py`. Detailed in
[maps.md](maps.md); the short version:

Map geometry arrives as vector polygons inside the device's **batch text payload**:

```
POST /dreame-user-iot/iotuserdata/getDeviceData
{"did": "<did>", "model": ["MAP", "M_PATH"]}
```

Note the request key is literally `model` even though it holds the requested
property prefixes. The response is flat text:

| Key | Content |
| --- | --- |
| `MAP.0`, `MAP.1`, … | Chunks of a double-encoded JSON blob |
| `MAP.info` | Character offset splitting the first map from the rest |
| `M_PATH.*` | The historical mowing trail |

Reassembly joins the chunks in numeric order, splits at the `MAP.info` offset,
then unwraps a JSON array of JSON strings — one string per map.

Each map object carries `mowingAreas`, `forbiddenAreas`, `spotAreas`, `paths`,
`contours`, `cruisePoints`, `obstacles`, `mapIndex`, `name` and `totalArea`.
Every collection uses the same envelope:

```json
{"dataType": "Map", "value": [[1, {"name": "Zone A", "path": [{"x": 0, "y": 0}, …]}]]}
```

Three shapes arrive inside those objects and are expanded at parse time:

| `shapeType` | Meaning | Expansion |
| --- | --- | --- |
| 1 | Polygon | Used as-is |
| 2 | Rotated rectangle | Rotated about its centroid by `-angle` |
| 3 | Circle | Bounding box expanded to 36 points |

Coordinates are centimetres in a mirrored frame — X increases west, Y increases
north. [maps.md](maps.md) covers the projection in full.

## Framed binary payloads

Two byte-array properties carry information that does not fit in JSON.

Both start and end with `0xCE`. The integration calls this `FRAME_MARKER`.

### `1.1` — heartbeat, 20 bytes

| Offset | Meaning |
| --- | --- |
| 0 | `0xCE` |
| 11 | Battery. Bit 7 set means charging; the low 7 bits are the percentage |
| 12 | Main state in the low nibble (`- 1`). `4` means an active task |
| 13 | Sub-state; `sub - 33` indexes the task status |
| 14 | Docking state in bits 2–4 |
| 19 | `0xCE` |

Task status index: `0` idle, `1` starting, `2` mowing, `3` paused, `4` finished,
`5` failed, `6` exit, `7` returning to dock.

A3 firmware appends two bytes, making a 22-byte heartbeat. Only its observed
idle-in-station form is decoded; anything else is left alone rather than guessed
at.

### `1.4` — runtime telemetry

A 13, 22, 33 or 44 byte frame carrying the live pose.

**Pose.** Six bytes hold two signed 20-bit centimetre coordinates that *overlap*
— each axis starts 12 bits into a 24-bit window, so X and Y share bytes:

```
raw_x = ((b2 << 28) | (b1 << 20) | (b0 << 12)) & 0xFFFFFFFF
raw_y = ((b4 << 24) | (b3 << 16) | (b2 << 8))  & 0xFFFFFFFF
x     = sign_extend(raw_x) >> 12  × 10
y     = sign_extend(raw_y) >> 12  × 10
heading = round(b5 / 255 × 360, 1)
```

**Trail.** From offset 7, `(15 - 3) / 4 = 3` pairs of signed little-endian
`int16` deltas, relative to the pose, scaled by 10. A pair where both magnitudes
exceed 32766 marks a discontinuity and starts a new polyline. A 44-byte frame
carries a second run at offset 32.

**Mission block.** 33- and 44-byte frames carry a 10-byte tail at offset 22:
region id, task id, progress as `int16 / 10`, and two 24-bit area counters in
hundredths of a square metre.

This is what puts a live marker on the map. Without it, the map is a picture;
with it, it is a position.

## State and error decoding

### Activity

The raw `2.1` state decodes to a name, which collapses onto one of Home
Assistant's five activities. The precedence is deliberate:

1. **A fault-tier device code wins.** Error outranks the state field, which can
   lag by seconds.
2. `returning` plus a confirmed dock or charge flag means the mower is `docked`,
   not returning — the app lags here.
3. Then paused, returning, the mowing set, and the docked set.
4. Boolean property fallbacks last.

Unknown state codes fall through to `idle`. They never become `mowing`.

`mapping` counts as mowing. The mower is working; showing it as idle would be a
lie.

Some firmware families renumber codes — VIAX 500 reuses 15, 16 and 19 for
`repositioning`. Those overrides live in `STATE_OVERRIDES` and are model-keyed.

### Device codes

`2.2` carries a numeric code, or `-1` for healthy. The table in
`_DEVICE_CODES` maps codes to a name and a severity tier:

| Tier | Effect |
| --- | --- |
| `error` | Activity becomes `error`, `problem` binary sensor turns on |
| `alert` | Reported, does not error the mower |
| `attention` | Reported, does not error the mower |
| `info` | Reported as a status notice |

The split matters. Reporting a "mowing started" notice as an error would make the
integration cry wolf. Model families can override individual entries — A2 firmware
reuses code `0` for "robot lifted", which is an error, while elsewhere `0` means
"no code".

An unrecognised code becomes `unknown_device_code_<n>` at `attention` tier. It is
named, never invented.

## Settings and maintenance

Settings come from one app-bridge read, `{"m": "g", "t": "CFG"}`, returning a
list of records tagged by type. The integration indexes them by tag:

| Tag | Shape | Entities |
| --- | --- | --- |
| `VOL` | `{"value": int}` | Voice volume |
| `WRP` | `{"value": bool, "time": hours, "sen": int}` | Rain protection, after-rain delay |
| `BAT` | `{"value": [enabled, start_minute, end_minute]}` | Charging window |
| `VOICE` | `{"value": [4 ints]}` | Four voice prompt groups |

Writes send the whole record back, because the read-modify-write is unavoidable
and the device has no partial-update form.

Maintenance counters come from `{"m": "g", "t": "CMS"}`, three minutes-used
values against fixed intervals: blade 6000, brush 30000, robot 3600. Resetting
zeroes one slot and re-sends all three, preserving the others.

Firmware status comes from `/dreame-user-iot/iotuserbind/checkDeviceVersion`,
which drives the `update` entity.

## Design decisions

Three rules shaped the code. Each is documented where it matters, so they survive
edits.

**Mutations are never retried.** A duplicated write can apply twice on the
device — mowing a zone twice, resetting a counter twice, toggling a setting back
to where it started. Reads (`m: "g"`) retry; writes (`m: "s"`) and actions
(`m: "a"`) do not. The cost is that a transient failure surfaces as an error
rather than resolving itself, which is the honest outcome.

**A `401` is always safe to retry.** It proves the cloud rejected the request
before it reached the device, so re-authenticating and sending it again cannot
double-apply anything. This is the one exception, and it applies to mutations too.

**Unknown means unknown.** An unrecognised device code is named, not guessed. An
unrecognised state falls back to idle. An unrecognised frame shape is skipped
rather than decoded optimistically. The protocol is undocumented and the
firmware changes; anything that fabricates meaning will eventually be wrong in a
way that is hard to notice.

Two smaller ones:

- **A clean MQTT session clears the cache.** On reconnect, cached timestamps
  belong to a transport epoch that has ended and cannot establish freshness.
- **Settings, maintenance and OTA have their own TTLs** (300 s and 3600 s). They
  change when a human opens the app, so polling them every cycle would be waste.

## Limitations

Stated plainly, because a protocol model that hides its edges is worse than one
that admits them.

| Not supported | Why |
| --- | --- |
| **Live video** | The vendor streams over a proprietary peer-to-peer transport that needs a native helper binary. |
| **Cutting-height write** | The write path is an encoded preference blob this project does not decode. Reads happen; writes are refused rather than guessed. |
| **Schedule editing** | Reads work, but a malformed write could corrupt a schedule the user depends on. |
| **Legacy A1 binary map** | A grid format behind AES-CBC and zlib with a 27-byte header. A1 mowers get state, battery and commands but no map. |
| **Per-zone height and direction** | Same encoded preference blob. |
| **Two-factor accounts** | There is no 2FA flow to complete. |
| **Point clouds** | A separate export request producing a large binary. |

None of these are stubbed out to look present. An entity is only created when the
setting is one the device actually reported.

### Contributing to the protocol layer

The parts most likely to need model-specific fixes are the two tables in
`client/models.py`:

- `STATE_NAMES` and `STATE_OVERRIDES` — state decoding
- `_DEVICE_CODES` and `_DEVICE_CODE_OVERRIDES` — error decoding

Both are plain dictionaries with a test each. Adding a model means adding a row
and proving the override wins. See [CONTRIBUTING.md](../CONTRIBUTING.md).
