# -*- coding: utf-8 -*-
"""
备份配置文件（模板）
复制此文件为 config.py 并填入实际配置信息。
注意: config.py 包含敏感信息，不应提交到版本控制系统。

============================================================================
配置模型
============
每个备份模块由一个 BACKUP_MODULES 条目描述：
  '<id>':  CLI 用的模块 ID（--list / -m 使用）
    name:        显示名称
    tmp_subdir:  临时目录子名（tmp/<tmp_subdir>）
    zip_prefix:  压缩包名前缀（<zip_prefix>_<时间戳>.zip）
    target:      连接目标 {host, port, user, auth, password?}
                   auth: 'key'（密钥）或 'password'（密码）
    operations:  操作列表，按顺序执行。支持 8 种类型：
      - run_command            仅执行远程命令
      - download_files         下载一组文件（可选 check_exists）
      - download_folder        递归下载目录
      - download_pattern       目录内按正则筛选下载
      - command_output_to_file 执行命令并把 stdout 存为文件
      - command_then_download  执行命令→正则解析路径→可选 copy→下载
      - vzdump_backup          PVE：循环 LXC 备份→下载→清理远程
      - interactive_shell      交换机：交互式登录→采集→清洗→存盘
============================================================================
"""

# ============================================================================
# SSH 通用配置
# ============================================================================
SSH = {
    'key_file': 'id_ed25519',    # SSH 私钥（相对于脚本目录或绝对路径）
    'known_hosts': 'known_hosts',  # 主机指纹文件（相对于脚本目录，需先 ssh-keyscan 采集）
    'timeout': 10,               # 连接超时（秒）
}

# ============================================================================
# 路径配置
# ============================================================================
PATHS = {
    'base_path': None,   # 备份基础路径（None 表示脚本所在目录）
    'tmp_dir': 'tmp',    # 临时文件目录名
    'backup_dir': 'backup',  # 备份输出目录名
}

