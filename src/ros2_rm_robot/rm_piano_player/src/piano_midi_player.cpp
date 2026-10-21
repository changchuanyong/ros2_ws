#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iterator>
#include <map>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <geometry_msgs/msg/pose.hpp>
#include <moveit/move_group_interface/move_group_interface.h>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <std_msgs/msg/bool.hpp>
#include <std_msgs/msg/string.hpp>

#include "key_positions.hpp"

namespace
{

using MoveGroupInterface = moveit::planning_interface::MoveGroupInterface;

template<typename T>
T parameter(const rclcpp::Node::SharedPtr & node, const std::string & name, const T & value)
{
  if (!node->has_parameter(name)) {
    node->declare_parameter<T>(name, value);
  }
  return node->get_parameter(name).get_value<T>();
}

struct NoteEvent
{
  int note{0};
  int velocity{0};
  double start_sec{0.0};
  double duration_sec{0.1};
};

struct RawMidiEvent
{
  std::uint64_t tick{0};
  std::uint64_t order{0};
  enum class Kind { NoteOn, NoteOff, Tempo } kind{Kind::NoteOn};
  int channel{0};
  int note{0};
  int velocity{0};
  std::uint32_t tempo_us_per_quarter{500000};
};

std::uint16_t readU16(const std::vector<std::uint8_t> & bytes, std::size_t & offset)
{
  if (offset + 2 > bytes.size()) {
    throw std::runtime_error("Unexpected end of MIDI data while reading uint16");
  }
  const auto value = static_cast<std::uint16_t>(bytes[offset] << 8 | bytes[offset + 1]);
  offset += 2;
  return value;
}

std::uint32_t readU32(const std::vector<std::uint8_t> & bytes, std::size_t & offset)
{
  if (offset + 4 > bytes.size()) {
    throw std::runtime_error("Unexpected end of MIDI data while reading uint32");
  }
  const auto value = (static_cast<std::uint32_t>(bytes[offset]) << 24) |
    (static_cast<std::uint32_t>(bytes[offset + 1]) << 16) |
    (static_cast<std::uint32_t>(bytes[offset + 2]) << 8) |
    static_cast<std::uint32_t>(bytes[offset + 3]);
  offset += 4;
  return value;
}

std::uint32_t readVlq(
  const std::vector<std::uint8_t> & bytes, std::size_t & offset, std::size_t limit)
{
  std::uint32_t value = 0;
  for (int count = 0; count < 4; ++count) {
    if (offset >= bytes.size() || offset >= limit) {
      throw std::runtime_error("Unexpected end of MIDI data while reading variable length value");
    }
    const auto byte = bytes[offset++];
    value = (value << 7) | (byte & 0x7f);
    if ((byte & 0x80) == 0) {
      return value;
    }
  }
  throw std::runtime_error("Invalid MIDI variable length value");
}

std::vector<std::uint8_t> readFile(const std::string & path)
{
  std::ifstream file(path, std::ios::binary);
  if (!file) {
    throw std::runtime_error("Cannot open MIDI file: " + path);
  }
  return std::vector<std::uint8_t>(
    std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>());
}

std::vector<NoteEvent> parseMidi(const std::string & path, std::size_t * missing_note_off_count)
{
  const auto bytes = readFile(path);
  std::size_t offset = 0;
  if (bytes.size() < 14 || std::string(bytes.begin(), bytes.begin() + 4) != "MThd") {
    throw std::runtime_error("MIDI file does not start with MThd");
  }
  offset = 4;
  const auto header_length = readU32(bytes, offset);
  if (header_length < 6 || offset + header_length > bytes.size()) {
    throw std::runtime_error("Invalid MIDI header length");
  }
  const auto format = readU16(bytes, offset);
  const auto track_count = readU16(bytes, offset);
  const auto division = readU16(bytes, offset);
  if ((division & 0x8000u) != 0) {
    throw std::runtime_error("SMPTE MIDI timing is not supported; use PPQ timing");
  }
  if (division == 0) {
    throw std::runtime_error("MIDI PPQ division cannot be zero");
  }
  offset = 8 + header_length;
  if (format > 1) {
    throw std::runtime_error("Unsupported MIDI format");
  }
  if (missing_note_off_count != nullptr) {
    *missing_note_off_count = 0;
  }

  std::vector<RawMidiEvent> raw_events;
  std::uint64_t order = 0;
  for (std::uint16_t track = 0; track < track_count; ++track) {
    if (offset + 8 > bytes.size() || std::string(bytes.begin() + offset, bytes.begin() + offset + 4) != "MTrk") {
      throw std::runtime_error("MIDI track header is missing");
    }
    offset += 4;
    const auto track_length = readU32(bytes, offset);
    if (offset + track_length > bytes.size()) {
      throw std::runtime_error("MIDI track extends past end of file");
    }
    const auto track_end = offset + track_length;
    std::uint64_t tick = 0;
    std::uint8_t running_status = 0;
    while (offset < track_end) {
      tick += readVlq(bytes, offset, track_end);
      if (offset >= track_end) {
        throw std::runtime_error("MIDI event has no status byte");
      }
      std::uint8_t status = bytes[offset++];
      if (status < 0x80) {
        if (running_status == 0) {
          throw std::runtime_error("MIDI data byte appears without running status");
        }
        --offset;
        status = running_status;
      } else if (status < 0xf0) {
        running_status = status;
      }

      if (status == 0xff) {
        if (offset >= track_end) {
          throw std::runtime_error("MIDI meta event is truncated");
        }
        const auto type = bytes[offset++];
        const auto length = readVlq(bytes, offset, track_end);
        if (length > track_end - offset) {
          throw std::runtime_error("MIDI meta event extends past track");
        }
        if (type == 0x51 && length == 3) {
          const auto tempo = (static_cast<std::uint32_t>(bytes[offset]) << 16) |
            (static_cast<std::uint32_t>(bytes[offset + 1]) << 8) |
            static_cast<std::uint32_t>(bytes[offset + 2]);
          raw_events.push_back({tick, order++, RawMidiEvent::Kind::Tempo, 0, 0, 0, tempo});
        }
        offset += length;
        running_status = 0;
        continue;
      }
      if (status == 0xf0 || status == 0xf7) {
        const auto length = readVlq(bytes, offset, track_end);
        if (length > track_end - offset) {
          throw std::runtime_error("MIDI system event extends past track");
        }
        offset += length;
        running_status = 0;
        continue;
      }
      if (status >= 0xf1) {
        const int data_length = (status == 0xf1 || status == 0xf3) ? 1 :
          (status == 0xf2 ? 2 : 0);
        if (offset + static_cast<std::size_t>(data_length) > track_end) {
          throw std::runtime_error("MIDI system event is truncated");
        }
        offset += static_cast<std::size_t>(data_length);
        running_status = 0;
        continue;
      }

      const int channel = status & 0x0f;
      const int command = status & 0xf0;
      if (offset >= track_end) {
        throw std::runtime_error("MIDI channel event is truncated");
      }
      const int data1 = bytes[offset++];
      if (command == 0xc0 || command == 0xd0) {
        continue;
      }
      if (offset >= track_end) {
        throw std::runtime_error("MIDI channel event is missing its second data byte");
      }
      const int data2 = bytes[offset++];
      if (command == 0x90 && data2 != 0) {
        raw_events.push_back({tick, order++, RawMidiEvent::Kind::NoteOn, channel, data1, data2, 0});
      } else if (command == 0x80 || command == 0x90) {
        raw_events.push_back({tick, order++, RawMidiEvent::Kind::NoteOff, channel, data1, data2, 0});
      }
    }
    offset = track_end;
  }

  std::stable_sort(raw_events.begin(), raw_events.end(), [](const auto & lhs, const auto & rhs) {
    if (lhs.tick != rhs.tick) {
      return lhs.tick < rhs.tick;
    }
    return lhs.order < rhs.order;
  });

  struct StartedNote { double start_sec; int velocity; };
  std::map<std::pair<int, int>, std::vector<StartedNote>> active;
  std::vector<NoteEvent> notes;
  std::uint64_t last_tick = 0;
  double current_sec = 0.0;
  std::uint32_t tempo = 500000;
  for (const auto & event : raw_events) {
    const auto delta_ticks = event.tick - last_tick;
    current_sec += static_cast<double>(delta_ticks) * static_cast<double>(tempo) /
      static_cast<double>(division) / 1000000.0;
    last_tick = event.tick;
    if (event.kind == RawMidiEvent::Kind::Tempo) {
      tempo = std::max<std::uint32_t>(1, event.tempo_us_per_quarter);
      continue;
    }
    const auto key = std::make_pair(event.channel, event.note);
    if (event.kind == RawMidiEvent::Kind::NoteOn) {
      active[key].push_back({current_sec, event.velocity});
    } else {
      auto found = active.find(key);
      if (found == active.end() || found->second.empty()) {
        continue;
      }
      const auto started = found->second.back();
      found->second.pop_back();
      notes.push_back({event.note, started.velocity, started.start_sec,
        std::max(0.01, current_sec - started.start_sec)});
    }
  }
  for (const auto & entry : active) {
    for (const auto & started : entry.second) {
      if (missing_note_off_count != nullptr) {
        ++(*missing_note_off_count);
      }
      notes.push_back({entry.first.second, started.velocity, started.start_sec, 0.1});
    }
  }
  std::stable_sort(notes.begin(), notes.end(), [](const auto & lhs, const auto & rhs) {
    if (lhs.start_sec != rhs.start_sec) {
      return lhs.start_sec < rhs.start_sec;
    }
    return lhs.note < rhs.note;
  });
  return notes;
}

class PianoMidiPlayer
{
public:
  explicit PianoMidiPlayer(const rclcpp::Node::SharedPtr & node)
  : node_(node)
  {
    midi_file_ = parameter(node_, "midi_file", std::string());
    piano_frame_ = parameter(node_, "piano_frame", std::string("piano_frame"));
    left_group_name_ = parameter(node_, "left_planning_group", std::string("left_arm"));
    right_group_name_ = parameter(node_, "right_planning_group", std::string("right_arm"));
    execute_ = parameter(node_, "execute", false);
    feedback_enabled_ = parameter(node_, "feedback_enabled", false);
    tempo_scale_ = parameter(node_, "tempo_scale", 2.0);
    feedback_tolerance_sec_ = parameter(node_, "feedback_tolerance_sec", 0.15);
    keyboard_note_min_ = parameter(node_, "keyboard_note_min", 21);
    keyboard_note_max_ = parameter(node_, "keyboard_note_max", 108);
    left_max_note_ = parameter(node_, "left_max_note", 59);
    key_x_start_ = parameter(node_, "key_x_start", 0.30);
    key_x_step_ = parameter(node_, "key_x_step", 0.014);
    key_y_ = parameter(node_, "key_y", 0.0);
    black_key_y_ = parameter(node_, "black_key_y", 0.012);
    key_z_ = parameter(node_, "key_z", 0.312);
    key_positions_ = parameter(node_, "key_positions", std::vector<double>{});
    approach_height_ = parameter(node_, "approach_height", 0.04);
    press_depth_ = parameter(node_, "press_depth", 0.008);
    orientation_xyzw_ = parameter(node_, "orientation_xyzw", std::vector<double>{0, 0, 0, 1});
    velocity_scaling_ = parameter(node_, "velocity_scaling", 0.1);
    acceleration_scaling_ = parameter(node_, "acceleration_scaling", 0.1);
    planning_time_ = parameter(node_, "planning_time", 5.0);
    return_home_ = parameter(node_, "return_home", false);
    hand_open_ = parameter(node_, "hand_open", std::vector<double>(20, 0.0));
    hand_press_value_ = parameter(node_, "hand_press_value", 180.0);

    if (orientation_xyzw_.size() != 4 || hand_open_.size() != 20) {
      throw std::runtime_error("orientation_xyzw must have 4 values and hand_open must have 20 values");
    }
    if (tempo_scale_ <= 0.0 || (key_positions_.empty() && key_x_step_ <= 0.0) ||
      left_max_note_ < keyboard_note_min_ ||
      left_max_note_ >= keyboard_note_max_ || keyboard_note_min_ < 0 || keyboard_note_max_ > 127)
    {
      throw std::runtime_error("Invalid MIDI piano timing or keyboard range parameters");
    }
    rm_piano_player::validateKeyPositions(
      key_positions_, keyboard_note_min_, keyboard_note_max_);

    left_hand_pub_ = node_->create_publisher<sensor_msgs::msg::JointState>(
      "/cb_left_hand_control_cmd", 10);
    right_hand_pub_ = node_->create_publisher<sensor_msgs::msg::JointState>(
      "/cb_right_hand_control_cmd", 10);
    expected_event_pub_ = node_->create_publisher<std_msgs::msg::String>(
      "/robopianist/expected_event", rclcpp::QoS(10).transient_local());
    status_pub_ = node_->create_publisher<std_msgs::msg::String>(
      "/robopianist/status", 10);
    abort_sub_ = node_->create_subscription<std_msgs::msg::Bool>(
      "/robopianist/feedback_abort", 10,
      [this](const std_msgs::msg::Bool::SharedPtr message) {
        if (message->data) {
          abort_requested_.store(true);
          if (left_group_) {
            left_group_->stop();
          }
          if (right_group_) {
            right_group_->stop();
          }
        }
      });
  }

