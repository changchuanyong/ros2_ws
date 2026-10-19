# ros2_rm_robot: RM75-6FB-V dual arm and dual L20 simulation

This workspace is reduced to the RM75-6FB-V robot model and the MuJoCo dual-arm simulation with two L20 hands. The supported development environment is Ubuntu 22.04 with ROS 2 Humble.

The current target path is:

- two RM75-6FB-V arms in MuJoCo;
- MoveIt 2 and RViz planning for the `left_arm`, `right_arm`, and `dual_arms` groups;
- two L20 hand controllers in MuJoCo, driven by the dual hand command bridge.

The repository does not contain an L20 RS485 hardware driver. The L20 bridge described below is for the MuJoCo controllers. The real-arm bringup file still starts one RM75 driver instance; a physical dual-arm setup needs two driver instances with separate robot network settings before it can be used on hardware.

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

## Real-arm entry point

The remaining RM75-6FB-V hardware entry is:

```bash
source ~/ros2_ws/install/setup.bash
ros2 launch rm_bringup rm_75_6fb_v_bringup.launch.py
```

Before using hardware, check the arm IP address in `rm_driver/config/rm_75_config.yaml`, confirm the target arm, and test the launch in simulation first. This entry currently configures one arm. Do not use it as a dual-arm hardware launch until two driver instances and independent network parameters have been added.

## Validation

The Windows checkout cannot run ROS 2 or `colcon`. Before deploying on Ubuntu, run:

```bash
colcon test
colcon test-result --verbose
```

Then start the MuJoCo launch with RViz disabled first, verify both arm controllers and both hand controllers, and enable RViz after the simulation is stable.
