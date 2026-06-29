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

# Surfaces — deepest → most elevated (a refined slate-charcoal, not near-black)
APP_BG        = "#181922"   # window background behind everything
SIDEBAR_BG    = "#1F2029"   # left navigation rail
SIDEBAR_HOVER = "#2E2F3D"   # nav item hover
SIDEBAR_SEL   = "#3A3460"   # nav item selected (violet-tinted)
CARD          = "#262732"   # standard panel / card surface
CARD_ELEVATED = "#2F3040"   # raised surface (headers, table rows)
CONSOLE_BG    = "#171821"   # CLI output console (darker for contrast)
INPUT_BG      = "#1C1D26"   # entry / textbox fields
BORDER        = "#3A3B4B"   # hairline separators / input borders

# Distinct panel behind the MIGRATION nav group
MIG_PANEL     = "#2B2640"   # violet-tinted container
MIG_BORDER    = "#43396E"   # subtle violet border around it

# Brand (primary action / selection / focus)
BRAND         = "#8B5CF6"   # SentinelOne violet (slightly brighter on lighter bg)
BRAND_HOVER   = "#7C3AED"
BRAND_LIGHT   = "#C4B5FD"   # for text/icons on dark, section accents

# Semantic — role + status
GREEN         = "#10B981"   # SOURCE / success
GREEN_HOVER   = "#059669"
GREEN_BG      = "#0C2E26"   # green-tinted chip background
ACCENT        = "#F43F5E"   # DESTINATION / danger / error (rose-red)
ACCENT_HOVER  = "#E11D48"
ACCENT_BG     = "#2E0F1A"   # rose-tinted chip background
WARN          = "#F59E0B"   # warnings
WARN_HOVER    = "#D97706"
INFO          = "#38BDF8"   # informational highlights

# Neutral controls
NEUTRAL       = "#2B2B38"   # secondary/ghost button fill
NEUTRAL_HOVER = "#3A3A4A"

# Text
TEXT          = "#E7E7EE"   # primary text
TEXT_MUTED    = "#9CA3AF"   # secondary text / labels
TEXT_FAINT    = "#6B7280"   # tertiary / disabled / captions

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

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")  # complete base; patched below

    t = ctk.ThemeManager.theme

    def dual(c):            # CTk colours are [light, dark]; we run dark-only
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
            "progress_color": dual(BRAND),
            "button_color":   dual("#FFFFFF"),
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
                "fg_color":     dual("#101018"),
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
