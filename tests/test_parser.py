import os
import sys
import unittest

# Add parent directory to path so we can import from gpu_monitor
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gpu_monitor import parse_output


class TestGPUOutputParser(unittest.TestCase):
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
        gpus, processes = parse_output(stdout)

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
        gpus, processes = parse_output(stdout)
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
        gpus, processes = parse_output(stdout)
        self.assertEqual(len(gpus), 1)
        self.assertEqual(len(processes), 0)

    def test_nvidia_smi_not_found(self):
        stdout = "ERROR: nvidia-smi not found"
        with self.assertRaises(ValueError) as context:
            parse_output(stdout)
        self.assertIn("ERROR: nvidia-smi not found", str(context.exception))


if __name__ == "__main__":
    unittest.main()
