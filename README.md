# CIN Telegram Agent

ThinkCentre-resident bot. Conversation + shell execution, no token waste on routine ops.

---

## Architecture

```
User Message
    │
    ▼
command_parser.py  ──── intent detection ────►  "command" | "chat" | "confused"
    │                                                  │
    ▼ command                                          ▼ chat
shell_ghost.py                                   Ollama (local)
    │                                                  │
    ├── whitelist check                          Cloud fallback (optional)
    ├── dangerous pattern block                        │
    ├── confirmation gate                              ▼
    └── execute → result                         memory.py (persist context)
    │
    ▼
Telegram reply
```

---

## Quick Install

```bash
git clone <your-repo> && cd cin_agent
sudo ./install.sh $USER
sudo nano /etc/cin_agent/env    # add TELEGRAM_BOT_TOKEN
sudo systemctl start cin-agent@$USER
```

---

## Environment Variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | From @BotFather |
| `ALLOWED_USER_IDS` | — | (all) | Comma-separated Telegram IDs |
| `OLLAMA_URL` | — | `http://localhost:11434` | Local Ollama endpoint |
| `OLLAMA_MODEL` | — | `llama3` | Any model you have pulled |
| `ANTHROPIC_API_KEY` | — | (disabled) | Cloud fallback, leave empty to skip |
| `CIN_DATA_DIR` | — | `~/.cin_agent` | Memory + audit log location |

---

## Usage Examples

### Conversation
```
You: hey what's up
CIN: Online. What do you need?

You: do you remember my name?
CIN: You're [name]. Registered when you first ran /start.
```

### System Commands
```
You: show me disk space
CIN: ✅ df -h
     Filesystem  Size  Used  Avail  Use%  Mounted
     /dev/sda1   500G  120G   380G   24%  /

You: check memory
CIN: ✅ free -h
     (memory table)

You: check status
CIN: ✅ uptime && free -h && df -h /
     (full system snapshot)
```

### File Operations
```
You: list files in ~/Downloads
CIN: ✅ ls -la ~/Downloads
     (directory listing)

You: create file notes.txt with content buy milk, fix speaker
CIN: ✅ Created /home/user/notes.txt

You: read file notes.txt
CIN: ✅ cat notes.txt
     buy milk, fix speaker

You: find config in ~/
CIN: ✅ find ~/ -name '*config*' ...
     (results)
```

### Git
```
You: git status
CIN: ✅ git status
     (output)

You: git log
CIN: ✅ git log
     (recent commits)
```

---

## Safety Model

### Whitelist (always allowed)
`ls, cat, df, free, ps, git, find, grep, mkdir, touch, cp, mv, uptime, ...`

### Blocked (always)
`rm -rf, sudo, dd if=, mkfs, fork bombs, curl | bash, ...`

### Confirmation Required
`rm, rmdir, mv, kill, iptables, crontab`

---

## Service Management

```bash
# Status
sudo systemctl status cin-agent@$USER

# Logs (live)
sudo journalctl -u cin-agent@$USER -f

# Restart after config change
sudo systemctl restart cin-agent@$USER

# Upgrade (re-run installer)
sudo ./install.sh $USER
```

---

## Files

```
/opt/cin_agent/
├── telegram_bot.py      Main bot + routing logic
├── command_parser.py    NL → intent detection
├── shell_ghost.py       Safe shell execution layer
├── memory.py            Persistent user context
└── venv/                Python dependencies

/etc/cin_agent/
└── env                  Config (token, model, etc.)

~/.cin_agent/
├── memory.json          User facts + conversation history
├── audit.log            All executed commands
└── bot.log              Runtime logs
```

---

## Extending

### Add a new command pattern

In `command_parser.py`, add to `COMMAND_PATTERNS`:
```python
(r"(?:check|show)\s+gpu", "gpu_status"),
```

Then add the command builder in `_build_command`:
```python
if action == "gpu_status":
    return "nvidia-smi"
```

### Add to whitelist

In `shell_ghost.py`, add to `SAFE_COMMANDS`:
```python
SAFE_COMMANDS = {
    ...,
    "nvidia-smi",
    "your-tool",
}
```

---

## Token Economics

- Routine shell commands: `$0.00` (local execution, no LLM)
- Casual chat: `$0.00` (Ollama, local 7B)
- Complex reasoning (fallback): `~$0.001` per exchange (Haiku)

The agent routes to cloud only when local model can't handle it.
