# Native DLL Migration Status

## Current Slice

This folder contains the first native Windows DLL migration slice for the project.

The current DLL is intentionally passive:

- Exports a normal host-loaded plugin API.
- Uses embedded config defaults instead of `config.ini`.
- Contains native C++ ports of the movement controller and output scheduler.
- Contains native movement tests for the migrated controller and scheduler.
- Contains a custom native vision foundation with no OpenCV runtime dependency.
- Does not load Python.
- Does not require `.py`, `.pyd`, `.ini`, virtualenv, OpenCV DLLs, or other runtime files.
- Does not change host UI behavior.
- Does not implement stealth, evasion, injection, rootkit behavior, or hidden process behavior.
- Does not emit mouse/input events yet.
- Does not capture the screen yet.

Built release artifact:

```text
native_plugin/build/Release/UnibotPlugin.dll
```

Verified exports:

```text
Initialize
Run
Tick
GetStatus
Shutdown
```

Verified runtime dependency:

```text
KERNEL32.dll
```

Verified native tests:

```text
UnibotMovementTests: ok
UnibotVisionTests: ok
```

## Ported So Far

| Python Source | Native Destination | Status |
|---|---|---|
| `config.ini` | `include/Config.h`, `src/Config.cpp` | INLINE INTO DLL |
| `src/cheats.py` | `src/AimController.*` | PORT TO C++ |
| `src/aim_output.py` | `src/OutputScheduler.*` | PORT TO C++ |
| `src/unibot.py` lifecycle shell | `src/Engine.*`, `src/PluginApi.cpp` | PARTIAL PORT |
| Movement stress coverage | `tests/MovementTests.cpp` | PORT TO C++ |
| `cv2.cvtColor`, `cv2.inRange` subset | `src/ImageProcessing.*` | PORT TO C++ |
| `cv2.morphologyEx`, `cv2.dilate`, `cv2.threshold` subset | `src/ImageProcessing.*` | PORT TO C++ |
| `cv2.findContours` simple replacement | `ConnectedComponentRects` | PORT TO C++ |
| Vision foundation coverage | `tests/VisionTests.cpp` | PORT TO C++ |

## Not Ported Yet

| Python Source | Planned Native Destination | Status |
|---|---|---|
| `src/screen.py` capture | `ScreenCaptureDxgi.*` | PENDING |
| `src/screen.py` higher-level target selection | `TargetDetector.*` | PENDING |
| `src/screen.py` target selection | `TargetDetector.*` | PENDING |
| `src/mouse/microcontroller_serial_mouse.py` | `SerialOutput.*` | PENDING |
| `src/utils.py` key handling | `Win32KeyState.*` | PENDING |
| Debug window / overlay | None by default | REMOVE |
| Interception backend | None | REMOVE |

## Build

```powershell
cmake -S native_plugin -B native_plugin\build -G "Visual Studio 17 2022" -A x64
cmake --build native_plugin\build --config Release
```

## Next Implementation Order

1. Port the simple target path from `screen.py`:
   - `visible_mask_rect`
   - `simple_target_point`
   - `head_outline_midpoint`
   - `choose_simple_candidate`
   - `predict_simple_lock_target`
2. Add DXGI Desktop Duplication capture.
3. Add optional serial output through Win32 COM only after host policy confirms active output is allowed.

## Single-DLL Constraint Notes

The release DLL is built with the static MSVC runtime setting. Do not add dynamic third-party DLL dependencies unless they are statically linked into the plugin and license-compatible.

Before shipping, verify dependencies with:

```powershell
dumpbin /dependents native_plugin\build\Release\UnibotPlugin.dll
```
