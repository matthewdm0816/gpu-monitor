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

## 快速运行

本工具使用 `uv` 虚拟环境管理器自动创建虚拟环境并同步依赖。

### Linux & macOS

1. 赋予运行脚本可执行权限：
   ```bash
   chmod +x run.sh
   ```
2. **正常运行**（读取 `config.yaml` 监控远程主机）：
   ```bash
   ./run.sh
   ```
3. **Demo 模拟运行**（免 SSH 连线测试 UI 效果）：
   ```bash
   ./run.sh --demo
   ```

### Windows

1. **正常运行**：
   ```cmd
   run.bat
   ```
2. **Demo 模拟运行**：
   ```cmd
   run.bat --demo
   ```

---

## 配置文件说明 (`config.yaml`)

配置文件位于项目根目录，您可以通过编辑 `config.yaml` 调整监控选项：

```yaml
# 刷新时间间隔（单位：秒）
refresh_interval: 2.0

# SSH 连接超时时间（单位：秒）
timeout: 5.0

# 默认全局监控的目录路径（可配置多个，使用 df -h 查看）
monitored_paths:
  - "/data"
  - "/home"

# 待监控的主机列表
hosts:
  - name: "lab"                    # 对应 ~/.ssh/config 中的 Host 别名或 IP 地址
    display_name: "Lab Server 128" # 界面显示的友好名称
  - name: "lab127"
    display_name: "Lab Server 127"
    # 支持在主机级别重写监控路径 (可选)
    # monitored_paths:
    #   - "/data"
    #   - "/opt"
```

> **注意**：SSH 认证完全读取您的本地 `~/.ssh/config`，因此最便捷的方式是在本地系统的 `~/.ssh/config` 中配置好别名和私钥（或者开启 `SSH Agent`），只需在 `config.yaml` 中填写对应的 Host 别名即可。

---

## 测试与诊断

我们提供了测试脚本来帮助诊断连接与解析情况：

1. **测试解析器**（本地单元测试）：
   ```bash
   # Linux
   .venv/bin/python tests/test_parser.py
   # Windows
   .venv\Scripts\python.exe tests/test_parser.py
   ```
2. **诊断 SSH 连接**（针对特定主机拉取并输出裸数据）：
   ```bash
   # Linux
   .venv/bin/python tests/test_ssh_lab.py
   # Windows
   .venv\Scripts\python.exe tests/test_ssh_lab.py
   ```
