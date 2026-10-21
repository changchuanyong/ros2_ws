"""Check that idle and moving L20 joints do not reset the simulation clock."""

import math
from pathlib import Path
import sys

import pytest

mujoco = pytest.importorskip("mujoco")
np = pytest.importorskip("numpy")

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

from rm_mujoco.scene import build_model, load_layout  # noqa: E402


@pytest.fixture
def piano_model(tmp_path):
    layout = load_layout(PACKAGE / "config" / "piano_scene.yaml")
    model_path = build_model(
        PACKAGE / "models" / "rm_75_6fb_v_dual_l20.xml", layout, tmp_path)
    return mujoco.MjModel.from_xml_path(str(model_path)), layout


def test_ready_hands_clear_the_keyboard(piano_model):
    model, layout = piano_model
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key("piano_ready").id)
    mujoco.mj_forward(model, data)
    highest_key = layout["piano_frame"]["position"][2] + layout["keyboard"]["black_height"]
    for side in ("left", "right"):
        for finger in ("thumb", "index", "middle", "ring", "little"):
            mesh_name = f"l20_{finger}_link{5 if finger == 'thumb' else 4}"
            mesh_id = model.mesh(mesh_name).id
            tips = [index for index in range(model.ngeom)
                    if model.geom_type[index] == mujoco.mjtGeom.mjGEOM_MESH
                    and model.geom_dataid[index] == mesh_id
                    and model.body(model.geom_bodyid[index]).name.startswith(side + "_")]
            assert len(tips) == 1
            geom_id = tips[0]
            start = model.mesh_vertadr[mesh_id]
            vertices = model.mesh_vert[start:start + model.mesh_vertnum[mesh_id]]
            rotation = data.geom_xmat[geom_id].reshape(3, 3)
            world_vertices = vertices @ rotation.T + data.geom_xpos[geom_id]
            assert world_vertices[:, 2].min() > highest_key + 0.005, (side, finger)
            if finger != "thumb":
                # An open finger must extend down toward the keys, not upward.
                root_height = data.body(f"{side}_{finger}_link0").xpos[2]
                assert world_vertices[:, 2].mean() < root_height - 0.03


def test_dual_l20_model_remains_stable(piano_model):
    model, _ = piano_model
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key("piano_ready").id)
    ready = data.ctrl.copy()
    targets = ready.copy()
    for index, joint_id in enumerate(model.actuator_trnid[:, 0]):
        name = model.joint(joint_id).name
        if name == "left_joint1":
            targets[index] += 0.1
        elif name == "right_joint1":
            targets[index] -= 0.1
        elif any(finger in name for finger in ("thumb", "index", "middle", "ring", "little")):
            targets[index] = model.actuator_ctrlrange[index, 1]

    # One second at rest, then two smooth open/close cycles. The original model
    # diverged at 0.008 s and MuJoCo reset time, blocking controller activation.
    for _ in range(round(5.0 / model.opt.timestep)):
        phase = max(0.0, data.time - 1.0)
        data.ctrl[:] = ready + (targets - ready) * 0.5 * (1.0 - math.cos(math.pi * phase))
        previous_time = data.time
        mujoco.mj_step(model, data)
        assert data.time > previous_time, "MuJoCo reset the simulation clock"
        assert np.isfinite(data.qpos).all()
        assert np.isfinite(data.qvel).all()
        assert not data.warning.number.any(), "MuJoCo reported unstable dynamics"

    assert data.time == pytest.approx(5.0)


def test_ready_position_servos_hold_against_gravity(piano_model):
    model, layout = piano_model
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key("piano_ready").id)
    for _ in range(round(2.0 / model.opt.timestep)):
        mujoco.mj_step(model, data)
    for name, target in layout["initial_positions"].items():
        position = data.qpos[model.joint(name).qposadr[0]]
        assert abs(position - target) < 0.01, name
