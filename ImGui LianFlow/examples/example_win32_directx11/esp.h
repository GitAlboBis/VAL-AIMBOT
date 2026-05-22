#pragma once
// https://discord.authguards.com/
// https://authguards.com/
#include <array>
#include <string>
#include "imgui.h"
#include "imgui_internal.h"

static int esp_scale = 19;

class c_esp_drag {
public:
    class Box_t {
    public:
        int x, y, w, h;
    };

    struct Position {
        ImVec2 pos;
    };

    class c_drag_item {
    public:
        int pos;
        int type;
        ImColor col;
        std::string text;
        std::string name;
        bool small_text = false;
        ImVec2 pos_;
        ImVec2 size;
        bool hovered = false;
        int helding = 0;
        float move_animation = 0;
        float animations[6];
        bool enabled = true;
        int think_pos;
        bool enable_popup;
        int font;
    };

    std::array<c_drag_item, 8> m_items = {
        c_drag_item{0, 1, ImColor(0, 255, 12), "Health bar", "Health bar"},
        c_drag_item{ 3, 1, ImColor(25, 120, 245), "Ammo bar" , "Ammo bar"},
        c_drag_item{ 2, 0, ImColor(255,255,255), "Nickname", "Lyapos"},
        c_drag_item{ 1, 0, ImColor(255,255,255), "HK", "HK", 1},
        c_drag_item{ 1, 0, ImColor(25, 110, 245), "Scoped", "SCOPED", 1},
        c_drag_item{ 1, 0, ImColor(255,120,0), "FD", "FD", 1} ,
        c_drag_item{ 1, 0, ImColor(255,0,0), "C4", "C4", 1},
        c_drag_item{ 3, 0, ImColor(255,255,255), "SCAR-20", "SCAR-20"}};
    int m_offsets[8];
    Box_t box;

    int find_closest_position(ImVec2 curr, Position positions[]) {
        float closest = FLT_MAX;
        int best = -1;
        for (int i = 0; i < 4; i++) {
            auto pos = positions[i].pos;
            float dist = pos.dist_to(curr);

            if (closest > dist) {
                closest = dist;
                best = i;
            }
        }

        return best;
    }

    void set_positions() {
        Position Positions[] = {
            {ImVec2(ImGui::GetWindowPos().x + box.x - 5, ImGui::GetWindowPos().y + box.y)}, // l
            {ImVec2(ImGui::GetWindowPos().x + box.x + box.w + 2, ImGui::GetWindowPos().y + box.y)}, // r
            {ImVec2(ImGui::GetWindowPos().x + box.x, ImGui::GetWindowPos().y + box.y - 5)},
            {ImVec2(ImGui::GetWindowPos().x + box.x, ImGui::GetWindowPos().y + box.y + box.h + 2)},
        };

        auto mouse_in_region = [&](ImVec2 pos, ImVec2 size) -> bool {
            auto m_pos = ImGui::GetMousePos();
            if (m_pos.x >= pos.x && m_pos.y >= pos.y &&
                m_pos.x <= pos.x + size.x && m_pos.y <= pos.y + size.y)
                return true;
            return false;
        };

        for (int i = 0; i < m_items.size(); i++) {
            auto& item = m_items[i];
            if (!item.enabled)
                continue;
            ImGui::PushID(i);
            ImGui::SetCursorScreenPos(item.pos_);
            ImGui::PushStyleVar(0, 0.0f);
            ImGui::Button((u8"#я ебу собак" + item.text).c_str(), item.size);
            bool hovered = ImGui::IsItemHovered();
            ImGui::PopStyleVar();

            int pos = find_closest_position(ImGui::GetMousePos(), Positions);
            item.hovered = false;
            if (ImGui::BeginDragDropSource(ImGuiDragDropFlags_SourceNoPreviewTooltip)) {
                ImGui::SetDragDropPayload("#я ебу собак", &i, sizeof(int), 0);
                for (int t = 0; t < m_items.size(); t++)
                    m_items[t].move_animation = ImGui::GetIO().DeltaTime * 34.f;

                item.pos = 4, item.think_pos = pos;
                item.helding = pos > 1, item.hovered = true;
                ImGui::EndDragDropSource();
            }
            else if (item.pos == 4) {
                item.pos = item.think_pos;
                item.think_pos = -1;
                item.move_animation = 0.f;
            }
            item.animations[0] = ImLerp(item.animations[0], item.hovered || hovered ? 1.f : 0.f, ImGui::GetIO().DeltaTime * 34.f);
            ImGui::GetWindowDrawList()->AddRect(item.pos_ - ImVec2(1, 1), item.pos_ + item.size + ImVec2(1, 1), ImColor(255, 255, 255, int(255 * item.animations[0])));
            ImGui::PopID();
        }
    }

