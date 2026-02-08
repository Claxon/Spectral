"""Color themes and gradient helpers for the Spectrum Analyzer."""

from dataclasses import dataclass
from config import ColorTheme


@dataclass
class ThemeColors:
    background: tuple
    text: tuple
    grid: tuple
    bar_gradient_low: tuple     # green / cool
    bar_gradient_mid: tuple     # yellow / warm
    bar_gradient_high: tuple    # red / hot
    line_color: tuple
    line_fill: tuple
    peak_marker: tuple
    rms_meter: tuple
    peak_meter: tuple
    spectrogram_colormap: int   # implot colormap index
    waveform_color: tuple
    window_bg: tuple
    border: tuple
    title_bg: tuple
    title_bg_active: tuple
    frame_bg: tuple
    frame_bg_hovered: tuple
    frame_bg_active: tuple
    button: tuple
    button_hovered: tuple
    button_active: tuple
    slider_grab: tuple
    header: tuple
    header_hovered: tuple
    separator: tuple


THEMES: dict[ColorTheme, ThemeColors] = {
    ColorTheme.DARK: ThemeColors(
        background=(0.06, 0.06, 0.08, 1.0),
        text=(0.92, 0.92, 0.94, 1.0),
        grid=(0.25, 0.25, 0.3, 0.4),
        bar_gradient_low=(0.08, 0.72, 0.28, 1.0),
        bar_gradient_mid=(0.95, 0.82, 0.08, 1.0),
        bar_gradient_high=(0.95, 0.12, 0.08, 1.0),
        line_color=(0.3, 0.7, 1.0, 1.0),
        line_fill=(0.3, 0.7, 1.0, 0.15),
        peak_marker=(1.0, 1.0, 1.0, 0.85),
        rms_meter=(0.2, 0.75, 0.35, 1.0),
        peak_meter=(0.95, 0.2, 0.2, 1.0),
        spectrogram_colormap=4,  # Viridis
        waveform_color=(0.3, 0.85, 0.45, 1.0),
        window_bg=(0.08, 0.08, 0.10, 0.97),
        border=(0.22, 0.22, 0.28, 0.65),
        title_bg=(0.10, 0.10, 0.14, 1.0),
        title_bg_active=(0.16, 0.16, 0.22, 1.0),
        frame_bg=(0.14, 0.14, 0.18, 1.0),
        frame_bg_hovered=(0.22, 0.22, 0.28, 1.0),
        frame_bg_active=(0.28, 0.28, 0.35, 1.0),
        button=(0.20, 0.22, 0.30, 1.0),
        button_hovered=(0.28, 0.32, 0.42, 1.0),
        button_active=(0.35, 0.40, 0.52, 1.0),
        slider_grab=(0.40, 0.50, 0.70, 1.0),
        header=(0.18, 0.20, 0.28, 1.0),
        header_hovered=(0.25, 0.28, 0.38, 1.0),
        separator=(0.28, 0.28, 0.35, 0.5),
    ),

    ColorTheme.NEON_CYBERPUNK: ThemeColors(
        background=(0.02, 0.0, 0.06, 1.0),
        text=(0.0, 1.0, 0.92, 1.0),
        grid=(0.18, 0.0, 0.35, 0.5),
        bar_gradient_low=(0.0, 0.35, 1.0, 1.0),
        bar_gradient_mid=(0.75, 0.0, 1.0, 1.0),
        bar_gradient_high=(1.0, 0.0, 0.45, 1.0),
        line_color=(0.0, 1.0, 0.85, 1.0),
        line_fill=(0.0, 1.0, 0.85, 0.12),
        peak_marker=(1.0, 0.0, 0.85, 0.9),
        rms_meter=(0.0, 0.85, 1.0, 1.0),
        peak_meter=(1.0, 0.0, 0.55, 1.0),
        spectrogram_colormap=5,  # Plasma
        waveform_color=(0.0, 1.0, 0.65, 1.0),
        window_bg=(0.03, 0.0, 0.08, 0.97),
        border=(0.35, 0.0, 0.55, 0.6),
        title_bg=(0.06, 0.0, 0.12, 1.0),
        title_bg_active=(0.12, 0.0, 0.22, 1.0),
        frame_bg=(0.08, 0.0, 0.15, 1.0),
        frame_bg_hovered=(0.15, 0.0, 0.28, 1.0),
        frame_bg_active=(0.22, 0.0, 0.38, 1.0),
        button=(0.15, 0.0, 0.30, 1.0),
        button_hovered=(0.25, 0.0, 0.45, 1.0),
        button_active=(0.35, 0.0, 0.55, 1.0),
        slider_grab=(0.5, 0.0, 0.85, 1.0),
        header=(0.12, 0.0, 0.25, 1.0),
        header_hovered=(0.20, 0.0, 0.38, 1.0),
        separator=(0.35, 0.0, 0.55, 0.4),
    ),

    ColorTheme.WARM_SUNSET: ThemeColors(
        background=(0.10, 0.06, 0.04, 1.0),
        text=(1.0, 0.92, 0.82, 1.0),
        grid=(0.35, 0.22, 0.12, 0.45),
        bar_gradient_low=(1.0, 0.65, 0.15, 1.0),
        bar_gradient_mid=(1.0, 0.35, 0.10, 1.0),
        bar_gradient_high=(0.85, 0.08, 0.15, 1.0),
        line_color=(1.0, 0.55, 0.2, 1.0),
        line_fill=(1.0, 0.55, 0.2, 0.15),
        peak_marker=(1.0, 0.95, 0.65, 0.9),
        rms_meter=(1.0, 0.65, 0.2, 1.0),
        peak_meter=(0.9, 0.15, 0.15, 1.0),
        spectrogram_colormap=6,  # Hot
        waveform_color=(1.0, 0.72, 0.3, 1.0),
        window_bg=(0.12, 0.07, 0.05, 0.97),
        border=(0.40, 0.25, 0.15, 0.6),
        title_bg=(0.14, 0.08, 0.04, 1.0),
        title_bg_active=(0.22, 0.12, 0.06, 1.0),
        frame_bg=(0.18, 0.10, 0.06, 1.0),
        frame_bg_hovered=(0.28, 0.16, 0.08, 1.0),
        frame_bg_active=(0.35, 0.20, 0.10, 1.0),
        button=(0.30, 0.16, 0.08, 1.0),
        button_hovered=(0.42, 0.22, 0.10, 1.0),
        button_active=(0.52, 0.28, 0.12, 1.0),
        slider_grab=(0.85, 0.45, 0.15, 1.0),
        header=(0.25, 0.14, 0.06, 1.0),
        header_hovered=(0.35, 0.20, 0.08, 1.0),
        separator=(0.40, 0.25, 0.12, 0.4),
    ),

    ColorTheme.OCEAN: ThemeColors(
        background=(0.02, 0.06, 0.10, 1.0),
        text=(0.78, 0.92, 1.0, 1.0),
        grid=(0.10, 0.25, 0.38, 0.45),
        bar_gradient_low=(0.0, 0.55, 0.75, 1.0),
        bar_gradient_mid=(0.15, 0.80, 0.65, 1.0),
        bar_gradient_high=(0.45, 0.95, 0.85, 1.0),
        line_color=(0.2, 0.75, 0.95, 1.0),
        line_fill=(0.2, 0.75, 0.95, 0.15),
        peak_marker=(0.65, 0.95, 1.0, 0.9),
        rms_meter=(0.15, 0.70, 0.85, 1.0),
        peak_meter=(0.35, 0.90, 0.75, 1.0),
        spectrogram_colormap=4,  # Viridis
        waveform_color=(0.25, 0.82, 0.92, 1.0),
        window_bg=(0.03, 0.07, 0.12, 0.97),
        border=(0.12, 0.28, 0.42, 0.6),
        title_bg=(0.04, 0.10, 0.16, 1.0),
        title_bg_active=(0.06, 0.16, 0.25, 1.0),
        frame_bg=(0.06, 0.12, 0.20, 1.0),
        frame_bg_hovered=(0.10, 0.20, 0.30, 1.0),
        frame_bg_active=(0.14, 0.26, 0.38, 1.0),
        button=(0.08, 0.18, 0.30, 1.0),
        button_hovered=(0.12, 0.28, 0.42, 1.0),
        button_active=(0.16, 0.35, 0.52, 1.0),
        slider_grab=(0.20, 0.55, 0.78, 1.0),
        header=(0.06, 0.16, 0.28, 1.0),
        header_hovered=(0.10, 0.25, 0.38, 1.0),
        separator=(0.12, 0.28, 0.42, 0.4),
    ),

    ColorTheme.LIGHT: ThemeColors(
        background=(0.95, 0.95, 0.97, 1.0),
        text=(0.10, 0.10, 0.12, 1.0),
        grid=(0.70, 0.70, 0.75, 0.4),
        bar_gradient_low=(0.15, 0.60, 0.30, 1.0),
        bar_gradient_mid=(0.85, 0.72, 0.10, 1.0),
        bar_gradient_high=(0.85, 0.18, 0.15, 1.0),
        line_color=(0.15, 0.45, 0.80, 1.0),
        line_fill=(0.15, 0.45, 0.80, 0.15),
        peak_marker=(0.55, 0.15, 0.15, 0.85),
        rms_meter=(0.18, 0.62, 0.32, 1.0),
        peak_meter=(0.82, 0.18, 0.18, 1.0),
        spectrogram_colormap=4,  # Viridis
        waveform_color=(0.20, 0.55, 0.30, 1.0),
        window_bg=(0.96, 0.96, 0.98, 0.97),
        border=(0.75, 0.75, 0.80, 0.5),
        title_bg=(0.88, 0.88, 0.92, 1.0),
        title_bg_active=(0.78, 0.78, 0.85, 1.0),
        frame_bg=(0.88, 0.88, 0.92, 1.0),
        frame_bg_hovered=(0.80, 0.80, 0.86, 1.0),
        frame_bg_active=(0.72, 0.72, 0.80, 1.0),
        button=(0.78, 0.78, 0.85, 1.0),
        button_hovered=(0.68, 0.68, 0.78, 1.0),
        button_active=(0.58, 0.58, 0.70, 1.0),
        slider_grab=(0.40, 0.50, 0.72, 1.0),
        header=(0.82, 0.82, 0.88, 1.0),
        header_hovered=(0.72, 0.72, 0.80, 1.0),
        separator=(0.72, 0.72, 0.78, 0.4),
    ),
}


