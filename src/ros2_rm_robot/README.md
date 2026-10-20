# ros2_rm_robot: RM75-6FB-V dual arm and dual L20 simulation

This workspace is reduced to the RM75-6FB-V robot model and the MuJoCo dual-arm simulation with two L20 hands. The supported development environment is Ubuntu 22.04 with ROS 2 Humble.

The current target path is:

- two RM75-6FB-V arms in MuJoCo;
- MoveIt 2 and RViz planning for the `left_arm`, `right_arm`, and `dual_arms` groups;
- two L20 hand controllers in MuJoCo, driven by the dual hand command bridge.

The intended real-hardware configuration is also dual-arm. The repository does not contain an L20 RS485 hardware driver, and the L20 bridge described below is for the MuJoCo controllers. The real-arm entry now starts separate left and right RM75 drivers and control nodes, a dual-arm joint-state bridge, and dual-arm MoveIt/RViz.

## Packages

| Package | Purpose |
| --- | --- |
| `rm_description` | RM75-6FB-V URDF, meshes, and dual-arm description |
| `rm_75_config` | RM75-6FB-V MoveIt configuration and dual-arm SRDF |
| `rm_mujoco` | Dual RM75 + dual L20 MuJoCo model, controllers, and launch file |
| `rm_driver` | RealMan arm driver |
| `rm_control` | MoveIt to driver trajectory forwarding |
| `rm_bringup` | RM75-6FB-V real-arm launch entry |
| `rm_moveit2` | MoveIt example node |
| `rm_ros_interfaces` | ROS messages and services |
| `rm_piano_player` | MIDI playback, dual-arm planning, dual L20 commands, and MIDI feedback |

Legacy examples and Gazebo sources that are marked with `COLCON_IGNORE` are not part of the current build path.

## Build

On Ubuntu 22.04 with ROS 2 Humble:

```bash
cd ~/ros2_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
```

The MuJoCo launch requires the external `mujoco_ros2_control` package, MoveIt 2, RViz 2, `xacro`, and the standard ROS 2 controller packages.

## Launch the dual-arm MuJoCo simulation

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

The real entry defaults to left arm `192.168.1.18`, right arm `192.168.1.19`, left hand `/dev/ttyUSB0`, right hand `/dev/ttyUSB1`, and the SDK hand parameter `L20-11`:

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_real.launch.py \
  midi_file:=/absolute/path/song.mid execute:=false
```

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

The launch isolates the two driver/control stacks in the `left_arm` and `right_arm` namespaces and merges their joint states to `/joint_states` for the dual-arm URDF, MoveIt, and RViz. The L20 RS485 hardware driver is still outside this repository; connect it separately on `/dev/ttyUSB0` and `/dev/ttyUSB1`.

Before using hardware, build on Ubuntu/ROS 2 Humble and verify both arm IP addresses, UDP feedback addresses, and ports. This checkout has only received static validation; physical motion has not been tested here.

Hardware acceptance order: test `/dev/ttyUSB0`, then `/dev/ttyUSB1`, inspect both hand state topics, run single-key arm motions, run a slow scale, and only then enable MIDI feedback for a fixed song. Keep the emergency stop accessible and clear the robot workspace before enabling execution.

## Validation

The Windows checkout cannot run ROS 2 or `colcon`. Before deploying on Ubuntu, run:

```bash
colcon test
colcon test-result --verbose
```

Then start the MuJoCo launch with RViz disabled first, verify both arm controllers and both hand controllers, and enable RViz after the simulation is stable.
