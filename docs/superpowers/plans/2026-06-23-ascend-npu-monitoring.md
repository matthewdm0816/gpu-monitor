# Ascend NPU Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add automatic Huawei Ascend NPU monitoring with optional per-host accelerator overrides.

**Architecture:** Keep the current single-file application structure, but extract command construction and accelerator parsing into small helpers inside `gpu_monitor.py`. Remote output remains split by `---`, with the accelerator section marked as `BACKEND:nvidia`, `BACKEND:npu`, or `BACKEND:none` so parsing is explicit.

**Tech Stack:** Python 3, unittest, asyncssh, Textual/Rich.

---

### Task 1: Parse Ascend `npu-smi info`

**Files:**
- Modify: `tests/test_parser.py`
- Modify: `gpu_monitor.py`

- [ ] **Step 1: Write the failing NPU parser test**

Add this test to `TestGPUOutputParser`:

```python
    def test_npu_smi_info_output(self):
        stdout = (
            "BACKEND:npu\n"
            "+------------------------------------------------------------------------------------------------+\n"
            "| npu-smi 24.1.0.3                 Version: 24.1.0.3                                             |\n"
            "+---------------------------+---------------+----------------------------------------------------+\n"
            "| NPU   Name                | Health        | Power(W)    Temp(C)           Hugepages-Usage(page)|\n"
            "| Chip                      | Bus-Id        | AICore(%)   Memory-Usage(MB)  HBM-Usage(MB)        |\n"
            "+===========================+===============+====================================================+\n"
            "| 0     910B1               | OK            | 92.6        50                0    / 0             |\n"
            "| 0                         | 0000:C1:00.0  | 12          0    / 0          3494 / 65536         |\n"
            "+===========================+===============+====================================================+\n"
            "| 1     910B1               | OK            | 99.9        52                0    / 0             |\n"
            "| 0                         | 0000:01:00.0  | 0           0    / 0          3475 / 65536         |\n"
            "+===========================+===============+====================================================+\n"
            "+---------------------------+---------------+----------------------------------------------------+\n"
            "| NPU     Chip              | Process id    | Process name             | Process memory(MB)      |\n"
            "+===========================+===============+====================================================+\n"
            "| 0       0                 | 2479700       | python                   | 111                     |\n"
            "+===========================+===============+====================================================+\n"
            "---\n"
            "---\n"
            "  PID USER\n"
            "2479700 alice\n"
            "---\n"
            "---\n"
        )
        gpus, processes, quotas, disks = parse_output(stdout)
        self.assertEqual(len(gpus), 2)
        self.assertEqual(gpus[0]["accelerator_type"], "NPU")
        self.assertEqual(gpus[0]["memory_label"], "HBM")
        self.assertEqual(gpus[0]["index"], 0)
        self.assertEqual(gpus[0]["name"], "910B1")
        self.assertEqual(gpus[0]["temp"], 50)
        self.assertEqual(gpus[0]["gpu_util"], 12)
        self.assertEqual(gpus[0]["mem_used"], 3494)
        self.assertEqual(gpus[0]["mem_total"], 65536)
        self.assertEqual(gpus[0]["power_draw"], "92.6")
        self.assertEqual(gpus[0]["power_limit"], "N/A")
        self.assertEqual(processes[0]["gpu_index"], 0)
        self.assertEqual(processes[0]["pid"], 2479700)
        self.assertEqual(processes[0]["user"], "alice")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
C:\Users\matth\AppData\Local\miniconda3\python.exe tests\test_parser.py
```

Expected: FAIL because NPU rows are not parsed yet.

- [ ] **Step 3: Implement minimal parser support**

Add helpers in `gpu_monitor.py`:

```python
def split_backend_marker(section):
    lines = section.splitlines()
    if lines and lines[0].strip().startswith("BACKEND:"):
        return lines[0].strip().split(":", 1)[1].strip().lower(), "\n".join(lines[1:])
    return "nvidia", section

def parse_npu_smi_output(npu_section, pid_to_user):
    # Parse pairs of device rows and later process rows from the npu-smi text table.
    return gpus, processes
```

Update `parse_output` to dispatch on the backend marker and keep NVIDIA behavior as default for legacy test data.

- [ ] **Step 4: Run parser tests to verify pass**

Run:

```powershell
C:\Users\matth\AppData\Local\miniconda3\python.exe tests\test_parser.py
```

Expected: all parser tests pass.

### Task 2: Build Accelerator-Aware SSH Command

