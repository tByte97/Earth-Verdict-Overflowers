# Regional NEX-GDDP-CMIP6 Download Runbook

Runbook for downloading a regional NEX-GDDP-CMIP6 ensemble on an unattended Linux server.
No API keys or credentials are required (public NASA NCCS THREDDS data).

## 1. Requirements

- Python 3.10+
- `numpy` and `scipy` (no other third-party packages needed)
- ~1 GB free disk space (each NetCDF-3 file is deleted immediately after monthly reduction; cached `.npy` files for 5 models × 2,790 tasks over Ukraine+Poland use ~75 MB total; final JSON is < 5 MB)
- Outbound HTTPS access to `ds.nccs.nasa.gov`

## 2. Setup

```bash
git clone <repo-url>
cd <repo-dir>
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install numpy scipy
```

## 3. Estimate Tasks & Runtime

Check task count and estimated runtime before launching:

```bash
.venv/bin/python tools/fetch_cmip6_region.py --name europe-east --bbox 44 20 53 41 --estimate
```

Output for the 5 default models (`ACCESS-CM2`, `GFDL-ESM4`, `IPSL-CM6A-LR`, `MIROC6`, `MPI-ESM1-2-HR`) with `--workers 4`:

```
Estimate for region='europe-east' bbox=[44.0, 20.0, 53.0, 41.0] models=5 (ACCESS-CM2, GFDL-ESM4, IPSL-CM6A-LR, MIROC6, MPI-ESM1-2-HR) workers=4:
  total tasks: 2790 (0 cached, 2790 remaining)
  full time (~27s/task / 4 workers): 5.2 h (5h 13m)
  remaining time: 5.2 h (5h 13m)
```

(Optional) Run a quick ~30-second smoke test first:

```bash
.venv/bin/python tools/fetch_cmip6_region.py --smoke
```

## 4. Launch Full Run (`europe-east`, Ukraine + Poland)

Using `nohup`:

```bash
nohup .venv/bin/python -u tools/fetch_cmip6_region.py \
  --name europe-east \
  --bbox 44 20 53 41 \
  --workers 4 \
  > europe-east.log 2>&1 &
```

Or inside `tmux`:

```bash
tmux new -s cmip6
.venv/bin/python -u tools/fetch_cmip6_region.py --name europe-east --bbox 44 20 53 41 --workers 4 2>&1 | tee -a europe-east.log
# Detach with Ctrl-b d; reattach with: tmux attach -t cmip6
```

Optional time cap: pass `--max-hours 4.0` to stop cleanly after 4 hours.

## 5. Monitor Progress & Resume

Watch progress (printed every 25 tasks):

```bash
tail -f europe-east.log
ls data/cache/cmip6-region/europe-east/*.npy | wc -l
```

If the process is interrupted (`Ctrl-C`, `SIGTERM`, reboot, or `--max-hours`), **re-run the exact same command** to resume. Completed `.npy` files are skipped automatically:

```bash
.venv/bin/python -u tools/fetch_cmip6_region.py --name europe-east --bbox 44 20 53 41 --workers 4
```

You can also run `--estimate` at any time to see how many cached tasks remain.

## 6. Finalize Only

If all needed `.npy` files are already cached (at least 3 complete models out of 5) and you want to regenerate the JSON without making any network requests:

```bash
.venv/bin/python tools/fetch_cmip6_region.py --name europe-east --bbox 44 20 53 41 --finalize-only
```

## 7. File to Copy Back

Copy back this single file:

```text
data/cmip6/region-europe-east.json
```
