# Contributing

This guide covers Git workflow and local development for the Meshtastic
Scheduled Announcer.

## Git workflow

1. Check the current branch and working tree before editing:

   ```bash
   git status --short --branch
   ```

2. Create a focused branch from the repository's default branch:

   ```bash
   git switch -c docs/operations-guides
   ```

3. Keep changes focused. Review and validate them before committing:

   ```bash
   git diff --check
   git diff
   ```

4. Stage only the intended project files, then use a concise commit message.
   For example, from the repository root:

   ```bash
   git add autoannounce/announce.py autoannounce/Readme.me
   git commit -m "Describe the change"
   ```

   Adjust paths to match the repository root and files being changed. Avoid
   `git add .` when unrelated or private files may be present.

Do not commit local `config.yaml`, `state.json`, logs, virtual environments,
environment files, or backups. The project `.gitignore` excludes these local
files. If a sensitive file is already tracked, `.gitignore` does not untrack it;
remove it from the index carefully and address its existing history separately.

## Development setup

Use Python 3.10 or newer and a project-local virtual environment:

```bash
cd /path/to/autoannounce
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Create `config.yaml` using the configuration example in [Readme.me](./Readme.me).
Use reachable test nodes and channels; the runtime configuration is ignored by
Git.

## Validation

There is currently no automated test suite in this project. Before submitting
Python changes, at minimum check syntax:

```bash
.venv/bin/python -m compileall -q announce.py
```

For changes affecting configuration or message rendering, run a dry run:

```bash
.venv/bin/python announce.py --dry-run
```

Dry run does not send an announcement or update state, but it does connect to
each configured node to retrieve metrics. It therefore requires reachable
nodes, and the script holds each connection open briefly before closing it.
Do not use `--force` as a validation shortcut; it transmits messages.

Update the relevant documentation when changing configuration, command-line
behavior, deployment, or operational behavior.
