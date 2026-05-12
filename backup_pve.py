import os
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import paramiko


class BackupClient:
    """SSH/SFTP备份客户端基类"""

    def __init__(self, config: dict, ssh_config: dict):
        self.host = config['host']
        self.port = config.get('port', 22)
        self.user = config['user']
        self.timeout = ssh_config.get('timeout', 10)

        key_file = ssh_config.get('key_file', 'id_ed25519')
        base_path = Path(__file__).parent.absolute()
        self.ssh_key_path = base_path / key_file

        self.ssh: Optional[paramiko.SSHClient] = None
        self.sftp: Optional[paramiko.SFTPClient] = None

    def connect(self) -> None:
        print(f'正在连接服务器 {self.host}...')
        key = paramiko.Ed25519Key.from_private_key_file(self.ssh_key_path)
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(hostname=self.host, username=self.user, pkey=key, timeout=self.timeout)
        self.sftp = self.ssh.open_sftp()
        print('连接成功！')

    def close(self) -> None:
        print('正在关闭连接...')
        if self.sftp:
            self.sftp.close()
        if self.ssh:
            self.ssh.close()
        print('连接已关闭')

    def download_file(self, remote_path: str, local_path: str) -> None:
        self.sftp.get(remotepath=remote_path, localpath=local_path)

    def exec_command_with_pty(self, cmd: str, input_data: str = '') -> tuple[int, str, str]:
        stdin, stdout, stderr = self.ssh.exec_command(cmd, get_pty=True)
        if input_data:
            stdin.write(input_data)
            stdin.flush()
        exit_status = stdout.channel.recv_exit_status()
        return exit_status, stdout.read().decode(), stderr.read().decode()


class PveBackup:
    """PVE服务器备份任务"""

    BACKUP_COMMAND = 'vzdump {id} --mode snapshot --notes-template \'{{guestname}}\' --node pve --notification-mode auto --storage local --prune-backups keep-last=1 --remove 1 --compress zstd'

    def __init__(self, base_path: Optional[str] = None, config: dict = None, ssh_config: dict = None):
        self.base_path = Path(base_path) if base_path else Path(__file__).parent.absolute()
        self.tmp_path = self.base_path / 'tmp' / '4'
        self.backup_path = self.base_path / 'backup'

        if config and ssh_config:
            self.client = BackupClient(config, ssh_config)
            self.lxc_ids = config.get('lxc_ids', ['100', '101', '102', '105', '106'])
        else:
            self.client = BackupClient(
                {'host': '192.168.50.4', 'port': 22, 'user': 'root'},
                {'key_file': 'id_ed25519', 'timeout': 10}
            )
            self.lxc_ids = ['100', '101', '102', '105', '106']

        self.backup_files: list[str] = []

    def prepare_dirs(self) -> None:
        self.tmp_path.mkdir(parents=True, exist_ok=True)
        self.backup_path.mkdir(parents=True, exist_ok=True)

    def backup_lxc(self, lxc_id: str) -> Optional[str]:
        print(f'  正在备份 LXC {lxc_id}...')

        cmd = self.BACKUP_COMMAND.format(id=lxc_id)
        exit_status, stdout, stderr = self.client.exec_command_with_pty(cmd, 'Y\n')

        if exit_status != 0:
            print(f'  备份 LXC {lxc_id} 失败: {stderr}')
            return None

        for line in stdout.splitlines():
            if 'creating vzdump archive' in line or 'INFO: creating vzdump archive' in line:
                match = re.search(r"(/var/lib/vz/dump/[^\s'\"]+)", line)
                if match:
                    backup_path = match.group(1)
                    file_name = Path(backup_path).name
                    print(f'    备份文件: {file_name}')
                    return backup_path

        print(f'  无法解析 LXC {lxc_id} 的备份文件路径')
        return None

    def download_backup_files(self) -> None:
        if not self.backup_files:
            print('  没有成功创建任何备份文件')
            return

        print('正在下载备份文件...')
        local_path = self.tmp_path / 'lxc'
        local_path.mkdir(parents=True, exist_ok=True)

        for remote_file in self.backup_files:
            file_name = Path(remote_file).name
            local_file = local_path / file_name
            try:
                self.client.download_file(remote_file, str(local_file))
                print(f'  已下载: {file_name}')
            except Exception as e:
                print(f'  下载失败 {file_name}: {e}')

    def cleanup_remote_backups(self) -> None:
        print('正在清理远程备份文件...')
        for remote_file in self.backup_files:
            try:
                self.client.exec_command_with_pty(f'rm -f "{remote_file}"')
                file_name = Path(remote_file).name
                print(f'  已清理: {file_name}')
            except Exception as e:
                print(f'  清理失败 {remote_file}: {e}')

    def get_lxc(self) -> None:
        print('正在备份LXC容器...')

        for lxc_id in self.lxc_ids:
            backup_path = self.backup_lxc(lxc_id)
            if backup_path:
                self.backup_files.append(backup_path)

        self.download_backup_files()
        self.cleanup_remote_backups()

    def compress_backup(self) -> Path:
        print('正在压缩备份文件...')

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        zip_filename = f'4_{timestamp}.zip'
        zip_filepath = self.backup_path / zip_filename

        with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(self.tmp_path):
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(self.tmp_path.parent)
                    zipf.write(file_path, arcname)

        file_size = zip_filepath.stat().st_size
        size_mb = file_size / (1024 * 1024)
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
            print('开始备份任务 - PVE (192.168.50.4)')
            print('=' * 50)

            self.prepare_dirs()
            self.client.connect()

            self.get_lxc()

            print('=' * 50)
            zip_file = self.compress_backup()

            print('=' * 50)
            print('备份任务完成！')
            print(f'备份文件位置: {zip_file}')
            print('=' * 50)

            self.cleanup_temp()

        except Exception as e:
            print(f'备份过程出错: {e}')
            import traceback
            traceback.print_exc()
            raise
        finally:
            self.client.close()


def main():
    backup = PveBackup()
    backup.run()


if __name__ == '__main__':
    main()
