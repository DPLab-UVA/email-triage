---
name: uva-server-dev
description: Use when work involves Junjun's UVA servers, including DPLab and Rivanna, or when syncing and running the DP image/text project between the local Mac and those servers. Covers SSH entry points, canonical server paths, code-only sync workflow, and remote use of codex, claude, and gemini.
---

# UVA Server Dev

Use this skill whenever the task involves:

- connecting to `portal`, `dplab01`-`dplab08`, or `rivanna`
- reading or modifying the image project on server
- syncing code between local and server
- launching or monitoring long experiments remotely
- using remote `codex`, `claude`, or `gemini` when local quota is tight
- checking DPLab node health or finding idle GPUs
- submitting or monitoring jobs on Rivanna

Official references:

- UVA CS compute portal: `https://www.cs.virginia.edu/wiki/doku.php?id=compute_portal`
- UVA CS Slurm docs: `https://www.cs.virginia.edu/wiki/doku.php?id=compute_slurm`
- UVA RC HPC overview: `https://www.rc.virginia.edu/userinfo/hpc/`
- UVA RC Slurm docs: `https://www.rc.virginia.edu/userinfo/hpc/slurm/`
- UVA RC allocation access: `https://www.rc.virginia.edu/userinfo/hpc/access/`

Supplemental user-maintained reference:

- `https://docs.google.com/document/d/1ISPhon9uJqRv0Y_Q4FF5py1uM0YjuLR-Aa0_XeZNmMg/edit`

Treat that Google Doc as a helpful secondary map of lab resources and past
usage patterns. When it conflicts with live probes or the official CS / RC
docs, trust the live probes and official docs. Do not reuse or propagate any
credentials that may appear in shared notes. In particular, the doc contains
older names such as `jaguar04` and `sds01`. As confirmed by CS IT on
`2026-03-21`, `jaguar04` was reclaimed by SDS and moved to the UDC, while
`sds01` was renamed to `cheetah08`. The doc references `sds01`, not `sts`.

## Canonical Paths

- Image code: `/p/fzv6enresearch/gap`
- Image results: `/bigtemp/fzv6en/gap_data/exp`
- Public text code to integrate: `https://github.com/KaiChen9909/textsyn`
- Unified local/server integration repo: `/Users/tianhao/Documents/GitHub/dp-pe-multimodal`
  locally and `/u/nkp2mr/dp-pe-multimodal` on DPLab

Do not treat `/u/nkp2mr/kecen/text_diffusion_project` as the canonical text
repo unless the user explicitly asks for that separate project.

## SSH Entry Points

- `portal`
- `dplab01` through `dplab08`
- `rivanna`