  bool run()
  {
    if (midi_file_.empty()) {
      RCLCPP_ERROR(node_->get_logger(), "midi_file is empty");
      return false;
    }
    std::size_t missing_note_off_count = 0;
    const auto notes = parseMidi(midi_file_, &missing_note_off_count);
    if (notes.empty()) {
      RCLCPP_ERROR(node_->get_logger(), "MIDI file contains no note events");
      return false;
    }
    if (missing_note_off_count > 0) {
      RCLCPP_WARN(node_->get_logger(),
        "%zu MIDI note(s) have no note-off; using a 0.1 second default duration",
        missing_note_off_count);
    }

    std::vector<NoteEvent> left_notes;
    std::vector<NoteEvent> right_notes;
    for (const auto & note : notes) {
      if (note.note < keyboard_note_min_ || note.note > keyboard_note_max_) {
        throw std::runtime_error("MIDI note " + std::to_string(note.note) +
          " is outside the configured 88-key range");
      }
      (note.note <= left_max_note_ ? left_notes : right_notes).push_back(note);
    }
    validateNoSameHandOverlap(left_notes, "left");
    validateNoSameHandOverlap(right_notes, "right");

    if (execute_) {
      initializeMoveGroups();
    }

    publishStatus("validated " + std::to_string(notes.size()) + " notes");
    if (feedback_enabled_) {
      RCLCPP_INFO(node_->get_logger(),
        "MIDI feedback is enabled with %.3f s tolerance; run midi_feedback_monitor.py with the keyboard input port",
        feedback_tolerance_sec_);
    }

    const auto start_time = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    std::thread left_thread([this, &left_notes, start_time]() {
      playSide("left", left_notes, left_group_, start_time);
    });
    std::thread right_thread([this, &right_notes, start_time]() {
      playSide("right", right_notes, right_group_, start_time);
    });
    left_thread.join();
    right_thread.join();

    if (return_home_ && !abort_requested_.load()) {
      if (execute_) {
        left_group_->setNamedTarget("forward");
        right_group_->setNamedTarget("forward");
        const auto left_result = left_group_->move();
        const auto right_result = right_group_->move();
        if (left_result != moveit::core::MoveItErrorCode::SUCCESS ||
          right_result != moveit::core::MoveItErrorCode::SUCCESS)
        {
          abort_requested_.store(true);
        }
      }
    }
    const bool success = !abort_requested_.load();
    publishStatus(success ? "completed" : "aborted");
    return success;
  }

private:
  void configureGroup(const std::shared_ptr<MoveGroupInterface> & group)
  {
    group->setPoseReferenceFrame(piano_frame_);
    group->setMaxVelocityScalingFactor(velocity_scaling_);
    group->setMaxAccelerationScalingFactor(acceleration_scaling_);
    group->setPlanningTime(planning_time_);
  }

