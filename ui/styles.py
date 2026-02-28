class StyleProvider:
    """Centralized stylesheet patterns and color definitions for the application."""
    
    @staticmethod
    def get_container_style(is_light_theme: bool, is_interactable: bool) -> str:
        """Returns the dynamic QSS string for the main rounded container frame."""
        if is_interactable:
            if is_light_theme:
                return "QFrame#container { background-color: rgba(220, 220, 220, 240); border: 1px solid #888; border-radius: 15px; }"
            else:
                return "QFrame#container { background-color: rgba(40, 40, 40, 240); border: 1px solid #666; border-radius: 15px; }"
        else:
            if is_light_theme:
                return "QFrame#container { background-color: rgba(240, 240, 240, 220); border: 1px solid #ccc; border-radius: 15px; }"
            else:
                return "QFrame#container { background-color: rgba(20, 20, 20, 200); border-radius: 15px; }"

    @staticmethod
    def get_scrollbar_style() -> str:
        return """
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.2);
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.4);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                background: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """

    @staticmethod
    def apply_theme_to_labels(is_light: bool, title_lbl, artist_lbl, lyrics_lbls, unsynced_lbl):
        """Applies dynamic font colors based on the current theme mode."""
        if is_light:
            title_lbl.setStyleSheet("color: black;")
            artist_lbl.setStyleSheet("color: #444444;")
            for i, lbl in enumerate(lyrics_lbls):
                if i == 2:
                    lbl.setStyleSheet("color: black;")
                else:
                    lbl.setStyleSheet("color: #555555;")
            unsynced_lbl.setStyleSheet("color: rgba(0, 0, 0, 230); font-size: 18px; font-weight: bold; background: transparent;")
        else:
            title_lbl.setStyleSheet("color: white;")
            artist_lbl.setStyleSheet("color: #aaaaaa;")
            for i, lbl in enumerate(lyrics_lbls):
                if i == 2:
                    lbl.setStyleSheet("color: white;")
                else:
                    lbl.setStyleSheet("color: #777777;")
            unsynced_lbl.setStyleSheet("color: rgba(255, 255, 255, 230); font-size: 18px; font-weight: bold; background: transparent;")
