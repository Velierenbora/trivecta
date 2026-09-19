// Layout.cpp -- see Layout.h.

#include "app/gui/Layout.h"

#include "app/gui/Ui.h"

#include <algorithm>
#include <cmath>

namespace gui {

namespace {

// The window the sizes in this GUI were chosen against. Below it the auto
// scale shrinks so the viewport keeps its share of a small screen; above it
// it grows, up to the point where growing stops buying legibility.
constexpr float kRefW = 1600.0f;
constexpr float kRefH = 950.0f;
constexpr float kAutoMin = 0.80f;
constexpr float kAutoMax = 1.25f;

}  // namespace

void apply_style(float scale) {
    ImGuiStyle& style = ImGui::GetStyle();
    style = ImGuiStyle();
    ImGui::StyleColorsLight(&style);
    style.WindowRounding = 6.0f;
    style.FrameRounding = 5.0f;
    style.GrabRounding = 5.0f;
    style.TabRounding = 5.0f;
    style.ScrollbarRounding = 5.0f;
    style.FramePadding = ImVec2(8, 5);
    style.ItemSpacing = ImVec2(9, 7);
    ImVec4* c = style.Colors;
    // A clean, airy light theme: white surfaces, soft grey frames, a calm blue
    // accent. (Was the stock dark theme.)
    c[ImGuiCol_WindowBg]         = ImVec4(0.985f, 0.988f, 0.995f, 1.0f);
    c[ImGuiCol_ChildBg]          = ImVec4(1.000f, 1.000f, 1.000f, 1.0f);
    c[ImGuiCol_PopupBg]          = ImVec4(1.000f, 1.000f, 1.000f, 0.99f);
    c[ImGuiCol_Border]           = ImVec4(0.855f, 0.875f, 0.905f, 1.0f);
    c[ImGuiCol_FrameBg]          = ImVec4(0.945f, 0.955f, 0.970f, 1.0f);
    c[ImGuiCol_FrameBgHovered]   = ImVec4(0.900f, 0.930f, 0.975f, 1.0f);
    c[ImGuiCol_FrameBgActive]    = ImVec4(0.850f, 0.900f, 0.965f, 1.0f);
    c[ImGuiCol_Button]           = ImVec4(0.290f, 0.470f, 0.850f, 1.0f);
    c[ImGuiCol_ButtonHovered]    = ImVec4(0.220f, 0.400f, 0.800f, 1.0f);
    c[ImGuiCol_ButtonActive]     = ImVec4(0.160f, 0.330f, 0.720f, 1.0f);
    c[ImGuiCol_Text]             = ImVec4(0.105f, 0.130f, 0.170f, 1.0f);
    c[ImGuiCol_TextDisabled]     = ImVec4(0.490f, 0.530f, 0.590f, 1.0f);
    c[ImGuiCol_Header]           = ImVec4(0.900f, 0.925f, 0.965f, 1.0f);
    c[ImGuiCol_HeaderHovered]    = ImVec4(0.855f, 0.895f, 0.955f, 1.0f);
    c[ImGuiCol_HeaderActive]     = ImVec4(0.800f, 0.860f, 0.945f, 1.0f);
    c[ImGuiCol_Separator]        = ImVec4(0.870f, 0.890f, 0.915f, 1.0f);
    c[ImGuiCol_PlotLines]        = ImVec4(0.230f, 0.450f, 0.820f, 1.0f);
    c[ImGuiCol_PlotHistogram]    = ImVec4(0.290f, 0.470f, 0.850f, 1.0f);  // also ProgressBar
    style.ScaleAllSizes(scale);
    style.FontScaleMain = scale;
}

void UiScale::update(ImVec2 display_size) {
    float f = _user;
    if (f <= 0.0f) {
        const float w = display_size.x / _dpi, h = display_size.y / _dpi;
        f = std::min(w / kRefW, h / kRefH);
        f = std::clamp(f, kAutoMin, kAutoMax);
        // Snapped, so that dragging a window edge steps the interface size a
        // few times rather than reflowing it on every pixel.
        f = std::round(f * 20.0f) / 20.0f;
    }
    const float s = _dpi * f;
    if (std::fabs(s - _applied) < 1e-3f) return;
    _applied = s;
    apply_style(s);
}

// ---------------------------------------------------------------------------
// Splitters
// ---------------------------------------------------------------------------

namespace {

float grab_thickness() { return std::max(4.0f, px(6.0f)); }

void draw_grab(ImVec2 p, ImVec2 size, bool hot) {
    const ImU32 col = ImGui::GetColorU32(hot ? ImGuiCol_SeparatorActive
                                            : ImGuiCol_Separator);
    const float t = 1.0f + px(0.5f);
    ImVec2 a, b;
    if (size.x < size.y) {
        const float cx = p.x + size.x * 0.5f;
        a = ImVec2(cx - t, p.y);
        b = ImVec2(cx + t, p.y + size.y);
    } else {
        const float cy = p.y + size.y * 0.5f;
        a = ImVec2(p.x, cy - t);
        b = ImVec2(p.x + size.x, cy + t);
    }
    ImGui::GetWindowDrawList()->AddRectFilled(a, b, col);
}

}  // namespace

float splitter_extent() {
    return grab_thickness() + ImGui::GetStyle().ItemSpacing.y;
}

bool splitter_v(const char* id, float* extent, float lo, float hi, float span) {
    hi = std::max(hi, lo);   // a window too narrow for the minimum: pin it
    const float t = grab_thickness();
    ImGui::SameLine(0.0f, 0.0f);
    const ImVec2 p = ImGui::GetCursorScreenPos();
    ui::InvisibleButtonRaw(id, ImVec2(t, span));
    const bool hot = ImGui::IsItemActive() || ImGui::IsItemHovered();
    if (hot) ImGui::SetMouseCursor(ImGuiMouseCursor_ResizeEW);
    draw_grab(p, ImVec2(t, span), hot);
    ImGui::SameLine(0.0f, 0.0f);
    if (!ImGui::IsItemActive()) return false;
    const float was = *extent;
    *extent = std::clamp(*extent + ImGui::GetIO().MouseDelta.x, lo, hi);
    return *extent != was;
}

bool splitter_h(const char* id, float* extent, float lo, float hi, float span) {
    hi = std::max(hi, lo);
    const float t = grab_thickness();
    const ImVec2 p = ImGui::GetCursorScreenPos();
    ui::InvisibleButtonRaw(id, ImVec2(span, t));
    const bool hot = ImGui::IsItemActive() || ImGui::IsItemHovered();
    if (hot) ImGui::SetMouseCursor(ImGuiMouseCursor_ResizeNS);
    draw_grab(p, ImVec2(span, t), hot);
    if (!ImGui::IsItemActive()) return false;
    const float was = *extent;
    // The handle sits above the pane it sizes, so dragging up makes it taller.
    *extent = std::clamp(*extent - ImGui::GetIO().MouseDelta.y, lo, hi);
    return *extent != was;
}

// ---------------------------------------------------------------------------

std::string elide_middle(const std::string& s, float max_w) {
    if (max_w <= 0.0f || ImGui::CalcTextSize(s.c_str()).x <= max_w) return s;
    const char* kDots = "...";
    // Bytes kept from each end, grown together until the result stops fitting.
    size_t head = 0, tail = 0;
    std::string best = kDots;
    auto step_fwd = [&](size_t i) {
        i++;
        while (i < s.size() && (s[i] & 0xC0) == 0x80) i++;
        return i;
    };
    auto step_back = [&](size_t i) {
        i--;
        while (i > 0 && (s[i] & 0xC0) == 0x80) i--;
        return i;
    };
    while (true) {
        const size_t nh = step_fwd(head);
        const size_t nt = s.size() - step_back(s.size() - tail);
        if (nh + nt >= s.size()) return s;
        std::string cand = s.substr(0, nh) + kDots + s.substr(s.size() - nt);
        if (ImGui::CalcTextSize(cand.c_str()).x > max_w) return best;
        head = nh;
        tail = nt;
        best.swap(cand);
    }
}

}  // namespace gui
