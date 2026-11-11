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
    config/piano_scene_88key.yaml
    config/piano_scene_static5.yaml
    config/static_pose_reference.yaml
    config/piano_direct_env.yaml
    config/right_hand_piano_sim.yaml
    config/right_tail_v29.yaml
    config/piano_rl_environment.yaml
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
  DIRECTORY rm_mujoco
  DESTINATION share/${PROJECT_NAME}
  FILES_MATCHING PATTERN "*.py"
)

install(
  PROGRAMS
    scripts/l20_dual_command_bridge.py
    scripts/import_pianovam.py
    scripts/plan_performance.py
    scripts/run_performance.py
    scripts/analyze_88_keys.py
    scripts/optimize_88key_layout.py
    scripts/retry_dynamic_failures.py
    scripts/render_key_postures.py
    scripts/render_performance_video.py
    scripts/calibrate_piano_chord.py
    scripts/verify_right_tail.py
    scripts/verify_two_tigers.py
    scripts/train_piano_rl.py
    scripts/prepare_piano_rl.py
    scripts/evaluate_piano_robustness.py
    scripts/prepare_pianovam_tasks.py
    scripts/check_piano_direct_env.py
    scripts/train_piano_direct.py
  DESTINATION lib/${PROJECT_NAME}
)

install(
  FILES
    scripts/run_performance.py
    scripts/plan_performance.py
    scripts/import_pianovam.py
    scripts/analyze_88_keys.py
    scripts/optimize_88key_layout.py
    scripts/retry_dynamic_failures.py
    scripts/render_key_postures.py
    scripts/render_performance_video.py
    scripts/prepare_pianovam_tasks.py
    scripts/check_piano_direct_env.py
    scripts/train_piano_direct.py
  DESTINATION share/${PROJECT_NAME}/scripts
)

install(FILES README.md DESTINATION share/${PROJECT_NAME})

install(
  FILES
    examples/two_tigers_flat_palms/run_flat_palms.py
    examples/two_tigers_flat_palms/fingering.yaml
    examples/two_tigers_flat_palms/two_tigers_original_pose_score.mid
    examples/two_tigers_flat_palms/two_tigers_c5_g5_1x.mid
    examples/two_tigers_flat_palms/two_tigers_c5_g5_1x.json
  DESTINATION share/${PROJECT_NAME}/examples/two_tigers_flat_palms
)

install(
  DIRECTORY examples/two_tigers_flat_palms/verified_40
  DESTINATION share/${PROJECT_NAME}/examples/two_tigers_flat_palms
)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(model_stability test/test_model_stability.py TIMEOUT 180)
  ament_add_pytest_test(piano_scene test/test_scene.py TIMEOUT 60)
  ament_add_pytest_test(key_events test/test_key_events.py TIMEOUT 60)
  ament_add_pytest_test(pig_score test/test_pig_score.py TIMEOUT 60)
  ament_add_pytest_test(import_pianovam test/test_import_pianovam.py TIMEOUT 60)
  ament_add_pytest_test(performance_plan test/test_performance.py TIMEOUT 60)
  ament_add_pytest_test(fingering test/test_fingering.py TIMEOUT 180)
  ament_add_pytest_test(right_tail test/test_right_tail.py TIMEOUT 180)
  ament_add_pytest_test(piano_rl test/test_piano_rl.py TIMEOUT 180)
  ament_add_pytest_test(pianovam_tasks test/test_pianovam_tasks.py TIMEOUT 60)
  ament_add_pytest_test(piano_direct_reward test/test_piano_direct_reward.py TIMEOUT 60)
  ament_add_pytest_test(piano_direct_eval test/test_piano_direct_eval.py TIMEOUT 60)
  ament_add_pytest_test(piano_direct test/test_piano_direct.py TIMEOUT 180)
  ament_add_pytest_test(two_tigers test/test_two_tigers.py TIMEOUT 180)
endif()

ament_package()
