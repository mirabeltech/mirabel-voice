## Factory sessions

- Start every factory session (Archon, `claude`, Remote Control) in the repository folder, not a parent folder. The tripwire and the shared permission rules in `.claude/settings.json` load only from the repository.
- Never add or remove the `auto-merge` or `plan-approved` labels. They record the owner's answers at the workflow gates, and only the workflow changes them. A brief that says "for the owner's review" means leave the pull request alone, not take the label off: the factory gate already decides whether the owner merges.
