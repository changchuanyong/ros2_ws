<div align="right">

[简体中文](https://github.com/RealManRobot/ros2_rm_robot/blob/humble/rm_moveit2/README_CN.md)|[English](https://github.com/RealManRobot/ros2_rm_robot/blob/humble/rm_moveit2/README.md)
 
</div>

<div align="center">

# 睿尔曼机械臂rm_moveit2使用说明书V1.0
 
睿尔曼智能科技（北京）有限公司 
文件修订记录：

| 版本号 | 时间 | 备注 |
| :---: | :----: | :---: |
| V1.0 | 2026-4-16 | 拟制 |

</div>

## 目录
* 1.[rm_moveit2功能包说明](#rm_moveit2功能包说明)
* 2.[rm_moveit2功能包使用](#rm_moveit2功能包使用)
* 2.1[基础功能包使用](#基础功能包使用)
* 2.2[高级功能包使用](#高级功能包使用)
* 3.[rm_moveit2功能包架构说明](#rm_moveit2功能包架构说明)
* 3.1[功能包文件总览](#功能包文件总览)

## rm_moveit2功能包说明
rm_moveit2是面向RM75-6FB-V双臂平台的MoveIt2控制示例功能包。
* 1.功能包使用。
* 2.功能包架构说明。
通过这两部分内容的介绍可以帮助大家：
* 1.了解该功能包的使用。
* 2.熟悉功能包中的文件构成及作用。

## rm_moveit2功能包使用
### 基础功能包使用
运行rm_moveit2之前，需要先启动RM75对应的rm_driver、rm_description、rm_control以及MoveIt配置功能包节点。

使用以下命令启动RM75示例。
```
rm@rm-desktop:~$ ros2 launch rm_moveit2 moveit_rm75.launch.py
```

### 高级功能包使用
rm_moveit2的通用参数在launch文件中配置。  
参数planning_group：MoveIt使用的规划组，默认值为rm_group。
参数current_state_wait_sec：读取当前状态的等待时间。  
参数velocity_scaling：运动速度缩放系数。  
参数acceleration_scaling：运动加速度缩放系数。  
参数planning_time：MoveIt规划时间。  
参数home_named_target：运动到初始姿态时使用的命名目标。  
参数enable_pose_target：是否直接规划到pose_target_csv给定的位姿目标。  
参数pose_target_csv：x,y,z,rx,ry,rz格式的位姿目标。  
参数pose_reference_frame：位姿目标使用的参考坐标系。  

## rm_moveit2功能包架构说明
### 功能包文件总览
当前rm_moveit2功能包的文件构成如下。
```
├── CMakeLists.txt
├── launch
│   └── moveit_rm75.launch.py               # RM75启动文件
├── package.xml
├── README_CN.md
├── README.md
└── src
    ├── linear_motion_node.cpp              # MoveIt运动辅助文件
    └── simple_moveit_node.cpp              # 主节点文件
```
