# Contributing

## Before you commit

Run `pre-commit run --all-files`. It rejects RFC1918 addresses, raw internal
hostnames, credentials, and unnamed private repositories. The owner-approved
logical alias `appsecgate-lab` is allowed. See `docs/adr/README.md` for the
publication policy.

Run the project checks with `make check`.
