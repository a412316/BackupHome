#!/usr/bin/env python3
"""
统一备份CLI工具
支持运行所有备份任务或单独运行指定备份。

模块注册表与每个模块的备份内容均来自 config.py（BACKUP_MODULES），
本脚本只负责参数解析、调度与结果汇总。
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from config import BACKUP_MODULES, SSH, PATHS
except ImportError:
    print('错误: 未找到配置文件 config.py')
    print('请复制 config.example.py 为 config.py 并填入实际配置')
    sys.exit(1)

from backup_engine import BackupTask


class BackupRunner:
    """备份运行器：按 config 声明依次执行各模块。"""

    def __init__(self, base_path: Optional[str] = None):
        self.base_path = Path(base_path) if base_path else Path(__file__).parent.absolute()
        self.results = {}

    def run_module(self, module_id: str) -> bool:
        if module_id not in BACKUP_MODULES:
            print(f'错误: 未知的备份模块 "{module_id}"')
            return False

        module_config = BACKUP_MODULES[module_id]
        target = module_config['target']

        print(f'\n{"=" * 60}')
        print(f'开始执行: {module_config["name"]} - {target.get("description", "")}')
        print(f'目标: {target["user"]}@{target["host"]}:{target.get("port", 22)}')
        print(f'{"=" * 60}')

        try:
            task = BackupTask(
                module_id=module_id,
                module_config=module_config,
                ssh_config=SSH,
                paths_config=PATHS,
                base_path=str(self.base_path),
            )
            task.run()

            self.results[module_id] = {
                'success': True,
                'name': module_config['name'],
                'target': f"{target['user']}@{target['host']}",
            }
            return True

        except Exception as e:
            print(f'\n错误: {module_config["name"]} 备份失败: {e}')
            self.results[module_id] = {
                'success': False,
                'name': module_config['name'],
                'target': f"{target.get('user', '?')}@{target.get('host', '?')}",
                'error': str(e),
            }
            return False

    def run_all(self) -> dict:
        print(f'\n{"=" * 60}')
        print('开始执行全部备份任务')
        print(f'启动时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        print(f'{"=" * 60}')

        success_count = 0
        failed_modules = []

        for module_id in BACKUP_MODULES:
            if self.run_module(module_id):
                success_count += 1
            else:
                failed_modules.append(module_id)

        self._print_summary(success_count, failed_modules)
        return self.results

    def _print_summary(self, success_count: int, failed_modules: list) -> None:
        print(f'\n\n{"=" * 60}')
        print('备份任务汇总')
        print(f'{"=" * 60}')
        print(f'总计: {len(self.results)} 个模块')
        print(f'成功: {success_count} 个')
        print(f'失败: {len(failed_modules)} 个')

        if failed_modules:
            print('\n失败的模块:')
            for module_id in failed_modules:
                result = self.results[module_id]
                print(f'  - [{result["target"]}] {result["name"]}: {result.get("error", "未知错误")}')

        print(f'{"=" * 60}\n')


def list_modules() -> None:
    print('\n可用的备份模块:')
    print(f'{"ID":<10} {"名称":<15} {"描述"}')
    print('-' * 80)

    for module_id, module in BACKUP_MODULES.items():
        target = module.get('target', {})
        description = target.get('description', '')
        print(f'{module_id:<10} {module["name"]:<15} {description} ✓')


def main():
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

    parser.add_argument('-a', '--all', action='store_true', help='运行所有备份任务')
    parser.add_argument('-m', '--modules', nargs='+', metavar='MODULE', help='指定要运行的备份模块ID')
    parser.add_argument('-l', '--list', action='store_true', help='列出所有可用的备份模块')
    parser.add_argument('--base-path', type=str, default=None, help='备份基础路径 (默认: 脚本所在目录)')

    args = parser.parse_args()

    if args.list:
        list_modules()
        return 0

    if not args.all and not args.modules:
        parser.print_help()
        print('\n错误: 请指定 --all 或 -m/--modules 参数')
        return 1

    runner = BackupRunner(base_path=args.base_path)

    try:
        if args.all:
            runner.run_all()
        else:
            for module_id in args.modules:
                runner.run_module(module_id)
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
