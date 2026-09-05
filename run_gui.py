"""Convenience launcher: python run_gui.py"""

from autolook.utils.silence import silence_third_party_noise

silence_third_party_noise()

from autolook.gui.main_window import run_gui

if __name__ == "__main__":
    run_gui()
