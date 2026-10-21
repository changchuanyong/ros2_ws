# ros2_rm_robot: RM75-6FB-V dual arm and dual L20 simulation

This workspace is reduced to the RM75-6FB-V robot model and the MuJoCo dual-arm simulation with two L20 hands. The supported development environment is Ubuntu 22.04 with ROS 2 Humble.

The current target path is:

- two RM75-6FB-V arms in MuJoCo;
- MoveIt 2 and RViz planning for the `left_arm`, `right_arm`, and `dual_arms` groups;
- two L20 hand controllers in MuJoCo, driven by the dual hand command bridge.

The intended real-hardware configuration also has two arms and two hands. The repository includes the L20-11 RS485 protocol and ROS node in `rm_l20_driver`; an external LinkerHand SDK is no longer required. The L20 bridge described below is for the MuJoCo controllers. The real-arm entry starts separate left and right RM75 drivers and control nodes, a dual-arm joint-state bridge, and dual-arm MoveIt/RViz. The piano hardware entry also starts both L20 drivers.

## Packages

| Package | Purpose |
| --- | --- |
| `rm_description` | RM75-6FB-V URDF, meshes, and dual-arm description |
| `rm_75_config` | RM75-6FB-V MoveIt configuration and dual-arm SRDF |
| `rm_mujoco` | Dual RM75 + dual L20 MuJoCo model, controllers, and launch file |
| `rm_driver` | RealMan arm driver |
| `rm_l20_driver` | L20-11 RS485 protocol and hardware ROS driver |
| `rm_control` | MoveIt to driver trajectory forwarding |
| `rm_bringup` | RM75-6FB-V real-arm launch entry |
| `rm_moveit2` | MoveIt example node |
| `rm_ros_interfaces` | ROS messages and services |
| `rm_piano_player` | MIDI playback, dual-arm planning, dual L20 commands, and MIDI feedback |

Legacy examples and Gazebo sources that are marked with `COLCON_IGNORE` are not part of the current build path.

## Build

Use a fresh terminal on Ubuntu 22.04 with ROS 2 Humble. Only source Humble before building; an external LinkerHand SDK overlay is not needed:

```bash
cd ~/ros2_ws
source /opt/ros/humble/setup.bash
python3 -m pip install --user -r src/ros2_rm_robot/requirements-hardware.txt
colcon build --symlink-install
source install/setup.bash
```

The MuJoCo launch requires the external `mujoco_ros2_control` package, MoveIt 2, RViz 2, `xacro`, and the standard ROS 2 controller packages.

`requirements-hardware.txt` records version constraints for `pymodbus`, `pyserial`, `numpy`, `mido`, and `python-rtmidi`. The integrated L20 protocol still requires these basic communication and MIDI libraries. ROS package dependencies are declared in each package's `package.xml`.

## Launch the dual-arm MuJoCo simulation

The default scene places two upright RM75 arms on a wooden table facing an 88-key
digital piano, with both L20 hands hovering downward. The approximate dimensions,
initial joint positions, and cameras are configured in `rm_mujoco/config/piano_scene.yaml`.
See [the scene guide](rm_mujoco/README.md) for layout overrides and offscreen previews.

```bash
source ~/ros2_ws/install/setup.bash
ros2 launch rm_mujoco rm_75_dual_l20_mujoco.launch.py
```

Useful launch arguments are:

```bash
ros2 launch rm_mujoco rm_75_dual_l20_mujoco.launch.py headless:=true
ros2 launch rm_mujoco rm_75_dual_l20_mujoco.launch.py use_rviz:=false
```

The launch file starts the robot state publisher, MuJoCo ROS 2 control, both arm controllers, both L20 controllers, MoveIt 2, and RViz. The MoveIt SRDF provides the `left_arm`, `right_arm`, and `dual_arms` planning groups. The L20 joints are simulated and controlled by their trajectory controllers; they are not included in the current MoveIt SRDF groups.

## Send L20 hand commands

`l20_dual_command_bridge.py` subscribes to:

- `/cb_left_hand_control_cmd`
- `/cb_right_hand_control_cmd`

Both topics use `sensor_msgs/msg/JointState`. Each message must contain at least 20 values in `position`, using the hand command range `0` to `255`. The bridge converts the values into L20 joint trajectories and publishes them to:

