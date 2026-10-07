#!/usr/bin/env python3
"""
统一备份CLI工具
支持运行所有备份任务或单独运行指定备份。

模块注册表与每个模块的备份内容均来自 config.py（BACKUP_MODULES），
本脚本只负责参数解析、调度与结果汇总。
"""

import argparse
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Optional

try:
    from config import BACKUP_MODULES, SSH, PATHS
except ImportError:
    print('错误: 未找到配置文件 config.py')
    print('请复制 config.example.py 为 config.py 并填入实际配置')
    sys.exit(1)


class ThreadStdoutRouter:
    """并发时按线程路由输出：工作线程写入各自缓冲，其余写回原终端。

    contextlib.redirect_stdout 是进程级全局替换，多线程会互相覆盖，
    因此这里用 threading.local 区分各工作线程的输出去向。
    """

    def __init__(self, original):
        self.original = original
        self._local = threading.local()

    def capture(self) -> StringIO:
        buffer = StringIO()
        self._local.buffer = buffer
        return buffer

    def release(self) -> str:
        buffer = getattr(self._local, 'buffer', None)
        self._local.buffer = None
        return buffer.getvalue() if buffer else ''

    def write(self, text):
        buffer = getattr(self._local, 'buffer', None)
        if buffer is not None:
            buffer.write(text)
        else:
            self.original.write(text)

    def flush(self):
        buffer = getattr(self._local, 'buffer', None)
        if buffer is None:
            self.original.flush()

    def isatty(self):
        return False


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
            from backup_engine import BackupTask  # 延迟导入：--list/--help 无需 paramiko
            task = BackupTask(
                module_id=module_id,
                module_config=module_config,
                ssh_config=SSH,
                paths_config=PATHS,
                base_path=str(self.base_path),
            )
            task.run()

            if task.failed_items:
                # 存在失败项的模块记为失败，即使 zip 已生成（内容不完整）
                error = f"{len(task.failed_items)} 项操作失败: " + '; '.join(task.failed_items)
                self.results[module_id] = {
                    'success': False,
                    'name': module_config['name'],
                    'target': f"{target['user']}@{target['host']}",
                    'error': error,
                }
                return False

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

    def _run_module_routed(self, module_id: str, router: ThreadStdoutRouter) -> str:
        """在当前线程内捕获该模块的全部输出，结束后整段返回。"""
        router.capture()
        try:
            self.run_module(module_id)
        finally:
            output = router.release()
        return output

    def run_selected(self, module_ids: list, jobs: int = 1) -> None:
        """执行给定模块；jobs > 1 时并发（输出按模块整段打印）。"""
        if jobs <= 1:
            for module_id in module_ids:
                self.run_module(module_id)
            return

        router = ThreadStdoutRouter(sys.stdout)
        sys.stdout = router
        try:
            def worker(module_id):
                return self._run_module_routed(module_id, router)

            with ThreadPoolExecutor(max_workers=jobs) as pool:
                futures = [pool.submit(worker, mid) for mid in module_ids]
                for module_id, future in zip(module_ids, futures):
                    output = future.result()
                    print(f'\n{"=" * 60}\n[模块 {module_id} 执行完毕]\n{output}')
        finally:
            sys.stdout = router.original
            sys.stdout.flush()

    def run_all(self, jobs: int = 1) -> dict:
        print(f'\n{"=" * 60}')
        print('开始执行全部备份任务')
        print(f'启动时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        print(f'{"=" * 60}')

        self.run_selected(list(BACKUP_MODULES), jobs=jobs)

        failed_modules = [mid for mid, r in self.results.items() if not r['success']]
        success_count = len(self.results) - len(failed_modules)

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


def _op_summary(op: dict) -> str:
    """dry-run 时单个操作的一行摘要。"""
    op_type = op.get('type')
    if op_type == 'download_files':
        return ', '.join(op.get('files', []))
    if op_type == 'download_folder':
        return op.get('remote_path', '')
    if op_type == 'download_pattern':
        return f"{op.get('remote_dirs') or op.get('remote_dir')} 匹配 {op.get('pattern')}"
    if op_type in ('run_command', 'command_output_to_file', 'command_then_download'):
        return op.get('command', '')[:100]
    if op_type == 'sqlite_backup':
        return op.get('db', '')
    if op_type == 'vzdump_backup':
        return f"LXC {op.get('lxc_ids')}"
    if op_type == 'interactive_shell':
        return op.get('capture_command', '')
    return str({k: v for k, v in op.items() if k != 'type'})[:100]


def dry_run(module_ids: list) -> None:
    """列出将执行的操作，不建立任何连接。"""
    print('\ndry-run: 仅列出将执行的操作，不实际连接\n')
    unknown = False
    for module_id in module_ids:
        module = BACKUP_MODULES.get(module_id)
        if module is None:
            print(f'[!] 未知模块: {module_id}')
            unknown = True
            continue
        target = module['target']
        print(f'[{module_id}] {module["name"]} -> '
              f'{target["user"]}@{target["host"]}:{target.get("port", 22)}')
        for op in module.get('operations', []):
            print(f'  - {op.get("type")}: {_op_summary(op)}')
        print()
    if unknown:
        print('注意: 存在未知模块\n')
    print('dry-run 结束')


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
    parser.add_argument('-j', '--jobs', type=int, default=1, metavar='N',
                        help='并发执行的模块数（默认 1 串行；并发时输出按模块整段打印）')
    parser.add_argument('--dry-run', action='store_true', help='仅列出将执行的操作，不实际连接')
    parser.add_argument('--base-path', type=str, default=None, help='备份基础路径 (默认: 脚本所在目录)')

    args = parser.parse_args()

    if args.list:
        list_modules()
        return 0

    if args.dry_run:
        dry_run(args.modules if args.modules else list(BACKUP_MODULES))
        return 0

    if not args.all and not args.modules:
        parser.print_help()
        print('\n错误: 请指定 --all 或 -m/--modules 参数')
        return 1

    runner = BackupRunner(base_path=args.base_path)

    try:
        jobs = max(1, args.jobs)
        if args.all:
            runner.run_all(jobs=jobs)
        else:
            runner.run_selected(args.modules, jobs=jobs)
            success_count = sum(1 for r in runner.results.values() if r['success'])
            failed_modules = [mid for mid, r in runner.results.items() if not r['success']]
            runner._print_summary(success_count, failed_modules)
        # 任一模块失败则以非零退出，便于 cron 等自动化感知
        return 0 if all(r['success'] for r in runner.results.values()) else 1

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
