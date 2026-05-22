#include "imgui.h"
#include "../examples/example_win32_directx11/font_defines.h"
#include <string>
// https://discord.authguards.com/
// https://authguards.com/
inline ImVec4 rgba(int r, int g, int b, float a) {
	return ImVec4(
		(float)r / 255.0f,
		(float)g / 255.0f,
		(float)b / 255.0f,
		a
	);
}

namespace font
{
	inline ImFont* icomoon_logo = nullptr;
	inline ImFont* esp_font = nullptr;
	inline ImFont* regular_m = nullptr;
	inline ImFont* regular_l = nullptr;
	inline ImFont* icomoon_page = nullptr;
	inline ImFont* inter_semibold = nullptr;
	inline ImFont* bold_font = nullptr;
	inline ImFont* s_inter_semibold = nullptr;
	inline ImFont* inter_medium = nullptr;
	inline ImFont* icon_notify = nullptr;
}

namespace utils
{
	inline ImColor GetColorWithAlpha(ImColor color, float alpha)
	{
		return ImColor(color.Value.x, color.Value.y, color.Value.z, alpha);
	}

	inline ImVec2 center_text(ImVec2 min, ImVec2 max, const char* text)
	{
		return min + (max - min) / 2 - ImGui::CalcTextSize(text) / 2;
	}

	inline ImColor GetDarkColor(const ImColor& color)
	{
		float r, g, b, a;
		r = color.Value.x;
		g = color.Value.y;
		b = color.Value.z;
		a = 255;

		float darkPercentage = 0.4f;
		float darkR = r * darkPercentage;
		float darkG = g * darkPercentage;
		float darkB = b * darkPercentage;

		return ImColor(darkR, darkG, darkB, a);
	}
	inline ImVec4 ImColorToImVec4(const ImColor& color)
	{
		return ImVec4(color.Value.x, color.Value.y, color.Value.z, color.Value.w);
	}

}

inline namespace c
{
	inline ImColor main_color = rgba(173, 143, 233, 1);
	inline ImColor second_color = rgba(100, 92, 122, 1);
	
	inline ImColor background_color = rgba(20, 20, 20, 0.5);
	inline ImColor stroke_color(255, 255, 255, 0);
	inline ImColor window_bg_color = rgba(22, 22, 22, 0.71);

	inline ImVec4 separator = ImColor(22, 23, 26);


	inline namespace anim
	{
		inline float speed;
		inline ImColor active(114, 149, 255, 255);
		inline ImColor default(22, 23, 26, 255);
	}

	inline namespace bg
	{
		inline ImVec4 background = rgba(22, 22, 22, 0.71);
		inline ImVec2 size = ImVec2(850, 596);
		inline float rounding = 15.f;
	}

	inline namespace child
	{
		inline ImVec4 background = rgba(60, 60, 60, 0.25);
		inline ImVec4 stroke = ImColor(18, 18, 24, 0);
		inline float rounding = 8.f;
	}

	namespace page
	{
		inline ImVec4 background_active = ImColor(21, 22, 25);
		inline ImVec4 background = ImColor(16, 17, 18);

		inline ImVec4 text_hov = ImColor(150, 162, 205);
		inline ImVec4 text = ImColor(150, 162, 205);

		inline float rounding = 4.f;
	}

	inline namespace elements
	{
		inline ImVec4 background_hovered = ImColor(21, 22, 25);
		inline ImVec4 background = ImColor(16, 17, 18);
		inline float rounding = 2.5f;
	}

	inline namespace checkbox
	{
		inline ImVec4 mark = ImColor(255, 255, 255, 255);
	}

	inline namespace text
	{
		inline namespace label
		{
			inline ImColor active = ImColor(255, 255, 255, 255);
			inline ImColor hovered = ImColor(205, 205, 205, 255);
			inline ImColor default = ImColor(150, 150, 150, 220);
		}

		inline namespace description
		{
			inline ImColor active = ImColor(200, 200, 200, 102);
			inline ImColor hovered = ImColor(200, 200, 200, 63);
			inline ImColor default = ImColor(200, 200, 200, 40);
		}

		inline ImVec4 text_active = ImColor(255, 255, 255);
		inline ImVec4 text_hov = ImColor(150, 162, 205);
		inline ImVec4 text = ImColor(150, 162, 205);
	}
}

inline float page_offset;
inline bool page_is_changing;
inline std::string wanted_category;
inline int wanted_idx;