Prefer noninteractive checks first:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 dplab01 'hostname; pwd'
ssh -o BatchMode=yes -o ConnectTimeout=10 rivanna 'hostname; pwd'
```

The UVA CS `portal` host is a gateway/login cluster, not the place to run long
compute jobs. Use it for logins, editing, compilation, short checks, and to
reach other CS resources. Use the CS SLURM-managed nodes or Rivanna for long or
compute-intensive work.

## Shared Filesystem

Treat the DPLab nodes as separate compute hosts on a shared home/filesystem.
For this project, `/u/nkp2mr/...` is visible across at least `dplab01`,
`dplab03`, `dplab06`, `dplab07`, and `dplab08`, so chunked jobs can be launched
from multiple nodes while writing to the same artifact directory.

Operational consequence: cleanup or installation work under `/u/nkp2mr`
is usually cluster-wide for DPLab, not host-local. If you delete a model cache,
rewrite a symlink such as `~/.local/bin/vllm`, or remove an environment under
`/u/nkp2mr/.venvs`, assume that change will affect other DPLab nodes that share
the same filesystem view.

## Node Discovery

The managed DPLab scan helper lives at:

- local managed copy:
  `/Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/uva-server-dev/scripts/scan_idle_hosts.py`
- typical server copy:
  `/u/nkp2mr/scan_idle_hosts.py`

Use it from a DPLab node such as `dplab01`:

```bash
python3 /u/nkp2mr/scan_idle_hosts.py
python3 /u/nkp2mr/scan_idle_hosts.py --sort-by idle
python3 /u/nkp2mr/scan_idle_hosts.py --only-gpu-free --json
```

It scans `dplab01`-`dplab08`, reports CPU load, memory pressure, per-GPU usage,
and distinguishes a true GPU driver failure from a merely busy or GPU-less
machine.

If host-key verification breaks inside DPLab-to-DPLab SSH, repair the stale
entry from the node that is running the scanner:

```bash
ssh-keygen -R dplab04
ssh-keygen -R dplab04.cs.virginia.edu
ssh-keyscan -H dplab04.cs.virginia.edu >> ~/.ssh/known_hosts
```

Repeat for any node with a changed host key.

## Subnet SSH Sweep

For cases where a DPLab host may have rebooted onto a bad state and simple
hostname-based SSH tests are inconclusive, use the broader SSH sweep helper:

- local managed copy:
  `/Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/uva-server-dev/scripts/scan_server.py`
- typical server copy:
  `/u/nkp2mr/scan_server.py`

By default it scans `128.143.71.1-254` for TCP port `22` and prints the IPs
that accept an SSH connection. The managed local copy also accepts alternate
prefixes and optional reverse-DNS / SSH-banner output.

Use it from `portal` or from a reachable DPLab node such as `dplab02`:

```bash
ssh portal 'python3 /u/nkp2mr/scan_server.py'
ssh dplab02 'python3 /u/nkp2mr/scan_server.py'
python3 /Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/uva-server-dev/scripts/scan_server.py --prefix 128.143.67 --resolve --banner
```

Use this sweep to answer questions like:

- whether a host such as `dplab03` is still absent from its expected IP
- whether a machine appears elsewhere inside the `128.143.71.0/24` range
- whether the subnet itself is broadly reachable on `22/tcp`

The server copy is a simple fixed sweep over `128.143.71.0/24`. The managed
local copy can also scan alternative prefixes such as `128.143.67.0/24` and can
optionally include reverse DNS and SSH banner capture. Neither copy does GPU
health checks; follow up with `scan_idle_hosts.py` or a targeted SSH probe if
an unexpected IP appears open.

For non-DPLab fallbacks, use a targeted probe after the subnet sweep:

```bash
ssh portal 'ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new hiperal02.cs.virginia.edu "hostname; nproc; free -h | sed -n \"2p\"; nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv,noheader"'
```

This separates:

- TCP reachability (`scan_server.py`)
- user access rights (`ssh ... true`)
- actual hardware fit (`nvidia-smi`, `free -h`, `uptime`)

## Working Rules

- Run experiments on server, not on the local machine.
- Keep datasets, checkpoints, generated samples, and result tables on server.
- Keep local copies code-only unless the user asks for small artifact pulls.
- Keep large caches on server by default. Model caches, dataset caches,
  benchmark caches, and experiment result caches should stay on DPLab,
  `groupml*`, or Rivanna unless the user explicitly asks for a local copy.
- When syncing code to server, exclude repo-local virtual environments such as
  `.venv`, `.venv311`, and `.venv313`. A local macOS venv can overwrite a
  working server Linux venv with broken symlinks if it is copied into the repo
  tree.
- Prefer packing GPU jobs onto the same host before spilling onto a second
  host. Do not occupy one GPU on `dplab04` and one GPU on `dplab05` if the
  same work could fit by filling one machine first.
- Preserve fully free multi-GPU hosts when possible. This matters for tensor
  parallelism, larger checkpoints, and any follow-on experiment that may need
  `2+` GPUs on the same node.
- When syncing image code locally, exclude `dataset/`, `exp/`, large logs, and
  generated artifact directories.
- The multimodal repo should use `venv` bootstrap scripts, not `conda`.
- For bounded text variants built from filtered custom CSVs, do not hardcode
  the parent dataset size into DP accounting. Count the retained rows on the
  materialized file and pass that value into the launcher. If the training
  loader expects a paired valid split, either materialize it explicitly or use
  a launcher-local smoke fallback that is clearly labeled as non-paper-facing.

## Experiment Placement Playbook

Before launching jobs, classify the workload. Use the managed scripts to make
the choice explicit instead of relying on memory.

- For a raw DPLab availability snapshot, run:

```bash
python3 /Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/uva-server-dev/scripts/scan_idle_hosts.py --sort-by idle
python3 /Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/uva-server-dev/scripts/scan_idle_hosts.py --only-gpu-free --json
```

- For a placement recommendation that combines DPLab host state with a Rivanna
  queue snapshot, run:

```bash
python3 /Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/uva-server-dev/scripts/recommend_compute_target.py --profile cpu-long
python3 /Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/uva-server-dev/scripts/recommend_compute_target.py --profile gpu-short
python3 /Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/uva-server-dev/scripts/recommend_compute_target.py --profile gpu-long
```

Use the following placement defaults unless the live probe suggests otherwise:

- `cpu-long`: Prefer `rivanna`. This includes full-scale benchmark sweeps,
  accountant or formal-DP sweeps, large preprocessing jobs, and any run that
  can benefit from scheduler-managed CPU throughput.
- `preprocess`: Prefer `rivanna`, especially when the job is mostly ETL,
  caching, feature extraction, or artifact aggregation.
- `gpu-short`: Prefer an actually idle `dplab*` host. This is the best fit for
  exploratory neural baselines, debugging a single configuration, or short
  interactive tuning. When multiple GPUs are needed soon, prefer consuming free
  GPUs on one host before touching another.
- `gpu-long`: Prefer scheduler-managed GPU resources when the run will be long,
  restart-sensitive, or likely to monopolize a shared DPLab GPU. If an idle
  `dplab*` machine is clearly free and the run is modest, it is acceptable to
  use DPLab; otherwise move to a scheduled GPU queue.
- `benchmark`: If the benchmark is CPU-heavy or multi-scale, treat it like
  `cpu-long` and use `rivanna`. If the benchmark is a single neural model check
  or a quick comparator retune, treat it like `gpu-short`.

Decision heuristic:

- prefer `rivanna` for long or batched CPU work
- prefer `dplab` for short interactive GPU work
- avoid using the local Mac for heavy experiments
- pack GPUs onto one DPLab machine before opening a second one
- avoid fragmenting multi-GPU hosts with single-GPU jobs when a same-host
  packing choice is available
- if a model may need tensor parallelism or `2+` GPUs, reserve a same-node
  placement instead of spreading single-GPU experiments across candidate hosts
- do not assume a DPLab GPU is free just because load average is low; always
  check actual `nvidia-smi` usage or use the scanner
- if all DPLab GPUs are busy, or the job needs scheduling guarantees, switch to
  a scheduler-backed queue instead of waiting indefinitely on an ad hoc host
- if the job needs guaranteed GPU access beyond DPLab, check public CS Slurm
  or an IT-provided reservation before looking for ad hoc fallbacks

## Preferred Compute Order

Prefer DPLab first for the user's normal work.

Within DPLab, prefer this allocation order unless the user says otherwise:

- first fill additional free GPUs on the currently selected host
- then choose another host with enough same-node free GPUs for the next job
- only fragment across hosts when the job is explicitly single-GPU and there is
  no realistic chance of near-term multi-GPU demand

The fallback priority order after DPLab is:

- `groupml*` and `jaguar*`
- other known accessible non-DPLab hosts such as `hiperal*`,
  `grasshopper*`, `sabr*`, and `earth`
- other unfamiliar CS resources only after targeted verification
- public CS Slurm-cluster GPU nodes from the official wiki when they are a
  better fit or the higher-priority options are unavailable

Only fall back to non-DPLab UVA CS servers when one of these is true:

- the DPLab machines are all occupied
- the available DPLab GPUs do not have enough memory for the task
- a special accelerator type is needed that DPLab does not currently provide

When falling back, first run the DPLab health/idle scan, then use the subnet SSH
sweep plus targeted probes to find accessible non-DPLab hosts.

Historically accessible non-DPLab host families for this user have included:

- `hiperal*`
- `grasshopper*`
- `groupml*`
- `jaguar*`
- `sabr*`
- `earth`

Some other SSH-open CS hosts, such as `sfo*`, `iad*`, or `sherlock`, may still
deny this user's login, so always verify access with a no-op SSH check before
planning work on them.

Treat any "SSH-open but not formally planned" host as a probe result, not an
automatic green light. Only use it after confirming all three:

- the user can actually log in
- the hardware fits the job
- the intended use is compatible with the machine's policy or reservation model

Do not rely on undocumented or "sneaky" use as a primary workflow. Prefer
documented DPLab, Rivanna, or public CS Slurm resources when they fit.

For this user, `jaguar` sits in the same preferred fallback tier as `groupml`,
but may require an IT reservation workflow before actual use.

The user also reports that public CS Slurm GPU nodes can be reserved by
emailing CS IT, not just group-associated machines such as `jaguar*`. Treat
that as a valid option when a public node is the right fit and stable access is
important.

Known validated examples:

- `groupml01`: `4 x NVIDIA A100 80GB PCIe`, about `503 GiB` RAM
- `groupml02`: `8 x NVIDIA RTX A6000`, about `503 GiB` RAM
- `jaguar01`: CS Slurm node with `4 x NVIDIA A40 48GB`, about `1000 GiB` RAM
- `jaguar04`: historical SDS-associated name from older notes; CS IT confirmed
  on `2026-03-21` that SDS reclaimed it and moved it to the UDC, so it is no
  longer part of this resource pool
- `sds01`: older public-server name from the user-maintained doc; CS IT
  confirmed on `2026-03-21` that it was renamed to `cheetah08`
- `cheetah08`: public CS Slurm node with `4 x NVIDIA RTX A4000`, about
  `512 GiB` RAM; this is the current name for older `sds01`
- public CS Slurm examples from the official wiki include:
  `cheetah01` (`4 x A100 40GB`), `cheetah04` (`4 x A100 80GB`),
  `serval03` (`1 x H100 NVL 94GB`), `serval06-09` (`2 x H100 NVL 94GB`),
  and `ai01-04` (`4 x RTX 2080 Ti`)

Validated on `2026-03-22` for `groupml02`:

- `groupml02` currently exposes `8 x RTX A6000 48GB`
- `/u/nkp2mr` shows roughly `3T` user quota with about `41%` used
- `/u/nkp2mr/.cache/huggingface` is already large enough to act as the shared
  model cache for repeated benchmark work
- if you need a current per-GPU snapshot, use:

```bash
ssh portal 'ssh groupml02 "nvidia-smi --query-gpu=index,name,memory.total,memory.used,utilization.gpu --format=csv,noheader"'
ssh portal 'ssh groupml02 "df -h /u/nkp2mr; du -sh /u/nkp2mr/.cache/huggingface"'
```

If `groupml02` reports a host-key mismatch from `portal`, clear the stale key
first on the jumping host and reconnect:

```bash
ssh portal 'ssh-keygen -R groupml02; ssh-keygen -R groupml02.cs.virginia.edu'
ssh portal 'ssh -o StrictHostKeyChecking=accept-new groupml02 hostname'
```

On `grasshopper*`, `nvidia-smi` may report a single `NVIDIA GH200 480GB`
device. Treat that as one Grace Hopper superchip per host. In practice,
`nvidia-smi` GPU memory will look closer to `~96 GiB`; the `480GB` label refers
to the larger Grace-side LPDDR / unified-memory system configuration, not raw
GPU HBM alone.

## CS Slurm Cluster Notes

The official CS Slurm wiki is:

- `https://www.cs.virginia.edu/wiki/doku.php?id=compute_slurm`

