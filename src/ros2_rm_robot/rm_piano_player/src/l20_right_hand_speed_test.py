#!/usr/bin/env python3
"""Run the stationary right-hand speed test or list exact MIDI input names."""

import sys


if __name__ == '__main__':
    if sys.argv[1:] == ['--list-midi-inputs']:
        from rm_piano_player.midi_capture import MidiCaptureError, list_inputs

        try:
            names = list_inputs()
        except MidiCaptureError as error:
            print(f'MIDI input unavailable: {error}', file=sys.stderr)
            raise SystemExit(1)
        for name in names:
            print(name)
        if not names:
            print('No MIDI input ports found.', file=sys.stderr)
    else:
        from rm_piano_player.speed_test_node import main

        raise SystemExit(main())
