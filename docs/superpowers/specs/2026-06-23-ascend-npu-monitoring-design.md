# Ascend NPU Monitoring Design

Date: 2026-06-23

## Goal

Add monitoring support for Huawei Ascend NPU servers, including hosts like the SSH config alias `hw` where `npu-smi` is installed. Existing NVIDIA GPU monitoring, storage monitoring, SSH pooling, and demo mode must keep working.

## Scope

- Detect accelerator backend per host automatically by default.
- Support a host-level override: `accelerator: auto`, `gpu`, `npu`, or `none`.
- Parse `npu-smi info` output for device status and process usage.
- Display NPU hosts in the same TUI card layout with NPU/HBM wording.
- Keep quota and `df` collection unchanged.
- Add parser tests using the observed `npu-smi 24.1.0.3` table shape from `hw`.

## Architecture

The SSH collection command will use a small backend selector:

- `auto`: prefer `nvidia-smi` when available, otherwise use `npu-smi`, otherwise emit an accelerator-not-found section.
- `gpu`: require `nvidia-smi`.
- `npu`: require `npu-smi`.
- `none`: skip accelerator collection and only collect process owner, quota, and disk data.

The remote output will still be separated by `---` sections so the existing parser flow remains familiar. Accelerator sections will include a backend marker so `parse_output` can dispatch to either the existing NVIDIA CSV parser or a new Ascend NPU parser without guessing from table text alone.

## Data Model

The existing `gpus` and `processes` lists will remain the TUI contract to keep the change narrow. NPU entries will use the same keys where possible:

- `index`: NPU ID
- `uuid`: stable synthetic ID such as `NPU-<index>-<chip>`
- `name`: model, for example `910B1`
- `temp`: temperature in Celsius
- `gpu_util`: AICore utilization percentage
- `mem_total`: HBM total in MB
- `mem_used`: HBM used in MB
- `mem_pct`: derived HBM percentage
- `power_draw`: power draw as a string
- `power_limit`: `N/A` when unavailable
- `accelerator_type`: `GPU` or `NPU`
- `memory_label`: `VRAM` or `HBM`

NPU process entries will keep `gpu_index`, `pid`, `name`, `used_mem`, and `user`. The `gpu_index` name can stay internal for compatibility, while display labels become accelerator-aware.

## Error Handling

Errors must be explicit:

- If `accelerator: npu` is set and `npu-smi` is missing, show a clear NPU-specific error in the card.
- If `accelerator: gpu` is set and `nvidia-smi` is missing, show a clear GPU-specific error.
- If `auto` finds neither tool, degrade gracefully and continue showing quota and disk information.
- Parser failures for malformed accelerator rows should skip only the bad row, not the whole host, unless the whole response is empty.

## Testing

Use test-first implementation:

- Add parser tests for `npu-smi info` with 910B1 devices and process rows.
- Add parser tests for `auto` no-accelerator fallback.
- Add command-building tests if the collection command is extracted into a helper.
- Run the current parser test suite after implementation.

## Documentation

Update README and sample config comments to mention:

- Automatic accelerator detection.
- `hosts[].accelerator` override values.
- Ascend NPU display uses HBM/AICore data from `npu-smi info`.
