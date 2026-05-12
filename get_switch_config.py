import os
import re
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import paramiko


class SwitchConfigBackup:
    """交换机配置备份类"""

    def __init__(
        self,
        base_path: Optional[str] = None,
        config: dict = None,
        ssh_config: dict = None,
        host: str = None,
        port: int = None,
        username: str = None,
        password: str = None
    ):
        """
        初始化交换机配置备份

        Args:
            base_path: 备份基础路径
            config: 目标服务器配置（从config.py传入）
            ssh_config: SSH通用配置（从config.py传入）
            host: 主机地址（直接指定时优先）
            port: 端口（直接指定时优先）
            username: 用户名（直接指定时优先）
            password: 密码（直接指定时优先）
        """
        self.base_path = Path(base_path) if base_path else Path(__file__).parent.absolute()
        self.tmp_path = self.base_path / 'tmp' / 'switch'
        self.backup_path = self.base_path / 'backup'

        # 优先使用直接传入的参数（用于独立运行或向后兼容）
        if host:
            self.host = host
            self.port = port or 22
            self.username = username or 'admin'
            self.password = password or ''
            self.timeout = 10
        elif config:
            self.host = config['host']
            self.port = config.get('port', 22)
            self.username = config['user']
            self.password = config.get('password', '')
            self.timeout = ssh_config.get('timeout', 10) if ssh_config else 10
        else:
            # 向后兼容的默认值
            self.host = '192.168.50.3'
            self.port = 22
            self.username = 'admin'
            self.password = '***REMOVED***'
            self.timeout = 10

        self.ssh: Optional[paramiko.SSHClient] = None

    def prepare_dirs(self) -> None:
        self.tmp_path.mkdir(parents=True, exist_ok=True)
        self.backup_path.mkdir(parents=True, exist_ok=True)

    def _wait_for_output(self, shell: paramiko.Channel, wait_time: float = 0.5) -> str:
        time.sleep(wait_time)
        output = ''
        while shell.recv_ready():
            output += shell.recv(4096).decode('utf-8', errors='ignore')
        return output

    def _clean_config_output(self, output: str) -> list[str]:
        config_lines = []
        skip_until_marker = True
        found_end = False
        prompt_pattern = re.compile(r'^[\w-]+[>#]$')

        for line in output.splitlines():
            if 'show running-config' in line:
                skip_until_marker = False
                continue
            if skip_until_marker:
                continue

            stripped = line.strip()
            if stripped == 'end':
                found_end = True
                config_lines.append(line)
                continue

            if found_end:
                continue

            if not stripped:
                continue

            if prompt_pattern.match(stripped):
                continue

            if stripped.endswith(('#', '>')):
                line = re.sub(r'[>#].*$', '', line).rstrip()
                if not line:
                    continue

            config_lines.append(line)

        return config_lines

    def get_config(self) -> Optional[Path]:
        print(f'正在连接交换机 {self.host}...')

        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            self.ssh.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=self.timeout,
                look_for_keys=False,
                allow_agent=False
            )
            print('连接成功！')

            shell = self.ssh.invoke_shell()
            self._wait_for_output(shell, wait_time=1)

            print('正在登录...')
            shell.send(f'{self.username}\n')
            self._wait_for_output(shell)

            shell.send(f'{self.password}\n')
            self._wait_for_output(shell)

            print('正在进入特权模式...')
            shell.send('en\n')
            self._wait_for_output(shell)

            shell.send('terminal length 0\n')
            self._wait_for_output(shell)

            print('正在获取配置...')
            shell.send('show running-config\n')
            time.sleep(3)

            output = ''
            while shell.recv_ready():
                output += shell.recv(4096).decode('utf-8', errors='ignore')

            if 'show running-config' not in output or len(output) < 100:
                shell.send(' \n')
                time.sleep(2)
                while shell.recv_ready():
                    output += shell.recv(4096).decode('utf-8', errors='ignore')

            print(f'配置获取完成，共 {len(output)} 字节')

            config_lines = self._clean_config_output(output)

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            config_file = self.tmp_path / f'switch_config_{timestamp}.txt'

            with open(config_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(config_lines))

            print(f'配置已保存至: {config_file}')
            return config_file

        except Exception as e:
            print(f'获取配置失败: {e}')
            import traceback
            traceback.print_exc()
            return None

    def compress_backup(self, config_file: Path) -> Optional[Path]:
        if not config_file or not config_file.exists():
            print('没有配置文件需要压缩')
            return None

        print('正在压缩配置文件...')

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        zip_filename = f'switch_config_{timestamp}.zip'
        zip_filepath = self.backup_path / zip_filename

        with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
            arcname = config_file.relative_to(self.tmp_path.parent)
            zipf.write(config_file, arcname)

        file_size = zip_filepath.stat().st_size
        print(f'  压缩完成: {zip_filename} ({file_size} 字节)')
        return zip_filepath

    def cleanup_temp(self) -> None:
        print('正在清理临时文件夹...')
        try:
            shutil.rmtree(self.tmp_path)
            print('  临时文件夹已清理')
        except Exception as e:
            print(f'  清理失败: {e}')

    def close(self) -> None:
        print('正在关闭连接...')
        if self.ssh:
            self.ssh.close()
        print('连接已关闭')

    def run(self) -> None:
        try:
            print('=' * 50)
            print('开始备份交换机配置')
            print(f'交换机: {self.host}')
            print('=' * 50)

            self.prepare_dirs()

            config_file = self.get_config()

            if config_file:
                print('=' * 50)
                zip_file = self.compress_backup(config_file)

                print('=' * 50)
                print('备份任务完成！')
                if zip_file:
                    print(f'备份文件位置: {zip_file}')
                print('=' * 50)

            self.cleanup_temp()

        except Exception as e:
            print(f'备份过程出错: {e}')
            import traceback
            traceback.print_exc()
        finally:
            self.close()


def main():
    """主函数"""
    backup = SwitchConfigBackup()
    backup.run()


if __name__ == '__main__':
    main()