Direct SSH to CS Slurm compute nodes is disabled. For nodes such as
`jaguar01`, use `portal` plus Slurm commands such as `salloc`, `srun`, or
`sbatch` instead of `ssh jaguar01`.

Reservations are not limited to group-associated nodes. For this user, public
CS Slurm GPU nodes can also be reserved by emailing CS IT. If IT provides a
reservation tag, include it explicitly in `srun` / `sbatch`, for example:

```bash
ssh portal 'bash -lc "srun --reservation=<tag> -w jaguar01 -p gpu --pty bash -i -l"'
```

When probing Slurm state noninteractively from `portal`, use a login shell so
the Slurm tools are on `PATH`:

```bash
ssh portal 'bash -lc "command -v sinfo squeue salloc sbatch srun"'
ssh portal 'bash -lc "sinfo -N -h -o \"%N | %P | %T | %G | %f\""'
```

Use the official wiki as the source of truth for publicly documented CS cluster
GPU nodes, reservation workflow, and interactive-job instructions. Do not infer
that an older hostname still exists unless DNS, `sinfo`, or IT confirmation
supports it. In particular, `jaguar04` has been reclaimed by SDS and `sds01`
has been renamed to `cheetah08`.

For this user, the practical CS-cluster fallback order is:

- `portal` + public CS Slurm when scheduler-managed GPU access is needed
- an IT-backed reservation on a named CS node when stability matters
- individually verified non-DPLab hosts only after targeted access and policy checks

