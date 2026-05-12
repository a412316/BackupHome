# 统一备份工具

一套用于自动备份多个服务器和设备的 Python 脚本集合，支持外部配置文件管理敏感信息。

## 功能特性

- 支持多种备份目标：1Panel、Oracle、ADG、Mini、PVE、VPN、交换机
- 统一的 CLI 入口，支持批量或单独执行
- 外部配置文件管理敏感信息（IP、端口、用户名、密码）
- 自动压缩备份文件
- 清晰的执行反馈和错误处理
- 模块化设计，易于扩展

## 环境要求

- Python 3.8+
- 依赖库：`paramiko`

## 安装

```bash
# 安装依赖
pip install paramiko

# 复制配置文件模板
cp config.example.py config.py

# 编辑配置文件，填入实际的服务器信息和凭据
vim config.py

# 确保有 SSH 密钥文件（在脚本目录下）
# chmod 600 id_ed25519
```

## 配置说明

### 配置文件结构

`config.py` 包含所有敏感信息，**不应提交到版本控制系统**。

```python
# SSH 通用配置
SSH = {
    'key_file': 'id_ed25519',  # SSH 私钥文件路径
    'timeout': 10,              # 连接超时时间（秒）
}

# 备份目标配置
BACKUP_TARGETS = {
    'panel12': {
        'host': '192.168.50.12',
        'port': 22,
        'user': 'root',
        'description': '1Panel 12服务器',
    },
    'oracle': {
        'host': '192.168.50.x',  # 修改为实际 IP
        'port': 22,
        'user': 'root',
        'description': 'Oracle服务器',
    },
    # ... 其他配置
}
```

### 配置文件注意事项

1. **安全性**：`config.py` 包含敏感信息，已在 `.gitignore` 中排除
2. **模板文件**：`config.example.py` 可作为参考，但不包含真实凭据
3. **交换机密码**：交换机使用密码认证，需要单独配置
4. **PVE LXC IDs**：在 PVE 配置中指定要备份的容器 ID 列表

## 快速开始

### 查看帮助

```bash
python backup_all.py --help
```

### 列出所有可用模块

```bash
python backup_all.py --list
```

输出示例：
```
可用的备份模块:
ID         名称              描述
--------------------------------------------------------------------------------
12         1Panel 12       1Panel 12服务器 (Grafana, Prometheus, sun-panel, sub-store) ✓
oracle     Oracle          Oracle服务器 (Bitwarden, AdGuardHome, Gitea) ✗ (未配置)
7          ADG             ADG服务器 (AdGuardHome, Nginx, crontab) ✓
91         Mini            Mini服务器 (Surge配置) ✓
4          PVE             PVE服务器 (LXC容器备份) ✓
5          VPN             VPN服务器 (Shadowsocks, Snell, OpenVPN) ✓
switch     Switch          交换机配置备份 ✓
```

### 运行所有备份

```bash
python backup_all.py --all
```

### 运行指定模块

```bash
# 备份 1Panel 12 和 ADG 服务器
python backup_all.py -m 12 7

# 仅备份交换机配置
python backup_all.py -m switch
```

## 备份模块说明

| ID | 名称 | 描述 | 配置键 |
|----|------|------|--------|
| `12` | 1Panel 12 | Grafana, Prometheus, sun-panel, sub-store | `panel12` |
| `oracle` | Oracle | Bitwarden, AdGuardHome, Gitea | `oracle` |
| `7` | ADG | AdGuardHome, Nginx, crontab | `adg` |
| `91` | Mini | Surge 配置文件 | `mini` |
| `4` | PVE | LXC 容器备份 | `pve` |
| `5` | VPN | Shadowsocks, Snell, OpenVPN | `vpn` |
| `switch` | Switch | 交换机配置备份 | `switch` |

## 单独使用各模块

如果需要单独运行某个备份脚本（会使用内置的默认值，不推荐生产环境）：