# ============================================================================
# 备份模块（注册表 + 每个模块的操作列表）
# ============================================================================
BACKUP_MODULES = {
    # ----------------------------------------------------------------------
    # 1Panel 12：Grafana / Prometheus / sun-panel / sub-store
    # ----------------------------------------------------------------------
    '12': {
        'name': '1Panel 12',
        'tmp_subdir': '12',
        'zip_prefix': '12',
        'target': {
            'host': '192.168.50.12',
            'port': 22,
            'user': 'root',
            'auth': 'key',
            'description': '1Panel 12服务器',
        },
        'operations': [
            # 先把 grafana.ini 从容器拷到宿主机，便于 SFTP 下载
            {
                'type': 'run_command',
                'command': 'docker ps -qf "name=grafana" | xargs -I {} docker cp {}:/etc/grafana/grafana.ini /opt/1panel/apps/grafana/grafana/data/',
            },
            {
                'type': 'download_files',
                'dest_subdir': 'Grafana',
                'files': [
                    '/opt/1panel/apps/grafana/grafana/data/grafana.ini',
                    '/opt/1panel/apps/grafana/grafana/data/grafana.db',
                ],
            },
            {
                'type': 'download_folder',
                'dest_subdir': 'prometheus',
                'remote_path': '/opt/1panel/apps/prometheus/prometheus/conf',
            },
            {
                'type': 'download_folder',
                'dest_subdir': 'sun-panel',
                'remote_path': '/opt/1panel/apps/local/sun-panel/localsun-panel/data/conf/',
            },
            {
                'type': 'download_folder',
                'dest_subdir': 'sub-store',
                'remote_path': '/opt/1panel/apps/local/sub-store/localsub-store/data',
            },
        ],
    },

    # ----------------------------------------------------------------------
    # Oracle：Bitwarden / AdGuardHome / Gitea
    # ----------------------------------------------------------------------
    'oracle': {
        'name': 'Oracle',
        'tmp_subdir': 'oracle',
        'zip_prefix': 'oracle',
        'target': {
            'host': '192.168.50.x',  # 请修改为实际 IP
            'port': 22,
            'user': 'root',
            'auth': 'key',
            'description': 'Oracle服务器',
        },
        'operations': [
            {
                'type': 'download_files',
                'dest_subdir': 'bitwarden',
                'files': [
                    '/opt/1panel/apps/bitwarden/bitwarden/data/db.sqlite3',
                    '/opt/1panel/apps/bitwarden/bitwarden/data/rsa_key.pem',
                ],
            },
            {
                'type': 'download_folder',
                'dest_subdir': 'AdGuardHome',
                'remote_path': '/opt/1panel/apps/adguardhome/adguardhome/data/conf/',
            },
            {
                'type': 'command_then_download',
                'dest_subdir': 'gitea',
                'command': 'docker exec -u git -w /tmp $(docker ps -qf "name=gitea") bash -c "/usr/local/bin/gitea dump -c /data/gitea/conf/app.ini"',
                'match_marker': 'Finish dumping in file',
                'parse_regex': r'/tmp/gitea-dump-\d+\.zip',
                'copy_command': 'docker cp $(docker ps -qf "name=gitea"):{dump_path} {dump_path}',
            },
        ],
    },

    # ----------------------------------------------------------------------
    # ADG：AdGuardHome / Nginx（/ crontab / ssl）
    # ----------------------------------------------------------------------
    '7': {
        'name': 'ADG',
        'tmp_subdir': '7',
        'zip_prefix': '7',
        'target': {
            'host': '192.168.50.7',
            'port': 22,
            'user': 'root',
            'auth': 'key',
            'description': 'ADG服务器',
        },
        'operations': [
            {
                'type': 'download_files',
                'dest_subdir': 'AdGuardHome',
                'files': [
                    '/etc/adguardhome/AdGuardHome.yaml',
                    '/etc/adguardhome/update_github_hosts.sh',
                ],
            },
            {
                'type': 'download_pattern',
                'dest_subdir': 'nginx',
                'remote_dir': '/etc/nginx/conf.d',
                'pattern': r'com\.conf$',
            },
            # 如需 crontab，取消下面注释
            # {
            #     'type': 'command_output_to_file',
            #     'dest_subdir': '',
            #     'dest_file': 'crontab.txt',
            #     'command': 'crontab -l',
            #     'skip_blank_and_comments': True,
            # },
            # {
            #     'type': 'download_folder',
            #     'dest_subdir': 'AdGuardHome/ssl',
            #     'remote_path': '/root/AdGuardHome/ssl',
            # },
        ],
    },

    # ----------------------------------------------------------------------
    # Mini：Surge 配置文件
    # ----------------------------------------------------------------------
    '91': {
        'name': 'Mini',
        'tmp_subdir': '91',
        'zip_prefix': '91',
        'target': {
            'host': '192.168.50.91',
            'port': 22,
            'user': 'xy',
            'auth': 'key',
            'description': 'Mini服务器',
        },
        'operations': [
            {
                'type': 'download_files',
                'dest_subdir': 'Surge',
                'files': [
                    '/Users/xy/Library/Application Support/Surge/Profiles/sub-store_mini_External.conf',
                ],
            },
        ],
    },

    # ----------------------------------------------------------------------
    # VPN：xray / snell / services / openvpn
    # ----------------------------------------------------------------------
    '5': {
        'name': 'VPN',
        'tmp_subdir': '5',
        'zip_prefix': '5',
        'target': {
            'host': '192.168.50.5',
            'port': 22,
            'user': 'root',
            'auth': 'key',
            'description': 'VPN服务器',
        },
        'operations': [
            {
                'type': 'download_files',
                'dest_subdir': 'vpn/xray',
                'files': ['/usr/local/etc/xray/config.json'],
            },
            {
                'type': 'download_files',
                'dest_subdir': 'vpn/snell',
                'files': ['/etc/snell/snell.conf'],
            },
            {
                'type': 'download_files',
                'dest_subdir': 'vpn/services',
                'check_exists': True,
                'files': [
                    '/etc/systemd/system/shadow-tls-snell.service',
                    '/etc/systemd/system/xray.service',
                    '/etc/systemd/system/snell.service',
                ],
            },
            {
                'type': 'download_pattern',
                'dest_subdir': 'vpn/openvpn',
                'remote_dirs': ['/etc/openvpn', '/etc/openvpn-server'],
                'pattern': r'\.(conf|ovpn)$',
            },
        ],
    },

    # ----------------------------------------------------------------------
    # PVE：LXC 容器备份（vzdump + PTY + 下载 + 清理远程）
    # ----------------------------------------------------------------------
    '4': {
        'name': 'PVE',
        'tmp_subdir': '4',
        'zip_prefix': '4',
        'target': {
            'host': '192.168.50.4',
            'port': 22,
            'user': 'root',
            'auth': 'key',
            'description': 'PVE服务器',
        },
        'operations': [
            {
                'type': 'vzdump_backup',
                'dest_subdir': 'lxc',
                'lxc_ids': ['100', '101'],  # 要备份的 LXC 容器 ID
                'command_template': (
                    "vzdump {id} --mode snapshot "
                    "--notes-template '{{guestname}}' --node pve "
                    "--notification-mode auto --storage local "
                    "--prune-backups keep-last=1 --remove 1 --compress zstd"
                ),
                'pty_input': 'Y\n',
                'parse_marker': 'creating vzdump archive',
                'parse_regex': r"(/var/lib/vz/dump/[^\s'\"]+)",
                'cleanup_remote': True,
            },
        ],
    },

    # ----------------------------------------------------------------------
    # Switch：交换机配置（密码认证 + 交互式 shell）
    # ----------------------------------------------------------------------
    'switch': {
        'name': 'Switch',
        'tmp_subdir': 'switch',
        'zip_prefix': 'switch_config',
        'target': {
            'host': '192.168.50.3',
            'port': 22,
            'user': 'admin',
            'auth': 'password',
            'password': 'YOUR_SWITCH_PASSWORD',  # 交换机使用密码认证（请填真实密码，勿提交）
            'description': '交换机',
        },
        'operations': [
            {
                'type': 'interactive_shell',
                'dest_subdir': '',
                'dest_file': 'switch_config.txt',
                'login_sequence': ['{username}', '{password}', 'en', 'terminal length 0'],
                'capture_command': 'show running-config',
                'capture_wait': 3,
                'min_output': 100,
                'clean': {
                    'skip_until_contains': 'show running-config',
                    'stop_at': 'end',
                    'prompt_regex': r'^[\w-]+[>#]$',
                    'strip_trailing': ['#', '>'],
                    'drop_empty': True,
                },
            },
        ],
    },
}
