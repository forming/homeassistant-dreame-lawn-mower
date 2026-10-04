# Maps

How the map subsystem works, from the vendor's wire format to the pixels on your
dashboard. This is the part that makes a mower integration different from a
vacuum one, so it is worth understanding if you ever need to debug it.

## Contents

- [Where the map comes from](#where-the-map-came-from)
- [The batch payload](#the-batch-payload)
- [Collections](#collections)
- [Compact shapes](#compact-shapes)
- [Coordinate system](#coordinate-system)
- [The projection](#the-projection)
- [Multiple maps](#multiple-maps)
- [Rendering the PNG](#rendering-the-png)
- [The map.json endpoint](#the-mapjson-endpoint)
- [Caching](#caching)
- [Why no map for some models](#why-no-map-for-some-models)

## Where the map came from

Three sources exist in the vendor ecosystem. This integration uses one of them,
on purpose.

| Source | Format | Used here |
| --- | --- | --- |
| Vector polygons in the cloud batch payload | JSON polygons | **Yes** — this is the map |
| Chunked app-bridge map (`MAPL`/`MAPI`/`MAPD`) | Chunked JSON | No |
| Legacy binary grid map | AES-CBC + zlib + a 27-byte header | No |

The vector payload gives clean named polygons, areas and paths in one request,
and it is the only source that does not need per-map chunked transfers with
hash verification. It also happens to be the one the current firmware writes for
every model this integration supports.

The legacy binary grid is a large amount of work for the older A1-generation
mowers only, and it cannot be verified without one of those in hand. It is not
implemented. Those mowers get state, battery, errors and commands, but no map.

## The batch payload

`POST /dreame-user-iot/iotuserdata/getDeviceData`

```json
{"did": "<device id>", "model": ["MAP", "M_PATH"]}
```

The request key is literally `model`, even though it carries the requested
property prefixes. Sending an empty list requests every key, which is wasteful —
the payload also carries mowing history and preferences. Asking only for `MAP`
and `M_PATH` keeps the response small.

The response is flat text, chunked, because a map can exceed one request:

| Key | Content |
| --- | --- |
| `MAP.0`, `MAP.1`, `MAP.2`, … | Chunks of one blob |
| `MAP.info` | A **character** offset, not a byte count |
| `M_PATH.0`, … | The historical mowing trail |

Decoding, in order:

1. Join `MAP.<n>` chunks in **numeric** order. Lexicographic order breaks at
   chunk 10.
2. Split at the character offset in `MAP.info`. Everything before is the first
   map, everything after holds any others.
3. `json.loads` each part. It yields an **array of JSON strings** — one string per
   map, each still encoded.
4. `json.loads` each string to get a map object.

Step 2 matters: the offset is a character index into the joined text, so slicing
bytes would be wrong for any map containing non-ASCII.

Re-created maps reuse their index. A deleted and re-mapped lawn can come back with
the same `mapIndex`, so the **last** record for an index wins — it is the newest
generation.

## Collections

Every geometry collection uses the same envelope:

```json
{
  "dataType": "Map",
  "value": [
    [1, {"name": "Zone A", "area": 84.2, "path": [{"x": 0, "y": 0}, {"x": 1200, "y": 0}]}],
    [2, {"name": "Zone B", "area": 44.2, "path": [...]}]
  ]
}
```

| Collection | Meaning |
| --- | --- |
| `mowingAreas` | Lawn zones — the things you actually mow |
| `forbiddenAreas` | No-go areas. The mower avoids them; it cannot be told to mow them |
| `spotAreas` | Ad-hoc patches, often under a tree or a bench |
| `paths` | Navigation corridors between areas |
| `contours` | Map edges, for edge mowing |
| `cruisePoints` | Named points of interest |
| `obstacles` | Recorded obstacles, passed through but not drawn |

Coordinates arrive as `{"x": …, "y": …}` objects. Older payloads use bare
`[x, y]` pairs, and the parser accepts both — it costs three lines and avoids a
class of "my map is empty" report.

The whole envelope is validated before use: a non-`Map` `dataType`, a non-list
`value`, an entry that is not a two-item list, or an id that will not coerce to
an integer all cause that entry to be skipped rather than crashing the parse.

## Compact shapes

Zones normally arrive as explicit polygons, but two shapes arrive as a summary
and are expanded at parse time:

| `shapeType` | Arrives as | Becomes |
| --- | --- | --- |
| 1 | A polygon | Unchanged |
| 2 | A rectangle plus an `angle` | Rotated about its centroid by `-angle` |
| 3 | A bounding box | 36 points around an ellipse inscribed in it |

The circle case takes the **extremes** of the incoming points rather than just
the first two. A bounding box may arrive as two opposite corners or as four
corners; taking extremes gives the same circle either way, where taking the first
two silently produces a flat line if four corners arrive.

## Coordinate system

Native units are **centimetres**, in a mirrored frame:

```
  y ↑        ┌─────────────────────┐
    │        │                     │
    │        │      the lawn       │   X increases to the WEST
    │        │                     │
    │        └─────────────────────┘
    └──────────────────────────────────→ 
   X increases WESTWARD (mirrored)      Y increases NORTH
```

The mirror is the vendor's own, and it exists so that yaw and screen rotation
behave the way the app expects. It is preserved rather than corrected, because
correcting it would break heading and break every coordinate the device stores.

Consequences worth remembering:

- Higher `x` is further **west**, not east.
- Higher `y` is further **north**.
- The boundary is a bounding box in these units, not a walkable outline. The
  drawable lawn is the union of the `mowingAreas` polygons.

There is no dock coordinate in this payload. The station's position is inferable
from charging, but inferring a coordinate and drawing it as if the device reported
one would be inventing data, so the integration does not draw a dock.

## The projection

Native centimetres become canvas pixels in `client/render.py`. A single
`Projection` handles it:

```python
px = (max_x - x) * scale + PADDING  # X mirrored
py = (y - min_y) * scale + PADDING
```

Then the whole canvas rotates, if configured:

| Rotation | Transform |
| --- | --- |
| 0° | identity |
| 90° | `(px, py) → (native_height - py, px)` |
| 180° | `(px, py) → (native_width - px, native_height - py)` |
| 270° | `(px, py) → (py, native_width - px)` |

Constants:

| Constant | Value | Reason |
| --- | --- | --- |
| `CANVAS_MAX` | 1600 px | Long edge, so a big lawn stays readable without huge images |
| `PADDING` | 36 px | Keeps shapes off the edge, where they would be clipped |
| `MIN_EDGE` | 320 px | A tiny lawn should not render as a stamp |

Scale is chosen to fit the boundary inside the canvas, then floored so the longer
edge is at least `MIN_EDGE`.

### The inverse, and why it exists

The card needs to turn a tap back into a coordinate the mower understands, which
means undoing the projection:

```python
def inverse(self, px, py) -> tuple[float, float]:
```

`Projection.inverse` rotates first (the inverse of the rotation), then reverses
the mirroring and scaling.

This is the part most likely to be subtly wrong, so it is tested at all four
rotations: project a native point, invert it, and assert it comes back within one
centimetre. The card's own JavaScript `invert()` mirrors the Python, and the
browser check confirms the two agree — a tap at 30% across the canvas resolves to
the same coordinate either way.

## Multiple maps

A mower can store several maps — front lawn, back lawn, a side patch. Each map
has its own `mapIndex`.

| Concept | Value |
| --- | --- |
| `mapIndex` | The device's zero-based index |
| `map_id` | `mapIndex + 1`, because Home Assistant keys entities by a stable id and zero reads as "unset" |

The active map defaults to the **newest** one — the highest index. That is
normally right, because re-mapping a lawn produces the newest record. Use
`select.*_map` when you need a different one; it writes a map-switch command to
the device rather than just filtering locally.

Zone and edge identifiers are only meaningful within their own map. Sending a
zone id from the front lawn while the side lawn is active will either be ignored
or do nothing useful. The card reads identifiers from the map it is displaying,
so it cannot get this wrong; a hand-written service call can.

## Rendering the PNG

`client/render.py` draws with Pillow, back to front:

1. Navigation paths
2. Spot areas
3. Mowing zones
4. **Forbidden areas** — after the zones, because a no-go area sits *inside* a
   zone and would otherwise be hidden
5. Map contours
6. Labels
7. Cruise points
8. Travel trail
9. The mower, as a triangle pointing along its heading

Step 4 is the one that matters. Getting the order wrong makes every no-go area
invisible, which is exactly backwards.

Heading is drawn as `(270 - heading + rotation) % 360`: the native X mirror
reverses yaw, so a clockwise-from-north heading becomes clockwise-from-up on
screen after the flip.

The renderer returns `None` — not a blank image — when a map has no drawable
geometry, so the image entity can report unavailable instead of showing an empty
picture.

## The map.json endpoint

`GET /api/dreame_robot/<entry_id>/map.json`, authenticated like any other Home
Assistant API call.

One view serves every configured mower; the entry id selects which. Nothing is
removed on unload, because the router has no supported way to drop a route.

The payload:

| Field | Shape | Used by |
| --- | --- | --- |
| `available` | bool | Whether there is anything to draw |
| `canvas` | `{width, height}` | The SVG viewBox |
| `projection` | `{max_x, min_y, scale, padding, native_width, native_height, rotation}` | Inverting a tap |
| `boundary` | `[x1, y1, x2, y2]` | Native bounding box |
| `name`, `total_area` | string, float | Header pills |
| `zones`, `forbidden`, `spots`, `contours` | polygons | Drawing and tap targets |
| `paths`, `points`, `trail` | polylines | Drawing |
| `maps` | `[{id, index, name, total_area}]` | Map switcher |
| `robot` | `{x, y, heading, native}` | Live marker |
| `entry_id`, `title`, `model` | | Diagnostics |
| `activity`, `battery_level`, `charging`, `error`, `error_tier` | | Status pills |

Every point is **already projected** to canvas pixels, so the card never has to
duplicate the maths. The only thing it computes is the inverse, for taps.

Each polygon keeps its native `id`, so a tap can be turned straight into a
service call.

One guard: if a single polygon somehow carries more than 20,000 points, the
request fails with a clear error rather than serialising a payload that would
lock up the event loop. The mower produces these, not the caller, so this is a
"the map is corrupt" signal rather than something to handle gracefully.

## Caching

| Data | TTL | Why |
| --- | --- | --- |
| Map geometry | 600 s | Changes only when a human edits the map in the app |
| Settings, maintenance | 300 s | Changes when a human opens the app |
| Firmware status | 3600 s | Changes rarely |
| State | Every poll, plus every push | This is the point of the integration |

The map is the expensive call, so it is the one worth caching hard. The PNG is
re-rendered only when the mower's pose changes, not on every update.

Live position, by contrast, is never cached — it arrives over MQTT as the mower
moves, and the map card polls the JSON endpoint every three seconds by default.

## Why no map for some models

Three reasons, in the order you are likely to hit them:

1. **The mower has never mapped.** No map exists. Run a mapping job in the vendor
   app.
2. **The map is stored in the legacy binary format.** Some A1-generation mowers
   use the AES-CBC + zlib grid format instead of vector polygons. Not decoded —
   those mowers get everything else.
3. **The map exists but has no drawable geometry.** A mapping run that was
   interrupted, or a map with zones but no paths. The image entity reports
   unavailable rather than rendering nothing, which distinguishes this from a
   missing map.
