# Multi-Host SSH GPU & Storage Monitor (TUI)

一个基于 Python Textual 构建的终端 TUI 监控工具，能够通过 SSH 同时监控多个远程服务器的 GPU 状态（显存、温度、使用率、功耗）、活跃进程（PID、所有者、使用显存）以及磁盘配额 (Quota) 和指定目录的剩余空间。

---

## 功能特性

- **多主机集中监控**：在一个终端窗口中平铺显示多个远程服务器的运行状态。
- **类似 `gpustat` 的展示**：直观展示每张 GPU 的使用率、温度、功耗与显存，并且基于 `GPU UUID` 准确匹配活跃进程的所有者与显存占用。
- **存储与配额监控**：不仅监控 GPU，还支持获取当前用户在各服务器的磁盘配额 (Quota) 和指定挂载目录的剩余空间 (DF)。
- **强健的容错性**：
  - 支持没有 GPU 的纯 CPU/存储服务器，即使 `nvidia-smi` 报错或不存在，也会优雅显示并继续监控磁盘空间与配额。
  - 支持自适应高度布局，完美展现从 2 卡到 8 卡乃至 CPU 单板的各种规格服务器。
- **安全的密钥认证**：强制使用私钥 SSH 认证，杜绝交互式密码输入，非常适合后台自动运行。若私钥缺失，提供友好的排查指导。
- **模拟 Demo 模式**：支持免连接的本地 Demo 演示模式，动态模拟多卡及存储空间变化。

---

## 环境要求

| 依赖 | 最低版本 | 说明 |
|------|---------|------|
| Python | 3.8+ | 推荐 3.10 以上 |
| uv | 最新版 | 虚拟环境与依赖管理（运行脚本会自动安装） |
| OpenSSH | - | 远程主机需开启 SSH 服务，本地需配置密钥认证 |

**Python 依赖包**（运行脚本会自动安装）：

| 包名 | 用途 |
|------|------|
| `textual` (>=0.80.0) | TUI 框架 |
| `asyncssh` (>=2.14.0) | 异步 SSH 连接 |
| `pyyaml` (>=6.0.1) | 解析 `config.yaml` 配置文件 |

---

## 安装与运行

### 方式一：使用运行脚本（推荐）

运行脚本会自动创建虚拟环境、安装依赖并启动程序。

#### Linux & macOS

```bash
# 1. 赋予执行权限
chmod +x run.sh

# 2. 正常运行（读取 config.yaml 监控远程主机）
./run.sh

# 3. Demo 模拟运行（免 SSH 连线测试 UI 效果）
./run.sh --demo
```

#### Windows

```cmd
:: 正常运行
run.bat

:: Demo 模拟运行
run.bat --demo
```

### 方式二：手动安装

如果你想手动管理环境：

```bash
# 1. 创建虚拟环境
uv venv

# 2. 安装依赖
uv pip install -r requirements.txt

# 3. 运行
# Linux / macOS
.venv/bin/python gpu_monitor.py
# Windows
.venv\Scripts\python.exe gpu_monitor.py

# Demo 模式
.venv/bin/python gpu_monitor.py --demo
```

或者使用 `pip`：

```bash
python -m venv .venv
source .venv/bin/activate        # Linux / macOS
# .venv\Scripts\activate.bat     # Windows
pip install -r requirements.txt
python gpu_monitor.py
```

---

## SSH 密钥配置

本工具**强制使用 SSH 私钥认证**，不支持交互式密码输入。请确保在运行前完成以下配置：

### 1. 生成 SSH 密钥（如果还没有）

```bash
ssh-keygen -t ed25519 -C "your_email@example.com"
```

### 2. 将公钥部署到远程服务器

```bash
ssh-copy-id user@remote-host
```

### 3. 配置 `~/.ssh/config`（推荐）

在 `~/.ssh/config` 中为每台服务器设置别名和连接参数，这样 `config.yaml` 中只需填写别名即可：

```
Host gpu-server-1
    HostName 192.168.1.101
    User your_username
    IdentityFile ~/.ssh/id_ed25519

Host gpu-server-2
    HostName 192.168.1.102
    User your_username
    IdentityFile ~/.ssh/id_ed25519
```

### 4. 测试 SSH 连接

```bash
ssh gpu-server-1    # 应该免密直接登录
ssh gpu-server-2
```

