# Preparing the GitHub repository

This checklist is for the first upload. It deliberately leaves the account and
repository URL unset until the maintainer chooses them.

## Before the first push

1. Review every tracked candidate with `git status --short` and `git diff
   --no-index /dev/null FILE` where needed. Do not stage `vents/`,
   `venting.json`, `.venting-summaries/`, terminal captures, or build output.
2. Confirm the ignore rules with:

   ```sh
   git check-ignore -v venting.json vents/private.txt .venting-summaries/example
   ```

3. Search the source and documentation for personal names, absolute home paths,
   email addresses, credentials, and copied vent text. Use only synthetic test
   content.
4. Run the validation commands in `docs/RELEASING.md`.
5. Review `LICENSE`, `THIRD_PARTY.md`, `SECURITY.md`, and the bundled dictionary
   notices.
6. Set the repository URL in `pyproject.toml` only after its final location is
   known, for example under a `[project.urls]` table.

If private material was ever committed, removing the current file is not
enough: clean the history before publishing and rotate any exposed credential.

## Create and push

Create an empty GitHub repository without a generated README, license, or
`.gitignore`, then connect this existing repository:

```sh
git remote add origin git@github.com:YOUR_ACCOUNT/venting.git
git push -u origin main
```

Do not paste a token into the remote URL. Use SSH or a credential manager.

## Repository settings

- Enable private vulnerability reporting and the dependency graph.
- Give Actions read-only repository contents by default.
- Protect `main`: require the CI check, block force pushes, and require the
  branch to be current before merging.
- Enable automatic deletion of merged branches.
- Keep Discussions, Wiki, and Pages disabled unless there is a concrete use.
- Add a short description and topics such as `terminal`, `curses`, `journal`,
  `text-editor`, and `ollama` without describing the tool as encrypted storage.

The included issue forms remind reporters not to disclose private vent content.
Inspect the first Actions run before announcing the repository.

