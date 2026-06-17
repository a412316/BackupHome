#!/usr/bin/env python3
"""
通用备份引擎

- BackupClient: 统一的 SSH/SFTP 客户端，支持密钥与密码两种认证
- BackupTask:   通用备份任务，按 config 中的 operations 列表依次执行
- 操作处理器:    download_files / download_folder / download_pattern /
                run_command / command_output_to_file / command_then_download /
                vzdump_backup / interactive_shell

所有“备份什么”由 config.py 声明，本模块只负责“如何执行”。
"""

import os
import re
import shutil
import stat
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import paramiko


class BackupClient:
    """SSH/SFTP 备份客户端，支持密钥认证与密码认证。"""

    def __init__(self, target: dict, ssh_config: dict):
        """
        Args:
            target: 目标配置 {host, port, user, auth, password?}
            ssh_config: SSH 通用配置 {key_file, timeout}
        """
        self.host = target['host']
        self.port = target.get('port', 22)
        self.user = target['user']
        self.auth = target.get('auth', 'key')
        self.password = target.get('password', '')
        self.timeout = ssh_config.get('timeout', 10)

        key_file = ssh_config.get('key_file', 'id_ed25519')
        self.ssh_key_path = Path(__file__).parent.absolute() / key_file

        self.ssh: Optional[paramiko.SSHClient] = None
        self.sftp: Optional[paramiko.SFTPClient] = None

    def connect(self) -> None:
        print(f'正在连接服务器 {self.host}...')
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if self.auth == 'password':
            # 密码认证（如交换机），不使用密钥代理，也不打开 SFTP
            self.ssh.connect(
                hostname=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                timeout=self.timeout,
                look_for_keys=False,
                allow_agent=False,
            )
        else:
            # 密钥认证，并打开 SFTP 供文件下载使用
            key = paramiko.Ed25519Key.from_private_key_file(self.ssh_key_path)
            self.ssh.connect(
                hostname=self.host,
                port=self.port,
                username=self.user,
                pkey=key,
                timeout=self.timeout,
            )
            self.sftp = self.ssh.open_sftp()
        print('连接成功！')

    def close(self) -> None:
        print('正在关闭连接...')
        if self.sftp:
            self.sftp.close()
        if self.ssh:
            self.ssh.close()
        print('连接已关闭')

    def download_file(self, remote_path: str, local_path: str) -> bool:
        try:
            self.sftp.get(remotepath=remote_path, localpath=local_path)
            return True
        except Exception:
            return False

    def download_folder(self, remote_path: str, local_path: str) -> None:
        for item in self.sftp.listdir_attr(remote_path):
            remote_item_path = f"{remote_path}/{item.filename}"
            local_item_path = os.path.join(local_path, item.filename)

            if stat.S_ISDIR(item.st_mode):
                os.makedirs(local_item_path, exist_ok=True)
                self.download_folder(remote_item_path, local_item_path)
            else:
                self.sftp.get(remotepath=remote_item_path, localpath=local_item_path)

    def listdir(self, remote_path: str) -> list:
        try:
            return self.sftp.listdir(remote_path)
        except IOError:
            return []

    def file_exists(self, remote_path: str) -> bool:
        try:
            self.sftp.stat(remote_path)
            return True
        except IOError:
            return False

    def exec_command(self, cmd: str) -> tuple:
        """执行命令，返回 (stdout, stderr)。"""
        _, stdout, stderr = self.ssh.exec_command(cmd)
        return stdout.read().decode(), stderr.read().decode()

    def exec_command_with_pty(self, cmd: str, input_data: str = '') -> tuple:
        """以 PTY 方式执行命令，返回 (exit_status, stdout, stderr)。"""
        stdin, stdout, stderr = self.ssh.exec_command(cmd, get_pty=True)
        if input_data:
            stdin.write(input_data)
            stdin.flush()
        exit_status = stdout.channel.recv_exit_status()
        return exit_status, stdout.read().decode(), stderr.read().decode()


