# AR Live Guidance Phase 1 Plan

## 1) Goal
Build a reliable live AR assistant that:
- Detects scene objects from mobile camera frames
- Generates structured step-by-step guidance
- Overlays world-anchored hints (card, arrow, highlight)
- Updates guidance as the scene changes

## 2) Scope (Phase 1)
### In scope
- Snapshot and follow-up guidance with stable JSON schema
- World-space step card anchored in AR scene
- Per-step visual hint type: highlight or arrow
- Simple step progression (manual next + optional auto-check)

### Out of scope (Phase 2+)
- Key-level precision (example: exact keyboard key N)
- Full 3D mesh-aware occlusion
- Advanced hand/object interaction verification

## 3) Backend Contract (Recommended)
Use this response schema for step guidance:

```json
{
  "type": "step_guidance",
  "recipe_title": "Tomato Omelette",
  "current_step": 1,
  "total_steps": 5,
  "steps": [
    {
      "step_id": "s1",
      "title": "Chop tomato",
      "instruction": "Cut tomato into small cubes.",
      "target_object": "tomato",
      "visual_hint": "arrow",
      "confidence": 0.82,
      "estimated_seconds": 60
    }
  ],
  "active_hint": {
    "visual_type": "arrow",
    "target_object": "tomato",
    "location_3d": [0.1, 0.0, 1.2]
  }
}
```

Notes:
- Keep instructions short (single sentence)
- Always include confidence
- Keep location_3d as fallback anchor even if exact object pose is unknown

## 4) Unity Runtime Components (Recommended)
Create these runtime systems:
- GuidanceStateMachine: idle, scanned, planning, step_active, step_done, replan
- GuidanceOverlayManager: spawns and updates world-space card and hint prefabs
- AnchorResolver: chooses AR anchor from plane + camera ray + target object
- HintRenderer: arrow/highlight visuals with smoothing
- StepProgressController: next, previous, complete, replan

## 5) Live Update Loop
1. Capture snapshot/frame
2. Backend returns scene + step guidance JSON
3. Resolve anchor position
4. Render/refresh card + hint
5. Re-run every N seconds or on major scene change
6. Replan if confidence drops below threshold

Recommended initial thresholds:
- Update interval: 1.5s to 2.5s
- Confidence floor for auto-highlight: 0.6
- Replan trigger: confidence < 0.45 for 2 consecutive updates

## 6) Realism Path
### Tomato use-case
- Detect tomato + board region
- Place card near board
- Draw animated knife trajectory arc (simple line or sprite animation)
- Mark completion on user action or visual change

### Keyboard key use-case
- Detect keyboard bounding box
- Estimate keyboard plane pose
- Map canonical keyboard layout to camera image with homography
- Project key N coordinate back to AR world
- Render focused glow/arrow over target key

## 7) Backup Strategy (Without Copying 9GB)
Do not copy cache/build folders each time.

### Copy only these Unity folders/files
- My project (1)/Assets/
- My project (1)/Packages/
- My project (1)/ProjectSettings/
- My project (1)/UserSettings/ (optional, editor preferences)

### Optional but useful
- My project (1)/My project (1).slnx
- My project (1)/*.csproj (usually auto-generated, optional)

### Do NOT back up these heavy folders
- My project (1)/Library/
- My project (1)/Temp/
- My project (1)/Logs/
- My project (1)/obj/
- My project (1)/Build/
- My project (1)/My project (1)_BurstDebugInformation_DoNotShip/
- My project (1)/dummy_BackUpThisFolder_ButDontShipItWithYourGame/
- My project (1)/dummy2_BackUpThisFolder_ButDontShipItWithYourGame/

## 8) Fast Backup Commands (Windows)
From workspace root, create compact zip backups.

### Unity minimal backup zip
```powershell
Compress-Archive -Path "My project (1)/Assets","My project (1)/Packages","My project (1)/ProjectSettings" -DestinationPath "backup_unity_minimal.zip" -Force
```

### Backend backup zip
```powershell
Compress-Archive -Path "backend" -DestinationPath "backup_backend.zip" -Force
```

If zip becomes large over time, use date-based filenames:

```powershell
$ts = Get-Date -Format "yyyyMMdd_HHmm"
Compress-Archive -Path "My project (1)/Assets","My project (1)/Packages","My project (1)/ProjectSettings" -DestinationPath ("backup_unity_" + $ts + ".zip") -Force
Compress-Archive -Path "backend" -DestinationPath ("backup_backend_" + $ts + ".zip") -Force
```

## 9) Best Practice (Strongly Recommended)
Use Git so backups are incremental instead of full copies:
- Track: Assets, Packages, ProjectSettings, backend
- Ignore: Library, Temp, Logs, build outputs
- Push to private GitHub/GitLab repo

This gives small incremental saves and easy rollback.

## 10) Immediate Next Build Step
Implement Step Guidance schema end-to-end:
1. Backend returns step_guidance JSON
2. Unity parses it
3. Unity renders one world-space step card + one arrow/highlight hint
4. Add next-step button and confidence display