```bash
python backup_1panel12.py
python backup_oracle.py
python backup_adg.py
python backup_mini.py
python backup_pve.py
python backup_vpn.py
python get_switch_config.py
```

**注意**：单独运行时使用硬编码的默认配置，建议通过 `backup_all.py` 统一管理。

## 目录结构

```
.
├── backup_all.py          # 统一 CLI 入口
├── config.py              # 配置文件（包含敏感信息，不提交）
├── config.example.py      # 配置文件模板
├── .gitignore             # Git 忽略文件
├── backup_1panel12.py     # 1Panel 12 备份模块
├── backup_oracle.py       # Oracle 备份模块
├── backup_adg.py          # ADG 备份模块
├── backup_mini.py         # Mini 备份模块
├── backup_pve.py          # PVE 备份模块
├── backup_vpn.py          # VPN 备份模块
├── get_switch_config.py   # 交换机配置备份模块
├── id_ed25519            # SSH 私钥（不提交）
├── backup/               # 备份文件输出目录
└── tmp/                  # 临时文件目录
```

## 命令行参数

```
usage: backup_all.py [-h] [-a] [-m MODULE [MODULE ...]] [-l] [--base-path BASE_PATH]

选项:
  -h, --help            显示帮助信息
  -a, --all             运行所有备份任务
  -m, --modules MODULE  指定要运行的备份模块ID（可多个）
  -l, --list            列出所有可用的备份模块
  --base-path BASE_PATH 备份基础路径（默认: 脚本所在目录）
```

## 故障排查

### 配置文件错误

```
错误: 未找到配置文件 config.py
请复制 config.example.py 为 config.py 并填入实际配置
```

**解决方法**：
```bash
cp config.example.py config.py
# 编辑 config.py 填入正确的配置
```

### 连接超时

- 检查目标服务器是否在线
- 检查 SSH 密钥是否正确
- 检查防火墙规则
- 增加 `config.py` 中的 `timeout` 值

### 权限错误

- 确保 SSH 密钥有正确的权限（`chmod 600 id_ed25519`）
- 检查远程服务器上的用户权限
- 确认密钥文件路径正确

### 找不到文件

- 检查远程路径是否正确
- 确认服务/容器正在运行

## 开发

### 添加新的备份模块

1. 创建新的备份脚本，参考现有模块的结构
2. 在 `config.py` 的 `BACKUP_TARGETS` 中添加配置
3. 在 `backup_all.py` 的 `BACKUP_MODULES` 中注册新模块
4. 测试新模块

### 模块开发模板

```python
from pathlib import Path
from typing import Optional
import paramiko

class BackupClient:
    """SSH/SFTP 客户端基类"""
    # ... 详见现有代码

class MyBackup:
    """我的备份任务"""

    def __init__(self, base_path: Optional[str] = None, config: dict = None, ssh_config: dict = None):
        self.base_path = Path(base_path) if base_path else Path(__file__).parent.absolute()
        self.tmp_path = self.base_path / 'tmp' / 'my_backup'
        self.backup_path = self.base_path / 'backup'

        if config and ssh_config:
            self.client = BackupClient(config, ssh_config)
        else:
            # 向后兼容的默认值
            self.client = BackupClient(
                {'host': '192.168.50.x', 'port': 22, 'user': 'root'},
                {'key_file': 'id_ed25519', 'timeout': 10}
            )

    def run(self) -> None:
        # 实现备份逻辑
        pass
```

## 安全建议

1. **密钥管理**：使用强密钥短语保护 SSH 私钥
2. **权限控制**：设置 `config.py` 和 `id_ed25519` 的文件权限为 `600`
3. **定期轮换**：定期更换 SSH 密钥和密码
4. **最小权限**：为备份任务创建专用账户，仅授予必要权限
5. **网络隔离**：在受信任的网络环境中运行

## 许可证

MIT License