## Remote Tooling

The DPLab environment has the following CLIs in PATH:

- `codex`
- `claude`
- `gemini`

Check paths with:

```bash
ssh dplab01 'which codex; which claude; which gemini'
```

When local quota is tight, it is acceptable to run those tools remotely over
SSH or inside `tmux`.

## Codex Resume Hooks For Long Remote Runs

When a long DPLab or Rivanna run should wake Codex back up after it finishes,
use a local Mac-side watcher rather than trying to have the server talk to the
desktop app directly. The reliable pattern is:

1. run the real experiment on server
2. watch its remote log over SSH from the local Mac
3. when the run becomes terminal, write a local summary, notify the calling
   hook/agent in a machine-readable way, and call
   `codex -C <cwd> exec resume <thread_id> <prompt>` when Codex should wake up

Important gotcha:

- launching a remote run does **not** automatically attach a watcher unless the
  launcher explicitly starts one
- a plain project launcher often only starts the remote job
- to get automatic Codex wake-up, either start the watcher as a second command
  or use a project wrapper that launches the run and the watcher together

Why this pattern:

- the server already knows how to run the experiment
- the local Mac already has Codex auth and the active thread state
- `codex -C <cwd> exec resume` can send a new prompt back into the current
  Codex thread
- this avoids trying to expose local app internals to a remote host

Use the managed helper:

- local managed copy:
  `/Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/uva-server-dev/scripts/watch_remote_run_and_resume_codex.py`

Important notes:

- inside Codex Desktop, the current thread id is usually available as the
  environment variable `CODEX_THREAD_ID`
- for nested access such as `portal -> groupml02`, use
  `--remote-command-prefix "ssh -o BatchMode=yes groupml02.cs.virginia.edu"`
  so the local watcher still stays on the Mac while the actual checks run on
  the worker through the jump host
- for benchmark-style runs that do not emit training-step metrics, prefer a
  terminal artifact signal such as
  `--terminal-file /path/to/output/matrix_manifest.json`; the watcher will
  resume Codex when that file appears even if the log has no parsed `step`
  markers
- prefer `--log-tail-lines` for large benchmark logs so each poll reads only
  the tail instead of `cat`-ing the full log every time
- for `launchd`, capture the thread id in the parent shell and pass it
  explicitly; do not assume `launchd` will inherit `CODEX_THREAD_ID`
- the watcher logic is intentionally simple: one watcher process watches one
  remote run, calls `codex exec resume` at most once when that run becomes
  terminal, and then exits
- if you see repeated replays in Codex, the problem is almost always that
  multiple watchers were launched for the same run or a supervisor kept
  restarting the watcher after it already finished
- if a background launcher such as `launchd` cannot read project files under
  `~/Documents`, copy the watcher script to `/tmp` first and write the summary
  to `/tmp` as well
- the watcher should live on the local Mac, even when the run itself is on
  `dplab*` or `rivanna`
- prefer `--resume-instruction` for real runs so the desired follow-up is fixed
  when the watcher starts while the hook still includes the terminal summary
- the default resume prompt now asks Codex to start its reply with a visible
  `[WATCHER] <label> finished (...)` first line so the event is easier to spot
  inside the Codex Desktop thread
- if `--resume-instruction` is omitted, the default follow-up is: `Inspect the
  result, update the notes/tables if needed, then continue with the next
  planned step.`
- the helper supports `--resume-prompt`, which is useful for safe end-to-end
  testing or for fully overriding the hook message before wiring the watcher to
  a real experiment
- desktop notifications are now opt-in with `--notify-mode desktop`
- default `--notify-mode auto` is agent-friendly: if `--codex-thread-id` is
  present, the watcher resumes Codex and skips local desktop notifications;
  otherwise it emits a terminal JSON event on stdout for the hook caller
- if you want both an in-thread Codex message and a visible macOS notification,
  pass both `--codex-thread-id ...` and `--notify-mode desktop`
- if Codex Desktop fails to visibly surface externally resumed thread messages,
  pass `--refresh-codex-ui`; after a successful `codex exec resume`, the
  watcher will call `/Users/tianhao/.local/bin/codex-ui-refresh`
- `--refresh-codex-ui-mode route-cycle` is experimental; it visits
  `codex://settings` and then navigates back to `codex://threads/<thread_id>`,
  but in clean end-to-end testing it was **not** reliable enough to surface
  externally resumed messages
- `--refresh-codex-ui-mode nudge` is lighter, but it was also insufficient in
  testing when the active thread view failed to invalidate after an external
  resume
- the watcher now defaults `--refresh-codex-ui-mode` back to `restart`
- `--refresh-codex-ui-mode restart` remains the only consistently reliable
  workaround observed so far; it relaunches Codex with window state preserved
  so the thread view is rebuilt
- `--refresh-delay-seconds` controls how long the watcher waits between the
  successful resume call and the forced UI refresh; the default is `2.0`

Validated on `2026-03-21`:

- the helper successfully watched a dummy remote log on `dplab05`
- it wrote the terminal summary and JSON sidecar locally
- it resumed the active Codex Desktop thread by calling
  `codex -C /Users/tianhao/Documents/GitHub/dp-pe-multimodal exec resume --skip-git-repo-check ...`
- a direct `codex exec resume ... -C ...` call is **wrong** because `-C` must
  appear before `exec`
- if the watcher may run from a non-trusted or `launchd` context, include
  `--skip-git-repo-check` on `codex exec resume`
