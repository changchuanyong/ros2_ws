#ifndef RM_PIANO_PLAYER_KEY_POSITIONS_HPP_
#define RM_PIANO_PLAYER_KEY_POSITIONS_HPP_

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <stdexcept>
#include <vector>

namespace rm_piano_player
{

inline void validateKeyPositions(
  const std::vector<double> & positions, int note_min, int note_max)
{
  if (positions.empty()) {
    return;
  }
  if (note_min < 0 || note_max > 127 || note_max < note_min ||
    positions.size() != 3 * static_cast<std::size_t>(note_max - note_min + 1))
  {
    throw std::runtime_error(
      "key_positions must contain one x, y, z triplet per configured MIDI note");
  }
  if (!std::all_of(positions.begin(), positions.end(), [](double value) {
      return std::isfinite(value);
    }))
  {
    throw std::runtime_error("key_positions must contain only finite values");
  }
}

inline std::array<double, 3> keyPosition(
  const std::vector<double> & positions, int note, int note_min,
  const std::array<double, 3> & fallback, double z_offset)
{
  auto result = fallback;
  if (!positions.empty()) {
    if (note < note_min) {
      throw std::out_of_range("MIDI note is below the key_positions range");
    }
    const auto index = 3 * static_cast<std::size_t>(note - note_min);
    result = {positions.at(index), positions.at(index + 1), positions.at(index + 2)};
  }
  result[2] += z_offset;
  return result;
}

}  // namespace rm_piano_player

#endif  // RM_PIANO_PLAYER_KEY_POSITIONS_HPP_