class BackupTask:
    """通用备份任务：按 operations 列表依次执行各操作。"""

    def __init__(self, module_id: str, module_config: dict, ssh_config: dict,
                 paths_config: dict, base_path: Optional[str] = None):
        self.module_id = module_id
        self.name = module_config['name']
        self.tmp_subdir = module_config.get('tmp_subdir', module_id)
        self.zip_prefix = module_config.get('zip_prefix', module_id)
        self.target = module_config['target']
        self.operations = module_config.get('operations', [])

        self.base_path = Path(base_path) if base_path else Path(__file__).parent.absolute()
        tmp_root = self.base_path / paths_config.get('tmp_dir', 'tmp')
        self.tmp_path = tmp_root / self.tmp_subdir
        self.backup_path = self.base_path / paths_config.get('backup_dir', 'backup')

        self.client = BackupClient(self.target, ssh_config)

    # ------------------------------------------------------------------ 公共流程

    def prepare_dirs(self) -> None:
        self.tmp_path.mkdir(parents=True, exist_ok=True)
        self.backup_path.mkdir(parents=True, exist_ok=True)

    def compress_backup(self) -> Path:
        print('正在压缩备份文件...')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        zip_filename = f'{self.zip_prefix}_{timestamp}.zip'
        zip_filepath = self.backup_path / zip_filename

        with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(self.tmp_path):
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(self.tmp_path.parent)
                    zipf.write(file_path, arcname)

        size_mb = zip_filepath.stat().st_size / (1024 * 1024)
        print(f'  压缩完成: {zip_filename} ({size_mb:.2f} MB)')
        return zip_filepath

    def cleanup_temp(self) -> None:
        print('正在清理临时文件夹...')
        try:
            shutil.rmtree(self.tmp_path)
            print('  临时文件夹已清理')
        except Exception as e:
            print(f'  清理失败: {e}')

    def run(self) -> None:
        try:
            print('=' * 50)
            print(f'开始备份任务 - {self.name}')
            print('=' * 50)

            self.prepare_dirs()
            self.client.connect()

            for op in self.operations:
                self.dispatch(op)

            print('=' * 50)
            zip_file = self.compress_backup()

            print('=' * 50)
            print('备份任务完成！')
            print(f'备份文件位置: {zip_file}')
            print('=' * 50)

            self.cleanup_temp()

        except Exception as e:
            print(f'备份过程出错: {e}')
            raise
        finally:
            self.client.close()

    # ------------------------------------------------------------------ 操作分发

    def dispatch(self, op: dict) -> None:
        op_type = op.get('type')
        handler = getattr(self, f'_op_{op_type}', None)
        if handler is None:
            raise ValueError(f'不支持的操作类型: {op_type}')
        print(f'\n--- 执行操作: {op_type} ---')
        handler(op)

    def _dest_dir(self, op: dict) -> Path:
        dest = self.tmp_path / op.get('dest_subdir', '')
        dest.mkdir(parents=True, exist_ok=True)
        return dest

    # ------------------------------------------------------------------ 操作处理器

    def _op_run_command(self, op: dict) -> None:
        self.client.exec_command(op['command'])
        print('  命令已执行')

    def _op_download_files(self, op: dict) -> None:
        dest = self._dest_dir(op)
        check_exists = op.get('check_exists', False)

        for remote_file in op['files']:
            file_name = Path(remote_file).name
            local_file = dest / file_name

            if check_exists and not self.client.file_exists(remote_file):
                print(f'  ✗ 文件不存在: {file_name}')
                continue

            if self.client.download_file(remote_file, str(local_file)):
                print(f'  ✓ 已下载: {file_name}')
            else:
                print(f'  ✗ 下载失败: {file_name}')

    def _op_download_folder(self, op: dict) -> None:
        dest = self._dest_dir(op)
        self.client.download_folder(op['remote_path'], str(dest))
        print(f'  文件夹下载完成: {op["remote_path"]}')

    def _op_download_pattern(self, op: dict) -> None:
        dest = self._dest_dir(op)
        pattern = re.compile(op['pattern'])
        remote_dirs = op.get('remote_dirs') or [op['remote_dir']]

        for remote_dir in remote_dirs:
            for filename in self.client.listdir(remote_dir):
                if pattern.search(filename):
                    remote_file = f"{remote_dir}/{filename}"
                    local_file = dest / filename
                    if self.client.download_file(remote_file, str(local_file)):
                        print(f'  ✓ 已下载: {filename}')
                    else:
                        print(f'  ✗ 下载失败: {filename}')

    def _op_command_output_to_file(self, op: dict) -> None:
        dest_dir = self._dest_dir(op)
        dest_file = dest_dir / op['dest_file']

        stdout, _ = self.client.exec_command(op['command'])
        lines = stdout.splitlines()

        if op.get('skip_blank_and_comments'):
            lines = [ln for ln in lines if ln and not ln.lstrip().startswith('#')]

        with open(dest_file, 'w', encoding='utf8') as f:
            f.write('\n'.join(lines))
        print(f'  已保存: {op["dest_file"]}')

    def _op_command_then_download(self, op: dict) -> None:
        """执行命令 -> 正则解析输出得到文件路径 -> 可选 copy_command -> 下载。"""
        dest = self._dest_dir(op)
        regex = re.compile(op['parse_regex'])
        marker = op.get('match_marker')
        use_group = 1 if op.get('parse_group') is not None else (1 if regex.groups > 0 else 0)

        stdout, stderr = self.client.exec_command(op['command'])
        dump_path = None
        for line in (stdout + stderr).splitlines():
            if marker and marker not in line:
                continue
            match = regex.search(line)
            if match:
                dump_path = match.group(op.get('parse_group', use_group))
                break

        if not dump_path:
            print('  未解析到目标文件路径')
            return

        copy_cmd_tpl = op.get('copy_command')
        if copy_cmd_tpl:
            self.client.exec_command(copy_cmd_tpl.format(dump_path=dump_path))

        file_name = Path(dump_path).name
        local_file = dest / file_name
        if self.client.download_file(dump_path, str(local_file)):
            print(f'  ✓ 已下载: {file_name}')
        else:
            print(f'  ✗ 下载失败: {file_name}')

    def _op_vzdump_backup(self, op: dict) -> None:
        """PVE: 循环 LXC -> PTY 执行 vzdump -> 解析归档路径 -> 下载 -> 清理远程。"""
        dest = self._dest_dir(op)
        regex = re.compile(op['parse_regex'])
        marker = op.get('parse_marker', 'creating vzdump archive')
        pty_input = op.get('pty_input', '')
        cmd_tpl = op['command_template']
        parse_group = op.get('parse_group', 1 if regex.groups > 0 else 0)

        remote_files = []
        for lxc_id in op['lxc_ids']:
            print(f'  正在备份 LXC {lxc_id}...')
            exit_status, stdout, _ = self.client.exec_command_with_pty(
                cmd_tpl.format(id=lxc_id), pty_input
            )
            if exit_status != 0:
                print(f'  备份 LXC {lxc_id} 失败 (exit {exit_status})')
                continue
            for line in stdout.splitlines():
                if marker in line:
                    match = regex.search(line)
                    if match:
                        remote_files.append(match.group(parse_group))
                        print(f'    归档: {Path(remote_files[-1]).name}')
                        break

        if not remote_files:
            print('  没有成功创建任何备份文件')
            return

        print('正在下载备份文件...')
        for remote_file in remote_files:
            file_name = Path(remote_file).name
            local_file = dest / file_name
            if self.client.download_file(remote_file, str(local_file)):
                print(f'  ✓ 已下载: {file_name}')
            else:
                print(f'  ✗ 下载失败: {file_name}')

        if op.get('cleanup_remote'):
            print('正在清理远程备份文件...')
            for remote_file in remote_files:
                self.client.exec_command_with_pty(f'rm -f "{remote_file}"')
                print(f'  已清理: {Path(remote_file).name}')

    def _op_interactive_shell(self, op: dict) -> None:
        """交换机等交互式设备：invoke_shell 登录 -> 采集命令 -> 清洗输出 -> 存盘。"""
        dest_dir = self._dest_dir(op)
        dest_file = dest_dir / op['dest_file']

        shell = self.client.ssh.invoke_shell()
        self._drain(shell, op.get('login_wait', 1.0))

        fmt = {'username': self.client.user, 'password': self.client.password}
        print('正在执行登录序列...')
        for step in op.get('login_sequence', []):
            shell.send(f'{step.format(**fmt)}\n')
            self._drain(shell, op.get('step_wait', 0.5))

        print(f'正在获取: {op["capture_command"]}')
        shell.send(f'{op["capture_command"]}\n')
        time.sleep(op.get('capture_wait', 3))

        output = ''
        while shell.recv_ready():
            output += shell.recv(4096).decode('utf-8', errors='ignore')

        # 输出过短时再补一次
        marker = op['capture_command']
        if marker not in output or len(output) < op.get('min_output', 100):
            shell.send(' \n')
            time.sleep(2)
            while shell.recv_ready():
                output += shell.recv(4096).decode('utf-8', errors='ignore')

        print(f'输出获取完成，共 {len(output)} 字节')

        lines = self._clean_output(output, op.get('clean', {}))
        with open(dest_file, 'w', encoding='utf8') as f:
            f.write('\n'.join(lines))
        print(f'  已保存: {op["dest_file"]}')

    # ------------------------------------------------------------------ 交互辅助

    @staticmethod
    def _drain(shell: paramiko.Channel, wait: float) -> str:
        time.sleep(wait)
        output = ''
        while shell.recv_ready():
            output += shell.recv(4096).decode('utf-8', errors='ignore')
        return output

    @staticmethod
    def _clean_output(output: str, rules: dict) -> list:
        """按规则清洗交互式输出，规则来自 config（对应原 _clean_config_output）。"""
        skip_until = rules.get('skip_until_contains')
        stop_at = rules.get('stop_at')
        prompt_regex = re.compile(rules['prompt_regex']) if rules.get('prompt_regex') else None
        strip_trailing = rules.get('strip_trailing', [])
        drop_empty = rules.get('drop_empty', True)

        result = []
        skipping = bool(skip_until)
        reached_end = False

        for line in output.splitlines():
            if skipping:
                if skip_until in line:
                    skipping = False
                continue

            stripped = line.strip()
            if reached_end:
                continue
            if stop_at is not None and stripped == stop_at:
                result.append(line)
                reached_end = True
                continue
            if drop_empty and not stripped:
                continue
            if prompt_regex and prompt_regex.match(stripped):
                continue
            if strip_trailing and stripped.endswith(tuple(strip_trailing)):
                line = re.sub(r'[>#].*$', '', line).rstrip()
                if not line.strip():
                    continue

            result.append(line)

        return result
