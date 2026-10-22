# L20 RS485 protocol source

`rm_l20_driver/protocol.py` is adapted from the standalone L20 RS485 module
in the user's existing LinkerHand ROS 2 SDK checkout. The original license
is retained in `LICENSE` (Apache-2.0).

Source inspected and copied on 2026-10-21:

- Checkout: `/home/dianjinglab/linker_hand_ros2_sdk/src/linkerhand-ros2-sdk`
- File: `linker_hand_ros2_sdk/linker_hand_ros2_sdk/LinkerHand/core/rs485/linker_hand_l20_rs485.py`
- Repository HEAD: `ae514927f99322b2a045f851143674fdf26319fa`
- Source file SHA-256: `1a5ca6b51a5e4783df0cb2bd099050c94b47e21c9c4c0a3face5d30f87b6b73e`
- License file SHA-256: `1eb85fc97224598dad1852b5d6483bbcf0aa8608790dcc657a5a2a761ae9c8c6`

The source checkout contains local changes. These hashes identify the
actual imported files; the HEAD alone does not describe their contents.
Protocol references named in the source are retained as provenance, not
as an independent hardware validation of the implementation.

Local adaptations:

- Remove the directly executable hardware/motion demonstration.
- Honor the configured slave ID and close the serial client on failed connection.
- Reject invalid 20-value position commands rather than wrapping out-of-range bytes.
- Reject empty, erroneous, and incomplete Modbus responses, and requests after close.
- Add a ROS 2 node for position commands and state feedback, with communication
  failure handling and tests using fake clients.
- Decode UID characters low-byte first within each register, verified against two
  real read-only replies; keep ordinary numeric-register byte order unchanged.
- Add exact-UID discovery, retained exclusive serial connections, and shared
  dual-hand readiness and fault handling without automatic reconnection.

The external SDK's package loader, CAN drivers, other hand models and GUI
are not bundled in this package. The local dual-hand debug GUI is independently
implemented, referencing the SDK's joint-control layout without copying its
preset poses or depending on its packages. It uses this package's ROS topics
and saves command-pose files; the ROS driver does not expose device calibration,
flash writes, sensor configuration, or factory-reset operations.
