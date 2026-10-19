import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, TimerAction
from launch.conditions import IfCondition
from launch.substitutions import Command, FindExecutable, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from moveit_configs_utils import MoveItConfigsBuilder


def build_moveit_config():
    description_path = os.path.join(
        get_package_share_directory("rm_description"),
        "urdf",
        "rm_75_6fb_v_dual.urdf.xacro",
    )
    return (
        MoveItConfigsBuilder("rm_75_6fb_v_dual", package_name="rm_75_config")
        .robot_description(
            file_path=description_path,
            mappings={
                "left_xyz": "0 -0.075 0.5",
                "left_rpy": "3.14 1.57 1.5707963267949",
                "right_xyz": "0 0.075 0.5",
                "right_rpy": "3.14 1.57 -1.5707963267949",
            },
        )
        .robot_description_semantic(file_path="config/rm_75_6fb_v_dual_description.srdf")
        .robot_description_kinematics(file_path="config/kinematics_dual.yaml")
        .trajectory_execution(
            file_path="config/moveit_controllers_dual_gazebo.yaml",
            moveit_manage_controllers=False,
        )
        .planning_pipelines(
            default_planning_pipeline="ompl",
            pipelines=["ompl", "pilz_industrial_motion_planner"],
            load_all=False,
        )
        .pilz_cartesian_limits(file_path="config/pilz_cartesian_limits.yaml")
        .joint_limits(file_path="config/joint_limits_dual.yaml")
        .to_moveit_configs()
    )


def generate_launch_description():
    package_share = get_package_share_directory("rm_mujoco")
    description_file = os.path.join(
        get_package_share_directory("rm_description"),
        "urdf",
        "rm_75_6fb_v_dual.urdf.xacro",
    )
    control_file = os.path.join(
        package_share, "config", "rm_75_6fb_v_dual_l20_mujoco_control.urdf.xacro"
    )
    controller_file = os.path.join(
        package_share, "config", "rm_75_6fb_v_dual_l20_mujoco_controllers.yaml"
    )

    robot_description = ParameterValue(
        Command([
            FindExecutable(name="xacro"),
            " ",
            description_file,
            " left_xyz:='0 -0.075 0.5'",
            " left_rpy:='3.14 1.57 1.5707963267949'",
            " right_xyz:='0 0.075 0.5'",
            " right_rpy:='3.14 1.57 -1.5707963267949'",
        ]),
        value_type=str,
    )
    mujoco_description = ParameterValue(
        Command([
            FindExecutable(name="xacro"),
            " ",
            control_file,
            " headless:=",
            LaunchConfiguration("headless"),
        ]),
        value_type=str,
    )
    moveit_config = build_moveit_config()

    move_group_configuration = {
        "publish_robot_description_semantic": True,
        "allow_trajectory_execution": True,
        "publish_planning_scene": True,
        "publish_geometry_updates": True,
        "publish_state_updates": True,
        "publish_transforms_updates": True,
        "monitor_dynamics": False,
    }

    return LaunchDescription([
        DeclareLaunchArgument("headless", default_value="false"),
        DeclareLaunchArgument("use_rviz", default_value="true"),
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            output="screen",
            parameters=[{"robot_description": robot_description, "use_sim_time": True}],
        ),
        Node(
            package="mujoco_ros2_control",
            executable="ros2_control_node",
            output="screen",
            parameters=[
                {"robot_description": mujoco_description, "use_sim_time": True},
                controller_file,
            ],
        ),
        TimerAction(
            period=2.0,
            actions=[
                Node(
                    package="controller_manager",
                    executable="spawner",
                    arguments=[controller, "--controller-manager", "/controller_manager"],
                    output="screen",
                )
                for controller in [
                    "joint_state_broadcaster",
                    "left_arm_controller",
                    "right_arm_controller",
                    "left_l20_hand_controller",
                    "right_l20_hand_controller",
                ]
            ],
        ),
        Node(
            package="rm_mujoco",
            executable="l20_dual_command_bridge.py",
            output="screen",
        ),
        Node(
            package="moveit_ros_move_group",
            executable="move_group",
            output="screen",
            parameters=[
                moveit_config.to_dict(),
                move_group_configuration,
                {"use_sim_time": True},
            ],
        ),
        Node(
            package="rviz2",
            executable="rviz2",
            name="rviz2",
            arguments=[
                "-d",
                os.path.join(
                    get_package_share_directory("rm_75_config"),
                    "config",
                    "moveit.rviz",
                ),
            ],
            parameters=[
                moveit_config.robot_description,
                moveit_config.robot_description_semantic,
                moveit_config.planning_pipelines,
                moveit_config.robot_description_kinematics,
                moveit_config.joint_limits,
                {"use_sim_time": True},
            ],
            condition=IfCondition(LaunchConfiguration("use_rviz")),
            output="screen",
        ),
    ])
