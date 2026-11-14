# Third-party components and attribution

- **PowerContext 1.2.0** — OceanBase, Apache-2.0. Used as an installed Python
  package for the local Server/Client and Memory persistence. No PowerContext
  source is copied into this directory.
- **seekdb 1.4.0** — OceanBase. Used either as a local server binary or as an
  existing MySQL-protocol endpoint; no seekdb source is copied into this
  directory.
- **MiniMax-M3.1-Flash** — MiniMax. Used through the OpenAI-compatible HTTP
  API at `https://api.minimax.cn/v1`; the generated code and usage record are
  included in `evidence/`.
- The sample `subledger` business project, its specs, tests, and the
  `sdd_context` module were written for this submission. The dataset is
  synthetic (no third-party data).

The exact dependency versions are pinned in `requirements.txt`.
