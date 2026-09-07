"""
backend/services/ui_detector.py
UI element detection via Windows UIA Automation (pywinauto).
Returns exact screen-pixel coordinates of named buttons/controls
in any running Windows application.
"""

from __future__ import annotations
import time
from typing import Optional

try:
    from pywinauto import Application
    from pywinauto.findwindows import ElementNotFoundError
    PYWINAUTO_AVAILABLE = True
except ImportError:
    PYWINAUTO_AVAILABLE = False
    print("[UIDetector] WARNING: pywinauto not installed. Run: pip install pywinauto")


class UIDetector:
    """
    Connects to a running Windows application and resolves
    UI element bounding rects by name + control type.
    """

    def __init__(self, app_title_pattern: str = ""):
        self.app_title_pattern = app_title_pattern
        self.app: Optional[object] = None
        self.window: Optional[object] = None
        self._connected_title: str = ""

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self, title_pattern: str = "") -> bool:
        """Connect (or reconnect) to a running application by window title pattern."""
        if not PYWINAUTO_AVAILABLE:
            print("[UIDetector] pywinauto unavailable — returning mock failure.")
            return False

        pattern = title_pattern or self.app_title_pattern
        if not pattern:
            print("[UIDetector] No title pattern provided.")
            return False

        try:
            self.app = Application(backend="uia").connect(title_re=f".*{pattern}.*")
            self.window = self.app.top_window()
            self._connected_title = self.window.window_text()
            print(f"[UIDetector] Connected to: '{self._connected_title}'")
            return True
        except Exception as e:
            print(f"[UIDetector] Failed to connect to '{pattern}': {e}")
            self.app = None
            self.window = None
            return False

    def is_connected(self) -> bool:
        """Check if still connected to a live window."""
        if self.window is None:
            return False
        try:
            _ = self.window.window_text()
            return True
        except Exception:
            self.window = None
            return False

    # ------------------------------------------------------------------
    # Element Resolution
    # ------------------------------------------------------------------

    def get_element_rect(
        self,
        title: str,
        control_type: str = "Button",
        timeout: float = 2.0,
    ) -> Optional[dict]:
        """
        Resolve the screen-space bounding rect of a named UI element.

        Returns dict:
            { x, y, left, top, width, height, label }
            where (x, y) is the center point in screen pixels.
        Returns None if element not found.
        """
        if not self.is_connected():
            print(f"[UIDetector] Not connected — cannot find '{title}'")
            return None

        candidates = self._control_type_candidates(control_type)
        for candidate in candidates:
            try:
                element = self.window.child_window(
                    title=title,
                    control_type=candidate,
                )
                rect = element.rectangle()
                if rect and rect.left >= 0 and rect.right > rect.left:
                    center_x = (rect.left + rect.right) // 2
                    center_y = (rect.top + rect.bottom) // 2
                    return {
                        "x": center_x,
                        "y": center_y,
                        "left": rect.left,
                        "top": rect.top,
                        "width": rect.right - rect.left,
                        "height": rect.bottom - rect.top,
                        "label": title,
                        "type": candidate,
                    }
            except Exception:
                continue

        # Fallback: search by title only across common control types
        for candidate in self._common_control_types():
            try:
                element = self.window.child_window(
                    title=title,
                    control_type=candidate,
                )
                rect = element.rectangle()
                if rect and rect.left >= 0 and rect.right > rect.left:
                    center_x = (rect.left + rect.right) // 2
                    center_y = (rect.top + rect.bottom) // 2
                    return {
                        "x": center_x,
                        "y": center_y,
                        "left": rect.left,
                        "top": rect.top,
                        "width": rect.right - rect.left,
                        "height": rect.bottom - rect.top,
                        "label": title,
                        "type": candidate,
                    }
            except Exception:
                continue

        print(f"[UIDetector] Element '{title}' ({control_type}) not found after fallback attempts")
        return None

    def get_multiple_elements(self, targets: list[dict]) -> list[dict]:
        """
        Resolve a list of LLM-generated step targets.

        Input format (from LLMCopilotService):
            [{"action": "click", "target": "Bold", "type": "Button"}, ...]

        Output: List of resolved rects with action embedded.
        Elements that cannot be found are skipped gracefully.
        """
        results = []
        for step in targets:
            target_name = step.get("target", "")
            control_type = step.get("type", "Button")
            action = step.get("action", "click")
            value = step.get("value", "")

            rect = self.get_element_rect(target_name, control_type)
            if rect:
                rect["action"] = action
                rect["resolved"] = True
                if value:
                    rect["value"] = value
                results.append(rect)
            else:
                # Include as unresolved so Unity can show a warning
                results.append({
                    "x": -1,
                    "y": -1,
                    "label": target_name,
                    "type": control_type,
                    "action": action,
                    "resolved": False,
                    "error": f"Element '{target_name}' not found in {self._connected_title}",
                })

        print(f"[UIDetector] Resolved {len([r for r in results if r.get('x', -1) >= 0])}/{len(results)} elements")
        return results

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def list_all_controls(self) -> list[dict]:
        """
        Dump primary UI controls in the connected window.
        Avoid descending the entire tree as apps like MS Word have 10,000+ elements
        which will hang pywinauto indefinitely.
        """
        if not self.is_connected():
            return []
        
        # We skip full enumeration for LLM context to prevent hanging and context overflow.
        # Returning an empty list makes the LLM rely on its pre-trained knowledge 
        # of common app interfaces, which works better for local 4B models.
        return []

    def get_control_titles_for_prompt(self) -> str:
        """
        Return a compact string listing common control names.
        Disabled to prevent confusing small models (like qwen3-vl:4b) with
        too much token bloat, ensuring they format JSON cleanly.
        """
        return ""

    def _control_type_candidates(self, control_type: str) -> list[str]:
        raw = str(control_type or "Button").strip()
        key = raw.lower().replace("_", " ")

        mapped = {
            "button": ["Button"],
            "menuitem": ["MenuItem"],
            "menu item": ["MenuItem"],
            "menu": ["MenuItem"],
            "tab": ["TabItem"],
            "tabitem": ["TabItem"],
            "tab item": ["TabItem"],
            "edit": ["Edit"],
            "textbox": ["Edit"],
            "text box": ["Edit"],
            "combobox": ["ComboBox"],
            "combo box": ["ComboBox"],
            "chart type": ["MenuItem", "ListItem", "Button"],
            "listitem": ["ListItem"],
            "list item": ["ListItem"],
        }

        if key in mapped:
            return mapped[key]

        # If model already returned a valid UIA type-like token, try it first.
        normalized = raw[:1].upper() + raw[1:] if raw else "Button"
        candidates = [normalized]
        for common in self._common_control_types():
            if common not in candidates:
                candidates.append(common)
        return candidates

    def _common_control_types(self) -> list[str]:
        return [
            "Button",
            "TabItem",
            "MenuItem",
            "Edit",
            "ComboBox",
            "ListItem",
            "TreeItem",
            "Hyperlink",
            "Text",
        ]
