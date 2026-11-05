# Mirabel Voice

Push-to-talk dictation for Windows (`src/mirabel_voice/`) and the AWS Lambda relay it calls (`src/mirabel_relay/`). `README.md` is for users; `ADMIN.md` is for the owner.

## Releases and production

- Releases, version tags, GitHub releases, Drive uploads and relay deploys belong to Tommy McCormick. Never start one, even when a ticket asks for it; say in the pull request what is left for him.
- Never run `scripts/deploy_relay.py`, `scripts/set_relay.py`, `scripts/setup_relay.py`, `scripts/setup_operations.py` or `scripts/approve_bundle.py`, the `aws` CLI, or code that loads `boto3`. `.claude/hooks/production-guard.mjs` blocks them.
- Never read `relay.json` or anything under `~/.aws`. They hold credentials.
- `.mdk/profile.json` puts `src/mirabel_relay/`, `packaging/`, `operations/`, the scripts above, `docs/deploy-policy.json`, `install.ps1` and `setup.ps1` at T3, so Tommy merges changes to them.
- The public install command, the in-app updater and `deploy_relay.py` read this repository without signing in. Keep the repository public, and keep `install.ps1`, `packaging/bundles.json` and the release tags where they are.

## Tests

- Run the tests from the worktree root with `C:\Dev\mirabel-voice\.venv\Scripts\python.exe -m pytest -q`. A factory worktree has no `.venv` of its own; `pyproject.toml` puts `src` and `scripts` on the path.
- CI (`Verify Windows Python bundle`) also builds the Windows ZIP and checks it on x64 and ARM. A change that only CI can check says so in the pull request.

## Factory sessions

- Start every factory session (Archon, `claude`, Remote Control) in the repository folder, not a parent folder. The tripwire and the shared permission rules in `.claude/settings.json` load only from the repository.
- Never add or remove the `auto-merge` or `plan-approved` labels. They record the owner's answers at the workflow gates, and only the workflow changes them. A brief that says "for the owner's review" means leave the pull request alone, not take the label off: the factory gate already decides whether the owner merges.
