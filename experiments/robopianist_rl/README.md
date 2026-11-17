# robopianist-rl

Reinforcement learning code for [RoboPianist](https://github.com/google-research/robopianist).

This workspace copy preserves the upstream [robopianist-rl](https://github.com/kevinzakka/robopianist-rl) sources at base commit `f3b62a91910eceef6d7133b876407e4c962dccbe` and the project's RM75/L20 and JAX changes. See the [RM75 integration guide](RM75.md) and the [pinned single-note baseline](../droq_single_note/README.md).

## Installation

The scripts use the [bundled RoboPianist runtime](../../third_party/robopianist/README.md). Set up the Python and MuJoCo dependencies from the [single-note baseline guide](../droq_single_note/README.md), then install this directory's `requirements.txt` for the generic `train.py` runner.

## Usage

From the workspace root, run the RM75/L20 example on the built-in Twinkle Twinkle Little Star score.

```bash
bash experiments/robopianist_rl/run.sh
```

To look at all the possible command-line flags, run:

```bash
python experiments/robopianist_rl/train.py --help
```

Evaluation logs MIDI metrics by default. To record video with synthesized audio, set `ROBOPIANIST_SOUNDFONT` and pass `--record-dir`.

## Citation

If you use this code, please cite our paper:

```bibtex
@article{zakka2023robopianist,
  author = {Zakka, Kevin and Smith, Laura and Gileadi, Nimrod and Howell, Taylor and Peng, Xue Bin and Singh, Sumeet and Tassa, Yuval and Florence, Pete and Zeng, Andy and Abbeel, Pieter},
  title = {{RoboPianist: A Benchmark for High-Dimensional Robot Control}},
  journal = {arXiv preprint arXiv:2304.04150},
  year = {2023},
}
```
