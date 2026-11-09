# fastbot_bringup tests

`test_camera_config.py` contains six pytest cases for the reviewed camera boot
configuration editor: preservation, idempotence, missing settings, and rejection
of duplicate or conflicting settings. Tests operate on strings and do not change
the host boot configuration or reboot.

```bash
cd ~/ros2_ws
colcon test --packages-select fastbot_bringup
colcon test-result --verbose
```

CTest wrapping is not an additional independent behavior case. Preview-launch,
sensor-stream, and bounded keyboard checks live in `tools/`; they are separate
from this pytest suite. Opening real devices or driving motors requires the
corresponding current authorization. See the
[integration guide](../../docs/INTEGRATION.md) for actual runtime evidence.

Tooling scaffolds and passing configuration tests do not certify hardware,
official grading, generated documentation, or learner completion.
