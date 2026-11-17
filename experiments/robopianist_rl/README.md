# robopianist-rl

Reinforcement learning code for [RoboPianist](https://github.com/google-research/robopianist).

This workspace copy preserves the upstream [robopianist-rl](https://github.com/kevinzakka/robopianist-rl) sources at base commit `f3b62a91910eceef6d7133b876407e4c962dccbe` and the project's RM75/L20 and JAX changes. See the [RM75 integration guide](RM75.md) and the [pinned single-note baseline](../droq_single_note/README.md).

## Installation

Note: Make sure you are using the same conda environment you created for RoboPianist (see [here](https://github.com/google-research/robopianist/blob/main/README.md#installation)).

1. Install [JAX](https://github.com/google/jax#installation)
2. Run `pip install -r requirements.txt`

## Usage

From the workspace root, enter this training directory to run the example that uses the paper's task parameters for Twinkle Twinkle Little Star.

```bash
cd experiments/robopianist_rl
bash run.sh
```

To look at all the possible command-line flags, run:

```bash
python train.py --help
```

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
