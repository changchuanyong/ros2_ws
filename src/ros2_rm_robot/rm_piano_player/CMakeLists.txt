cmake_minimum_required(VERSION 3.8)
project(rm_piano_player)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(ament_cmake REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(moveit_msgs REQUIRED)
find_package(moveit_ros_planning_interface REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)

add_executable(piano_player src/piano_player.cpp)
add_executable(piano_midi_player src/piano_midi_player.cpp)

ament_target_dependencies(
  piano_player
  geometry_msgs
  moveit_msgs
  moveit_ros_planning_interface
  rclcpp
)

ament_target_dependencies(
  piano_midi_player
  geometry_msgs
  moveit_msgs
  moveit_ros_planning_interface
  rclcpp
  sensor_msgs
  std_msgs
)

install(TARGETS
  piano_player
  piano_midi_player
  DESTINATION lib/${PROJECT_NAME}
)

install(PROGRAMS
  src/midi_feedback_monitor.py
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY config launch models
  DESTINATION share/${PROJECT_NAME}
)

install(FILES README_CN.md
  DESTINATION share/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(test_midi_feedback_monitor
    test/test_midi_feedback_monitor.py
    TIMEOUT 30
  )
endif()

ament_package()
