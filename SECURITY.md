# Security policy

## Supported versions

Until the first public release, security fixes are made on the `main` branch.
After releases begin, the newest released version and `main` are supported.

## Reporting a vulnerability

Once the repository is on GitHub, use **Security → Advisories → New draft
security advisory** so the report stays private. If private vulnerability
reporting has not yet been enabled, contact the repository owner privately and
ask for a secure reporting channel. Do not open a public issue with exploit
details.

Include the affected version, operating system, impact, and a minimal synthetic
reproduction. Do not include real journal text, filenames, settings, summary
metadata, tokens, usernames, home-directory paths, or an unredacted terminal
capture.

Venting writes private local text and can optionally send saved text to a
loopback Ollama server. Reports involving unexpected network access, unsafe file
replacement, permission loss, symlink handling, clipboard disclosure, terminal
escape injection, or ignored private data are especially important.