- non-fatal warnings about `logs_1.sqlite` migrations or third-party skill
  metadata may still appear on stderr; treat the resume step as successful when
  the command returns `0` and emits an `item.completed` JSON event

Validated on `2026-03-23`:

- externally resumed messages were confirmed to enter both session history and
  the local state DB for the target thread
- `nudge`, `thread-cycle`, `route-cycle`, and a stronger `thread-hop` style
  remount were **not** reliable enough to guarantee UI visibility in the
  Codex Desktop app
- full app restart remained the only consistently reliable way to make the
  hidden externally resumed messages visible

Typical direct usage from the local Mac:

```bash
python3 /Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/uva-server-dev/scripts/watch_remote_run_and_resume_codex.py \
  --host dplab05 \
  --log /u/nkp2mr/dp-pe-multimodal/image/24h_fmnist_28_pe_train_img24h_r2_memsafe128.launch.log \
  --process-pattern 24h_fmnist_28_pe_train_img24h_r2_memsafe128 \
  --label fmnist_28_eps1.0_pe_train_memsafe128 \
  --output /tmp/fmnist_28_eps1.0_pe_train_memsafe128.md \
  --json-output /tmp/fmnist_28_eps1.0_pe_train_memsafe128.json \
  --poll-seconds 180 \
  --codex-thread-id "$CODEX_THREAD_ID" \
  --codex-cwd /Users/tianhao/Documents/GitHub/dp-pe-multimodal \
  --resume-instruction "Inspect the result, update the experiment notes and summary tables if needed, then continue with the next planned step."
```

Benchmark-specific example for `autoresearch-bench`:

- run one watcher per remote system log, for example `codex`, `claude`, and
  `gemini` when they are launched on different `dplab*` hosts
- keep `--codex-cwd` pointed at the local benchmark repo so the resumed thread
  lands back in the right workspace
- use a label that includes the benchmark pack and system name
- for bench logs, a broad `--process-pattern benchrun.py` is usually enough
  because the terminal signal is primarily the remote log reaching its final
  summary / output dir line

Example:

```bash
python3 /Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/uva-server-dev/scripts/watch_remote_run_and_resume_codex.py \
  --host dplab02 \
  --log /u/nkp2mr/autoresearch-bench/benchmark_runs/logs/paper_v1_codex_20260321-231541.log \
  --process-pattern benchrun.py \
  --label autoresearch-bench-paper-v1-codex \
  --output /tmp/autoresearch-bench-paper-v1-codex.md \
  --json-output /tmp/autoresearch-bench-paper-v1-codex.json \
  --poll-seconds 180 \
  --codex-thread-id "$CODEX_THREAD_ID" \
  --codex-cwd /Users/tianhao/Documents/GitHub/autoresearch-bench \
  --resume-instruction "Check the benchmark output, update the run artifacts if needed, and continue the benchmark workflow." \
  --skip-git-repo-check
```

For benchmark sweeps that launch multiple remote systems in parallel:

- start one watcher per remote log
- let each watcher resume Codex with its own label and summary path
- after all systems finish, run the benchmark's own aggregation / rescoring
  utilities rather than relying on the watcher summary alone

If you want the watcher to survive the current shell, launch it through
`launchd`:

```bash
thread_id="${CODEX_THREAD_ID:?missing CODEX_THREAD_ID}"
launchctl remove com.tianhao.remote-run-watch >/dev/null 2>&1 || true

cp /Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/uva-server-dev/scripts/watch_remote_run_and_resume_codex.py /tmp/watch_remote_run_and_resume_codex.py
chmod +x /tmp/watch_remote_run_and_resume_codex.py

launchctl submit -l com.tianhao.remote-run-watch -- \
  /bin/zsh -lc '/usr/bin/python3 /tmp/watch_remote_run_and_resume_codex.py \
    --host dplab05 \
    --log /u/nkp2mr/dp-pe-multimodal/image/24h_fmnist_28_pe_train_img24h_r2_memsafe128.launch.log \
    --process-pattern 24h_fmnist_28_pe_train_img24h_r2_memsafe128 \
    --label fmnist_28_eps1.0_pe_train_memsafe128 \
    --output /tmp/fmnist_28_eps1.0_pe_train_memsafe128.md \
    --json-output /tmp/fmnist_28_eps1.0_pe_train_memsafe128.json \
    --poll-seconds 180 \
    --codex-thread-id '"${thread_id}"' \
    --codex-cwd /Users/tianhao/Documents/GitHub/dp-pe-multimodal \
    </dev/null >/tmp/remote-run-watch.log 2>&1'
```

Background-launcher guardrails:

- prefer one-shot launchers such as `launchctl submit`, not `KeepAlive`
  respawn loops, for a single watched run
- use exactly one watcher per remote log / run label / Codex thread
- reuse one `launchctl` label per watched run and remove any stale job with the
  same label before submitting a new watcher
- once a watcher has resumed Codex for a terminal run, let it exit; do not
  immediately resubmit it against the same already-finished log
- if you need to watch a new run, start a new watcher for the new run instead
  of recycling the old one against the old terminal log

Example for a `portal -> groupml02` benchmark run that finishes by writing
`matrix_manifest.json`:

