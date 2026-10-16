cmake_minimum_required(VERSION 3.8)
project(rm_mujoco)

find_package(ament_cmake REQUIRED)

install(
  DIRECTORY config launch models meshes
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
