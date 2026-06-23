# Fauxdex Workspace Loop

Fauxdex is the bounded workspace engine underneath Fennix.

Initial loop:

1. Observe the active project, git status, threads, and current goal.
2. Read or search only the files needed for the task.
3. Plan the smallest useful change.
4. Propose edits before applying risky changes.
5. Verify with focused commands.
6. Snapshot state through `fauxnix-git`.

Useful commands:

- `fauxdex status`
- `fauxdex observe`
- `fauxdex plan <request>`
- `fauxdex prompt <request>`
- `fauxdex set-project <project>`
- `fauxdex set-goal <goal>`
- `fauxdex read <project> <relative-path>`
- `fauxdex search <project> <query>`
