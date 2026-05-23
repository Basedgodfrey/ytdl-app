"""
Canopy — YouTube Downloader for macOS
Entry point: imports CanopyApp from the canopy package and launches it.
"""

import customtkinter as ctk
from canopy.ui.main_window import CanopyApp


def main() -> None:
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("green")
    root = ctk.CTk()
    CanopyApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
