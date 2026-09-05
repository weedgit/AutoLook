"""Suppress noisy third-party console warnings (PyTorch / EasyOCR / NudeNet)."""

import logging
import os
import warnings


def silence_third_party_noise():
    """Call once at process start, before loading ML models."""
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    warnings.filterwarnings(
        "ignore",
        message=r".*pin_memory.*",
        category=UserWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r".*quantize_per_tensor.*",
        category=UserWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r".*quantized tensor.*",
        category=UserWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r".*accelerator is found.*",
        category=UserWarning,
    )
    # Torch / torchvision chatter
    for name in (
        "torch",
        "torchvision",
        "easyocr",
        "nudenet",
        "PIL",
    ):
        logging.getLogger(name).setLevel(logging.ERROR)
