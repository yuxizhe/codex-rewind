#!/usr/bin/env python3
"""Install codex rewind alongside the standalone Codex distribution."""
import os
from pathlib import Path
import shutil


def main():
    home = Path.home()
    command = home / '.local/bin/codex'
    real = home / '.codex/packages/standalone/current/bin/codex'
    destination = home / '.local/lib/codex-rewind'
    marker = '# codex-rewind dispatcher v1'
    if not real.is_file():
        raise SystemExit(f'Expected standalone Codex at {real}; installation unchanged')
    if command.is_symlink():
        if command.resolve() != real.resolve():
            raise SystemExit('Unknown codex symlink; installation unchanged')
    elif command.exists() and marker not in command.read_text():
        raise SystemExit('Unknown codex executable; installation unchanged')
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__).with_name('codex-rewind.py'), destination / 'codex-rewind.py')
    # Store the original launcher target for uninstall; no version-specific path.
    (destination / 'original-target.txt').write_text(str(real) + '\n')
    wrapper = '''#!/bin/sh
# codex-rewind dispatcher v1
real="$HOME/.codex/packages/standalone/current/bin/codex"
if [ "${1-}" = rewind ]; then
    shift
    exec python3 "$HOME/.local/lib/codex-rewind/codex-rewind.py" --codex "$real" "$@"
fi
exec "$real" "$@"
'''
    temporary = command.with_name('codex-rewind-install.tmp')
    with temporary.open('x') as output:
        output.write(wrapper)
    temporary.chmod(0o755)
    os.replace(temporary, command)
    print(f'Installed: {command} rewind (source copied to {destination})')


if __name__ == '__main__':
    main()
