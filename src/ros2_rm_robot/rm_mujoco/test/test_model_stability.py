"""Check that idle and moving L20 joints do not reset the simulation clock."""

import math
from pathlib import Path

import pytest

mujoco = pytest.importorskip("mujoco")
np = pytest.importorskip("numpy")


def test_dual_l20_model_remains_stable():
    model_path = Path(__file__).resolve().parents[1] / "models" / "rm_75_6fb_v_dual_l20.xml"
    model = mujoco.MjModel.from_xml_path(str(model_path))
    data = mujoco.MjData(model)
    targets = np.zeros(model.nu)
    for index, joint_id in enumerate(model.actuator_trnid[:, 0]):
        name = model.joint(joint_id).name
        if name == "left_joint1":
            targets[index] = 0.1
        elif name == "right_joint1":
            targets[index] = -0.1
        elif any(finger in name for finger in ("thumb", "index", "middle", "ring", "little")):
            targets[index] = model.actuator_ctrlrange[index, 1]

    # One second at rest, then two smooth open/close cycles. The original model
    # diverged at 0.008 s and MuJoCo reset time, blocking controller activation.
    for _ in range(round(5.0 / model.opt.timestep)):
        phase = max(0.0, data.time - 1.0)
        data.ctrl[:] = targets * 0.5 * (1.0 - math.cos(math.pi * phase))
        previous_time = data.time
        mujoco.mj_step(model, data)
        assert data.time > previous_time, "MuJoCo reset the simulation clock"
        assert np.isfinite(data.qpos).all()
        assert np.isfinite(data.qvel).all()
        assert not data.warning.number.any(), "MuJoCo reported unstable dynamics"

    assert data.time == pytest.approx(5.0)