```bash
thread_id="${CODEX_THREAD_ID:?missing CODEX_THREAD_ID}"
cp /Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/uva-server-dev/scripts/watch_remote_run_and_resume_codex.py /tmp/watch_remote_run_and_resume_codex.py
chmod +x /tmp/watch_remote_run_and_resume_codex.py

launchctl remove com.tianhao.yasl-watch.lg4 >/dev/null 2>&1 || true
launchctl submit -l com.tianhao.yasl-watch.lg4 -- \
  /bin/zsh -lc '/usr/bin/python3 /tmp/watch_remote_run_and_resume_codex.py \
    --host portal \
    --remote-command-prefix "ssh -o BatchMode=yes groupml02.cs.virginia.edu" \
    --log /u/nkp2mr/youth-ai-safety-lab/logs/phase1_full_llama-guard-4_groupml02.log \
    --process-pattern phase1_full_llama-guard-4_groupml02 \
    --label phase1_full_llama-guard-4_groupml02 \
    --output /tmp/phase1_full_llama-guard-4_groupml02.watch.md \
    --json-output /tmp/phase1_full_llama-guard-4_groupml02.watch.json \
    --terminal-file /u/nkp2mr/youth-ai-safety-lab/runs/groupml02/phase1_full_llama-guard-4_groupml02/matrix_manifest.json \
    --poll-seconds 180 \
    --log-tail-lines 120 \
    --codex-thread-id '"${thread_id}"' \
    --codex-cwd /Users/tianhao/Documents/GitHub/youth-ai-safety-lab \
    --resume-instruction "Inspect the completed groupml02 run, pull the artifacts if needed, update the notes/tables, and continue the next experiment step." \
    </dev/null >/tmp/phase1_full_llama-guard-4_groupml02.watch.launch.log 2>&1'
```

The minimal success criterion is:

- the watcher writes a summary
- the watcher resumes the current Codex thread with a self-message that
  includes the run label, terminal reason, summary path, remote log path, and
  latest metrics when `--codex-thread-id` is supplied
- otherwise, the watcher emits a machine-readable terminal JSON event on stdout
  for the hook caller to consume
- the watcher only shows a desktop notification when explicitly asked to do so
  with `--notify-mode desktop`
- the workflow launches one watcher per run and therefore writes one
  `codex exec resume` back into the Codex thread for that run

## Rivanna / UVA Research Computing

Rivanna is the UVA Research Computing environment and uses Slurm. For this
account, `allocations` reports an active `dplab` allocation and `sbatch` is
available.

Useful commands:

```bash
ssh rivanna 'allocations'
ssh rivanna 'allocations -a dplab'
ssh rivanna 'sbatch --version'
ssh rivanna 'sinfo -o "%P %a %l %D %G"'
ssh rivanna 'squeue -u $USER'
```

Validated on `2026-03-22` for this account:

- login-node default `python3` is `/home/nkp2mr/miniconda3/bin/python3`
  and reports `Python 3.9.12`
- system `Python 3.11` is available at `/usr/bin/python3.11`
- `sbatch` is available at `/opt/slurm/current/bin/sbatch`

This matters for repos that require `python>=3.10`. On Rivanna, do not assume
`python3` from `PATH` is new enough just because Slurm is available. Probe both
interpreters explicitly:

```bash
ssh rivanna 'python3 --version; which python3; /usr/bin/python3.11 --version'
```

For repo bootstrap and `sbatch` scripts that create a `venv`, prefer an
explicit interpreter such as `/usr/bin/python3.11` instead of bare `python3`:

```bash
ssh rivanna 'cd /path/to/repo && /usr/bin/python3.11 -m venv .venv'
ssh rivanna 'cd /path/to/repo && sbatch --export=ALL,PYTHON_BIN=/usr/bin/python3.11 path/to/job.slurm'
```

Use the `dplab` allocation when submitting jobs if the default account is not
already set:

```bash
ssh rivanna 'sbatch -A dplab path/to/job.slurm'
ssh rivanna 'srun -A dplab --pty bash'
ssh rivanna 'scancel <jobid>'
```

Prefer scheduler-managed execution on Rivanna rather than backgrounding long
GPU workloads in an interactive shell.

## Sync Pattern

For this project, local editing and server execution should use this pattern:

1. Pull code from `dplab01:/p/fzv6enresearch/gap` into the local integration
   repo.
2. Make code or documentation changes locally.
3. Sync code changes back to the server repo without copying datasets or results.
4. Run heavy jobs on DPLab or Rivanna.

For the unified repo, the standard sync entry point is:

```bash
cd /Users/tianhao/Documents/GitHub/dp-pe-multimodal
bash scripts/sync_repo_to_dplab.sh dplab01 /u/nkp2mr/dp-pe-multimodal
```

The sync script uses `rsync --delete`, so it must protect remote runtime
artifacts that live inside the repo tree. In particular, keep patterns such as
`*.launch.log` and `docs/run_watch/` excluded from sync; otherwise a local sync
can silently unlink active server-side log files while the jobs are still
running, which breaks watcher-based monitoring and Codex resume hooks.

## Environment Maintenance

Prefer direct remote commands over repo cleanup scripts.

## Shared Preferred Environments And Models

Validated on `2026-03-22` for the shared DPLab filesystem under `/u/nkp2mr`.
Treat this section as the current default stack for shared UVA work unless a
project has a documented reason to pin something older.

Preferred shared user-space serving environment:

- `vLLM`: `/u/nkp2mr/.venvs/vllm`
- validated version in that env:
  - `Python 3.13.12`
  - `vLLM 0.18.0`
- `~/.local/bin/vllm` should point to `/u/nkp2mr/.venvs/vllm/bin/vllm`
- prefer this shared `vllm` env for OpenAI-compatible serving instead of
  creating new ad hoc `vllm-py310*` environments

Practical rule:

- repo-local `.venv` is still fine for project code, tests, and lightweight
  monitor logic
- for shared model serving, prefer one maintained shared `vllm` env plus repo
  `.venv`s, not many duplicated serving envs

Preferred shared model defaults currently worth reusing from the shared Hugging
Face cache:

- reasoning / target models:
  - `openai/gpt-oss-20b`
  - `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B`
- judge / monitor helper:
  - `Qwen/Qwen2.5-7B-Instruct`
