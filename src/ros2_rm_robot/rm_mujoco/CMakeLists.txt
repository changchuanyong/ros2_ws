cmake_minimum_required(VERSION 3.8)
project(rm_mujoco)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)

ament_python_install_package(${PROJECT_NAME})

install(
  FILES
    config/rm_75_6fb_v_dual_l20_mujoco_control.urdf.xacro
    config/rm_75_6fb_v_dual_l20_mujoco_controllers.yaml
    config/piano_scene.yaml
  DESTINATION share/${PROJECT_NAME}/config
)

install(
  FILES launch/rm_75_dual_l20_mujoco.launch.py
  DESTINATION share/${PROJECT_NAME}/launch
)

install(
  FILES
    models/rm_75_6fb_v_dual_l20.xml
    models/piano_keyboard.xml
  DESTINATION share/${PROJECT_NAME}/models
)

install(
  DIRECTORY meshes
  DESTINATION share/${PROJECT_NAME}
)

install(
  PROGRAMS
    scripts/l20_dual_command_bridge.py
  DESTINATION lib/${PROJECT_NAME}
)

install(FILES README.md DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(model_stability test/test_model_stability.py TIMEOUT 60)
  ament_add_pytest_test(piano_scene test/test_scene.py TIMEOUT 60)
endif()

ament_package()
