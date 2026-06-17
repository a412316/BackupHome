# 统一备份工具

一套用于自动备份多个服务器和设备的 Python 工具，采用**配置驱动**架构：所有“备份什么”写在 `config.py` 中，由通用引擎统一执行。

## 设计

```
backup_all.py   CLI 入口（参数解析、调度、汇总）
backup_engine.py 通用引擎（BackupClient + BackupTask + 操作处理器）
config.py       配置（模块注册表 + 每个模块的 operations 列表，含敏感信息，不提交）
```

每个备份模块在 `config.py` 的 `BACKUP_MODULES` 中以一个条目声明：连接目标 + 一串**操作**。引擎按顺序执行这些操作，支持 8 种操作类型，覆盖文件下载、命令执行、PVE 容器备份、交换机交互等所有场景。

## 环境要求

- Python 3.8+
- 依赖：`paramiko`

## 安装

```bash
pip install paramiko
cp config.example.py config.py   # 复制配置模板
vim config.py                    # 填入实际的服务器信息和凭据
# 确保有 SSH 密钥文件（脚本目录下 id_ed25519，chmod 600）
```

## 快速开始

```bash
python backup_all.py --help        # 查看帮助
python backup_all.py --list        # 列出所有可用模块
python backup_all.py --all         # 运行所有备份
python backup_all.py -m 12 7 91    # 运行指定模块
python backup_all.py -m switch     # 仅备份交换机
```

## 配置说明

`config.py`（参考 `config.example.py`）包含三部分：

### SSH 通用配置

```python
SSH = {'key_file': 'id_ed25519', 'timeout': 10}
PATHS = {'base_path': None, 'tmp_dir': 'tmp', 'backup_dir': 'backup'}
```

### 模块注册表 `BACKUP_MODULES`

每个模块的连接信息与备份内容：

```python
BACKUP_MODULES = {
    '12': {
        'name': '1Panel 12',
        'tmp_subdir': '12',          # 临时目录子名 tmp/<tmp_subdir>
        'zip_prefix': '12',          # 压缩包前缀 <zip_prefix>_<时间戳>.zip
        'target': {                  # 连接目标
            'host': '192.168.50.12',
            'port': 22,
            'user': 'root',
            'auth': 'key',           # 'key'（密钥）或 'password'（密码）
            'description': '1Panel 12服务器',
        },
        'operations': [ ... ],       # 操作列表，按顺序执行
    },
}
```

### 支持的操作类型

| type | 用途 | 关键字段 |
|------|------|----------|
| `run_command` | 仅执行远程命令 | `command` |
| `download_files` | 下载一组文件 | `dest_subdir`, `files`, 可选 `check_exists` |
| `download_folder` | 递归下载目录 | `dest_subdir`, `remote_path` |
| `download_pattern` | 目录内按正则筛选下载 | `dest_subdir`, `remote_dir`/`remote_dirs`, `pattern` |
| `command_output_to_file` | 执行命令并把 stdout 存为文件 | `dest_subdir`, `dest_file`, `command`, 可选 `skip_blank_and_comments` |
| `command_then_download` | 执行命令→正则解析路径→可选 copy→下载 | `command`, `parse_regex`, 可选 `match_marker`/`copy_command` |
| `vzdump_backup` | PVE：循环 LXC 备份→下载→清理远程 | `lxc_ids`, `command_template`, `pty_input`, `parse_regex`, `cleanup_remote` |
| `interactive_shell` | 交换机：交互式登录→采集→清洗→存盘 | `dest_file`, `login_sequence`, `capture_command`, `clean` |

`command_then_download` 示例（Gitea dump）：

```python
{
    'type': 'command_then_download',
    'dest_subdir': 'gitea',
    'command': 'docker exec -u git -w /tmp $(docker ps -qf "name=gitea") bash -c "/usr/local/bin/gitea dump -c /data/gitea/conf/app.ini"',
    'match_marker': 'Finish dumping in file',
    'parse_regex': r'/tmp/gitea-dump-\d+\.zip',
    'copy_command': 'docker cp $(docker ps -qf "name=gitea"):{dump_path} {dump_path}',
}
```

## 内置模块

| ID | 名称 | 描述 | 操作数 |
|----|------|------|--------|
| `12` | 1Panel 12 | Grafana, Prometheus, sun-panel, sub-store | 5 |
| `oracle` | Oracle | Bitwarden, AdGuardHome, Gitea | 3 |
| `7` | ADG | AdGuardHome, Nginx | 2 |
| `91` | Mini | Surge 配置 | 1 |
| `5` | VPN | xray, snell, systemd 服务, openvpn | 4 |
| `4` | PVE | LXC 容器备份 | 1 |
| `switch` | Switch | 交换机配置（密码认证 + 交互式 shell） | 1 |

## 添加新的备份模块

无需写代码，只需在 `config.py` 的 `BACKUP_MODULES` 中新增一个条目，用合适的操作类型组合描述备份内容即可。若现有 8 种操作类型无法满足（例如全新的交互协议），可在 `backup_engine.py` 的 `BackupTask` 中新增 `_op_<类型>` 方法并在此登记。

## 目录结构

```
.
├── backup_all.py          # CLI 入口
├── backup_engine.py       # 通用引擎（客户端 + 任务 + 操作处理器）
├── config.py              # 配置（含敏感信息，不提交）
├── config.example.py      # 配置模板
├── .gitignore
├── id_ed25519             # SSH 私钥（不提交）
├── backup/                # 备份输出目录
└── tmp/                   # 临时文件目录
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

## 安全建议

- 使用强密钥短语保护 SSH 私钥；`config.py` 与 `id_ed25519` 权限设为 `600`
- 定期轮换 SSH 密钥与交换机密码
- 为备份任务创建专用账户，仅授予必要权限
- 在受信任的网络环境中运行

## 许可证

MIT License
