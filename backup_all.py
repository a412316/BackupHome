#!/usr/bin/env python3
"""
统一备份CLI工具
支持运行所有备份任务或单独运行指定备份
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# 导入配置
try:
    from config import BACKUP_TARGETS, SSH, PATHS
except ImportError:
    print('错误: 未找到配置文件 config.py')
    print('请复制 config.example.py 为 config.py 并填入实际配置')
    sys.exit(1)


# 备份模块注册表
BACKUP_MODULES = {
    '12': {
        'name': '1Panel 12',
        'module': 'backup_1panel12',
        'class': 'Panel12Backup',
        'config_key': 'panel12',
    },
    'oracle': {
        'name': 'Oracle',
        'module': 'backup_oracle',
        'class': 'OracleBackup',
        'config_key': 'oracle',
    },
    '7': {
        'name': 'ADG',
        'module': 'backup_adg',
        'class': 'AdgBackup',
        'config_key': 'adg',
    },
    '91': {
        'name': 'Mini',
        'module': 'backup_mini',
        'class': 'MiniBackup',
        'config_key': 'mini',
    },
    '4': {
        'name': 'PVE',
        'module': 'backup_pve',
        'class': 'PveBackup',
        'config_key': 'pve',
    },
    '5': {
        'name': 'VPN',
        'module': 'backup_vpn',
        'class': 'VpnBackup',
        'config_key': 'vpn',
    },
    'switch': {
        'name': 'Switch',
        'module': 'get_switch_config',
        'class': 'SwitchConfigBackup',
        'config_key': 'switch',
    },
}


def _import_backup_class(module_id: str):
    """动态导入备份类"""
    module_info = BACKUP_MODULES[module_id]
    module = __import__(module_info['module'], fromlist=[module_info['class']])
    return getattr(module, module_info['class'])


class BackupRunner:
    """备份运行器"""

    def __init__(self, base_path: Optional[str] = None):
        self.base_path = Path(base_path) if base_path else Path(__file__).parent.absolute()
        self.results = {}

    def run_module(self, module_id: str) -> bool:
        """
        运行单个备份模块

        Args:
            module_id: 模块ID

        Returns:
            是否成功
        """
        if module_id not in BACKUP_MODULES:
            print(f'错误: 未知的备份模块 "{module_id}"')
            return False

        module_info = BACKUP_MODULES[module_id]
        config_key = module_info['config_key']

        if config_key not in BACKUP_TARGETS:
            print(f'错误: 配置文件中未找到 "{config_key}" 的配置')
            return False

        target_config = BACKUP_TARGETS[config_key]

        print(f'\n{"=" * 60}')
        print(f'开始执行: {module_info["name"]} - {target_config.get("description", "")}')
        print(f'目标: {target_config["user"]}@{target_config["host"]}:{target_config["port"]}')
        print(f'{"=" * 60}')

        try:
            # 动态导入备份类
            backup_class = _import_backup_class(module_id)

            # 准备初始化参数
            init_kwargs = {'config': target_config, 'ssh_config': SSH}

            # 交换机需要特殊处理（使用密码认证）
            if module_id == 'switch':
                init_kwargs['host'] = target_config['host']
                init_kwargs['port'] = target_config['port']
                init_kwargs['username'] = target_config['user']
                init_kwargs['password'] = target_config.get('password', '')

            # 创建备份实例
            backup_instance = backup_class(base_path=str(self.base_path), **init_kwargs)

            # 执行备份
            backup_instance.run()

            self.results[module_id] = {
                'success': True,
                'name': module_info['name'],
                'target': f"{target_config['user']}@{target_config['host']}"
            }
            return True

        except Exception as e:
            print(f'\n错误: {module_info["name"]} 备份失败: {e}')
            self.results[module_id] = {
                'success': False,
                'name': module_info['name'],
                'target': f"{target_config.get('user', '?')}@{target_config.get('host', '?')}",
                'error': str(e)
            }
            return False

    def run_all(self) -> dict:
        """
        运行所有备份模块

        Returns:
            结果字典 {module_id: {success, name, target, error?}}
        """
        print(f'\n{"=" * 60}')
        print(f'开始执行全部备份任务')
        print(f'启动时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        print(f'{"=" * 60}')

        success_count = 0
        failed_modules = []

        for module_id in BACKUP_MODULES:
            config_key = BACKUP_MODULES[module_id]['config_key']
            # 跳过未配置的模块
            if config_key not in BACKUP_TARGETS:
                print(f'\n跳过 {module_id} ({BACKUP_MODULES[module_id]["name"]}): 未配置')
                continue

            if self.run_module(module_id):
                success_count += 1
            else:
                failed_modules.append(module_id)

        # 打印汇总
        self._print_summary(success_count, failed_modules)

        return self.results

    def _print_summary(self, success_count: int, failed_modules: list) -> None:
        """打印备份汇总"""
        print(f'\n\n{"=" * 60}')
        print('备份任务汇总')
        print(f'{"=" * 60}')
        print(f'总计: {len(self.results)} 个模块')
        print(f'成功: {success_count} 个')
        print(f'失败: {len(failed_modules)} 个')

        if failed_modules:
            print(f'\n失败的模块:')
            for module_id in failed_modules:
                result = self.results[module_id]
                print(f'  - [{result["target"]}] {result["name"]}: {result.get("error", "未知错误")}')

        print(f'{"=" * 60}\n')


def list_modules() -> None:
    """列出所有可用的备份模块"""
    print('\n可用的备份模块:')
    print(f'{"ID":<10} {"名称":<15} {"描述"}')
    print('-' * 80)

    for module_id, module in BACKUP_MODULES.items():
        config_key = module['config_key']
        target_config = BACKUP_TARGETS.get(config_key, {})

        status = '✓' if config_key in BACKUP_TARGETS else '✗ (未配置)'
        description = target_config.get('description', module.get('description', ''))

        print(f'{module_id:<10} {module["name"]:<15} {description} {status}')


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='统一备份CLI工具 - 运行所有或指定的备份任务',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  %(prog)s --all              # 运行所有备份任务
  %(prog)s -m 12 7 91         # 运行指定的备份模块
  %(prog)s --list             # 列出所有可用的备份模块
  %(prog)s -m switch          # 仅备份交换机配置

配置文件:
  使用前请先配置 config.py 文件（可参考 config.example.py）
        '''
    )

    parser.add_argument(
        '-a', '--all',
        action='store_true',
        help='运行所有备份任务'
    )

    parser.add_argument(
        '-m', '--modules',
        nargs='+',
        metavar='MODULE',
        help='指定要运行的备份模块ID'
    )

    parser.add_argument(
        '-l', '--list',
        action='store_true',
        help='列出所有可用的备份模块'
    )

    parser.add_argument(
        '--base-path',
        type=str,
        default=None,
        help='备份基础路径 (默认: 脚本所在目录)'
    )

    args = parser.parse_args()

    # 列出模块
    if args.list:
        list_modules()
        return 0

    # 验证参数
    if not args.all and not args.modules:
        parser.print_help()
        print('\n错误: 请指定 --all 或 -m/--modules 参数')
        return 1

    # 创建运行器
    runner = BackupRunner(base_path=args.base_path)

    # 执行备份
    try:
        if args.all:
            runner.run_all()
        else:
            for module_id in args.modules:
                runner.run_module(module_id)

            # 打印汇总（指定模块模式）
            success_count = sum(1 for r in runner.results.values() if r['success'])
            failed_modules = [mid for mid, r in runner.results.items() if not r['success']]
            runner._print_summary(success_count, failed_modules)

        return 0

    except KeyboardInterrupt:
        print('\n\n备份任务被用户中断')
        return 130
    except Exception as e:
        print(f'\n错误: 备份过程中发生异常: {e}')
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
