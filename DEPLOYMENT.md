# Deployment

These instructions describe a typical Linux deployment. Adjust paths, account
names, node addresses, and channel indices for your installation.

## Install

Create or select a dedicated unprivileged service account, then create the
installation and log directories. The commands below assume the account is
named `meshtastic` and already exists:

```bash
cd /path/to/autoannounce
sudo install -d -o meshtastic -g meshtastic /opt/meshtastic-announcer
sudo install -d -o meshtastic -g meshtastic /opt/meshtastic-announcer/logs
sudo cp announce.py requirements.txt /opt/meshtastic-announcer/
sudo chown meshtastic:meshtastic \
  /opt/meshtastic-announcer/announce.py \
  /opt/meshtastic-announcer/requirements.txt
sudo -u meshtastic python3 -m venv /opt/meshtastic-announcer/.venv
sudo -u meshtastic \
  /opt/meshtastic-announcer/.venv/bin/python -m pip install \
  -r /opt/meshtastic-announcer/requirements.txt
```

Create a local `config.yaml` using the example in [Readme.me](./Readme.me); do
not copy a developer's real configuration. Set its log file and state-file
paths under `/opt/meshtastic-announcer/`, and configure the intended node
target(s) and channel index/indices. Keep the config readable only by the
service account and administrators.

Make sure the service account can read the application and configuration and
write to the configured log and state locations. Do not run the script as root
just to work around a permissions problem.

## Check before scheduling

Run a dry run as the same account that cron will use:

```bash
cd /opt/meshtastic-announcer
.venv/bin/python announce.py --dry-run
```

Dry run connects to every configured node and reads its metrics; it does not
send text or update state. Confirm each generated message and its UTF-8 payload
size, which must be no more than 233 bytes. Test actual transmission separately
and deliberately, since `--force` sends an announcement.

## Cron example

This example runs at minute 9 every six hours and serializes access with other
jobs that use the same lock file:

```cron
9 */6 * * * cd /opt/meshtastic-announcer && /usr/bin/flock -w 45 /tmp/meshtastic-node.lock /usr/bin/timeout 120 /opt/meshtastic-announcer/.venv/bin/python /opt/meshtastic-announcer/announce.py >> /opt/meshtastic-announcer/logs/cron.log 2>&1
```

Ensure the log directory is writable by the cron account. Use the same lock
path for every job that must not access the Meshtastic node concurrently.
Choose a command timeout long enough for connection setup, metrics collection,
all configured targets and channels, and the 2-second post-send hold for each
channel. `flock -w 45` limits how long the job waits for the lock; the command
timeout starts after the lock is acquired.

Cron uses its own environment and working directory. Use absolute paths and
change into the application directory because the script reads `config.yaml`
from its current working directory.

## Updates

Back up the local configuration and state before replacing application files.
Review dependency changes in `requirements.txt`, update packages in the
project's virtual environment, then repeat the dry run as the cron account.
Keep the configuration private and restore its file permissions after updates.
