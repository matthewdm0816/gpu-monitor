import os
import sys
import unittest
import tempfile
import time
import io

from rich.console import Console

# Add parent directory to path so we can import from gpu_monitor
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gpu_monitor import GPUMonitorApp, HostCard, build_monitor_command, parse_output, resolve_ssh_config


class TestGPUOutputParser(unittest.TestCase):
    def test_resolve_ssh_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = os.path.join(tmpdir, "id_test").replace("\\", "/")
            cfg_path = os.path.join(tmpdir, "config")
            with open(cfg_path, "w", encoding="utf-8") as f:
                f.write(
                    "Host lab\n"
                    "  HostName 192.0.2.10\n"
                    "  User testuser\n"
                    "  Port 2200\n"
                    f"  IdentityFile {key_path}\n"
                )

            host, opts = resolve_ssh_config("lab", cfg_path)

        self.assertEqual(host, "192.0.2.10")
        self.assertEqual(opts["username"], "testuser")
        self.assertEqual(opts["port"], 2200)
        self.assertEqual(opts["client_keys"], [key_path])

    def test_normal_output(self):
        stdout = (
            "0, GPU-12345, NVIDIA GeForce RTX 3090, 54, 12, 5, 24268, 1204, 85.34, 350.00\n"
            "1, GPU-67890, NVIDIA GeForce RTX 3090, 48, 0, 0, 24268, 0, 30.12, 350.00\n"
            "---\n"
            "GPU-12345, 12345, python, 1024\n"
            "---\n"
            "  PID USER\n"
            "    1 root\n"
            "12345 alice\n"
        )
        gpus, processes, quotas, disks = parse_output(stdout)

        # Assert GPU details
        self.assertEqual(len(gpus), 2)
        self.assertEqual(gpus[0]["index"], 0)
        self.assertEqual(gpus[0]["name"], "NVIDIA GeForce RTX 3090")
        self.assertEqual(gpus[0]["temp"], 54)
        self.assertEqual(gpus[0]["gpu_util"], 12)
        self.assertEqual(gpus[0]["mem_total"], 24268)
        self.assertEqual(gpus[0]["mem_used"], 1204)
        self.assertEqual(gpus[0]["mem_pct"], 4)  # 1204 / 24268 * 100
        self.assertEqual(gpus[0]["power_draw"], "85.34")
        self.assertEqual(gpus[0]["power_limit"], "350.00")

        self.assertEqual(gpus[1]["index"], 1)
        self.assertEqual(gpus[1]["mem_used"], 0)
        self.assertEqual(gpus[1]["mem_pct"], 0)

        # Assert processes mapping
        self.assertEqual(len(processes), 1)
        self.assertEqual(processes[0]["gpu_index"], 0)
        self.assertEqual(processes[0]["pid"], 12345)
        self.assertEqual(processes[0]["name"], "python")
        self.assertEqual(processes[0]["used_mem"], 1024)
        self.assertEqual(processes[0]["user"], "alice")

    def test_unsupported_power(self):
        stdout = (
            "0, GPU-12345, NVIDIA GeForce RTX 3090, 54, 12, 5, 24268, 1204, [Not Supported], [Not Supported]\n"
            "---\n"
            "---\n"
        )
        gpus, processes, quotas, disks = parse_output(stdout)
        self.assertEqual(len(gpus), 1)
        self.assertEqual(gpus[0]["power_draw"], "[Not Supported]")
        self.assertEqual(gpus[0]["power_limit"], "[Not Supported]")
        self.assertEqual(len(processes), 0)

    def test_no_processes(self):
        stdout = (
            "0, GPU-54321, NVIDIA GeForce RTX 3080 Ti, 40, 2, 0, 12288, 10, 25.00, 350.00\n"
            "---\n"
            "---\n"
            "  PID USER\n"
        )
        gpus, processes, quotas, disks = parse_output(stdout)
        self.assertEqual(len(gpus), 1)
        self.assertEqual(len(processes), 0)

    def test_nvidia_smi_not_found(self):
        stdout = "ERROR: nvidia-smi not found"
        gpus, processes, quotas, disks = parse_output(stdout)
        self.assertEqual(len(gpus), 0)
        self.assertEqual(len(processes), 0)
        self.assertEqual(len(quotas), 0)
        self.assertEqual(len(disks), 0)

    def test_quota_and_df_parsing(self):
        stdout = (
            "ERROR: nvidia-smi not found\n"
            "---\n"
            "---\n"
            "---\n"
            "Disk quotas for user test_user (uid 1001):\n"
            "     Filesystem   space   quota   limit   grace   files   quota   limit   grace\n"
            " /dev/mock_disk1   200G*  250G   300G           1000       0       0\n"
            "---\n"
            "Filesystem           Size  Used Avail Use% Mounted on\n"
            "/dev/mock_disk1       2.0T  1.2T  800G  60% /data\n"
            "/dev/mock_disk2       500G  100G  400G  20% /home\n"
        )
        gpus, processes, quotas, disks = parse_output(stdout)
        
        self.assertEqual(len(gpus), 0)
        self.assertEqual(len(processes), 0)
        
        # Assert quotas
        self.assertEqual(len(quotas), 1)
        self.assertEqual(quotas[0]["filesystem"], "/dev/mock_disk1")
        self.assertEqual(quotas[0]["used"], "200G")
        self.assertEqual(quotas[0]["soft"], "250G")
        self.assertEqual(quotas[0]["hard"], "300G")
        
        # Assert disks
        self.assertEqual(len(disks), 2)
        self.assertEqual(disks[0]["filesystem"], "/dev/mock_disk1")
        self.assertEqual(disks[0]["size"], "2.0T")
        self.assertEqual(disks[0]["used"], "1.2T")
        self.assertEqual(disks[0]["avail"], "800G")
        self.assertEqual(disks[0]["use_pct"], 60)
        self.assertEqual(disks[0]["mounted"], "/data")
        
        self.assertEqual(disks[1]["filesystem"], "/dev/mock_disk2")
        self.assertEqual(disks[1]["size"], "500G")
        self.assertEqual(disks[1]["used"], "100G")
        self.assertEqual(disks[1]["avail"], "400G")
        self.assertEqual(disks[1]["use_pct"], 20)
        self.assertEqual(disks[1]["mounted"], "/home")

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

    def test_host_card_renders_npu_labels(self):
        card = HostCard({"name": "hw", "display_name": "HW Ascend"})
        card.status = "online"
        card.latency = 0.01
        card.last_refresh_time = time.time()
        card.gpus = [{
            "index": 0,
            "uuid": "NPU-0-0",
            "name": "910B1",
            "temp": 50,
            "gpu_util": 12,
            "mem_total": 65536,
            "mem_used": 3494,
            "mem_pct": 5,
            "power_draw": "92.6",
            "power_limit": "N/A",
            "accelerator_type": "NPU",
            "memory_label": "HBM",
        }]
        card.processes = []
        card.quotas = []
        card.disks = []

        console = Console(record=True, width=140, file=io.StringIO(), force_terminal=False)
        console.print(card.render())
        rendered = console.export_text()

        self.assertIn("AICore Util", rendered)
        self.assertIn("HBM Util", rendered)
        self.assertNotIn("GPU Util", rendered)
        self.assertNotIn("VRAM Util", rendered)

    def test_demo_npu_mock_output_parses_as_npu(self):
        app = GPUMonitorApp({
            "hosts": [{"name": "demo-npu", "display_name": "Demo Ascend", "accelerator": "npu"}],
            "monitored_paths": ["/data"],
        }, demo_mode=True)

        stdout = app.generate_mock_output("demo-npu")
        gpus, processes, quotas, disks = parse_output(stdout)

        self.assertGreaterEqual(len(gpus), 1)
        self.assertEqual(gpus[0]["accelerator_type"], "NPU")
        self.assertEqual(gpus[0]["memory_label"], "HBM")

    def test_demo_gpu_mock_output_keeps_gpu_model_fields(self):
        app = GPUMonitorApp({
            "hosts": [{"name": "demo-gpu", "display_name": "Demo GPU"}],
            "monitored_paths": ["/data"],
        }, demo_mode=True)

        stdout = app.generate_mock_output("demo-gpu")
        gpus, processes, quotas, disks = parse_output(stdout)

        self.assertGreaterEqual(len(gpus), 1)
        self.assertEqual(gpus[0]["accelerator_type"], "GPU")
        self.assertEqual(gpus[0]["memory_label"], "VRAM")
        self.assertTrue(gpus[0]["name"].startswith("NVIDIA"))


if __name__ == "__main__":
    unittest.main()