  void initializeMoveGroups()
  {
    if (left_group_ && right_group_) {
      return;
    }
    left_group_ = std::make_shared<MoveGroupInterface>(node_, left_group_name_);
    right_group_ = std::make_shared<MoveGroupInterface>(node_, right_group_name_);
    configureGroup(left_group_);
    configureGroup(right_group_);
  }

  static void validateNoSameHandOverlap(const std::vector<NoteEvent> & notes, const std::string & side)
  {
    double previous_end = -1.0;
    int previous_note = -1;
    for (const auto & note : notes) {
      if (note.start_sec < previous_end - 1e-6) {
        throw std::runtime_error(
          "Unsupported " + side + " hand overlap/chord at MIDI note " + std::to_string(note.note) +
          "; first phase allows one active note per hand");
      }
      previous_end = note.start_sec + note.duration_sec;
      previous_note = note.note;
      (void)previous_note;
    }
  }

  static bool isBlackKey(int note)
  {
    switch (note % 12) {
      case 1:
      case 3:
      case 6:
      case 8:
      case 10:
        return true;
      default:
        return false;
    }
  }

  geometry_msgs::msg::Pose keyPose(int note, double z_offset) const
  {
    geometry_msgs::msg::Pose pose;
    const auto position = rm_piano_player::keyPosition(
      key_positions_, note, keyboard_note_min_,
      {key_x_start_ + static_cast<double>(note - keyboard_note_min_) * key_x_step_,
        isBlackKey(note) ? black_key_y_ : key_y_, key_z_}, z_offset);
    pose.position.x = position[0];
    pose.position.y = position[1];
    pose.position.z = position[2];
    pose.orientation.x = orientation_xyzw_[0];
    pose.orientation.y = orientation_xyzw_[1];
    pose.orientation.z = orientation_xyzw_[2];
    pose.orientation.w = orientation_xyzw_[3];
    return pose;
  }

