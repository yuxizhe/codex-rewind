# Codex Rewind

为 Codex CLI 添加 `codex rewind`：通过终端列表选择会话和消息，在保留备份的前提下，原地回退对话历史。

基于 Codex App Server 的 `thread/revert`，不手动修改会话存储文件。个人独立工具，非 OpenAI 官方项目。

## 使用体验

```text
  ↶  CODEX REWIND   /   01 / 03
  ──────────────────────────────────────────
  选择会话

  最近更新优先

   1  实现一个命令行工具
      10-30 15:40 ~/projects/example · 01a18bb6

   2  优化页面布局
      10-29 18:30 ~/projects/website · 01a1870a

  第 1 页 · 序号 选择 / n 下一页 / q 退出

  ›
```

1. 选择会话：显示标题、更新时间和工作目录。
2. 选择回退位置：预览用户消息，按整轮选择。
3. 执行：选中消息即自动备份并回退，不再要求输入确认。选择前请关闭目标会话的其他客户端。
4. 工具创建完整会话的 fork 备份，然后回退原会话，并自动继续原会话。

**回退至所选消息之前：所选消息所在整轮及后续历史都会被删除。原会话 ID 不变。代码和本地文件不会回滚。**

## 环境要求

- Python 3.9+，仅使用标准库，无第三方 Python 依赖。
- 已安装并配置 Codex CLI。
- CLI 必须支持实验性 `thread/revert` 接口，且目标会话使用 `paginated` 历史格式。
- 本地验证版本：Codex CLI 0.166.0。实验性接口可能变化，工具会先检查参数 schema；旧式 legacy 会话会被拒绝。
- 全局安装脚本目前适配 macOS/Linux 的 standalone 布局：`~/.codex/packages/standalone/current/bin/codex`。

## 安装

```bash
git clone https://github.com/yuxizhe/codex-rewind.git
cd codex-rewind
python3 install-codex-rewind.py
codex rewind
```

确保 `~/.local/bin` 在 `PATH` 中。安装器将源码复制到 `~/.local/lib/codex-rewind`，在 `~/.local/bin/codex` 安装分发脚本；其他 `codex` 命令透传原 CLI。安装器遇到不认识的现有 launcher 会拒绝覆盖。

安装后不依赖源码目录的位置。更新源码或 Codex 安装器覆盖 launcher 后，重新运行安装脚本即可。

其他安装布局可直接运行：

```bash
python3 codex-rewind.py --codex /absolute/path/to/codex
```

## 用法

```bash
# 交互选择会话与消息
codex rewind

# 直接进入某个会话的消息列表
codex rewind THREAD_ID

# 仅检查接口与目标会话格式，不执行回退
codex rewind THREAD_ID BEFORE_TURN_ID

# 指定位置回退，并继续原会话（先关闭该会话所有客户端）
codex rewind THREAD_ID BEFORE_TURN_ID --apply --stopped --continue
```

列表输入序号选择，`n` / `p` 翻页，`q` 退出。选中消息即执行；选择前可用 `q` 或 Ctrl+C 退出。`--no-continue` 可禁用交互回退后的自动继续。设置 `NO_COLOR=1` 可禁用颜色。

## 备份与恢复

执行顺序：

```text
原会话 ── thread/fork ──→ 完整历史备份（新 ID）
   │
   └── thread/resume → thread/revert ──→ 回退后的原会话（原 ID）
                              │
                              └── codex resume
```

备份成功后，工具会先保存恢复记录，再调用回退接口。记录位于：

```text
$CODEX_HOME/rewind-backups/rewind-*.json
# CODEX_HOME 未设置时使用 ~/.codex
```

终端会显示备份 ID 和恢复命令：

```bash
codex resume BACKUP_THREAD_ID
```

这会打开备份对话，不是将备份覆盖回原 ID。备份是同一 Codex 存储中的 fork，不是离线灾备；备份和恢复记录不会自动清理。

## 限制

- **不回退代码**，也不会撤销命令、外部 API 或其他工具操作产生的副作用。
- 回退粒度是整轮，不支持在同一轮内部截断助手消息或工具调用。
- 必须关闭目标会话的其他客户端。独立 App Server 无法可靠判断其他进程是否仍在使用该会话，`--stopped` 是使用者的确认。
- 发生超时或中断时，回退可能已经生效。先检查会话和备份，不要直接重复执行。
- 目前测试覆盖协议参数检查、选择列表、分页与取消，并实测了真实会话的列表读取。已在额外 fork 副本上验证 resume → revert 和目标轮移除；测试副本已归档。

## 开发与测试

```bash
python3 -m unittest discover -s . -p 'test_*.py'
```

| 文件 | 用途 |
| --- | --- |
| `codex-rewind.py` | App Server 客户端、终端界面、备份与回退流程 |
| `install-codex-rewind.py` | 安装全局 `codex rewind` 分发脚本 |
| `test_codex_rewind.py` | 单元测试 |

协议参考：[Codex App Server](https://developers.openai.com/codex/app-server)。兼容性以本机 CLI 生成的 schema 为准。

## 卸载全局命令

确认 `~/.local/bin/codex` 仍是本工具安装的分发脚本后，将其替换为原 launcher 的软链接。原目标记录在 `~/.local/lib/codex-rewind/original-target.txt`：

```bash
ln -sfn "$(cat ~/.local/lib/codex-rewind/original-target.txt)" ~/.local/bin/codex
```

这不会删除会话备份或源码。

### 会话被占用

出现 `already has an active writer` 表示另一个 Codex 客户端仍持有该会话的写入权。
请退出对应 CLI 或在桌面客户端关闭该会话，再运行 rewind。工具先加载原会话取得写入权，
成功后才创建备份；占用冲突不会再产生额外备份。工具不会强杀进程或删除存储锁。