**Files:**
- Modify: `tests/test_parser.py`
- Modify: `gpu_monitor.py`

- [ ] **Step 1: Write failing command builder tests**

Add:

```python
from gpu_monitor import build_monitor_command

    def test_build_monitor_command_auto_detects_gpu_then_npu(self):
        cmd = build_monitor_command({"name": "hw"}, {"monitored_paths": ["/data"]})
        self.assertIn("command -v nvidia-smi", cmd)
        self.assertIn("command -v npu-smi", cmd)
        self.assertIn("BACKEND:nvidia", cmd)
        self.assertIn("BACKEND:npu", cmd)
        self.assertIn("df -h /data", cmd)

    def test_build_monitor_command_npu_override_requires_npu_smi(self):
        cmd = build_monitor_command({"name": "hw", "accelerator": "npu"}, {"monitored_paths": ["/data"]})
        self.assertIn("ERROR: npu-smi not found", cmd)
        self.assertNotIn("command -v nvidia-smi", cmd)

    def test_build_monitor_command_none_skips_accelerator_tools(self):
        cmd = build_monitor_command({"name": "storage", "accelerator": "none"}, {"monitored_paths": ["/data"]})
        self.assertIn("BACKEND:none", cmd)
        self.assertNotIn("nvidia-smi --query-gpu", cmd)
        self.assertNotIn("npu-smi info", cmd)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
C:\Users\matth\AppData\Local\miniconda3\python.exe tests\test_parser.py
```

Expected: import fails because `build_monitor_command` does not exist.

- [ ] **Step 3: Extract command construction**

Create `build_monitor_command(host_cfg, config)` in `gpu_monitor.py`. It returns the full remote command, including accelerator sections, `ps -eo pid,user`, quota, and `df`.

- [ ] **Step 4: Use helper in `GPUMonitorApp.update_host`**

Replace inline `cmd = (...)` in `update_host` with:

```python
cmd = build_monitor_command(host_cfg, self.config)
```

- [ ] **Step 5: Run parser tests to verify pass**

Run:

```powershell
C:\Users\matth\AppData\Local\miniconda3\python.exe tests\test_parser.py
```

Expected: all parser tests pass.

### Task 3: Make TUI Labels Accelerator-Aware

**Files:**
- Modify: `gpu_monitor.py`

- [ ] **Step 1: Update HostCard labels**

In `HostCard.render`, derive:

```python
accelerator_label = gpu.get("accelerator_type", "GPU")
memory_label = gpu.get("memory_label", "VRAM")
util_label = "AICore Util" if accelerator_label == "NPU" else "GPU Util"
```

Use these labels in table column headers and process fallback text. Keep existing NVIDIA rows displaying GPU/VRAM.

- [ ] **Step 2: Run parser tests**

Run:

```powershell
C:\Users\matth\AppData\Local\miniconda3\python.exe tests\test_parser.py
```

Expected: all parser tests pass.

### Task 4: Update Demo and Docs

**Files:**
- Modify: `gpu_monitor.py`
- Modify: `README.md`
- Modify: `config.yaml`

- [ ] **Step 1: Update demo data**

Keep existing demo hosts, but add one simulated NPU host with `accelerator: "npu"` and mock NPU output so the UI can demonstrate both labels.

- [ ] **Step 2: Update README**

Document automatic accelerator detection and `hosts[].accelerator` values: `auto`, `gpu`, `npu`, `none`.

- [ ] **Step 3: Update sample config comments**

Add commented guidance near `hosts:` showing:

```yaml
# accelerator: "auto"  # optional: auto, gpu, npu, none
```

- [ ] **Step 4: Run parser tests**

Run:

```powershell
C:\Users\matth\AppData\Local\miniconda3\python.exe tests\test_parser.py
```

Expected: all parser tests pass.

### Task 5: Final Verification

**Files:**
- Verify: full diff
- Verify: parser suite

- [ ] **Step 1: Run parser suite**

Run:

```powershell
C:\Users\matth\AppData\Local\miniconda3\python.exe tests\test_parser.py
```

Expected: all tests pass.

- [ ] **Step 2: Run a real read-only command against `hw`**

Run:

```powershell
ssh -o BatchMode=yes -o ConnectTimeout=5 hw "npu-smi info"
```

Expected: `npu-smi` output contains 910B1 device rows and process rows.

- [ ] **Step 3: Review git diff**

Run:

```powershell
git diff -- gpu_monitor.py tests/test_parser.py README.md config.yaml
```

Expected: only NPU monitoring, docs, and sample config changes.
