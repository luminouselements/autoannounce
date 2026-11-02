# Security

## Protect local configuration and runtime data

- Keep `config.yaml` local. It contains node addresses and may contain
  identifying custom message text. Do not commit it or paste it into public
  issues.
- Keep `state.json`, logs, backups, virtual environments, and environment files
  out of version control. The project `.gitignore` excludes these paths.
- Restrict filesystem access to the service account and administrators. In
  particular, the service account needs write access only to the configured
  state and log locations.
- Review logs before sharing them; they can include node addresses, local paths,
  and exception details.

If sensitive information has already been committed, removing it in a later
commit is not enough. Treat the information as exposed, rotate any affected
credentials, and coordinate repository-history cleanup with its maintainers.

## Network and runtime

- Run the announcer as an unprivileged account.
- Permit the Meshtastic TCP connection only from trusted hosts on the network
  where the node is intended to be managed. Do not expose the node's TCP
  management interface to the public internet.
- Keep Python and the packages in `requirements.txt` updated from trusted
  sources. Review dependency changes before deploying them.
- Use a dedicated configuration and state location with permissions suitable
  for the service account; avoid writable-by-everyone directories.

## Reporting a vulnerability

Do not publish exploit details or sensitive node configuration in a public
issue. Report suspected vulnerabilities privately to the repository owner or
maintainer and include the affected version, impact, and a concise reproduction
that does not disclose credentials or private network data. Coordinate public
disclosure with the maintainer after a fix is available.
