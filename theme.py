"""
Design system for S1 Command Center.

A single source of truth for the app's colours, fonts, spacing and radii so
the whole GUI stays visually consistent and can be re-themed from one place.

Direction: a modern security-console dark theme built around the SentinelOne
brand violet (#7C3AED) on a deep neutral-slate base — the look of a polished,
enterprise-grade product rather than a hobby tool.

`app.py` re-exports the legacy constant names (CARD/GREEN/ACCENT/WARN/…) from
here, and every page imports those from `app`, so changing a value below
re-themes the entire application.
"""
import sys

# ─────────────────────────────────────────────────────────────────────────
# Palette
# ─────────────────────────────────────────────────────────────────────────

# Every colour is a (LIGHT, DARK) pair. CustomTkinter widgets accept the tuple
# directly and switch with set_appearance_mode(); raw tk widgets resolve it via
# theme.tkcolor(). The DARK element is the original security-console palette.

# Surfaces — deepest → most elevated
APP_BG        = ("#F4F5F7", "#181922")   # window background behind everything
SIDEBAR_BG    = ("#ECEEF2", "#1F2029")   # left navigation rail
SIDEBAR_HOVER = ("#E0E3EA", "#2E2F3D")   # nav item hover
SIDEBAR_SEL   = ("#E6DEFB", "#3A3460")   # nav item selected (violet-tinted)
CARD          = ("#FFFFFF", "#262732")   # standard panel / card surface
CARD_ELEVATED = ("#F0F1F4", "#2F3040")   # raised surface (headers, table rows)
CONSOLE_BG    = ("#F7F8FA", "#171821")   # CLI output console
INPUT_BG      = ("#FFFFFF", "#1C1D26")   # entry / textbox fields
BORDER        = ("#D4D7DE", "#3A3B4B")   # hairline separators / input borders

# Distinct panel behind the MIGRATION nav group
MIG_PANEL     = ("#F1ECFE", "#2B2640")   # violet-tinted container
MIG_BORDER    = ("#C9BCF3", "#43396E")   # subtle violet border around it

# Brand (primary action / selection / focus)
BRAND         = ("#7C3AED", "#8B5CF6")   # SentinelOne violet
BRAND_HOVER   = ("#6D28D9", "#7C3AED")
BRAND_LIGHT   = ("#6D28D9", "#C4B5FD")   # section accents / eyebrow text

# Semantic — role + status
GREEN         = ("#059669", "#10B981")   # SOURCE / success
GREEN_HOVER   = ("#047857", "#059669")
GREEN_BG      = ("#D1FAE5", "#0C2E26")   # green-tinted chip background
ACCENT        = ("#E11D48", "#F43F5E")   # DESTINATION / danger / error
ACCENT_HOVER  = ("#BE123C", "#E11D48")
ACCENT_BG     = ("#FFE4E6", "#2E0F1A")   # rose-tinted chip background
WARN          = ("#B45309", "#F59E0B")   # warnings
WARN_HOVER    = ("#92400E", "#D97706")
INFO          = ("#0284C7", "#38BDF8")   # informational highlights

# Neutral controls — kept saturated in light mode so white button text reads
NEUTRAL       = ("#64748B", "#2B2B38")   # secondary/ghost button fill
NEUTRAL_HOVER = ("#475569", "#3A3A4A")

# Soft "ghost" utility chips (help ?, footer gear, OUTPUT toggle) — light and
# unobtrusive in light mode, subtle dark in dark mode. Pair with a BORDER.
GHOST         = ("#F0F1F4", "#2B2B38")
GHOST_HOVER   = ("#E2E5EA", "#3A3A4A")

# Text
TEXT          = ("#1A1C23", "#E7E7EE")   # primary text
TEXT_MUTED    = ("#5A6270", "#9CA3AF")   # secondary text / labels
TEXT_FAINT    = ("#8A909C", "#6B7280")   # tertiary / disabled / captions