> **提示**：如果你的私钥有 passphrase，可以启动 `ssh-agent` 并添加密钥：
> ```bash
> eval "$(ssh-agent -s)"
> ssh-add ~/.ssh/id_ed25519
> ```

---

## 配置文件说明 (`config.yaml`)

配置文件位于项目根目录。以下是完整的配置选项：

```yaml
# 刷新时间间隔（单位：秒）
# 控制多久轮询一次所有远程主机的状态
refresh_interval: 2.0

# SSH 连接超时时间（单位：秒）
# 如果某台主机在此时间内未响应，将显示连接失败
timeout: 5.0

# SSH 配置文件路径（可选，默认读取 ~/.ssh/config）
ssh_config_path: "~/.ssh/config"

# 默认全局监控的目录路径
# 所有主机都会监控这些目录的剩余空间，主机级配置可覆盖此项
monitored_paths:
  - "/data"
  - "/home"

# 待监控的主机列表
hosts:
  # --- 基本配置 ---
  - name: "gpu-server-1"           # 必填：对应 ~/.ssh/config 中的 Host 别名或 IP 地址
    display_name: "GPU Server 1"   # 可选：界面显示的友好名称（不填则使用 name）

  # --- 自定义监控路径 ---
  - name: "gpu-server-2"
    display_name: "GPU Server 2"
    monitored_paths:               # 可选：覆盖全局的 monitored_paths
      - "/data"
      - "/data2"

  # --- 最简配置（display_name 缺省时使用 name）---
  - name: "192.168.1.100"

  # --- 无 GPU 的纯存储服务器也支持 ---
  - name: "storage-server"
    display_name: "Storage Server"
    monitored_paths:
      - "/mnt/data1"
      - "/home"
```

### 配置项详解

| 配置项 | 必填 | 默认值 | 说明 |
|-------|------|--------|------|
| `refresh_interval` | 否 | `2.0` | 轮询间隔（秒），值越小刷新越快但 SSH 开销越大 |
| `timeout` | 否 | `5.0` | SSH 连接超时（秒），超时的主机会显示连接失败 |
| `ssh_config_path` | 否 | `~/.ssh/config` | 自定义 SSH 配置文件路径 |
| `monitored_paths` | 否 | `["/data", "/home"]` | 全局默认监控目录，`df -h` 可查看可用挂载点 |
| `hosts` | 否 | 自动读取 `~/.ssh/config` | 主机列表，不填时自动从 SSH config 读取所有 Host |
| `hosts[].name` | **是** | - | 主机标识，匹配 `~/.ssh/config` 中的 Host 或直接填 IP |
| `hosts[].display_name` | 否 | 与 `name` 相同 | 界面中显示的名称 |
| `hosts[].monitored_paths` | 否 | 继承全局配置 | 该主机专属的监控目录，覆盖全局 `monitored_paths` |

> **注意**：如果 `config.yaml` 不存在，程序会自动读取 `~/.ssh/config` 中的所有 Host 并生成默认配置文件。

---

## 测试与诊断

我们提供了测试脚本来帮助诊断连接与解析情况：

1. **测试解析器**（本地单元测试）：
   ```bash
   # Linux / macOS
   .venv/bin/python tests/test_parser.py
   # Windows
   .venv\Scripts\python.exe tests/test_parser.py
   ```
2. **诊断 SSH 连接**（针对特定主机拉取并输出裸数据）：
   ```bash
   # Linux / macOS
   .venv/bin/python tests/test_ssh_lab.py
   # Windows
   .venv\Scripts\python.exe tests/test_ssh_lab.py
   ```

---

## 常见问题

### SSH 连接失败？
- 确认能手动 `ssh <host>` 免密登录
- 检查 `~/.ssh/config` 中的 `Host` 别名是否与 `config.yaml` 中的 `name` 一致
- 如果使用非默认密钥，确保在 SSH config 中指定了 `IdentityFile`
- 如果私钥有 passphrase，确保 `ssh-agent` 已启动并添加了密钥

### `nvidia-smi` 不存在？
- 完全没问题，程序会优雅降级，只显示磁盘配额和存储信息
- 适用于纯 CPU 服务器、存储节点等场景

### 刷新太慢/太快？
- 调整 `config.yaml` 中的 `refresh_interval`，默认 2 秒