- guardrails:
  - `Qwen/Qwen3Guard-Gen-8B`
  - `Qwen/Qwen3Guard-Gen-4B`
  - `RedHatAI/Llama-Guard-4-12B`
  - `nvidia/Llama-3.1-Nemotron-Safety-Guard-8B-v3`
  - `nvidia/Nemotron-3-Content-Safety`
  - `ibm-granite/granite-guardian-3.3-8b`
- embeddings / retrieval:
  - `Qwen/Qwen3-Embedding-0.6B`

Current model-line guidance:

- prefer `nvidia/Llama-3.1-Nemotron-Safety-Guard-8B-v3` over older NVIDIA text
  safety lines such as `nvidia/llama-3.1-nemoguard-8b-content-safety`
- prefer `nvidia/Nemotron-3-Content-Safety` when a shared multimodal safety
  baseline is needed
- keep `Qwen/Qwen3Guard-Gen-4B` only when the smaller guard model is
  intentionally needed; otherwise prefer `Qwen/Qwen3Guard-Gen-8B`
- keep `Qwen/Qwen3-Embedding-0.6B` as the shared lightweight embedding default

Older or non-default lines that should not be reintroduced casually:

- `nvidia/Aegis-AI-Content-Safety-LlamaGuard-Defensive-1.0`
- `nvidia/llama-3.1-nemoguard-8b-content-safety` as a default choice
- tiny generic models such as `Qwen/Qwen3-0.6B`, `Qwen/Qwen2.5-0.5B-Instruct`,
  and `gpt2`, unless a project explicitly needs them

Before downloading a model again, check the shared cache first:

```bash
ssh dplab04 'find /u/nkp2mr/.cache/huggingface/hub -maxdepth 1 -mindepth 1 -type d -name "models--*" | sort'
```

For current DPLab / `groupml02` work, prefer the newer Hugging Face CLI entry
point `hf`, not `huggingface-cli`. On `groupml02`, `huggingface-cli` may be
missing even when the Hub client is installed, while `hf` is available at
`/u/nkp2mr/.local/bin/hf`.

Reliable background download pattern:

```bash
ssh portal 'ssh groupml02 "nohup env HF_HOME=/u/nkp2mr/.cache/huggingface \
  /u/nkp2mr/.local/bin/hf download Qwen/Qwen3.5-35B-A3B \
  > /u/nkp2mr/logs/qwen35_download.log 2>&1 < /dev/null &"'
ssh portal 'ssh groupml02 "tail -n 40 /u/nkp2mr/logs/qwen35_download.log"'
```

Avoid using shell constructs that rely on local `$!` expansion through nested
SSH unless you have verified the quoting. In practice, a plain `nohup ... &`
plus log-tail check is more reliable than trying to capture the PID across
jump-host quoting layers.

## Large Model Deployment Heuristics

Validated on `2026-03-22` for `groupml02`-class hardware (`8 x RTX A6000 48GB`)
and this user's current benchmark workflow.

Treat these as practical engineering heuristics, not vendor guarantees:

- default local-screening assumption:
  - prefer `4-bit` style deployment first for modern open models on
    `groupml02`, unless the experiment specifically requires a higher-precision
    reference run
- treat `4-bit` as an engineering default for feasibility, not as proof that a
  model is cheap enough to deploy casually
- for paper-facing comparisons, write the quantization choice down explicitly
  and avoid silently mixing quantized and non-quantized baselines

- worth local download / deployment first:
  - `Qwen/Qwen3.5-35B-A3B`
- also worth local deployment on `groupml02`, especially under `4-bit`:
  - `meta-llama/Llama-3.1-8B-Instruct`
  - `meta-llama/Llama-3.3-70B-Instruct`
  - `nvidia/Llama-3.1-Nemotron-70B-Instruct-HF`
  - `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B`
  - `openai/gpt-oss-20b`
- keep as historical or defense-matched anchors:
  - `Qwen/Qwen2.5-*`
  - released checkpoints such as `RealGuardrails` or `SecAlign` that still sit
    on older bases
- prefer API instead of local deployment:
  - `MiniMax-M2.7`
  - `DeepSeek-V3.2` (`deepseek-chat`, `deepseek-reasoner`)
  - `Kimi-K2` / `K2.5`
  - `GLM-5`
- do not prioritize local deployment on `groupml02` even under `4-bit`:
  - `deepseek-ai/DeepSeek-V3`
  - `moonshotai/Kimi-K2-*`
  - `zai-org/GLM-5`
  - `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-*`

Practical fit notes:

- `Qwen3.5-35B-A3B` is the main current open-weight candidate worth testing
  locally on `groupml02`
- for day-to-day benchmark screening on this hardware tier, a good local roster
  is:
  - `Qwen/Qwen3.5-35B-A3B`
  - `meta-llama/Llama-3.1-8B-Instruct`
  - `meta-llama/Llama-3.3-70B-Instruct`
  - `nvidia/Llama-3.1-Nemotron-70B-Instruct-HF`
  - `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B`
  - `openai/gpt-oss-20b`
- for short-context benchmark work such as `8K-32K`, expect a realistic first
  attempt to use roughly `2-4` A6000 `48GB` GPUs
- for the long-context / official-style serving setup, expect something much
  closer to an `8 GPU` job
- `Llama-3.1-8B-Instruct` is an easy local baseline on a single `48GB` GPU
- `Llama-3.3-70B-Instruct` and `Llama-3.1-Nemotron-70B-Instruct-HF` are both
  realistic high-value local baselines when `4-bit` is acceptable; treat them
  as roughly `2-4 x 48GB` class jobs, depending on context length and serving
  stack
- among NVIDIA Nemotron lines, the best local first try is
  `nvidia/Llama-3.1-Nemotron-70B-Instruct-HF`