def apply_imgui_theme(theme: ThemeColors) -> None:
    """Apply theme colors to the imgui style."""
    from imgui_bundle import imgui

    style = imgui.get_style()

    def s(col_enum, rgba):
        style.set_color_(col_enum, imgui.ImVec4(*rgba))

    s(imgui.Col_.window_bg, theme.window_bg)
    s(imgui.Col_.text, theme.text)
    s(imgui.Col_.border, theme.border)
    s(imgui.Col_.title_bg, theme.title_bg)
    s(imgui.Col_.title_bg_active, theme.title_bg_active)
    s(imgui.Col_.frame_bg, theme.frame_bg)
    s(imgui.Col_.frame_bg_hovered, theme.frame_bg_hovered)
    s(imgui.Col_.frame_bg_active, theme.frame_bg_active)
    s(imgui.Col_.button, theme.button)
    s(imgui.Col_.button_hovered, theme.button_hovered)
    s(imgui.Col_.button_active, theme.button_active)
    s(imgui.Col_.slider_grab, theme.slider_grab)
    s(imgui.Col_.slider_grab_active, theme.slider_grab)
    s(imgui.Col_.header, theme.header)
    s(imgui.Col_.header_hovered, theme.header_hovered)
    s(imgui.Col_.header_active, theme.header_hovered)
    s(imgui.Col_.separator, theme.separator)
    s(imgui.Col_.check_mark, theme.slider_grab)
    s(imgui.Col_.tab, theme.title_bg)
    s(imgui.Col_.tab_hovered, theme.header_hovered)

    style.window_rounding = 6.0
    style.frame_rounding = 4.0
    style.grab_rounding = 3.0
    style.tab_rounding = 4.0
    style.scrollbar_rounding = 6.0
    style.window_border_size = 1.0
    style.frame_border_size = 0.0
    style.item_spacing = imgui.ImVec2(8, 6)
    style.frame_padding = imgui.ImVec2(6, 4)


def lerp_color(t: float, low: tuple, mid: tuple, high: tuple) -> tuple:
    """Gradient interpolation: t in [0,1]. 0..0.5->low..mid, 0.5..1->mid..high."""
    if t < 0.5:
        s = t * 2.0
        return tuple(a + (b - a) * s for a, b in zip(low, mid))
    else:
        s = (t - 0.5) * 2.0
        return tuple(a + (b - a) * s for a, b in zip(mid, high))


def color_to_u32(r: float, g: float, b: float, a: float = 1.0) -> int:
    """Convert RGBA floats to packed u32 color."""
    ri = max(0, min(255, int(r * 255)))
    gi = max(0, min(255, int(g * 255)))
    bi = max(0, min(255, int(b * 255)))
    ai = max(0, min(255, int(a * 255)))
    return (ai << 24) | (bi << 16) | (gi << 8) | ri