  int fingerFor(const std::string & side, int note) const
  {
    const int low = side == "left" ? keyboard_note_min_ : left_max_note_ + 1;
    const int high = side == "left" ? left_max_note_ : keyboard_note_max_;
    const int bucket = std::min(4, std::max(0, (note - low) * 5 / std::max(1, high - low + 1)));
    return side == "left" ? 4 - bucket : bucket;
  }

  std::vector<double> handPose(int finger, bool pressed, int velocity) const
  {
    auto pose = hand_open_;
    if (!pressed) {
      return pose;
    }
    const auto value = std::max(0.0, std::min(255.0,
      hand_press_value_ * static_cast<double>(velocity) / 127.0));
    pose[static_cast<std::size_t>(finger)] = value;
    pose[static_cast<std::size_t>(15 + finger)] = value;
    return pose;
  }

  void publishHand(const std::string & side, const std::vector<double> & values)
  {
    if (!execute_) {
      return;
    }
    sensor_msgs::msg::JointState message;
    message.header.stamp = node_->get_clock()->now();
    message.position = values;
    if (side == "left") {
      left_hand_pub_->publish(message);
    } else {
      right_hand_pub_->publish(message);
    }
  }

  bool moveToPose(const std::shared_ptr<MoveGroupInterface> & group,
    const geometry_msgs::msg::Pose & pose, const std::string & label)
  {
    if (abort_requested_.load()) {
      return false;
    }
    if (!execute_) {
      RCLCPP_INFO(node_->get_logger(), "DRY RUN: %s", label.c_str());
      return true;
    }
    if (!group) {
      RCLCPP_ERROR(node_->get_logger(), "MoveIt group is not initialized for %s", label.c_str());
      abort_requested_.store(true);
      return false;
    }
    group->setPoseReferenceFrame(piano_frame_);
    group->setPoseTarget(pose);
    const auto result = group->move();
    group->clearPoseTargets();
    if (result != moveit::core::MoveItErrorCode::SUCCESS) {
      RCLCPP_ERROR(node_->get_logger(), "MoveIt failed: %s", label.c_str());
      abort_requested_.store(true);
      return false;
    }
    return true;
  }

