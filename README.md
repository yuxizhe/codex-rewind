# Codex Rewind

English | [简体中文](README.zh-CN.md)

Add `codex rewind` to Codex CLI. Pick a conversation and a user message in your terminal, create a backup, and rewind the original conversation in place.

Built on Codex App Server's `thread/revert` API, without manually editing conversation storage. An independent project, not an official OpenAI tool.

## How it works

1. **Choose a conversation.** Browse titles, update times, and working directories.
2. **Choose a message.** Preview user messages and select a turn boundary.
3. **Rewind immediately.** Selecting a message starts the operation without another confirmation prompt. Any running target turn in the connected server is interrupted first.
4. **Keep a backup.** The tool forks the full conversation before reverting the original thread.

**Rewind removes the selected message's entire turn and every later turn. The original thread ID stays the same. Code and local files are not reverted.**

The terminal interface currently uses Chinese labels, with numbered choices, compact previews, and pagination.

## Requirements

- Python 3.9+. The installer creates an isolated virtual environment and installs `websockets==15.0.1`.
- An installed and configured Codex CLI.
- Support for the experimental `thread/revert` API and a conversation with `paginated` history. Legacy conversations are rejected.
- Locally verified with Codex CLI 0.166.0. Experimental APIs may change; the tool checks the locally generated parameter schema before proceeding.
- The global installer targets the macOS/Linux standalone layout at `~/.codex/packages/standalone/current/bin/codex`.

## Installation

```bash
git clone https://github.com/yuxizhe/codex-rewind.git
cd codex-rewind
python3 install-codex-rewind.py
codex rewind
```

Ensure `~/.local/bin` is on your `PATH`. The installer copies the tool into `~/.local/lib/codex-rewind` and installs a dispatcher at `~/.local/bin/codex`. Other Codex commands are passed through to the original CLI. Unrecognized existing launchers are not overwritten.

The installed command does not depend on the source directory. Rerun the installer after updating the source, or if a Codex installer replaces the dispatcher.

For other installation layouts, install the dependency and invoke the script directly:

```bash
python3 -m pip install websockets==15.0.1
python3 codex-rewind.py --codex /absolute/path/to/codex
```

## Usage

```bash
# Choose a conversation and a message interactively
codex rewind

# Open the message selector for a specific conversation
codex rewind THREAD_ID

# Check the API and conversation format without reverting
codex rewind THREAD_ID BEFORE_TURN_ID

# Rewind an explicit turn and continue (close other clients first)
codex rewind THREAD_ID BEFORE_TURN_ID --apply --stopped --continue
```

Enter a number to select, `n` / `p` to change pages, or `q` to quit. Selecting a message applies the rewind immediately; exit with `q` or Ctrl+C before selecting to cancel. Use `--no-continue` to disable automatic continuation after interactive rewind. Set `NO_COLOR=1` to disable colors.

## Existing App Server support

When the local `app-server-control/app-server-control.sock` exists under `CODEX_HOME` (default: `~/.codex`), the tool connects to the existing App Server over a Unix WebSocket. Otherwise, it starts a separate App Server.

If the selected thread has a running turn, the tool calls `turn/interrupt` and waits for it to stop before loading, backing up, and reverting the thread. It does not terminate shared processes or delete locks.

After a shared-server rewind, continue in the original client. The tool does not launch another CLI that could compete for the same writer lock. In standalone mode, it can launch `codex resume` automatically.

## Backups and recovery

The operation follows this sequence:

```text
Load original thread → Fork full-history backup → Save recovery record
                                                    │
                                                    └→ Revert original thread
                                                        (same thread ID)
```

Recovery records are saved before the revert request:

```text
$CODEX_HOME/rewind-backups/rewind-*.json
# Defaults to ~/.codex/rewind-backups
```

The terminal prints the backup ID and a recovery command:

```bash
codex resume BACKUP_THREAD_ID
```

This opens the backup conversation; it does not overwrite the original thread. Backups are forks in the same Codex storage, not offline disaster-recovery copies. Backups and recovery records are not automatically deleted.

## Limitations and troubleshooting

- **No code rollback.** File changes, commands, external API calls, and other tool side effects are not undone.
- Rewind operates on whole turns, not individual assistant messages or tool calls within a turn.
- A thread owned by another standalone process may still report `already has an active writer`. Exit that client and retry. Loading happens before backup creation, so writer conflicts do not create extra backups. The explicit-ID workflow requires `--stopped` as the user's assertion that other clients have been closed.
- After a timeout or interruption, the revert may already have succeeded. Inspect the thread and backup before retrying.
- Tests cover schema checks, selection, pagination, cancellation, writer conflicts, and interrupt dispatch. Revert has also been verified on extra fork copies through both standalone and shared servers; those test copies were archived.

## Development

```bash
python3 -m unittest discover -s . -p 'test_*.py'
```

| File | Purpose |
| --- | --- |
| `codex-rewind.py` | App Server client, terminal interface, backup and rewind workflow |
| `install-codex-rewind.py` | Global `codex rewind` installer |
| `test_codex_rewind.py` | Unit tests |

Protocol reference: [Codex App Server](https://developers.openai.com/codex/app-server). Compatibility is checked against the schema generated by the installed CLI.

## Uninstalling the global command

First verify that `~/.local/bin/codex` is still this tool's dispatcher. Then replace it with a symlink to the original launcher, whose path is recorded during installation:

```bash
ln -sfn "$(cat ~/.local/lib/codex-rewind/original-target.txt)" ~/.local/bin/codex
```

This leaves your source files and conversation backups intact.
