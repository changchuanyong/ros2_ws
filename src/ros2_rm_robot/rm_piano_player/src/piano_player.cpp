#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <iomanip>
#include <memory>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

#include <geometry_msgs/msg/pose.hpp>
#include <moveit/move_group_interface/move_group_interface.h>
#include <moveit_msgs/msg/robot_trajectory.hpp>
#include <rclcpp/rclcpp.hpp>

namespace
{

using MoveGroupInterface = moveit::planning_interface::MoveGroupInterface;

template<typename T>
T getOrDeclare(
  const rclcpp::Node::SharedPtr & node,
  const std::string & name,
  const T & default_value)
{
  if (!node->has_parameter(name)) {
    node->declare_parameter<T>(name, default_value);
  }
  return node->get_parameter(name).get_value<T>();
}

std::string formatNumber(double value)
{
  std::ostringstream stream;
  stream << std::fixed << std::setprecision(4) << value;
  return stream.str();
}

class PianoPlayer
{
public:
  explicit PianoPlayer(const rclcpp::Node::SharedPtr & node)
  : node_(node)
  {
    planning_group_ = getOrDeclare(node_, "planning_group", std::string("rm_group"));
    piano_frame_ = getOrDeclare(node_, "piano_frame", std::string("base_link"));
    execute_ = getOrDeclare(node_, "execute", false);
    velocity_scaling_ = getOrDeclare(node_, "velocity_scaling", 0.10);
    acceleration_scaling_ = getOrDeclare(node_, "acceleration_scaling", 0.10);
    planning_time_ = getOrDeclare(node_, "planning_time", 5.0);
    approach_height_ = getOrDeclare(node_, "approach_height", 0.04);
    press_depth_ = getOrDeclare(node_, "press_depth", 0.008);
    cartesian_step_ = getOrDeclare(node_, "cartesian_step", 0.005);
    default_duration_sec_ = getOrDeclare(node_, "default_duration_sec", 0.4);
    return_home_ = getOrDeclare(node_, "return_home", false);

    orientation_xyzw_ = getOrDeclare(
      node_, "orientation_xyzw", std::vector<double>{0.0, 0.0, 0.0, 1.0});
    key_names_ = getOrDeclare(node_, "key_names", std::vector<std::string>{});
    key_x_ = getOrDeclare(node_, "key_x", std::vector<double>{});
    key_y_ = getOrDeclare(node_, "key_y", std::vector<double>{});
    note_sequence_ = getOrDeclare(node_, "note_sequence", std::vector<std::string>{});
    note_durations_ = getOrDeclare(node_, "note_durations", std::vector<double>{});
    key_z_ = getOrDeclare(node_, "key_z", 0.30);

    if (orientation_xyzw_.size() != 4) {
      throw std::runtime_error("orientation_xyzw must contain four values");
    }
    if (key_names_.empty() || key_names_.size() != key_x_.size() ||
      key_names_.size() != key_y_.size())
    {
      throw std::runtime_error("key_names, key_x, and key_y must have the same non-zero length");
    }
    if (!note_durations_.empty() && note_durations_.size() != note_sequence_.size()) {
      throw std::runtime_error("note_durations must be empty or match note_sequence length");
    }

    for (std::size_t index = 0; index < key_names_.size(); ++index) {
      key_index_.emplace(key_names_[index], index);
    }

    move_group_ = std::make_unique<MoveGroupInterface>(node_, planning_group_);
    move_group_->setPoseReferenceFrame(piano_frame_);
    move_group_->setMaxVelocityScalingFactor(velocity_scaling_);
    move_group_->setMaxAccelerationScalingFactor(acceleration_scaling_);
    move_group_->setPlanningTime(planning_time_);

    RCLCPP_INFO(node_->get_logger(), "RM piano player initialized");
    RCLCPP_INFO(node_->get_logger(), "planning_group: %s", planning_group_.c_str());
    RCLCPP_INFO(node_->get_logger(), "piano_frame: %s", piano_frame_.c_str());
    RCLCPP_INFO(node_->get_logger(), "keys: %zu, notes: %zu, execute: %s",
      key_names_.size(), note_sequence_.size(), execute_ ? "true" : "false");
  }

  bool run()
  {
    if (note_sequence_.empty()) {
      RCLCPP_WARN(node_->get_logger(), "note_sequence is empty; nothing to play");
      return true;
    }

    for (std::size_t index = 0; index < note_sequence_.size(); ++index) {
      const std::string & note = note_sequence_[index];
      const auto key = key_index_.find(note);
      if (key == key_index_.end()) {
        RCLCPP_ERROR(node_->get_logger(), "Unknown note '%s'", note.c_str());
        return false;
      }

      const std::size_t key_index = key->second;
      const double duration = note_durations_.empty() ?
        default_duration_sec_ : note_durations_[index];

      const auto approach = makeKeyPose(key_index, approach_height_);
      const auto press = makeKeyPose(key_index, -press_depth_);

      RCLCPP_INFO(node_->get_logger(),
        "[%zu/%zu] note=%s key=(x=%s, y=%s, z=%s) duration=%.3fs",
        index + 1, note_sequence_.size(), note.c_str(),
        formatNumber(key_x_[key_index]).c_str(),
        formatNumber(key_y_[key_index]).c_str(),
        formatNumber(key_z_).c_str(), duration);

      if (!moveToPose(approach, "approach " + note)) {
        return false;
      }
      if (!moveCartesianTo(press, "press " + note)) {
        return false;
      }

      const auto hold_time = std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::duration<double>(std::max(0.0, duration)));
      rclcpp::sleep_for(hold_time);

      if (!moveCartesianTo(approach, "release " + note)) {
        return false;
      }
    }

