import os
import yaml

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, FindExecutable, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    arm_config = os.path.join(
        get_package_share_directory("rm_driver"), "config", "rm_75_config.yaml"
    )
    with open(arm_config, "r", encoding="utf-8") as config_file:
        driver_parameters = yaml.safe_load(config_file)["rm_driver"]["ros__parameters"]
    description_file = os.path.join(
        get_package_share_directory("rm_description"),
        "urdf",
        "rm_75_6fb_v_dual.urdf.xacro",
    )
    robot_description = ParameterValue(
        Command([
            FindExecutable(name="xacro"),
            " ",
            description_file,
            " left_xyz:='0 -0.35 0.5'",
            " left_rpy:='0 0 0'",
            " right_xyz:='0 0.35 0.5'",
            " right_rpy:='0 0 0'",
        ]),
        value_type=str,
    )

    left_driver = Node(
        package="rm_driver",
        executable="rm_driver",
        namespace="left_arm",
        parameters=[
            driver_parameters,
            {
                "arm_ip": LaunchConfiguration("left_arm_ip"),
                "udp_ip": LaunchConfiguration("left_udp_ip"),
                "udp_port": ParameterValue(
                    LaunchConfiguration("left_udp_port"), value_type=int
                ),
                "arm_joints": [
                    "left_joint1",
                    "left_joint2",
                    "left_joint3",
                    "left_joint4",
                    "left_joint5",
                    "left_joint6",
                    "left_joint7",
                ],
            },
        ],
        output="screen",
    )
    right_driver = Node(
        package="rm_driver",
        executable="rm_driver",
        namespace="right_arm",
        parameters=[
            driver_parameters,
            {
                "arm_ip": LaunchConfiguration("right_arm_ip"),
                "udp_ip": LaunchConfiguration("right_udp_ip"),
                "udp_port": ParameterValue(
                    LaunchConfiguration("right_udp_port"), value_type=int
                ),
                "arm_joints": [
                    "right_joint1",
                    "right_joint2",
                    "right_joint3",
                    "right_joint4",
                    "right_joint5",
                    "right_joint6",
                    "right_joint7",
                ],
            },
        ],
        output="screen",
    )
    left_control = Node(
        package="rm_control",
        executable="rm_control",
        namespace="left_arm",
        parameters=[{"follow": True}, {"arm_type": 75}],
        output="screen",
    )
    right_control = Node(
        package="rm_control",
        executable="rm_control",
        namespace="right_arm",
        parameters=[{"follow": True}, {"arm_type": 75}],
        output="screen",
    )
    joint_state_bridge = Node(
        package="rm_description",
        executable="dual_arm_joint_state_bridge.py",
        parameters=[
            {"left_topic": "/left_arm/joint_states"},
            {"right_topic": "/right_arm/joint_states"},
            {"output_topic": "/joint_states"},
        ],
        output="screen",
    )
    rm_moveit_config = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory("rm_75_config"),
                "launch",
                "real_moveit_demo_6fb_v.launch.py",
            )
        ),
        launch_arguments={
            "use_rviz": LaunchConfiguration("use_rviz"),
        }.items(),
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            "left_arm_ip",
            default_value="192.168.1.18",
            description="TCP IP address of the left RM75-6FB-V arm",
        ),
        DeclareLaunchArgument(
            "right_arm_ip",
            default_value="192.168.1.19",
            description="TCP IP address of the right RM75-6FB-V arm",
        ),
        DeclareLaunchArgument("left_udp_ip", default_value="192.168.1.100"),
        DeclareLaunchArgument("right_udp_ip", default_value="192.168.1.100"),
        DeclareLaunchArgument("left_udp_port", default_value="8089"),
        DeclareLaunchArgument("right_udp_port", default_value="8090"),
        DeclareLaunchArgument("use_rviz", default_value="true"),
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            name="robot_state_publisher",
            parameters=[{"robot_description": robot_description}],
            output="screen",
        ),
        left_driver,
        right_driver,
        left_control,
        right_control,
        joint_state_bridge,
        rm_moveit_config,
    ])