  void publishExpected(const std::string & type, int note)
  {
    if (!execute_ || !feedback_enabled_) {
      return;
    }
    std_msgs::msg::String message;
    message.data = "{\"type\":\"" + type + "\",\"note\":" + std::to_string(note) + "}";
    expected_event_pub_->publish(message);
  }

  void publishStatus(const std::string & text)
  {
    std_msgs::msg::String message;
    message.data = text;
    status_pub_->publish(message);
  }

  void playSide(const std::string & side, const std::vector<NoteEvent> & notes,
    const std::shared_ptr<MoveGroupInterface> & group,
    const std::chrono::steady_clock::time_point & start_time = std::chrono::steady_clock::now())
  {
    for (const auto & note : notes) {
      if (abort_requested_.load()) {
        return;
      }
      const auto target_time = start_time + std::chrono::duration_cast<std::chrono::steady_clock::duration>(
        std::chrono::duration<double>(note.start_sec * tempo_scale_));
      std::this_thread::sleep_until(target_time);
      if (abort_requested_.load()) {
        return;
      }
      const auto approach = keyPose(note.note, approach_height_);
      const auto press = keyPose(note.note, -press_depth_);
      const auto finger = fingerFor(side, note.note);
      if (!moveToPose(group, approach, side + " approach " + std::to_string(note.note))) {
        return;
      }
      publishHand(side, handPose(finger, true, note.velocity));
      if (!moveToPose(group, press, side + " press " + std::to_string(note.note))) {
        return;
      }
      publishExpected("on", note.note);
      const auto hold = std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::duration<double>(note.duration_sec * tempo_scale_));
      if (execute_) {
        rclcpp::sleep_for(hold);
      }
      publishHand(side, handPose(finger, false, note.velocity));
      publishExpected("off", note.note);
      if (!moveToPose(group, approach, side + " release " + std::to_string(note.note))) {
        return;
      }
    }
  }