    if (return_home_) {
      if (!moveToNamedTarget("forward", "return home")) {
        return false;
      }
    }

    RCLCPP_INFO(node_->get_logger(), "Piano sequence completed");
    return true;
  }

private:
  geometry_msgs::msg::Pose makeKeyPose(std::size_t index, double z_offset) const
  {
    geometry_msgs::msg::Pose pose;
    pose.position.x = key_x_[index];
    pose.position.y = key_y_[index];
    pose.position.z = key_z_ + z_offset;
    pose.orientation.x = orientation_xyzw_[0];
    pose.orientation.y = orientation_xyzw_[1];
    pose.orientation.z = orientation_xyzw_[2];
    pose.orientation.w = orientation_xyzw_[3];
    return pose;
  }

  bool moveToPose(const geometry_msgs::msg::Pose & pose, const std::string & label)
  {
    if (!execute_) {
      RCLCPP_INFO(node_->get_logger(), "DRY RUN: %s", label.c_str());
      return true;
    }

    move_group_->setPoseReferenceFrame(piano_frame_);
    move_group_->setPoseTarget(pose);
    const auto result = move_group_->move();
    move_group_->clearPoseTargets();
    if (result != moveit::core::MoveItErrorCode::SUCCESS) {
      RCLCPP_ERROR(node_->get_logger(), "MoveIt failed: %s", label.c_str());
      return false;
    }
    return true;
  }

  bool moveCartesianTo(const geometry_msgs::msg::Pose & target, const std::string & label)
  {
    if (!execute_) {
      RCLCPP_INFO(node_->get_logger(), "DRY RUN: %s", label.c_str());
      return true;
    }

    const auto current = move_group_->getCurrentPose().pose;
    std::vector<geometry_msgs::msg::Pose> waypoints{current, target};
    moveit_msgs::msg::RobotTrajectory trajectory;
    const double fraction = move_group_->computeCartesianPath(
      waypoints, cartesian_step_, 0.0, trajectory);

    if (fraction < 0.95) {
      RCLCPP_ERROR(node_->get_logger(),
        "Cartesian path for '%s' is incomplete: %.1f%%", label.c_str(), fraction * 100.0);
      return false;
    }

    MoveGroupInterface::Plan plan;
    plan.trajectory_ = trajectory;
    const auto result = move_group_->execute(plan);
    if (result != moveit::core::MoveItErrorCode::SUCCESS) {
      RCLCPP_ERROR(node_->get_logger(), "Cartesian execution failed: %s", label.c_str());
      return false;
    }
    return true;
  }

  bool moveToNamedTarget(const std::string & target, const std::string & label)
  {
    if (!execute_) {
      RCLCPP_INFO(node_->get_logger(), "DRY RUN: %s -> %s", label.c_str(), target.c_str());
      return true;
    }

    move_group_->setNamedTarget(target);
    const auto result = move_group_->move();
    if (result != moveit::core::MoveItErrorCode::SUCCESS) {
      RCLCPP_ERROR(node_->get_logger(), "Named target failed: %s", target.c_str());
      return false;
    }
    return true;
  }

  rclcpp::Node::SharedPtr node_;
  std::unique_ptr<MoveGroupInterface> move_group_;
  std::string planning_group_;
  std::string piano_frame_;
  bool execute_{false};
  bool return_home_{false};
  double velocity_scaling_{0.1};
  double acceleration_scaling_{0.1};
  double planning_time_{5.0};
  double approach_height_{0.04};
  double press_depth_{0.008};
  double cartesian_step_{0.005};
  double default_duration_sec_{0.4};
  double key_z_{0.30};
  std::vector<double> orientation_xyzw_;
  std::vector<std::string> key_names_;
  std::vector<double> key_x_;
  std::vector<double> key_y_;
  std::vector<std::string> note_sequence_;
  std::vector<double> note_durations_;
  std::unordered_map<std::string, std::size_t> key_index_;
};

}  // namespace

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);

  auto node = std::make_shared<rclcpp::Node>(
    "piano_player",
    rclcpp::NodeOptions().automatically_declare_parameters_from_overrides(true));

  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(node);
  std::thread spinner([&executor]() { executor.spin(); });

  int exit_code = 0;
  try {
    PianoPlayer player(node);
    exit_code = player.run() ? 0 : 1;
  } catch (const std::exception & exception) {
    RCLCPP_ERROR(node->get_logger(), "Piano player initialization failed: %s", exception.what());
    exit_code = 1;
  }

  rclcpp::shutdown();
  spinner.join();
  return exit_code;
}
