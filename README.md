# AutoLook

Local, offline content detection for **Net Monitor for Employees Pro**.
Reads Net Monitor's `reporting.db` + recording folder; detects NSFW, Korean text,
watched sites/apps, and custom keywords. No cloud services.

## Quick start

```bash
cd e:\Projects\AutoLook
pip install -r requirements.txt
python run_gui.py
# or:
python -m autolook.main --gui
```

### CLI

```bash
python -m autolook.main --status
python -m autolook.main --poll
python -m autolook.main --watch
python -m autolook.main --scan 2026-09-01 2026-09-04
```

### Build .exe

```bash
pip install pyinstaller
pyinstaller autolook.spec
```

## First-time setup in GUI

1. **Settings → Paths** — confirm:
   - Net Monitor DB: `C:\ProgramData\Net Monitor for Employees Pro\data\reporting.db`
   - Recording folder: `C:\ProgramData\Net Monitor for Employees Pro\data\recordings`
2. **Settings → Names** — click **Load hosts from Net Monitor**, fill Name for each IP/hostname
3. **Settings → Detection** — leave `Create LOW alerts` off to avoid telegram/youtube spam
4. Set date range → **Scan History**, or click **Start Watching**

## Detection notes

- NSFW: admin picks **NudeNet**, **OpenNSFW2** (Yahoo model via ONNX), or **both** in Settings.
  **Both** always runs NudeNet and can also alert from a high OpenNSFW score alone.
  **NSFW Sensitivity** is the minimum score to alert (more alerts = 20%, balanced = 40%, fewer = 60%).
- **History presets** (Settings → Detection): **CSV only**, **Fast history**, **Thorough**.
  For a month of recordings, use **Fast history** and scan a few days at a time.
- HTML export embeds screen previews and copies full images next to the report.
- Typing Korean (`KEYLOG` keystrokes) is skipped by default (Settings → Alerts); captions still checked.
- Video frames use **ffmpeg** from PATH or bundled **imageio-ffmpeg**.
- History/live media scans are limited (images first) so a PC without GPU stays usable.
  Tune limits in `config/default_config.json` / Settings.

## Noise controls

| Setting | Default | Effect |
|---------|---------|--------|
| Hide filters (dashboard) | NSFW / Korea / Name / From–To | Filter the alert list; all hits are kept (no dedupe) |
| Fast history preset | — | Images-first, sparse video for long periods |

## Project layout

```
autolook/
  main.py, config.py
  db/          Net Monitor reader + incidents.db
  detection/   text, domain/app, NSFW, OCR, scorer
  engine/      scanner, watcher, frame_extractor, worker
  gui/         main window, dashboard, settings, viewer, log
  utils/       hangul, thumbnails, host names, log handler
config/
  default_config.json
  user_config.json      # your overrides (saved from Settings)
```

## Review tips

- Multi-select rows → **Confirm Selected** / **Dismiss Selected**
- Double-click an incident → open thumbnail / source file / folder
- Status Log (right panel) can be hidden via toolbar
