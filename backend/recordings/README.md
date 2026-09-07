# NeuroGuide XR — Recordings Folder

## Quick Start (3 commands)

### 1. Record with OpenAdapt
```
openadapt capture start --name word-bold
```
> Perform the workflow in Word (e.g., click Bold button)
> Press Ctrl+C to stop recording

OpenAdapt saves captures to: `C:\Users\<YourName>\word-bold\recording.db`

### 2. Extract + Ingest (one command from backend/)
```
python extract_capture.py "word-bold" --title "Make text bold in Word" --app "WINWORD.EXE"
```
For different apps:
```
python extract_capture.py "word-toc"   --title "Insert table of contents"  --app "WINWORD.EXE"
python extract_capture.py "excel-pivot" --title "Create a pivot table"      --app "EXCEL.EXE"
```

### 3. Verify live
Start the backend and ask in the AR app: "how to make text bold"
You should see in the logs:
```
[Copilot] Matched lesson_id=X score=0.68
[Copilot] Serving lesson_id=X from DB (N steps)
```

---

## Folder Structure

```
backend/
  recordings/               <- JSON exports land here (auto-created by extract_capture.py)
    word-bold.json
    word-toc.json
    excel-pivot.json

  templates/                <- Auto-extracted 96x96 template PNGs (do not edit)
    winword/
      bold_button.png
      home_tab.png
      ...
    excel/
      insert_tab.png
      pivottable.png
      ...
```

---

## How OpenAdapt Stores Captures

OpenAdapt saves each capture as a **folder** under your home directory:
```
C:\Users\PC\word-bold\
  recording.db           <- SQLite with action events
  oa_recording-*.mp4     <- Video recording (for screenshot extraction)
  profiling.json
```

The folder name = the `--name` you used with `openadapt capture start`.

---

## Naming Convention

| --name used          | --title to use                          | --app            |
|----------------------|-----------------------------------------|------------------|
| word-bold            | Make text bold in Word                  | WINWORD.EXE      |
| word-toc             | Insert a table of contents in Word      | WINWORD.EXE      |
| word-insert-shape    | Insert a shape in Word                  | WINWORD.EXE      |
| excel-pivot          | Create a pivot table in Excel           | EXCEL.EXE        |
| excel-chart          | Insert a chart in Excel                 | EXCEL.EXE        |
| powerpoint-slide     | Add a new slide in PowerPoint           | POWERPNT.EXE     |

---

## Troubleshooting

**"Could not find capture 'word-bold'"**
  - Check exact folder name: the capture is under `C:\Users\PC\`
  - If the folder name differs from --name, pass the exact name:
    ```
    python extract_capture.py "Making text bold in word" --title "..." --app "..."
    ```
  - Or use --capture-dir to give the exact path:
    ```
    python extract_capture.py dummy --capture-dir "C:\Users\PC\Making text bold in word" --title "..."
    ```

**"No steps extracted"**
  - The recording may have had no meaningful click events (only mouse moves).
  - Re-record and make sure to actually click buttons (not just move the mouse).

**"0 templates saved"**
  - The MP4 video may be missing or corrupted.
  - Re-record with: `openadapt capture start --name word-bold --video`