# ─────────────────────────────────────────────────────────────────────────
# Typography — platform-native font families
# ("Segoe UI"/"Consolas" only exist on Windows; on macOS/Linux they fall
#  back to an unstyled default, which is the #1 reason the app looked
#  unpolished there. Pick the right family per OS instead.)
# ─────────────────────────────────────────────────────────────────────────

if sys.platform == "darwin":
    UI_FONT   = "SF Pro Text"   # macOS system UI font (11+)
    MONO_FONT = "Menlo"          # always present on macOS
elif sys.platform.startswith("win"):
    UI_FONT   = "Segoe UI"
    MONO_FONT = "Consolas"
else:
    UI_FONT   = "DejaVu Sans"
    MONO_FONT = "DejaVu Sans Mono"

# Type scale (size, weight) — use via theme.font(*DISPLAY) etc.
DISPLAY = (24, "bold")    # page hero / brand lockup
TITLE   = (18, "bold")    # page titles
HEADING = (15, "bold")    # section headers
SUBHEAD = (13, "bold")    # card titles
BODY    = (13, "normal")
LABEL   = (12, "normal")
CAPTION = (11, "normal")
TINY    = (9,  "bold")    # eyebrow / nav section labels


def font(size: int, weight: str = "normal"):
    """UI font tuple in the platform-native family."""
    return (UI_FONT, size, weight) if weight != "normal" else (UI_FONT, size)


def mono(size: int, weight: str = "normal"):
    """Monospace font tuple in the platform-native family."""
    return (MONO_FONT, size, weight) if weight != "normal" else (MONO_FONT, size)


# ─────────────────────────────────────────────────────────────────────────
# Spacing & radii (4px grid)
# ─────────────────────────────────────────────────────────────────────────
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24

RADIUS_SM = 6
RADIUS_MD = 10
RADIUS_LG = 14


# ─────────────────────────────────────────────────────────────────────────
# CustomTkinter global theme
# ─────────────────────────────────────────────────────────────────────────

