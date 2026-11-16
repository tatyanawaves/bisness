# GMGN skills in this project: analytics only

Installed from github.com/GMGNAI/gmgn-skills (MIT, see LICENSE-gmgn-skills): the 16
read-only skills. Left out on purpose: `gmgn-swap`, `gmgn-token-buy`, `gmgn-cooking`.
They trade or create tokens on-chain with real money and have no paper mode.

- Where an installed skill hands off to one of those three, stop and tell the user
  that trading is not installed here.
- `.claude/settings.json` denies `gmgn-cli swap`, `gmgn-cli order` and `gmgn-cli cooking`.
- Never configure `GMGN_PRIVATE_KEY` in this project. Commands that need it
  (`portfolio holdings`, `track follow-wallet`) stay unavailable.
- Setup the user still has to do: `npm install -g gmgn-cli`, then their own
  `GMGN_API_KEY` from gmgn.ai in `~/.config/gmgn/.env` or the environment's variables.
