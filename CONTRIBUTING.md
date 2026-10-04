# Contributing

Thanks for helping out. This integration talks to an undocumented vendor cloud,
so most contributions are either a protocol fix for one model family, or a
report that something does not work on real hardware.

## Reporting a model that does not work

Please include:

1. Your model's `model` id and firmware version, from **Settings → Devices &
   Services → Dreame Robot → the device**.
2. A diagnostics download: **⋮ menu → Download diagnostics**.
3. What you expected, and what happened instead.

Never include your account password, access token, or MQTT credentials.

## Development setup

```bash
uv venv --python 3.13
uv pip install -r requirements-test.txt
uv run ruff check .
uv run ruff format .
uv run pytest
```

## Ground rules for the client

- The client package (`custom_components/dreame_robot/client/`) must not import
  Home Assistant. It runs in an executor and is tested standalone.
- **Never retry a mutation.** A duplicated write can apply twice on the device.
  Reads retry; `set` and `action` calls do not. The one exception is a `401`,
  which proves the command never reached the device.
- **Never guess.** An unknown device code becomes
  `unknown_device_code_<n>`, not an invented meaning. The same goes for unknown
  state codes.
- Anything read from the network is validated before it is trusted, since the
  vendor app and the firmware are both outside our control.

## Adding a model

1. Add the model id and display name to `MODEL_NAMES` in `client/models.py`.
2. If the model renumbers states or device codes, add it to `STATE_OVERRIDES` or
   `_DEVICE_CODE_OVERRIDES` and add a test proving the override wins.
3. Update the model table in the README.
