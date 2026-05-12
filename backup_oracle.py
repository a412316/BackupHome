import os
import re
import stat
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

    def download_folder(self, remote_path: str, local_path: str) -> None:
        for item in self.sftp.listdir_attr(remote_path):
            remote_item_path = f"{remote_path}/{item.filename}"
            local_item_path = os.path.join(local_path, item.filename)

            if stat.S_ISDIR(item.st_mode):
                os.makedirs(local_item_path, exist_ok=True)
                self.download_folder(remote_item_path, local_item_path)
            else:
                self.sftp.get(remotepath=remote_item_path, localpath=local_item_path)

    def exec_command(self, cmd: str) -> tuple[str, str, str]:
        stdin, stdout, stderr = self.ssh.exec_command(cmd)
        return (
            stdin.read().decode() if stdin else '',
            stdout.read().decode(),
            stderr.read().decode()
        )


class OracleBackup:
    """Oracle服务器备份任务"""

    def __init__(self, base_path: Optional[str] = None, config: dict = None, ssh_config: dict = None):
        self.base_path = Path(base_path) if base_path else Path(__file__).parent.absolute()
        self.tmp_path = self.base_path / 'tmp' / 'oracle'
        self.backup_path = self.base_path / 'backup'

        if config and ssh_config:
            self.client = BackupClient(config, ssh_config)
        else:
            self.client = BackupClient(
                {'host': '192.168.50.x', 'port': 22, 'user': 'root'},
                {'key_file': 'id_ed25519', 'timeout': 10}
            )

    def prepare_dirs(self) -> None:
        self.tmp_path.mkdir(parents=True, exist_ok=True)
        self.backup_path.mkdir(parents=True, exist_ok=True)

    def get_bitwarden_files(self) -> None:
        print('正在下载Bitwarden配置文件...')
        local_path = self.tmp_path / 'bitwarden'
        local_path.mkdir(parents=True, exist_ok=True)

        file_list = [
            '/opt/1panel/apps/bitwarden/bitwarden/data/db.sqlite3',
            '/opt/1panel/apps/bitwarden/bitwarden/data/rsa_key.pem'
        ]

        for file in file_list:
            file_name = Path(file).name
            local_file = local_path / file_name
            self.client.download_file(file, str(local_file))
            print(f'  已下载: {file_name}')

    def get_adg_folder(self) -> None:
        print('正在下载AdGuardHome文件夹...')
        remote_path = '/opt/1panel/apps/adguardhome/adguardhome/data/conf/'
        local_path = self.tmp_path / 'AdGuardHome'
        local_path.mkdir(parents=True, exist_ok=True)

        self.client.download_folder(remote_path, str(local_path))
        print('  AdGuardHome文件夹下载完成')

    def get_gitea_files(self) -> None:
        print('正在下载Gitea配置文件...')
        local_path = self.tmp_path / 'gitea'
        local_path.mkdir(parents=True, exist_ok=True)

        cmd = 'docker exec -u git -w /tmp $(docker ps -qf "name=gitea") bash -c "/usr/local/bin/gitea dump -c /data/gitea/conf/app.ini"'
        _, stdout, stderr = self.client.exec_command(cmd)

        dump_file_path = None
        for line in stdout.splitlines():
            if 'Finish dumping in file' in line:
                match = re.search(r'/tmp/gitea-dump-\d+\.zip', line)
                if match:
                    dump_file_path = match.group(0)
                    break

        if not dump_file_path:
            print('  未找到Gitea dump文件')
            return

        copy_cmd = f'docker cp $(docker ps -qf "name=gitea"):{dump_file_path} {dump_file_path}'
        self.client.exec_command(copy_cmd)

        file_name = Path(dump_file_path).name
        local_file = local_path / file_name
        self.client.download_file(dump_file_path, str(local_file))
        print(f'  已下载: {file_name}')

    def compress_backup(self) -> Path:
        print('正在压缩备份文件...')

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        zip_filename = f'oracle_{timestamp}.zip'
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
        import shutil
        try:
            shutil.rmtree(self.tmp_path)
            print('  临时文件夹已清理')
        except Exception as e:
            print(f'  清理失败: {e}')

    def run(self) -> None:
        try:
            print('=' * 50)
            print('开始备份任务 - Oracle')
            print('=' * 50)

            self.prepare_dirs()
            self.client.connect()

            self.get_bitwarden_files()
            self.get_adg_folder()
            self.get_gitea_files()

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


def main():
    backup = OracleBackup()
    backup.run()


if __name__ == '__main__':
    main()