- NVIDIA safety lines such as
  `nvidia/Llama-3.1-Nemotron-Safety-Guard-8B-v3` and
  `nvidia/Nemotron-3-Content-Safety` are worth keeping as guard / classifier
  baselines, but they are not substitutes for a generative assistant model
- `nvidia/Llama-3_3-Nemotron-Super-49B-v1_5-FP8` is interesting but should be
  treated as a second-wave experiment rather than the first local baseline,
  because its deployment path is more specialized
- `DeepSeek-V3` / `V3.2`, `Kimi-K2`, and `GLM-5` are all large enough that
  they should be treated as multi-node or very high-end multi-GPU deployments,
  not routine `groupml02` local-serving targets
- on this hardware tier, do not casually plan local deployment for those lines;
  route them through official APIs unless there is a strong experimental reason
  to pay the local systems cost

Current rough lower-bound planning heuristics:

- `Qwen3.5-35B-A3B`:
  - local benchmark serving: start thinking in terms of `2-4 x 48GB`
  - official-style long-context serving: closer to `8 x 48GB`
- `Llama-3.1-8B-Instruct`:
  - straightforward `1 x 48GB` local baseline
- `Llama-3.3-70B-Instruct`:
  - realistic `2-4 x 48GB` local target under `4-bit`
- `Llama-3.1-Nemotron-70B-Instruct-HF`:
  - realistic `2-4 x 48GB` local target under `4-bit`
- `DeepSeek-V3` / `V3.2`:
  - do not plan around `groupml02`; think `16+ x 48GB` or equivalent higher-end
    cluster resources
- `Kimi-K2` / `K2.5`:
  - do not plan around `groupml02`; think `24+ x 48GB` class deployments if you
    are not using an API
- `GLM-5`:
  - do not plan around `groupml02`; think `16+ x 48GB` or use an API / hosted
    provider
- `NVIDIA-Nemotron-3-Super-120B-A12B-*`:
  - do not plan around `groupml02`; treat it as an `8 x 80GB`-class or better
    deployment and prefer other local baselines first

Decision rule:

- if the goal is to add a modern local baseline to a paper or benchmark,
  download and test `Qwen3.5-35B-A3B` first, then add `Llama-3.3-70B-Instruct`
  or `Llama-3.1-Nemotron-70B-Instruct-HF`
- if the goal is simply to compare against current frontier Chinese or hybrid
  models, integrate `MiniMax`, `DeepSeek`, `Kimi`, and `GLM` through their
  official APIs before attempting heavyweight local deployment
- if the goal is to compare a modern NVIDIA open instruct model locally,
  prefer `Llama-3.1-Nemotron-70B-Instruct-HF`; do not jump directly to the
  `120B` Nemotron line

## Model Freshness And Re-Check Rule

The model landscape in this workflow changes quickly. When the task involves
current model recommendations, "latest" baselines, or whether a model line is
worth downloading locally, do not trust stale memory.

Operational rule:

- re-check official sources before recommending a modern model lineup
- prefer official model cards, official API docs, and official release notes
- if a model question is even slightly time-sensitive, assume it may have
  changed since the last edit of this skill

Preferred source order for freshness checks:

- official Hugging Face model cards for open-weight models
- official provider API docs and release notes for hosted models
- official benchmark pages only as secondary evidence, not as the sole basis
  for a broad model-quality claim

In practice:

- re-check `Qwen`, `Meta-Llama`, `NVIDIA Nemotron`, `DeepSeek`, `MiniMax`,
  `Moonshot/Kimi`, and `GLM` against their official pages before finalizing a
  2026-era recommendation
- treat a prior local rule in this skill as a starting point, not a permanent
  truth, when the user explicitly asks about what is current

If cleaning shared models or environments:

- remember `/u/nkp2mr` is shared across DPLab nodes
- do not delete a shared model or env just because it looks idle on one host
- prefer updating this section when the shared default stack changes

Use the repo bootstrap scripts:

```bash
cd /u/nkp2mr/dp-pe-multimodal
bash scripts/bootstrap_image_venv.sh
bash scripts/bootstrap_text_venv.sh
bash scripts/bootstrap_text_eval_venv.sh
bash scripts/bootstrap_text_rl_venv.sh
```

The legacy project-specific conda envs that can be removed if explicitly
obsolete are:

- `/u/nkp2mr/anaconda3/envs/dpib-lite2`
- `/u/nkp2mr/anaconda3/envs/dplora`
- `/u/nkp2mr/anaconda3/envs/dp-transformers`
- `/u/nkp2mr/anaconda3/envs/rl_dp`

Delete them directly over SSH instead of keeping a repo script:

```bash
ssh dplab01 'rm -rf /u/nkp2mr/anaconda3/envs/dpib-lite2 /u/nkp2mr/anaconda3/envs/dplora /u/nkp2mr/anaconda3/envs/dp-transformers /u/nkp2mr/anaconda3/envs/rl_dp'
```

For long bootstrap or experiment startup, prefer `nohup` or `tmux` and watch
logs explicitly:

```bash
ssh dplab01 'cd /u/nkp2mr/dp-pe-multimodal && nohup bash scripts/bootstrap_text_venv.sh > bootstrap_text_venv.log 2>&1 < /dev/null &'
ssh dplab01 'tail -f /u/nkp2mr/dp-pe-multimodal/bootstrap_text_venv.log'
```

## Cautions

- The image repo on server is owned by another account, so some files may be
  unreadable through local `rsync`.
- Do not manually rewrite or prune `/bigtemp/fzv6en/gap_data/exp` unless the
  user explicitly asks.
- Use `tmux` or scheduler scripts for long jobs.
