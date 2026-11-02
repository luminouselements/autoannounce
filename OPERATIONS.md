# Operations

## Scheduling and node access

The script may target one node with `meshtastic.host` and
`meshtastic.channel_index`, or multiple nodes with a `meshtastic.targets` list.
For multiple targets, each node supplies its own metrics and rendered message.
Each target can send to multiple channel indices. Change detection is tracked
per node and channel.

Use a shared `flock` lock file for every scheduled job that must serialize
access to the Meshtastic node. The lock only coordinates jobs that use that
same lock path. Leave enough timeout for all node connections and channel
sends; the script waits two seconds after each channel send and also holds each
dry-run connection open for two seconds before closing.

## Logs and state

The configured application log uses rotation at 5 MB with five backups.
Cron's `>> ... 2>&1` output is a separate log and is not rotated by the script;
configure log rotation for it at the operating-system level.

`state.json` is written after a successful local send call and is used by
`send_only_on_change`. For multiple targets, the state is stored separately by
host and channel. Back it up only if preserving change-detection history is
important. It can be removed to reset that history; the next run may send
announcements again.

An `Announcement sent` log entry means the local Meshtastic `sendText` call
returned. It does not confirm over-the-air transmission or receipt by another
node.

## Troubleshooting

1. **No new log entry:** Check that cron is running, the schedule is installed
   for the expected account, and the cron output log is writable.
2. **Permission error:** Check ownership and write permissions for the
   configured application log, state-file parent directory, and cron log.
3. **Connection error:** Confirm the target address is reachable from the
   cron host and that the node's Meshtastic TCP service is enabled.
4. **No message received:** Verify the sending node and receivers use the
   intended channel index and compatible channel settings. A local send log
   alone is not delivery confirmation.
5. **Payload too large:** Run `--dry-run` and reduce template text or emojis
   until the rendered message is at most 233 UTF-8 bytes.
6. **Lock wait or timeout:** Check other jobs using the shared lock and allow
   adequate command runtime for each target and channel.

Run diagnostic commands as the cron account and from the application directory:

```bash
cd /opt/meshtastic-announcer
.venv/bin/python announce.py --dry-run
```

Dry run contacts each configured node to retrieve metrics, but it does not
transmit an announcement or update state.