    void on_draw() {
        box.x = 75, box.y = 47;
        box.w = 139; box.h = 262;

        Position Positions[] = {
            {ImVec2(ImGui::GetWindowPos().x + box.x - 5, ImGui::GetWindowPos().y + box.y)},
            {ImVec2(ImGui::GetWindowPos().x + box.x + box.w + 2, ImGui::GetWindowPos().y + box.y)},
            {ImVec2(ImGui::GetWindowPos().x + box.x, ImGui::GetWindowPos().y + box.y - 5)},
            {ImVec2(ImGui::GetWindowPos().x + box.x, ImGui::GetWindowPos().y + box.y + box.h + 2)},
        };

        ImVec2 Sizes[] = {
            ImVec2(2 + esp_scale - 15, box.h), // l
            ImVec2(2 + esp_scale - 15, box.h), // r
            ImVec2(box.w, 2 + esp_scale - 15),
            ImVec2(box.w, 2 + esp_scale - 15)
        };

        { // Box
            ImGui::GetWindowDrawList()->AddRect(ImVec2(ImGui::GetWindowPos().x + box.x, ImGui::GetWindowPos().y + box.y),
                ImVec2(ImGui::GetWindowPos().x + box.x + box.w, ImGui::GetWindowPos().y + box.y + box.h), ImColor(255, 255, 255, int(255 * ImGui::GetStyle().Alpha)));

            ImGui::GetWindowDrawList()->AddRect(ImVec2(ImGui::GetWindowPos().x + box.x - 1, ImGui::GetWindowPos().y + box.y - 1),
                ImVec2(ImGui::GetWindowPos().x + box.x + box.w + 1, ImGui::GetWindowPos().y + box.y + box.h + 1), ImColor(0, 0, 0, int(255 * ImGui::GetStyle().Alpha)));

            ImGui::GetWindowDrawList()->AddRect(ImVec2(ImGui::GetWindowPos().x + box.x + 1, ImGui::GetWindowPos().y + box.y + 1),
                ImVec2(ImGui::GetWindowPos().x + box.x + box.w - 1, ImGui::GetWindowPos().y + box.y + box.h - 1), ImColor(0, 0, 0, int(255 * ImGui::GetStyle().Alpha)));
        }

        float offsetY = 0.f;

        for (auto& item : m_items) {
            item.animations[2] = ImLerp(item.animations[2], item.enabled ? 1.f : 0.f, ImGui::GetIO().DeltaTime * 34.f);
            if (item.animations[2] < 0.1f) {
                for (int i = 0; i < m_items.size(); i++)
                    m_items[i].move_animation = ImGui::GetIO().DeltaTime * 34.f;
                continue;
            }
            else if (item.animations[2] > 0.f && item.animations[2] < 0.1f) {
                for (int i = 0; i < m_items.size(); i++)
                    m_items[i].move_animation = ImGui::GetIO().DeltaTime * 34.f;
            }

            item.move_animation += ImGui::GetIO().DeltaTime * 34.f;
            item.move_animation = ImClamp(item.move_animation, 0.f, 1.f);

            if (item.hovered) {
                //ImGui::PushFont(esp_font1[esp_scale - 4]);

                auto size = ImGui::CalcTextSize(item.text.c_str());
                static bool s = true;
                if (s) {
                    item.size = size;
                    s = false;
                }
                if (item.small_text)
                    size.y = 12;

                switch (item.think_pos) {
                case 0:
                    item.type == 0 ? m_offsets[4] += 2.f + size.y + offsetY : m_offsets[0] += 5.f;
                    break;
                case 1:
                    item.type == 0 ? m_offsets[5] += 2.f + size.y + offsetY : m_offsets[1] += 5.f;
                    break;
                case 2:
                    item.type == 0 ? m_offsets[6] += 2.f + size.y + offsetY : m_offsets[2] += 5.f;
                    break;
                case 3:
                    item.type == 0 ? m_offsets[7] += 2.f + size.y + offsetY : m_offsets[3] += 5.f;
                    break;
                }

                offsetY += size.y;

                //ImGui::PopFont();
            }

            if (item.type == 0) {
                //ImGui::PushFont(esp_font1[!item.small_text ? esp_scale : esp_scale - 6]);

                auto size = ImGui::CalcTextSize(item.text.c_str());
                item.size = size;
                if (item.small_text)
                    size.y = 12;

                switch (item.pos) {
                case 0:
                    item.pos_ = ImLerp(item.pos_, Positions[0].pos + ImVec2(-m_offsets[0] - size.x, m_offsets[4]), item.move_animation);
                    ImGui::GetWindowDrawList()->AddText(item.pos_ - ImVec2(1, 0), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_ + ImVec2(0, 1), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_ - ImVec2(0, 1), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_ + ImVec2(1, 0), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_, item.col.SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    m_offsets[4] += 2.f + size.y;
                    break;
                case 1:
                    item.pos_ = ImLerp(item.pos_, Positions[1].pos + ImVec2(m_offsets[1] + esp_scale - 15, m_offsets[5]), item.move_animation);
                    ImGui::GetWindowDrawList()->AddText(item.pos_ - ImVec2(1, 0), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_ + ImVec2(0, 1), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_ - ImVec2(0, 1), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_ + ImVec2(1, 0), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_, item.col.SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    m_offsets[5] += size.y;
                    break;
                case 2:
                    item.pos_ = ImLerp(item.pos_, Positions[2].pos + ImVec2(Sizes[2].x / 2.f - size.x / 2.f, -m_offsets[2] - size.y - m_offsets[6]), item.move_animation);
                    ImGui::GetWindowDrawList()->AddText(item.pos_ - ImVec2(1, 0), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_ + ImVec2(0, 1), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_ - ImVec2(0, 1), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_ + ImVec2(1, 0), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_, item.col.SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    m_offsets[6] += 2.f + size.y;
                    break;
                case 3:
                    item.pos_ = ImLerp(item.pos_, Positions[3].pos + ImVec2(Sizes[2].x / 2.f - size.x / 2.f, m_offsets[3] + m_offsets[7]), item.move_animation);
                    ImGui::GetWindowDrawList()->AddText(item.pos_ - ImVec2(1, 0), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_ + ImVec2(0, 1), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_ - ImVec2(0, 1), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_ + ImVec2(1, 0), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_, item.col.SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    m_offsets[7] += 2.f + size.y;
                    break;
                case 4:
                    item.pos_ = ImLerp(item.pos_, ImGui::GetMousePos() + ImVec2(-size.x / 2.f, 0), ImGui::GetIO().DeltaTime * 14.f);
                    ImGui::GetWindowDrawList()->AddText(item.pos_ - ImVec2(1, 0), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_ + ImVec2(0, 1), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_ - ImVec2(0, 1), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_ + ImVec2(1, 0), ImColor(0, 0, 0).SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    ImGui::GetWindowDrawList()->AddText(item.pos_, item.col.SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha), item.text.c_str());
                    break;
                }

                //ImGui::PopFont();

                continue;
            }
            item.size = Sizes[item.pos];
            switch (item.pos) {
            case 0:
                item.pos_ = ImLerp(item.pos_, Positions[0].pos + ImVec2(-m_offsets[0] + 15 - esp_scale, 0.f), item.move_animation);
                ImGui::GetWindowDrawList()->AddRectFilled(item.pos_, item.pos_ + Sizes[0], item.col.SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha));
                m_offsets[0] += 5.f + esp_scale - 15;
                break;
            case 1:
                item.pos_ = ImLerp(item.pos_, Positions[1].pos + ImVec2(m_offsets[1] + esp_scale - 15, 0.f), item.move_animation);
                ImGui::GetWindowDrawList()->AddRectFilled(item.pos_, item.pos_ + Sizes[1], item.col.SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha));
                m_offsets[1] += 5.f + esp_scale - 15;
                break;
            case 2:
                item.pos_ = ImLerp(item.pos_, Positions[2].pos + ImVec2(0.f, -m_offsets[2] + 15 - esp_scale), item.move_animation);
                ImGui::GetWindowDrawList()->AddRectFilled(item.pos_, item.pos_ + Sizes[2], item.col.SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha));
                m_offsets[2] += 5.f + esp_scale - 15;
                break;
            case 3:
                item.pos_ = ImLerp(item.pos_, Positions[3].pos + ImVec2(0.f, m_offsets[3] + esp_scale - 15), item.move_animation);
                ImGui::GetWindowDrawList()->AddRectFilled(item.pos_, item.pos_ + Sizes[3], item.col.SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha));
                m_offsets[3] += 5.f + esp_scale - 15;
                break;
            case 4:
                item.pos_ = ImLerp(item.pos_, ImGui::GetMousePos() + ImVec2(0.f, m_offsets[3]), ImGui::GetIO().DeltaTime * 34.f);
                if (item.helding == 1) {
                    item.size = Sizes[3];
                    ImGui::GetWindowDrawList()->AddRectFilled(item.pos_, item.pos_ + Sizes[3], item.col.SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha));
                }
                else if (item.helding == 0) {
                    item.size = Sizes[1];
                    ImGui::GetWindowDrawList()->AddRectFilled(item.pos_, item.pos_ + Sizes[1], item.col.SetAlpha(item.animations[2] * ImGui::GetStyle().Alpha));
                }
                break;
            }
        }

        for (int i = 0; i < 8; i++)
            m_offsets[i] = 0.f;
    }
} m_esp_draw;