def apply():
    """Set dark mode and patch the loaded CustomTkinter theme so every
    default-styled widget (buttons, entries, checkboxes, progress bars,
    scrollbars, …) adopts the brand palette without per-widget overrides.

    Call once at startup before any widget is created.
    """
    import customtkinter as ctk

    try:
        from config import SettingsManager
        mode = SettingsManager().get("appearance_mode", "Dark")
    except Exception:
        mode = "Dark"
    ctk.set_appearance_mode(mode)
    ctk.set_default_color_theme("blue")  # complete base; patched below

    t = ctk.ThemeManager.theme

    def dual(c):            # expand our (light, dark) tokens to CTk's [light, dark]
        if isinstance(c, (tuple, list)):
            return [c[0], c[1]]
        return [c, c]

    if "CTk" in t:
        t["CTk"]["fg_color"] = dual(APP_BG)
    if "CTkToplevel" in t:
        t["CTkToplevel"]["fg_color"] = dual(APP_BG)

    if "CTkFrame" in t:
        t["CTkFrame"].update({
            "fg_color":      dual(CARD),
            "top_fg_color":  dual(CARD_ELEVATED),
            "border_color":  dual(BORDER),
            "corner_radius": RADIUS_MD,
        })

    if "CTkButton" in t:
        t["CTkButton"].update({
            "fg_color":            dual(BRAND),
            "hover_color":         dual(BRAND_HOVER),
            "text_color":          dual("#FFFFFF"),
            "text_color_disabled": dual(TEXT_FAINT),
            "corner_radius":       RADIUS_SM,
            "border_width":        0,
        })

    if "CTkEntry" in t:
        t["CTkEntry"].update({
            "fg_color":               dual(INPUT_BG),
            "border_color":           dual(BORDER),
            "text_color":             dual(TEXT),
            "placeholder_text_color": dual(TEXT_FAINT),
            "border_width":           1,
            "corner_radius":          RADIUS_SM,
        })

    if "CTkLabel" in t:
        t["CTkLabel"]["text_color"] = dual(TEXT)

    if "CTkCheckBox" in t:
        t["CTkCheckBox"].update({
            "fg_color":      dual(BRAND),
            "hover_color":   dual(BRAND_HOVER),
            "border_color":  dual(BORDER),
            "text_color":    dual(TEXT),
        })

    if "CTkSwitch" in t:
        t["CTkSwitch"].update({
            "fg_color":           dual(("#C7CCD4", "#3A3A4A")),  # off-track
            "progress_color":     dual(BRAND),                    # on-track
            "button_color":       dual("#FFFFFF"),
            "button_hover_color": dual(("#EDEFF3", "#FFFFFF")),
        })

    if "CTkProgressBar" in t:
        t["CTkProgressBar"].update({
            "fg_color":       dual(INPUT_BG),
            "progress_color": dual(BRAND),
        })

    if "CTkSlider" in t:
        t["CTkSlider"].update({
            "button_color":       dual(BRAND),
            "button_hover_color": dual(BRAND_HOVER),
            "progress_color":     dual(BRAND_LIGHT),
        })

    if "CTkScrollbar" in t:
        t["CTkScrollbar"].update({
            "button_color":       dual(NEUTRAL),
            "button_hover_color": dual(NEUTRAL_HOVER),
        })

    if "CTkSegmentedButton" in t:
        t["CTkSegmentedButton"].update({
            "fg_color":             dual(CARD_ELEVATED),
            "selected_color":       dual(BRAND),
            "selected_hover_color": dual(BRAND_HOVER),
            "unselected_color":     dual(CARD_ELEVATED),
            "unselected_hover_color": dual(NEUTRAL_HOVER),
            "text_color":           dual(TEXT),
        })

    for combo in ("CTkComboBox", "CTkOptionMenu"):
        if combo in t:
            t[combo].update({
                "fg_color":     dual(("#FFFFFF", "#101018")),
                "button_color": dual(BRAND),
                "button_hover_color": dual(BRAND_HOVER),
                "border_color": dual(BORDER),
                "text_color":   dual(TEXT),
            })

    if "CTkTextbox" in t:
        t["CTkTextbox"].update({
            "fg_color":     dual(CARD),
            "border_color": dual(BORDER),
            "text_color":   dual(TEXT),
        })

    if "CTkScrollableFrame" in t:
        t["CTkScrollableFrame"]["label_fg_color"] = dual(CARD)

    if "DropdownMenu" in t:
        t["DropdownMenu"].update({
            "fg_color":     dual(CARD_ELEVATED),
            "hover_color":  dual(NEUTRAL_HOVER),
            "text_color":   dual(TEXT),
        })


# ─────────────────────────────────────────────────────────────────────────
# Raw-tk colour helpers
# CustomTkinter widgets take the (light, dark) tuples directly and follow
# set_appearance_mode(). Plain tk widgets (Canvas/Text/PanedWindow/tooltips)
# need a single string, so they resolve via tkcolor() and register with
# tk_track() so refresh_tk() can repaint them when the mode changes.
# ─────────────────────────────────────────────────────────────────────────
_TK_TRACKED = []


def tkcolor(token):
    """Resolve a (light, dark) token to the single hex for the active mode."""
    import customtkinter as ctk
    if isinstance(token, (tuple, list)):
        return token[0] if ctk.get_appearance_mode() == "Light" else token[1]
    return token


def tk_track(widget, apply_fn):
    """Register a raw tk widget + a function that (re)applies its colours for
    the current mode. Applies immediately and returns the widget."""
    try:
        apply_fn(widget)
    except Exception:
        pass
    _TK_TRACKED.append((widget, apply_fn))
    return widget


def refresh_tk(*_args):
    """Repaint every tracked raw tk widget for the current mode; prune dead ones."""
    global _TK_TRACKED
    alive = []
    for w, fn in _TK_TRACKED:
        try:
            if int(w.winfo_exists()):
                fn(w)
                alive.append((w, fn))
        except Exception:
            pass
    _TK_TRACKED = alive
