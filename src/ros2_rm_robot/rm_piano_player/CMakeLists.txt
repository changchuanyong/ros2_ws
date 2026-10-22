cmake_minimum_required(VERSION 3.8)
project(rm_piano_player)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
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

# Windows source copies may lack executable bits; symlink-install preserves them.
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
  "${CMAKE_CURRENT_SOURCE_DIR}/src/l20_right_hand_piano.py")
file(COPY src/l20_right_hand_piano.py
  DESTINATION "${CMAKE_CURRENT_BINARY_DIR}/scripts"
  FILE_PERMISSIONS OWNER_READ OWNER_WRITE OWNER_EXECUTE GROUP_READ GROUP_EXECUTE
                   WORLD_READ WORLD_EXECUTE
)

install(PROGRAMS
  src/midi_feedback_monitor.py
  "${CMAKE_CURRENT_BINARY_DIR}/scripts/l20_right_hand_piano.py"
  DESTINATION lib/${PROJECT_NAME}
)

ament_python_install_package(${PROJECT_NAME})

install(DIRECTORY config launch models
  DESTINATION share/${PROJECT_NAME}
)

install(FILES README_CN.md
  DESTINATION share/${PROJECT_NAME}
)

if(BUILD_TESTING)
  add_executable(test_key_positions test/test_key_positions.cpp)
  add_test(NAME test_key_positions COMMAND test_key_positions)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(test_midi_feedback_monitor
    test/test_midi_feedback_monitor.py
    TIMEOUT 30
  )
  ament_add_pytest_test(test_single_hand_core test/test_single_hand_core.py TIMEOUT 30)
  ament_add_pytest_test(test_single_hand_node test/test_single_hand_node.py TIMEOUT 120)
  ament_add_pytest_test(test_single_hand_launch test/test_single_hand_launch.py TIMEOUT 30)
  ament_add_pytest_test(test_single_hand_process test/test_single_hand_process.py TIMEOUT 90)
endif()

ament_package()
