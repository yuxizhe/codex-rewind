#!/usr/bin/env python3
"""Rewind a stopped Codex paginated thread, preserving a server-side fork."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import sys
import time
import shutil
import unicodedata
from datetime import datetime


def compatible(schema):
    return set(schema.get('required', [])) == {'threadId', 'beforeTurnId'}


class Server:
    def __init__(self, binary):
        self.process = subprocess.Popen([binary, 'app-server'], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, text=True)
        self.messages = queue.Queue()
        self.sequence = 0
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        try:
            for line in self.process.stdout:
                self.messages.put(json.loads(line))
        finally:
            self.messages.put(None)

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + '\n')
        self.process.stdin.flush()

    def call(self, method, params):
        self.sequence += 1
        request_id = self.sequence
        self.send(dict(id=request_id, method=method, params=params))
        while True:
            try:
                message = self.messages.get(timeout=60)
            except queue.Empty:
                raise RuntimeError(f'{method} timed out; outcome may be unknown. Do not retry blindly.')
            if message is None:
                raise RuntimeError('App Server exited')
            if message.get('id') == request_id and 'method' not in message:
                if 'error' in message:
                    raise RuntimeError(json.dumps(message['error']))
                return message['result']
            if 'id' in message and 'method' in message:
                self.send(dict(id=message['id'], error=dict(code=-32601, message='Unsupported request')))

    def close(self):
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


class SharedServer(Server):
    """Same RPC interface over the existing daemon's Unix WebSocket."""
    def __init__(self, path):
        from websockets.sync.client import unix_connect
        self.connection = unix_connect(str(path), uri='ws://localhost/', open_timeout=5, max_size=32 * 1024 * 1024)
        self.sequence = 0
        self.messages = queue.Queue()
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        from websockets.exceptions import ConnectionClosed
        try:
            for message in self.connection:
                self.messages.put(json.loads(message))
        except ConnectionClosed:
            pass
        finally:
            self.messages.put(None)

    def send(self, message):
        self.connection.send(json.dumps(message))

    def close(self):
        self.connection.close()


def connect(binary):
    path = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'app-server-control/app-server-control.sock'
    if path.exists():
        return SharedServer(path)
    return Server(binary)


def stop_target_turn(server, thread_id):
    thread = server.call('thread/read', dict(threadId=thread_id))['thread']
    if thread.get('status', {}).get('type') != 'active':
        return
    turns = server.call('thread/turns/list', dict(threadId=thread_id, limit=20, sortDirection='desc'))['data']
    active = [turn for turn in turns if turn.get('status') == 'inProgress']
    if len(active) != 1:
        raise RuntimeError('无法确定当前运行轮次，请在原客户端停止后重试。')
    server.call('turn/interrupt', dict(threadId=thread_id, turnId=active[0]['id']))
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        thread = server.call('thread/read', dict(threadId=thread_id))['thread']
        if thread.get('status', {}).get('type') != 'active':
            return
        time.sleep(0.2)
    raise RuntimeError('目标轮次尚未停止，未执行回退。')


def clean(value, limit=160):
    return ' '.join(''.join(c for c in str(value) if c.isprintable() or c.isspace()).split())[:limit]


def turn_label(turn):
    messages = []
    for item in turn.get('items', []):
        if item.get('type') == 'userMessage':
            messages.extend(part.get('text', '[' + part.get('type', 'attachment') + ']')
                            for part in item.get('content', []))
    return clean(' '.join(messages) or '(无用户文字消息)') + '  [' + clean(turn['id']) + ']'


def style(text, code='2'):
    if sys.stdout.isatty() and 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb':
        return f'\033[{code}m{text}\033[0m'
    return str(text)


def fit(text, width):
    text = clean(text, 10000)
    used = 0
    result = ''
    for char in text:
        size = 0 if unicodedata.combining(char) else (2 if unicodedata.east_asian_width(char) in 'WF' else 1)
        if used + size > max(0, width - 1):
            return result + '…'
        result += char
        used += size
    return result


def heading(step, title):
    width = min(shutil.get_terminal_size((88, 24)).columns, 96)
    print('\n  ' + style('↶  CODEX REWIND', '1;36') + style('   /   ' + step))
    print('  ' + style('─' * max(8, width - 4)))
    print('  ' + style(title, '1') + '\n')


def thread_label(thread):
    return clean(thread.get('name') or thread.get('preview') or '(未命名)')


def choose(server, method, params, title, label):
    cursors = [None]
    page_index = 0
    is_thread = method == 'thread/list'
    while True:
        page = server.call(method, dict(params, cursor=cursors[page_index], limit=8))
        rows = page['data']
        width = max(20, min(shutil.get_terminal_size((88, 24)).columns, 96) - 8)
        heading('01 / 03' if is_thread else '02 / 03', title)
        print('  ' + style('最近更新优先' if is_thread else '选中即执行 · 自动备份 · 删除所选整轮及后续历史') + '\n')
        if not is_thread:
            print('  运行中的目标轮次会自动停止。代码和文件不会回退。\n')
        for index, row in enumerate(rows, 1):
            text = label(row)
            if not is_thread:
                text = text.rsplit('  [', 1)[0]
            print('  ' + style(f'{index:>2}', '1;36') + '  ' + fit(text, width))
            if is_thread:
                stamp = row.get('updatedAt')
                date = datetime.fromtimestamp(stamp).strftime('%m-%d %H:%M') if isinstance(stamp, (int, float)) else ''
                path = str(row.get('cwd', '')).replace(str(Path.home()), '~', 1)
                detail = f'{date}  {path}  ·  {row["id"][:8]}'
            else:
                detail = '整轮回退  ·  ' + row['id'][:8]
            print('      ' + style(fit(detail, width)) + '\n')
        following = page.get('nextCursor')
        if not rows:
            print('  暂无可选条目。\n')
        controls = ['序号 选择']
        if page_index:
            controls.append('p 上一页')
        if following:
            controls.append('n 下一页')
        controls.append('q 退出')
        print('  ' + style(f'第 {page_index + 1} 页  ·  ' + '   /   '.join(controls)))
        while True:
            answer = input('\n  ' + style('› ', '1;36')).strip().lower()
            if answer == 'q':
                raise SystemExit(0)
            if answer == 'p' and page_index:
                page_index -= 1
                break
            if answer == 'n' and following:
                cursors[page_index + 1:] = [following]
                page_index += 1
                break
            if answer.isdecimal() and 1 <= int(answer) <= len(rows):
                return rows[int(answer) - 1]
            print('  ' + style('请输入有效序号或下方导航键。', '33'))