  rclcpp::Node::SharedPtr node_;
  std::string midi_file_;
  std::string piano_frame_;
  std::string left_group_name_;
  std::string right_group_name_;
  bool execute_{false};
  bool feedback_enabled_{false};
  double tempo_scale_{2.0};
  double feedback_tolerance_sec_{0.15};
  int keyboard_note_min_{21};
  int keyboard_note_max_{108};
  int left_max_note_{59};
  double key_x_start_{0.30};
  double key_x_step_{0.014};
  double key_y_{0.0};
  double black_key_y_{0.012};
  double key_z_{0.312};
  double approach_height_{0.04};
  double press_depth_{0.008};
  double velocity_scaling_{0.1};
  double acceleration_scaling_{0.1};
  double planning_time_{5.0};
  bool return_home_{false};
  double hand_press_value_{180.0};
  std::vector<double> orientation_xyzw_;
  std::vector<double> hand_open_;
  std::vector<double> key_positions_;
  std::shared_ptr<MoveGroupInterface> left_group_;
  std::shared_ptr<MoveGroupInterface> right_group_;
  rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr left_hand_pub_;
  rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr right_hand_pub_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr expected_event_pub_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr status_pub_;
  rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr abort_sub_;
  std::atomic_bool abort_requested_{false};
};

}  // namespace

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<rclcpp::Node>(
    "piano_midi_player", rclcpp::NodeOptions().automatically_declare_parameters_from_overrides(true));
  rclcpp::executors::MultiThreadedExecutor executor;
  executor.add_node(node);
  std::thread spinner([&executor]() { executor.spin(); });

  int exit_code = 0;
  try {
    PianoMidiPlayer player(node);
    exit_code = player.run() ? 0 : 1;
  } catch (const std::exception & exception) {
    RCLCPP_ERROR(node->get_logger(), "MIDI piano player failed: %s", exception.what());
    exit_code = 1;
  }

  rclcpp::shutdown();
  spinner.join();
  return exit_code;
}
