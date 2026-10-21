#include <array>
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

#include "../src/key_positions.hpp"

namespace
{

void require(bool condition, const char * message)
{
  if (!condition) {
    throw std::runtime_error(message);
  }
}

template<typename Function>
void requireThrows(Function function, const char * message)
{
  try {
    function();
  } catch (const std::exception &) {
    return;
  }
  throw std::runtime_error(message);
}

void requirePosition(
  const std::array<double, 3> & actual, const std::array<double, 3> & expected)
{
  for (std::size_t i = 0; i < actual.size(); ++i) {
    require(std::abs(actual[i] - expected[i]) < 1e-12, "Unexpected key coordinate");
  }
}

}  // namespace

int main()
{
  using rm_piano_player::keyPosition;
  using rm_piano_player::validateKeyPositions;
  try {
    validateKeyPositions({}, 21, 108);
    const std::array<double, 3> fallback{0.30, 0.012, 0.312};
    requirePosition(keyPosition({}, 22, 21, fallback, 0.04), {0.30, 0.012, 0.352});
    requirePosition(keyPosition({}, 22, 21, fallback, -0.008), {0.30, 0.012, 0.304});

    // C4, C#4, D4: black keys are offset in depth and raised above the white keys.
    const std::vector<double> octave{0.0, 0.0, 0.0, 0.01175, 0.045, 0.012, 0.0235, 0.0, 0.0};
    validateKeyPositions(octave, 60, 62);
    requirePosition(keyPosition(octave, 60, 60, fallback, 0.04), {0.0, 0.0, 0.04});
    requirePosition(keyPosition(octave, 61, 60, fallback, -0.008), {0.01175, 0.045, 0.004});
    requirePosition(keyPosition(octave, 62, 60, fallback, 0.04), {0.0235, 0.0, 0.04});
    requireThrows([&]() {keyPosition(octave, 59, 60, fallback, 0.0);}, "Accepted low note");
    requireThrows([&]() {keyPosition(octave, 63, 60, fallback, 0.0);}, "Accepted high note");

    std::vector<double> full_keyboard(88 * 3, 0.0);
    full_keyboard[0] = -0.6;
    full_keyboard[87 * 3] = 0.6;
    validateKeyPositions(full_keyboard, 21, 108);
    requirePosition(keyPosition(full_keyboard, 21, 21, fallback, 0.0), {-0.6, 0.0, 0.0});
    requirePosition(keyPosition(full_keyboard, 108, 21, fallback, 0.0), {0.6, 0.0, 0.0});
    requireThrows([&]() {validateKeyPositions(octave, 21, 108);}, "Accepted short table");
    full_keyboard.push_back(0.0);
    requireThrows([&]() {validateKeyPositions(full_keyboard, 21, 108);}, "Accepted long table");
    full_keyboard.pop_back();
    for (const auto value : {std::numeric_limits<double>::quiet_NaN(),
      std::numeric_limits<double>::infinity(), -std::numeric_limits<double>::infinity()})
    {
      full_keyboard.back() = value;
      requireThrows([&]() {validateKeyPositions(full_keyboard, 21, 108);}, "Accepted nonfinite table");
    }
    requireThrows([&]() {validateKeyPositions(octave, 62, 60);}, "Accepted reversed note range");
  } catch (const std::exception & error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
  return 0;
}
