import os
import sys
import asyncio
import asyncssh

# Add parent directory to path so we can import from gpu_monitor
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gpu_monitor import load_config, resolve_ssh_config, parse_output

async def test_conn():
    cfg = load_config()
    host_cfg = None
    for h in cfg.get('hosts', []):
        if h['name'] == 'lab':
            host_cfg = h
            break
            
    if not host_cfg:
        print("Error: 'lab' host not found in config.yaml")
        return
        
    print(f"Testing connection to host: {host_cfg['name']} ({host_cfg.get('display_name')})")
    
    # Resolve connection details
    resolved_host, conn_opts = resolve_ssh_config(host_cfg['name'], cfg.get('ssh_config_path', '~/.ssh/config'))
    
    # Apply overrides
    if 'user' in host_cfg:
        conn_opts['username'] = host_cfg['user']
    if 'port' in host_cfg:
        conn_opts['port'] = host_cfg['port']
    if 'key_file' in host_cfg:
        conn_opts['client_keys'] = [os.path.expanduser(host_cfg['key_file'])]
        
    conn_opts['password'] = None
    conn_opts['known_hosts'] = None
    conn_opts['connect_timeout'] = cfg.get('timeout', 5.0)
    
    # Apply cryptographic overrides to avoid MAC errors on Windows
    conn_opts['encryption_algs'] = ['aes256-gcm@openssh.com', 'aes128-gcm@openssh.com', 'aes256-ctr', 'aes128-ctr']
    conn_opts['mac_algs'] = ['hmac-sha2-256', 'hmac-sha2-512']
    
    print(f"Connecting to {resolved_host} with options: {conn_opts}...")
    try:
        async with asyncssh.connect(resolved_host, **conn_opts) as conn:
            print("Connected! Running nvidia-smi and process queries...")
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
            parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            raw_path = os.path.join(parent_dir, "raw_ssh.txt")
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(result.stdout)
            print("\n--- RAW SSH OUTPUT WRITTEN TO raw_ssh.txt ---")
            print(result.stdout[:500] + "\n...[truncated in console]...")
            print("----------------------\n")
            
            if "ERROR: nvidia-smi not found" in result.stdout:
                print("Error: nvidia-smi is not available on the remote host.")
            else:
                gpus, processes = parse_output(result.stdout)
                print("--- PARSED GPU DATA ---")
                for gpu in gpus:
                    print(f"GPU {gpu['index']}: {gpu['name']}")
                    print(f"  Temp: {gpu['temp']}°C | Power: {gpu['power_draw']}W / {gpu['power_limit']}W")
                    print(f"  Util: {gpu['gpu_util']}% | VRAM: {gpu['mem_used']} / {gpu['mem_total']} MiB ({gpu['mem_pct']}%)")
                
                print("\n--- PARSED PROCESS DATA ---")
                for p in processes:
                    print(f"  GPU {p['gpu_index']} | PID {p['pid']} | User: {p['user']} | Process: {p['name']} | VRAM: {p['used_mem']} MiB")
                if not processes:
                    print("  No active compute processes running.")
                print("-----------------------")
                
    except Exception as e:
        print(f"\nConnection failed: {e}")
        print("\nHelp/Diagnostic:")
        print("Since key-based authentication is forced, verify that:")
        print("1. Your private SSH key is loaded into the SSH Agent (run 'ssh-add -l' in a terminal).")
        print("2. Or, specify the path to your private key in config.yaml under 'key_file'.")
        print("3. Your public key is added to the remote host's ~/.ssh/authorized_keys file.")

if __name__ == "__main__":
    asyncio.run(test_conn())
