# Printer Status States

> Reference for the two status sensors this integration exposes, what each is
> for, and the lifecycle traps that bite automation authors.

**Sources**: the enum tables in
[`sdcp/models/enums.py`](../custom_components/elegoo_printer/sdcp/models/enums.py)
and the per-printer-type option lists in
[`definitions.py`](../custom_components/elegoo_printer/definitions.py), plus
recorder history captured from a Mars 5 Ultra (firmware V1.4.5) on HA Core
2026.8.0.

> **The tables in this document are verified by
> [`test_docs_print_states.py`](../custom_components/elegoo_printer/tests/test_docs_print_states.py).**
> They are parsed and compared against the enums on every test run. If you add
> a state to the code, that test fails until this file is updated — please keep
> the table rows in the delimited blocks intact.

## Table of Contents

1. [The two status sensors](#the-two-status-sensors)
2. [Lifecycle traps](#lifecycle-traps)
3. [Machine status reference](#machine-status-reference)
4. [Print status reference — resin](#print-status-reference--resin)
5. [Print status reference — FDM](#print-status-reference--fdm)
6. [States you will never see](#states-you-will-never-see)
7. [Sensor units and quirks](#sensor-units-and-quirks)
8. [Camera and connection budget](#camera-and-connection-budget)

---

## The two status sensors

| Sensor | Entity suffix | Use it for |
|---|---|---|
| Machine status | `_current_status` | Gating "is the printer busy / is a print running" |
| Print status | `_print_status` | Lifecycle events — started, paused, complete, failed |

Both are `device_class: enum`. **The HA state string is always the enum member
name lowercased** — `FILE_TRANSFERRING` becomes `file_transferring`. This is
mechanical; `definitions.py` builds the `options` list as
`[status.name.lower() for status in ElegooMachineStatus]`.

During a print, `_current_status` stays `printing` for the whole job while
`_print_status` cycles `lifting` → `dropping` → `printing` once per layer. On a
3.5-hour resin print that is ~2,700 transitions per state. Trigger automations
on `_print_status` only if you want per-layer granularity; otherwise gate on
`_current_status`.

---

## Lifecycle traps

These are the things that cost people hours. All three are verified against
recorder history covering two complete prints.

### 1. There is no completion state on machine status

`_current_status` has **no** value meaning "finished". When a print completes it
returns to `idle` — the same value it holds when the printer is sitting unused
and the same value it lands on after a manual stop.

Only `_print_status` has a true `complete` state. **Any "print finished"
automation must watch `_print_status`, not `_current_status`.**

Observed end-of-print transitions:

```
17:42:18  print_status     -> lifting
17:42:22  percent_complete -> unknown
17:42:22  print_status     -> stopping
17:42:46  current_status   -> idle
17:42:46  print_status     -> complete
```

Note that `stopped` did not appear at all. Over 12 hours covering two
successful prints, `_current_status` took only three values: `printing`,
`file_transferring`, and `idle`.

### 2. `stopping` is not an abort signal

`_print_status` passes through `stopping` on the way to `complete` on a
perfectly successful print — it appeared exactly twice for two completed jobs.
Do not treat `stopping` as evidence the user cancelled something.

### 3. `percent_complete` never reaches 100

It tops out around **99.95** and then goes straight to `unknown` when the job
ends. Across a full print, 2,764 numeric samples spanned 0.0–99.95 and 100 was
never observed.

Consequences:

- An automation gating on `percent_complete >= 100` will never fire.
- Rendering `percent_complete | int(0)` after a print ends displays `0%`,
  because the state is `unknown` by then.
- For milestone notifications, prefer the integer `_current_layer` over the
  float `_percent_complete`. The layer sensor increments by exactly 1 with no
  gaps, so exact-match modulo arithmetic is reliable; float modulo is not.

Use `_print_status == 'complete'` for completion, and hardcode 100 in the
"finished" message rather than reading the sensor.

**Why it goes `unknown` rather than settling at 100:** progress is only
computed while `_print_status` is in an "active" set, and `complete` is
deliberately not in it. The moment the job finishes, the sensor has no active
status to report against and blanks. `idle`, `homing`, `stopped`,
`file_checking` and `loading` are likewise inactive.

### 4. Uploading a file is its own state

Sending a job to the printer shows as `file_transferring` → `idle` →
`printing`, not a direct jump to `printing`.

---

## Machine status reference

`ElegooMachineStatus`. Applies to all SDCP printers, resin and FDM. The wire
value is what the printer reports; WebSocket printers send it as a
single-element list (`[1]`), MQTT printers as a bare integer.

<!-- machine-status-table:start -->

| Wire value | HA state | Meaning |
|---|---|---|
| 0 | `idle` | Not performing any task. Also the resting state after a print completes or is stopped. |
| 1 | `printing` | Executing a print task. |
| 2 | `file_transferring` | A file transfer is in progress. |
| 3 | `exposure_testing` | Performing an exposure test. |
| 4 | `devices_testing` | Running a device self-check. |
| 5 | `leveling` | Performing a leveling operation. |
| 6 | `input_shaping` | Performing input shaping calibration. |
| 7 | `stopping` | In the process of stopping. |
| 8 | `stopped` | Stopped. |
| 9 | `homing` | Homing its axes. |
| 10 | `loading_unloading` | Loading or unloading material. |
| 11 | `pid_tuning` | Performing PID tuning. |
| 12 | `recovery` | In recovery mode. |

<!-- machine-status-table:end -->

---

## Print status reference — resin

`ElegooPrintStatus` as exposed to resin printers (Mars, Saturn, Jupiter). The
value column is the enum member value; see
[States you will never see](#states-you-will-never-see) for wire codes that do
not map straight through.

<!-- resin-print-status-table:start -->

| Value | HA state | Meaning |
|---|---|---|
| 0 | `idle` | Not actively printing. |
| 1 | `homing` | Resetting or homing the axes. |
| 2 | `dropping` | The print platform is descending. |
| 3 | `printing` | Currently printing. |
| 4 | `lifting` | The print platform is lifting. |
| 5 | `pausing` | In the process of pausing. |
| 6 | `paused` | Print job is paused. |
| 7 | `stopping` | In the process of stopping. Also occurs on normal completion. |
| 8 | `stopped` | Print job stopped. |
| 9 | `complete` | Print job completed successfully. |
| 10 | `file_checking` | Checking the print file. |
| 12 | `recovery` | Recovering after an interruption. |
| 13 | `printing_recovery` | Printing after a recovery. Never reported — see below. |
| 15 | `loading` | Loading material. |
| 16 | `preheating` | Preheating. |
| 20 | `leveling` | Leveling. |

<!-- resin-print-status-table:end -->

---

## Print status reference — FDM

FDM firmware (Centauri Carbon) reports print sub-status from a **different code
table** than resin. The authoritative source is Elegoo's open-source
[elegoo-link](https://github.com/ELEGOO-3D/elegoo-link) adapter, which this
integration mirrors 1:1.

FDM-only members carry enum values offset by +100 from their wire code so they
can never collide with the resin table; the FDM path resolves wire codes through
its own map rather than by member value. **Read the wire code column here, not
the value column in the resin table.**

<!-- fdm-print-status-table:start -->

| Wire code | HA state | Meaning |
|---|---|---|
| 0 | `idle` | Not actively printing. |
| 1 | `homing` | Homing the axes. |
| 2 | `dropping` | Platform descending. Marked resin-only by Elegoo. |
| 4 | `lifting` | Platform lifting. Marked resin-only by Elegoo. |
| 5 | `pausing` | In the process of pausing. |
| 6 | `paused` | Print job is paused. |
| 7 | `stopping` | In the process of stopping. |
| 8 | `stopped` | Print job stopped. |
| 9 | `complete` | Print job completed successfully. |
| 10 | `file_checking` | Checking the print file. |
| 11 | `printers_checking` | Running printer self-checks. |
| 12 | `resuming` | Resuming a paused print. |
| 13 | `printing` | Currently printing. |
| 14 | `error` | The print is in an error state. |
| 15 | `leveling` | Auto leveling. |
| 16 | `preheating` | Preheating. |
| 17 | `resonance_testing` | Running a resonance (input shaping) test. |
| 18 | `print_started` | The print has just started. |
| 19 | `auto_leveling_completed` | Auto leveling finished. |
| 20 | `preheating_completed` | Preheating finished. |
| 21 | `homing_completed` | Homing finished. |
| 22 | `resonance_testing_completed` | Resonance testing finished. |
| 23 | `auto_feeding` | Auto-feeding filament. |
| 24 | `filament_unloading` | Unloading filament. |
| 25 | `filament_unload_abnormal` | Filament unload failed. |
| 26 | `filament_unload_paused` | Filament unload paused. |

<!-- fdm-print-status-table:end -->

Three FDM-specific behaviours worth knowing:

- **Wire code 3 is deliberately unmapped.** Elegoo marks it "Exposuring", a
  resin-only concept with no FDM meaning. If firmware ever sends it, it
  surfaces as `unrecognized`.
- **Unknown codes surface as `unrecognized`, never `None`** — on this path.
  New firmware states are made visible rather than silently absorbed, so the
  sensor can never freeze on a stale value. **This guarantee does not extend to
  CC2**; see below.
- **Milestones park.** The firmware can sit on `preheating_completed` for the
  duration of a job, so check machine status for plain "is it printing" rather
  than expecting `print_status` to read `printing` throughout.

### Centauri Carbon 2 (CC2) is different

CC2 printers are FDM and therefore advertise the full 30-value option list, but
the CC2 mapper uses its own private code tables and can only ever produce a
**subset**:

- Only nine `ElegooPrintStatus` members are reachable: `idle`, `preheating`,
  `printing`, `complete`, `pausing`, `paused`, `stopping`, `stopped`,
  `leveling`. No FDM-only state (`resuming`, `print_started`, `auto_feeding`,
  `filament_unloading`, …) is ever produced on CC2.
- `exposure_testing` and `stopping` are unreachable on CC2 machine status.
- **Unmapped CC2 sub-status codes fall back to `idle`, not `unrecognized`.**
  This includes codes that exist in the CC2 constants but are absent from the
  map — filament loading/unloading, PID calibration, resonance testing, file
  upload. A CC2 user mid-filament-load may see `print_status: idle`. Do not
  treat `idle` on CC2 as proof the printer is doing nothing.

> **CC2 wire codes live in a different namespace.** The CC2 machine-status
> codes documented in [CC2_PROTOCOL.md](CC2_PROTOCOL.md#status-codes-reference)
> are *not* the values in this document's tables — CC2 code `1` is idle,
> whereas `ElegooMachineStatus.IDLE` is `0`. Use CC2_PROTOCOL.md when reading
> raw CC2 traffic, and this document for the HA state strings that result.

### Printer type, not transport, selects the table

The resin/FDM split is decided by `PrinterType.from_model()` on the model name,
independently of whether the printer speaks WebSocket or MQTT. Models it does
not recognise return `None` and **fall through to the resin table**.

For an unrecognised FDM model this silently misreads states — wire code 20
resolves to `leveling` on the resin table but `preheating_completed` on the FDM
one. If a new FDM printer reports plausible-looking but wrong states, check
whether its model string is recognised before suspecting firmware.

---

## States you will never see

Some values are advertised in a sensor's `options` list but are unreachable in
practice. They are listed for completeness; do not write automations against
them.

**Resin:**

- `printing_recovery` — wire code 13 is rewritten to `printing` before it
  reaches the sensor.
- Wire codes 18, 19 and 21 all collapse to `loading`.
- Unrecognized resin codes yield no state at all rather than a fallback value.

**FDM:** the FDM options list is generated from every enum member, so it
advertises `recovery`, `printing_recovery` and `loading` even though the FDM
code table has no wire code for any of them.

---

## Sensor units and quirks

| Sensor | Unit / type | Note |
|---|---|---|
| `_remaining_print_time` | **minutes** | Not seconds. Multiply by 60 for a timestamp. |
| `_current_print_time` | **minutes** | Same. A 3.5 h print reads ~`210.16`. |
| `_percent_complete` | float | Caps at ~99.95, then `unknown`. See trap 3. |
| `_current_layer` | int | Increments by exactly 1, no gaps. Safe for modulo milestones. |
| `_mac_address` | string | May be empty on some firmware. |

---

## Camera and connection budget

Modern Elegoo printers cap simultaneous connections — commonly around 4, shared
between the camera stream, slicer, ChituManager, and this integration. The
printer reports its own limits, so prefer reading them over assuming a number:

- `sensor.*_video_stream_connected` / `sensor.*_video_stream_max`
- `sensor.*_cloud_services_connected` / `sensor.*_max_cloud_services`

Exhausting the budget causes connection failures. The optional
[local proxy](../README.md#️-local-proxy-server) exists to work around this by
funnelling everything through one connection.

**The chamber camera is fragile.** A continuous video stream can lock up or
crash the printer's controller board. This is a firmware limitation and cannot
be worked around in the integration. Recovery is a power cycle — and only
**between** prints, never during one.

The camera entity ships **disabled by default** for this reason. If you enable
it, use `camera_view: auto` on dashboard cards so the card shows a still image
and only opens the live stream when tapped:

```yaml
type: picture-entity
entity: camera.your_printer_chamber_camera
camera_view: auto
show_name: false
show_state: false
fit_mode: cover
```
