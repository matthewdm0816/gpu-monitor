import os
import re
import sys
import time
import asyncio

# Friendly dependency checks
try:
    import yaml
    import asyncssh
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from textual.app import App, ComposeResult
    from textual.widgets import Header, Footer, Static
    from textual.containers import VerticalScroll
except ImportError as e:
    print(f"Error: Missing dependency '{e.name}'", file=sys.stderr)
    print("Please install the required packages before running this script:", file=sys.stderr)
    print("  pip install textual asyncssh pyyaml", file=sys.stderr)
    print("\nOr run the setup helper script:\n  run.bat", file=sys.stderr)
    sys.exit(1)


def get_ssh_hosts(ssh_config_path):
    """
    Scans the SSH config file for Host entries to use as default hosts.
    Skips wildcard patterns.
    """
    hosts = []
    try:
        path = os.path.expanduser(ssh_config_path)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split()
                    if len(parts) >= 2 and parts[0].lower() == 'host':
                        for val in parts[1:]:
                            if '*' in val or '?' in val:
                                continue
                            hosts.append(val)
    except Exception:
        pass
    # De-duplicate while preserving order
    seen = set()
    return [x for x in hosts if not (x in seen or seen.add(x))]


def load_config():
    """
    Loads config.yaml from the script's directory.
    If it doesn't exist, it auto-detects hosts from ~/.ssh/config, writes them,
    and returns the configuration.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_file = os.path.join(script_dir, "config.yaml")
    config = {
        "refresh_interval": 2.0,
        "timeout": 5.0,
        "ssh_config_path": "~/.ssh/config",
        "hosts": []
    }

    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                user_cfg = yaml.safe_load(f)
                if isinstance(user_cfg, dict):
                    config.update(user_cfg)
        except Exception as e:
            print(f"Error loading config.yaml from {config_file}: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Fallback & Auto-populate from ~/.ssh/config
        ssh_hosts = get_ssh_hosts(config["ssh_config_path"])
        if ssh_hosts:
            config["hosts"] = [{"name": h, "display_name": h} for h in ssh_hosts]
        else:
            config["hosts"] = [
                {"name": "server-a", "display_name": "Example Lab Server A"},
                {"name": "server-b", "display_name": "Example Lab Server B"}
            ]
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)
            print(f"Auto-generated default '{config_file}' using SSH config.")
        except Exception as e:
            print(f"Warning: Could not write default config.yaml: {e}", file=sys.stderr)

    return config


def resolve_ssh_config(host_name, ssh_config_path="~/.ssh/config"):
    """
    Looks up connection options for host_name from ~/.ssh/config.
    """
    conn_opts = {}
    resolved_host = host_name
    try:
        path = os.path.expanduser(ssh_config_path)
        if os.path.exists(path):
            ssh_config = asyncssh.read_ssh_config(path)
            config_opts = ssh_config.lookup(host_name)
            
            if 'hostname' in config_opts:
                resolved_host = config_opts['hostname']
            if 'port' in config_opts:
                conn_opts['port'] = int(config_opts['port'])
            if 'user' in config_opts:
                conn_opts['username'] = config_opts['user']
            if 'identityfile' in config_opts:
                id_files = config_opts['identityfile']
                if isinstance(id_files, list):
                    conn_opts['client_keys'] = [os.path.expanduser(x) for x in id_files]
                else:
                    conn_opts['client_keys'] = [os.path.expanduser(id_files)]
    except Exception:
        pass
    return resolved_host, conn_opts


def parse_output(stdout):
    """
    Parses the command output sections separated by '---'.
    Section 1: GPU Info CSV (index, uuid, name, temperature.gpu, utilization.gpu, utilization.memory, memory.total, memory.used, power.draw, power.limit)
    Section 2: Compute Apps CSV (gpu_uuid, pid, process_name, used_gpu_memory)
    Section 3: Process Owner Map (ps -eo pid,user)
    """
    sections = stdout.split("---")
    if len(sections) == 0:
        raise ValueError("Empty response received from remote host")

    gpu_section = sections[0].strip()
    if gpu_section.startswith("ERROR:"):
        raise ValueError(gpu_section)

    gpus = []
    uuid_to_index = {}
    for line in gpu_section.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 9:
            continue

        try:
            gpu_idx = int(parts[0])
            gpu_uuid = parts[1]
            name = parts[2]
            temp = int(parts[3]) if parts[3].isdigit() else 0
            gpu_util = int(parts[4]) if parts[4].isdigit() else 0
            
            # Memory fields
            total_mem = int(parts[6]) if parts[6].isdigit() else 0
            used_mem = int(parts[7]) if parts[7].isdigit() else 0
            mem_pct = int((used_mem / total_mem) * 100) if total_mem > 0 else 0
            
            # Power fields
            power_draw = parts[8]
            power_limit = parts[9] if len(parts) > 9 else "N/A"
            
            gpus.append({
                "index": gpu_idx,
                "uuid": gpu_uuid,
                "name": name,
                "temp": temp,
                "gpu_util": gpu_util,
                "mem_total": total_mem,
                "mem_used": used_mem,
                "mem_pct": mem_pct,
                "power_draw": power_draw,
                "power_limit": power_limit,
            })
            uuid_to_index[gpu_uuid] = gpu_idx
        except ValueError:
            continue

    processes = []
    pid_to_user = {}

    # Section 3: User list from ps -eo pid,user
    if len(sections) > 2:
        ps_section = sections[2].strip()
        for line in ps_section.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2:
                pid_str, user = parts[0], parts[1]
                if pid_str.isdigit():
                    pid_to_user[int(pid_str)] = user

    # Section 2: Active compute apps from nvidia-smi
    if len(sections) > 1:
        proc_section = sections[1].strip()
        for line in proc_section.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 4:
                continue
            try:
                gpu_uuid = parts[0]
                pid = int(parts[1])
                proc_name = parts[2]
                used_mem = int(parts[3])
                
                # Resolve GPU index from UUID
                gpu_idx = uuid_to_index.get(gpu_uuid, -1)
                if gpu_idx == -1:
                    continue
                    
                user = pid_to_user.get(pid, "unknown")
                processes.append({
                    "gpu_index": gpu_idx,
                    "pid": pid,
                    "name": proc_name,
                    "used_mem": used_mem,
                    "user": user,
                })
            except ValueError:
                continue

    return gpus, processes


class HostCard(Static):
    """
    Widget to represent a remote host card containing status and GPU tables.
    """
    def __init__(self, host_cfg, **kwargs):
        super().__init__(**kwargs)
        self.host_cfg = host_cfg
        self.host_name = host_cfg['name']
        self.display_name = host_cfg.get('display_name', host_cfg['name'])
        self.status = "connecting"  # connecting, online, offline, error
        self.error_message = ""
        self.gpus = []
        self.processes = []
        self.latency = 0.0

    def update_data(self, status, gpus=None, processes=None, error_message="", latency=0.0):
        self.status = status
        self.gpus = gpus or []
        self.processes = processes or []
        self.error_message = error_message
        self.latency = latency
        self.refresh(layout=True)

    def render(self) -> Panel:
        status_symbols = {
            "connecting": "●",
            "online": "●",
            "offline": "●",
            "error": "●",
        }

        status_colors = {
            "connecting": "yellow",
            "online": "green",
            "offline": "red",
            "error": "red",
        }

        color = status_colors.get(self.status, "white")
        symbol = status_symbols.get(self.status, "●")
        title_text = Text.assemble(
            (f"{symbol} ", color),
            (self.display_name, "bold white"),
            (f" ({self.host_name})", "dim"),
        )
        
        if self.status == "online":
            title_text.append(Text(f" - {self.latency*1000:.0f}ms", style="dim green"))
        elif self.status == "connecting":
            title_text.append(Text(" - Connecting...", style="dim yellow"))
        elif self.status == "offline":
            title_text.append(Text(" - Host unreachable", style="dim red"))
        elif self.status == "error":
            title_text.append(Text(" - Error", style="dim red"))

        if self.status == "online":
            if not self.gpus:
                body = Text("No NVIDIA GPUs found or drivers not loaded.", style="dim italic")
            else:
                table = Table(box=None, expand=True, padding=(0, 1))
                table.add_column("ID", width=3, justify="right", style="cyan")
                table.add_column("Model", width=25, style="bold white")
                table.add_column("Temp", width=7, justify="right")
                table.add_column("Power", width=12, justify="right")
                table.add_column("GPU Util", width=18)
                table.add_column("VRAM Util", width=28)
                table.add_column("Processes", style="dim white")

                for gpu in self.gpus:
                    # Temperature style
                    temp = gpu['temp']
                    if temp < 60:
                        temp_style = "green"
                    elif temp < 80:
                        temp_style = "yellow"
                    else:
                        temp_style = "red"
                    temp_text = Text(f"{temp}°C", style=temp_style)

                    # Power style
                    power_draw = gpu['power_draw']
                    power_limit = gpu['power_limit']
                    try:
                        p_draw = float(power_draw)
                        p_limit = float(power_limit)
                        power_text = Text(f"{int(p_draw)}W/{int(p_limit)}W", style="white")
                    except ValueError:
                        power_text = Text("N/A", style="dim")

                    # GPU Util Progress Bar
                    gpu_pct = gpu['gpu_util']
                    if gpu_pct < 30:
                        gpu_color = "green"
                    elif gpu_pct < 75:
                        gpu_color = "yellow"
                    else:
                        gpu_color = "red"

                    bar_width = 8
                    filled = int(gpu_pct / 100 * bar_width)
                    bar_str = "█" * filled + "░" * (bar_width - filled)
                    gpu_util_text = Text.assemble(
                        ("[", "bright_black"),
                        (bar_str, gpu_color),
                        ("] ", "bright_black"),
                        (f"{gpu_pct:3d}%", f"bold {gpu_color}")
                    )

                    # VRAM Util Progress Bar
                    used_gb = gpu['mem_used'] / 1024.0
                    total_gb = gpu['mem_total'] / 1024.0
                    mem_pct = gpu['mem_pct']
                    if mem_pct < 50:
                        mem_color = "green"
                    elif mem_pct < 85:
                        mem_color = "yellow"
                    else:
                        mem_color = "red"

                    filled_mem = int(mem_pct / 100 * bar_width)
                    mem_bar_str = "█" * filled_mem + "░" * (bar_width - filled_mem)
                    vram_text = Text.assemble(
                        ("[", "bright_black"),
                        (mem_bar_str, mem_color),
                        ("] ", "bright_black"),
                        (f"{used_gb:4.1f}/{total_gb:4.1f}G", "white"),
                        (f" ({mem_pct:2d}%)", f"bold {mem_color}")
                    )

                    # Dynamic compact process list
                    gpu_procs = [p for p in self.processes if p['gpu_index'] == gpu['index']]
                    proc_texts = []
                    for p in gpu_procs:
                        mem_mb = p['used_mem']
                        proc_texts.append(f"{p['user']}({p['name']}:{mem_mb}M)")

                    if proc_texts:
                        processes_text = Text(", ".join(proc_texts), style="dim white")
                    else:
                        processes_text = Text("no processes", style="dim bright_black")

                    table.add_row(
                        str(gpu['index']),
                        gpu['name'],
                        temp_text,
                        power_text,
                        gpu_util_text,
                        vram_text,
                        processes_text
                    )
                body = table
        elif self.status == "connecting":
            body = Text("Connecting to remote host over SSH...", style="dim yellow italic")
        else:
            # Error card display
            if "private key" in self.error_message.lower() or "permission denied" in self.error_message.lower():
                body = Text.from_markup(
                    f"[bold red]Authentication Error:[/bold red] Key-based authentication failed.\n"
                    f"[yellow]Help:[/yellow] Key auth is enforced. Ensure your public key is added to the remote host's\n"
                    f"`~/.ssh/authorized_keys` and the private key is configured in `config.yaml` or loaded in SSH Agent."
                )
            else:
                body = Text(f"Error: {self.error_message}", style="bold red")

        border_color = "bright_black"
        if self.status == "online":
            border_color = "purple"
        elif self.status == "connecting":
            border_color = "yellow"
        elif self.status == "offline" or self.status == "error":
            border_color = "red"

        return Panel(
            body,
            title=title_text,
            border_style=border_color,
            expand=True
        )


class GPUMonitorApp(App):
    """
    Main Textual Application to monitor multiple remote GPU hosts.
    """
    TITLE = "GPU Remote Monitor"
    
    CSS = """
    Screen {
        background: #1e1e2e;
        color: #cdd6f4;
    }
    
    Header {
        background: #11111b;
        color: #cba6f7;
        text-style: bold;
    }
    
    Footer {
        background: #11111b;
        color: #a6adc8;
    }
    
    #host-container {
        padding: 1 2;
        height: 1fr;
    }
    
    HostCard {
        margin: 0 0 1 0;
        height: auto;
        min-height: 5;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh Now"),
        ("p", "toggle_pause", "Pause/Resume"),
    ]

    def __init__(self, config, demo_mode=False, **kwargs):
        super().__init__(**kwargs)
        self.config = config
        self.hosts = config.get('hosts', [])
        self.refresh_interval = config.get('refresh_interval', 2.0)
        self.conn_timeout = config.get('timeout', 5.0)
        self.ssh_config_path = config.get('ssh_config_path', '~/.ssh/config')
        self.is_paused = False
        self.host_cards = {}
        self._refreshing = False
        self.demo_mode = demo_mode

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="host-container"):
            for host in self.hosts:
                # Sanitize ID to ensure it is valid in Textual
                safe_id = "".join([c if c.isalnum() or c == "-" else "_" for c in host['name']])
                card = HostCard(host, id=f"card-{safe_id}")
                self.host_cards[host['name']] = card
                yield card
        yield Footer()

    async def on_mount(self) -> None:
        # Trigger first refresh
        self.run_worker(self.refresh_data())
        # Set up repeating refresh timer
        self.set_interval(self.refresh_interval, self.timer_refresh)

    async def timer_refresh(self) -> None:
        if not self.is_paused:
            self.run_worker(self.refresh_data())

    async def refresh_data(self, force=False) -> None:
        if self._refreshing and not force:
            return
        self._refreshing = True
        
        # Parallelize connections across all hosts
        tasks = [self.update_host(host) for host in self.hosts]
        await asyncio.gather(*tasks)
        
        self._refreshing = False

    def generate_mock_output(self, host_name):
        """Generates dynamic fluctuation data for demonstration/mock mode."""
        import random
        # Seed by hash of host name + current time block (updates every 2s)
        time_block = int(time.time() / 2.0)
        random.seed(hash(host_name) + time_block)
        
        # Determine number of GPUs for this mock host
        num_gpus = (hash(host_name) % 3) + 1  # 1 to 3 GPUs
        
        gpu_lines = []
        proc_lines = []
        pids = []
        
        users = ["alice", "bob", "charlie", "root", "dave"]
        procs = ["python", "jupyter-notebook", "torch_train", "llama-infer", "go-runner"]
        
        for idx in range(num_gpus):
            model = ["NVIDIA A100-SXM4-80GB", "NVIDIA GeForce RTX 4090", "NVIDIA RTX 6000 Ada"][idx % 3]
            temp = random.randint(45, 82)
            gpu_util = random.randint(0, 100)
            
            total_mem = [81920, 24576, 49152][idx % 3]
            mem_used = random.randint(int(total_mem * 0.1), int(total_mem * 0.95))
            
            p_limit = [400, 450, 300][idx % 3]
            p_draw = random.uniform(p_limit * 0.15, p_limit * 0.95)
            
            gpu_lines.append(f"{idx}, {model}, {temp}, {gpu_util}, 0, {total_mem}, {mem_used}, {p_draw:.2f}, {p_limit:.2f}")
            
            # Processes on this GPU
            if gpu_util > 5:
                num_procs = random.randint(1, 3)
                for _ in range(num_procs):
                    pid = random.randint(10000, 99999)
                    user = random.choice(users)
                    pids.append((pid, user))
                    proc_name = random.choice(procs)
                    proc_mem = random.randint(500, int(mem_used / num_procs))
                    proc_lines.append(f"{idx}, {pid}, {proc_name}, {proc_mem}")
        
        ps_lines = ["  PID USER"]
        for pid, user in pids:
            ps_lines.append(f"{pid} {user}")
            
        return "\n".join(gpu_lines) + "\n---\n" + "\n".join(proc_lines) + "\n---\n" + "\n".join(ps_lines)

    async def update_host(self, host_cfg) -> None:
        card = self.host_cards.get(host_cfg['name'])
        if not card:
            return

        start_time = time.perf_counter()
        
        # DEMO MODE SIMULATION
        if self.demo_mode:
            import random
            await asyncio.sleep(0.05 + 0.15 * random.random())  # simulate network latency
            latency = time.perf_counter() - start_time
            try:
                stdout = self.generate_mock_output(host_cfg['name'])
                gpus, processes = parse_output(stdout)
                card.update_data(
                    status="online",
                    gpus=gpus,
                    processes=processes,
                    latency=latency
                )
            except Exception as e:
                card.update_data(status="error", error_message=str(e), latency=latency)
            return

        try:
            host_name = host_cfg['name']
            
            # 1. Resolve host details from ~/.ssh/config
            resolved_host, conn_opts = resolve_ssh_config(host_name, self.ssh_config_path)
            
            # 2. Apply config.yaml overrides
            if 'user' in host_cfg:
                conn_opts['username'] = host_cfg['user']
            if 'port' in host_cfg:
                conn_opts['port'] = host_cfg['port']
            if 'key_file' in host_cfg:
                conn_opts['client_keys'] = [os.path.expanduser(host_cfg['key_file'])]

            # Enforce key authentication (disable password prompt fallbacks)
            conn_opts['password'] = None
            conn_opts['preferred_auth'] = ['publickey']
            conn_opts['known_hosts'] = None  # Disable host key check to avoid blocking
            conn_opts['connect_timeout'] = self.conn_timeout
            
            # Apply cryptographic overrides to avoid MAC errors on Windows
            conn_opts['encryption_algs'] = ['aes256-gcm@openssh.com', 'aes128-gcm@openssh.com', 'aes256-ctr', 'aes128-ctr']
            conn_opts['mac_algs'] = ['hmac-sha2-256', 'hmac-sha2-512']

            # Check for configured/available keys
            has_key = False
            if 'client_keys' in conn_opts and conn_opts['client_keys']:
                # Validate explicitly specified keys
                for key_path in conn_opts['client_keys']:
                    if os.path.exists(key_path):
                        has_key = True
                    else:
                        raise FileNotFoundError(f"Private key file not found: {key_path}")
            else:
                # Check default key files
                default_keys = [
                    os.path.expanduser("~/.ssh/id_rsa"),
                    os.path.expanduser("~/.ssh/id_dsa"),
                    os.path.expanduser("~/.ssh/id_ecdsa"),
                    os.path.expanduser("~/.ssh/id_ed25519"),
                ]
                if any(os.path.exists(k) for k in default_keys):
                    has_key = True
                else:
                    # Check SSH Agent
                    try:
                        agent = asyncssh.get_agent()
                        agent_keys = await agent.get_keys()
                        if agent_keys:
                            has_key = True
                    except Exception:
                        pass

            if not has_key:
                raise ValueError(
                    "No SSH private key configured or found. Key-based authentication is required.\n"
                    "Please configure 'key_file' in config.yaml or ensure a default SSH key exists (e.g. ~/.ssh/id_rsa)."
                )

            async with asyncssh.connect(resolved_host, **conn_opts) as conn:
                cmd = (
                    "if command -v nvidia-smi >/dev/null 2>&1; then "
                    "nvidia-smi --query-gpu=index,uuid,name,temperature.gpu,utilization.gpu,utilization.memory,memory.total,memory.used,power.draw,power.limit --format=csv,noheader,nounits; "
                    "echo '---'; "
                    "nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory --format=csv,noheader,nounits 2>/dev/null || true; "
                    "echo '---'; "
                    "ps -eo pid,user 2>/dev/null || true; "
                    "else "
                    "echo 'ERROR: nvidia-smi not found'; "
                    "fi"
                )
                result = await conn.run(cmd)
                stdout = result.stdout
                
                latency = time.perf_counter() - start_time
                
                if "ERROR: nvidia-smi not found" in stdout:
                    card.update_data(
                        status="error",
                        error_message="nvidia-smi not found on remote server. Make sure Nvidia drivers are installed.",
                        latency=latency
                    )
                else:
                    gpus, processes = parse_output(stdout)
                    card.update_data(
                        status="online",
                        gpus=gpus,
                        processes=processes,
                        latency=latency
                    )
        except asyncssh.PermissionDenied as e:
            latency = time.perf_counter() - start_time
            card.update_data(
                status="error",
                error_message="Authentication failed. Key-based authentication is required.\n"
                              "Make sure your public key is added to the remote ~/.ssh/authorized_keys\n"
                              "and your private key is loaded in SSH Agent or configured in config.yaml.",
                latency=latency
            )
        except (asyncssh.TimeoutError, asyncio.TimeoutError) as e:
            latency = time.perf_counter() - start_time
            card.update_data(
                status="offline",
                error_message=f"Connection timed out (>{self.conn_timeout}s).",
                latency=latency
            )
        except FileNotFoundError as e:
            latency = time.perf_counter() - start_time
            card.update_data(
                status="error",
                error_message=str(e),
                latency=latency
            )
        except Exception as e:
            latency = time.perf_counter() - start_time
            card.update_data(
                status="error",
                error_message=f"Connection failed: {str(e)}",
                latency=latency
            )

    def action_refresh(self) -> None:
        """Force immediate refresh."""
        self.notify("Refreshing all servers...", severity="info")
        self.run_worker(self.refresh_data(force=True))

    def action_toggle_pause(self) -> None:
        """Pause or resume automatic updates."""
        self.is_paused = not self.is_paused
        status = "PAUSED" if self.is_paused else "ACTIVE"
        self.notify(f"Auto-refresh is now {status}", severity="info")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TUI GPU Monitor for Remote SSH Hosts")
    parser.add_argument("--demo", action="store_true", help="Run in interactive demo mode with mock data")
    args = parser.parse_args()

    cfg = load_config()
    
    if args.demo:
        # Override hosts configuration with simulated demo hosts
        cfg["hosts"] = [
            {"name": "demo-server-1", "display_name": "Cluster-A Core-Node-01"},
            {"name": "demo-server-2", "display_name": "Cluster-A Gpu-Node-02"},
            {"name": "demo-server-3", "display_name": "RTX-3090-Workstation"}
        ]
        cfg["refresh_interval"] = 1.0  # speed up refresh for demo responsiveness
    
    if not cfg.get("hosts"):
        print("Error: No hosts specified in config.yaml, and no hosts found in ~/.ssh/config.", file=sys.stderr)
        print("Please edit 'config.yaml' to add your remote hosts.", file=sys.stderr)
        sys.exit(1)
        
    app = GPUMonitorApp(cfg, demo_mode=args.demo)
    app.run()