def load_for_revert(server, thread_id):
    # read/list query stored history; revert requires this server to own a loaded thread.
    try:
        loaded = server.call('thread/resume', dict(threadId=thread_id, excludeTurns=True))['thread']
    except RuntimeError as error:
        if 'already has an active writer' in str(error):
            raise RuntimeError('该会话仍被其他 Codex 客户端占用。请退出对应 CLI，或在桌面端关闭该会话后重试。尚未创建新备份，也未执行回退；不会强制终止其他进程。') from None
        raise
    if loaded['id'] != thread_id or loaded.get('status', {}).get('type') == 'active':
        raise RuntimeError('目标会话异常或正在执行，未创建备份，未执行回退。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('thread_id', nargs='?')
    parser.add_argument('before_turn_id', nargs='?')
    parser.add_argument('--codex', default='codex')
    parser.add_argument('--apply', action='store_true', help='Apply rewind; default only checks compatibility')
    parser.add_argument('--stopped', action='store_true', help='Confirm all clients using this thread are closed')
    parser.add_argument('--continue', dest='resume', action='store_true')
    parser.add_argument('--no-continue', action='store_true', help='Do not open CLI after interactive rewind')
    args = parser.parse_args()
    interactive = args.before_turn_id is None
    if interactive and not sys.stdin.isatty():
        parser.error('Interactive selection requires a terminal')
    if not interactive and args.apply and not args.stopped:
        parser.error('--apply requires --stopped: close the original CLI first')
    if not interactive and args.resume and not args.apply:
        parser.error('--continue requires --apply')
    with tempfile.TemporaryDirectory(prefix='codex-rewind-schema-') as directory:
        subprocess.run([args.codex, 'app-server', 'generate-json-schema', '--experimental', '--out', directory], check=True)
        schema = Path(directory, 'v2', 'ThreadRevertParams.json')
        if not schema.exists() or not compatible(json.loads(schema.read_text())):
            raise RuntimeError('Incompatible Codex: expected thread/revert(threadId, beforeTurnId)')
    server = connect(args.codex)
    try:
        server.call('initialize', dict(clientInfo=dict(name='codex_rewind', version='1.0.0'), capabilities=dict(experimentalApi=True)))
        server.send(dict(method='initialized'))
        if args.thread_id is None:
            selected = choose(server, 'thread/list', dict(sortKey='updated_at', sortDirection='desc'),
                              '选择会话', thread_label)
            args.thread_id = selected['id']
        thread = server.call('thread/read', dict(threadId=args.thread_id))['thread']
        if thread.get('historyMode') != 'paginated':
            raise RuntimeError('Only paginated threads support thread/revert; legacy history is unchanged')
        if interactive:
            selected = choose(server, 'thread/turns/list',
                              dict(threadId=args.thread_id, sortDirection='desc', itemsView='summary'),
                              '选择回退位置', turn_label)
            args.before_turn_id = selected['id']
            heading('03 / 03', '正在回退')
            print('  会话  ' + style(thread_label(thread), '1'))
            print('  消息  ' + turn_label(selected))
            print('\n  ' + style('所选整轮及后续历史将被移除。', '33'))
            print('  自动创建会话备份 · 代码和文件保持原样\n')
            args.apply = True
            args.resume = not args.no_continue
        if not args.apply:
            print('Protocol and history compatible. Close all clients, then use --apply --stopped [--continue].')
            return
        stop_target_turn(server, args.thread_id)
        load_for_revert(server, args.thread_id)
        backup = server.call('thread/fork', dict(threadId=args.thread_id))['thread']['id']
        # Persist the recovery handle before issuing the destructive request.
        root = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'rewind-backups'
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, manifest = tempfile.mkstemp(prefix='rewind-', suffix='.json', dir=root)
        with os.fdopen(fd, 'w') as output:
            json.dump(dict(threadId=args.thread_id, beforeTurnId=args.before_turn_id, backupThreadId=backup), output)
            output.flush()
            os.fsync(output.fileno())
        print(f'Backup: {backup}\nRecovery: codex resume {backup}\nManifest: {manifest}', flush=True)
        result = server.call('thread/revert', dict(threadId=args.thread_id, beforeTurnId=args.before_turn_id))
        if result['thread']['id'] != args.thread_id:
            raise RuntimeError('Unexpected reverted thread ID')
        print(f'Rewound: {args.thread_id}', flush=True)
    finally:
        server.close()
    if args.resume and isinstance(server, SharedServer):
        print('  已回退，请在原客户端继续会话。')
    elif args.resume:
        raise SystemExit(subprocess.call([args.codex, 'resume', args.thread_id], cwd=thread['cwd']))


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print('\n已取消。', file=sys.stderr)
        raise SystemExit(130)
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print('\n  回退未完成：' + str(error), file=sys.stderr)
        print('  若已显示备份 ID，可使用 codex resume <备份ID> 打开备份。', file=sys.stderr)
        raise SystemExit(1)