- `/left_l20_hand_controller/joint_trajectory`
- `/right_l20_hand_controller/joint_trajectory`

The MuJoCo model contains the two L20 hands. The arm-only dual URDF used by MoveIt does not yet contain L20 links, so RViz plans and displays the two arms while the hands are controlled through the bridge.

## RoboPianist-style MIDI playback

The first hardware milestone is a fixed-song loop using an 88-key MIDI digital piano. Notes `21–59` are assigned to the left hand and `60–108` to the right hand. The two RM75 arms use the `left_arm` and `right_arm` MoveIt groups, while each L20 hand receives 20-value commands. The first phase allows one active note per hand and rejects same-hand chords before execution.

MuJoCo playback entry:

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_mujoco.launch.py \
  midi_file:=/absolute/path/song.mid headless:=true use_rviz:=false execute:=false
```

The real entry defaults to left arm `192.168.1.18`, right arm `192.168.1.19`, and hand model `L20-11`. Hand serial ports are discovered by the exact UIDs in `rm_l20_driver/config/hand_identity.yaml`:

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_real.launch.py \
  midi_file:=/absolute/path/song.mid execute:=false
```

This entry uses the in-repository `rm_l20_driver/l20_dual_rs485_driver`. Both hand identities and first state reads must pass before the arms start; a ten-second readiness timeout or hand-process exit shuts down the launch. `execute=false` only disables player actions; the launch still connects to hand serial ports and, after readiness, to the arms. To inspect arguments without starting hardware nodes, use `ros2 launch rm_piano_player rm_75_dual_l20_piano_real.launch.py --show-args`.

Set `midi_input:=<port-name>` and `feedback_enabled:=true` to check missing notes, unexpected notes, and timing timeouts. `tempo_scale` is a time multiplier, so larger values slow playback. This is a RoboPianist-style hardware behavior reproduction; the original Shadow Hand RL policy and key-contact reward are outside the first phase.

## Launch the dual-arm hardware entry

The default mapping is left arm `192.168.1.18` and right arm `192.168.1.19`. Override these values at launch time when the hardware uses different addresses:

```bash
source ~/ros2_ws/install/setup.bash
ros2 launch rm_bringup rm_75_6fb_v_bringup.launch.py \
  left_arm_ip:=192.168.1.18 right_arm_ip:=192.168.1.19
```

The default UDP feedback ports are `8089` for the left arm and `8090` for the right arm, with `192.168.1.10` as the default host address. Override them when the controller configuration uses different values:

```bash
ros2 launch rm_bringup rm_75_6fb_v_bringup.launch.py \
  left_arm_ip:=192.168.1.18 right_arm_ip:=192.168.1.19 \
  left_udp_ip:=<host-ip> right_udp_ip:=<host-ip> \
  left_udp_port:=<left-udp-port> right_udp_port:=<right-udp-port>
```

The launch isolates the two driver/control stacks in the `left_arm` and `right_arm` namespaces and merges their joint states to `/joint_states` for the dual-arm URDF, MoveIt, and RViz. This arm-only entry does not start the hands. Use the piano hardware entry above to bind the in-repository L20 RS485 drivers by exact UID, independently of `ttyUSB` numbering.

Before using hardware, build on Ubuntu/ROS 2 Humble and verify both arm IP addresses, UDP feedback addresses, and ports. The original nine packages passed a Jetson build and basic dependency checks; physical motion has not been tested. Validation of this L20 driver integration will be recorded separately. Existing simulation and test evidence is documented in `rm_piano_player/README_CN.md`.

Hardware acceptance order: test `/dev/ttyUSB0`, then `/dev/ttyUSB1`, inspect both hand state topics, run single-key arm motions, run a slow scale, and only then enable MIDI feedback for a fixed song. Keep the emergency stop accessible and clear the robot workspace before enabling execution.

## Validation

The Windows checkout cannot run ROS 2 or `colcon`. Before deploying on Ubuntu, run:

```bash
colcon test
colcon test-result --verbose
```

Then start the MuJoCo launch with RViz disabled first, verify both arm controllers and both hand controllers, and enable RViz after the simulation is stable.
