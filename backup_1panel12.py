import os
import stat
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import paramiko


class BackupClient:
    """SSH/SFTP备份客户端基类"""

    def __init__(self, config: dict, ssh_config: dict):
        """
        初始化备份客户端

        Args:
            config: 目标服务器配置 {host, port, user, description}
            ssh_config: SSH通用配置 {key_file, timeout}
        """
        self.host = config['host']
        self.port = config.get('port', 22)
        self.user = config['user']
        self.timeout = ssh_config.get('timeout', 10)

        # 解析密钥文件路径
        key_file = ssh_config.get('key_file', 'id_ed25519')
        base_path = Path(__file__).parent.absolute()
        self.ssh_key_path = base_path / key_file

        self.ssh: Optional[paramiko.SSHClient] = None
        self.sftp: Optional[paramiko.SFTPClient] = None

    def connect(self) -> None:
        """连接SSH服务器"""
        print(f'正在连接服务器 {self.host}...')
        key = paramiko.Ed25519Key.from_private_key_file(self.ssh_key_path)
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(hostname=self.host, username=self.user, pkey=key, timeout=self.timeout)
        self.sftp = self.ssh.open_sftp()
        print('连接成功！')

    def close(self) -> None:
        """关闭连接"""
        print('正在关闭连接...')
        if self.sftp:
            self.sftp.close()
        if self.ssh:
            self.ssh.close()
        print('连接已关闭')

    def download_file(self, remote_path: str, local_path: str) -> None:
        """下载单个文件"""
        self.sftp.get(remotepath=remote_path, localpath=local_path)

    def download_folder(self, remote_path: str, local_path: str) -> None:
        """递归下载远程文件夹"""
        for item in self.sftp.listdir_attr(remote_path):
            remote_item_path = f"{remote_path}/{item.filename}"
            local_item_path = os.path.join(local_path, item.filename)

            if stat.S_ISDIR(item.st_mode):
                os.makedirs(local_item_path, exist_ok=True)
                self.download_folder(remote_item_path, local_item_path)
            else:
                self.sftp.get(remotepath=remote_item_path, localpath=local_item_path)

    def exec_command(self, cmd: str) -> tuple[str, str, str]:
        """执行SSH命令，返回(stdin, stdout, stderr)的字符串"""
        stdin, stdout, stderr = self.ssh.exec_command(cmd)
        return (
            stdin.read().decode() if stdin else '',
            stdout.read().decode(),
            stderr.read().decode()
        )


class Panel12Backup:
    """1Panel 12服务器备份任务"""

    def __init__(self, base_path: Optional[str] = None, config: dict = None, ssh_config: dict = None):
        """
        初始化备份任务

        Args:
            base_path: 备份基础路径
            config: 目标服务器配置（从config.py传入）
            ssh_config: SSH通用配置（从config.py传入）
        """
        self.base_path = Path(base_path) if base_path else Path(__file__).parent.absolute()
        self.tmp_path = self.base_path / 'tmp' / '12'
        self.backup_path = self.base_path / 'backup'

        # 使用传入的配置，如果没有则使用默认值（用于向后兼容）
        if config and ssh_config:
            self.client = BackupClient(config, ssh_config)
        else:
            # 向后兼容：如果未传入配置，使用默认值
            self.client = BackupClient(
                {'host': '192.168.50.12', 'port': 22, 'user': 'root'},
                {'key_file': 'id_ed25519', 'timeout': 10}
            )

    def prepare_dirs(self) -> None:
        """创建必要的目录"""
        self.tmp_path.mkdir(parents=True, exist_ok=True)
        self.backup_path.mkdir(parents=True, exist_ok=True)

    def get_grafana_files(self) -> None:
        """下载Grafana配置文件"""
        print('正在下载Grafana配置文件...')
        local_path = self.tmp_path / 'Grafana'
        local_path.mkdir(parents=True, exist_ok=True)

        # 先从容器复制配置文件
        cmd = 'docker ps -qf "name=grafana" | xargs -I {} docker cp {}:/etc/grafana/grafana.ini /opt/1panel/apps/grafana/grafana/data/'
        self.client.exec_command(cmd)

        file_list = [
            '/opt/1panel/apps/grafana/grafana/data/grafana.ini',
            '/opt/1panel/apps/grafana/grafana/data/grafana.db'
        ]

        for file in file_list:
            file_name = Path(file).name
            local_file = local_path / file_name
            self.client.download_file(file, str(local_file))
            print(f'  已下载: {file_name}')

    def get_prometheus_folder(self) -> None:
        """下载Prometheus配置文件夹"""
        print('正在下载Prometheus文件夹...')
        remote_path = '/opt/1panel/apps/prometheus/prometheus/conf'
        local_path = self.tmp_path / 'prometheus'
        local_path.mkdir(parents=True, exist_ok=True)

        self.client.download_folder(remote_path, str(local_path))
        print('  Prometheus文件夹下载完成')

    def get_sun_panel_folder(self) -> None:
        """下载sun-panel配置文件夹"""
        print('正在下载sun-panel文件夹...')
        remote_path = '/opt/1panel/apps/local/sun-panel/localsun-panel/data/conf/'
        local_path = self.tmp_path / 'sun-panel'
        local_path.mkdir(parents=True, exist_ok=True)

        self.client.download_folder(remote_path, str(local_path))
        print('  sun-panel文件夹下载完成')

    def get_sub_store_folder(self) -> None:
        """下载sub-store配置文件夹"""
        print('正在下载sub-store文件夹...')
        remote_path = '/opt/1panel/apps/local/sub-store/localsub-store/data'
        local_path = self.tmp_path / 'sub-store'
        local_path.mkdir(parents=True, exist_ok=True)

        self.client.download_folder(remote_path, str(local_path))
        print('  sub-store文件夹下载完成')

    def compress_backup(self) -> Path:
        """压缩备份文件"""
        print('正在压缩备份文件...')

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        zip_filename = f'12_{timestamp}.zip'
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
        """清理临时文件夹"""
        print('正在清理临时文件夹...')
        import shutil
        try:
            shutil.rmtree(self.tmp_path)
            print('  临时文件夹已清理')
        except Exception as e:
            print(f'  清理失败: {e}')

    def run(self) -> None:
        """执行完整备份流程"""
        try:
            print('=' * 50)
            print('开始备份任务 - 1Panel 12')
            print('=' * 50)

            self.prepare_dirs()
            self.client.connect()

            self.get_grafana_files()
            self.get_prometheus_folder()
            self.get_sun_panel_folder()
            self.get_sub_store_folder()

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
    """主函数 - 向后兼容独立运行"""
    backup = Panel12Backup()
    backup.run()


if __name__ == '__main__':
    main()
