#include "main.h"
// https://discord.authguards.com/
// https://authguards.com/
static bool checkboxes[60];
static int slider_int[30];
float color_edit[10][4];
static int combo[30];
static int keybind[30];
static int keybind_mode[30];
const char* combo_list[] = { "Automatic Rifle", "Thompson", "Revolver", "Bow", "Knife" };
static int iTabs;
static int iSubTabs;

#include "directx_blur.h"

static float menu_alpha = 0.1f;
static bool menu_active = true;
// https://discord.authguards.com/
// https://authguards.com/

#include <random>
// https://discord.authguards.com/
// https://authguards.com/

#include <D3DX11tex.h>
#pragma comment(lib, "D3DX11.lib")
#include <d3d11.h>
#include <tchar.h>


static bool g_showDiscordAvatar = true;



// Forward declarations for Discord avatar functions
#include <fstream> // this is for file operations
#include <filesystem> // this is for filesystem operations
#include <regex> // this is for regex parsing
#include <sstream> // this is for stringstream
#include <wininet.h> // this is for HTTP requests
#pragma comment(lib, "wininet.lib")
#include "json.hpp" // this is for JSON parsing
#include <thread>

// Discord avatar management
namespace DiscordAvatar {
    int gif_current_frame_index = 0;
    ID3D11ShaderResourceView* GetAvatarTexture() { return nullptr; }
    ID3D11ShaderResourceView* GetDecorationTexture() { return nullptr; }
    bool IsGif() { return false; }
    int GetGifFrameCount() { return 1; }
    int GetGifFramesPerRow() { return 1; }
    int GetCurrentFrameIndex() { return 0; }
    bool LoadDiscordAvatar() { return false; }
}










namespace custom
{
	void BindBox(const char* label, bool* v, int* key, int* key_mode)
	{
		custom::MiniBind("Minibind", key, key_mode);
		ImGui::SameLine(0); ImGui::SetCursorPosX(ImGui::GetStyle().WindowPadding.x);
		custom::Checkbox("Aimbots", v);
	}
}

int main(int, char**)
{
	WNDCLASSEXW wc = { sizeof(wc), CS_CLASSDC, WndProc, 0L, 0L, GetModuleHandle(nullptr), nullptr, nullptr, nullptr, nullptr, L"ImGui Example", nullptr };
	::RegisterClassExW(&wc);
	HWND hwnd = ::CreateWindowW(wc.lpszClassName, L"Dear ImGui DirectX11 Example", WS_POPUP, 0, 0, 2560, 1440, nullptr, nullptr, wc.hInstance, nullptr);

	if (!CreateDeviceD3D(hwnd))
	{
		CleanupDeviceD3D();
		::UnregisterClassW(wc.lpszClassName, wc.hInstance);
		return 1; 
	}

	::ShowWindow(hwnd, SW_SHOWDEFAULT);
	::UpdateWindow(hwnd);

	IMGUI_CHECKVERSION();
	ImGui::CreateContext();
	ImGuiIO& io = ImGui::GetIO(); (void)io;
	io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
	io.ConfigFlags |= ImGuiConfigFlags_NavEnableGamepad;

	ImFontConfig cfg;
	cfg.FontBuilderFlags = ImGuiFreeTypeBuilderFlags_NoHinting | ImGuiFreeTypeBuilderFlags_LightHinting | ImGuiFreeTypeBuilderFlags_LoadColor;;

	static ImWchar icomoon_ranges[] = { 0x1, 0x10FFFD, 0 };

	static ImFontConfig icomoon_config;
	icomoon_config.OversampleH = icomoon_config.OversampleV = 1;
	icomoon_config.MergeMode = true;
	icomoon_config.GlyphOffset.y = 2;

	io.Fonts->AddFontFromMemoryTTF(PoppinsRegular, sizeof(PoppinsRegular), 20.f, &cfg, io.Fonts->GetGlyphRangesCyrillic());
	io.Fonts->AddFontFromMemoryCompressedBase85TTF(icomoon_compressed_data_base85, 18.f, &icomoon_config, icomoon_ranges);

	font::esp_font = io.Fonts->AddFontFromMemoryTTF(PoppinsRegular, sizeof(PoppinsRegular), 17.f, &cfg, io.Fonts->GetGlyphRangesCyrillic());
	font::regular_m = io.Fonts->AddFontFromMemoryTTF(PoppinsMedium, sizeof(PoppinsMedium), 21.f, &cfg, io.Fonts->GetGlyphRangesCyrillic());
	font::regular_l = io.Fonts->AddFontFromMemoryTTF(PoppinsMedium, sizeof(PoppinsMedium), 41.f, &cfg, io.Fonts->GetGlyphRangesCyrillic());
	font::s_inter_semibold = io.Fonts->AddFontFromMemoryTTF(PoppinsSemiBold, sizeof(PoppinsSemiBold), 17.f, &cfg, io.Fonts->GetGlyphRangesCyrillic());
	font::bold_font = io.Fonts->AddFontFromMemoryTTF(PoppinsBold, sizeof(PoppinsBold), 23.f, &cfg, io.Fonts->GetGlyphRangesCyrillic());
	io.Fonts->AddFontFromMemoryCompressedBase85TTF(icomoon_compressed_data_base85, 32.f, &icomoon_config, icomoon_ranges);

	font::inter_medium = io.Fonts->AddFontFromMemoryTTF(PoppinsMedium, sizeof(PoppinsMedium), 17.f, &cfg, io.Fonts->GetGlyphRangesCyrillic());
	//font::icomoon_page = io.Fonts->AddFontFromMemoryTTF(icomoon_page, sizeof(icomoon_page), 28.f, &cfg, io.Fonts->GetGlyphRangesCyrillic());
	//font::icomoon_logo = io.Fonts->AddFontFromMemoryTTF(icomoon_page, sizeof(icomoon_page), 30.f, &cfg, io.Fonts->GetGlyphRangesCyrillic());
	//font::icon_notify = io.Fonts->AddFontFromMemoryTTF(icon_notify, sizeof(icon_notify), 17.f, &cfg, io.Fonts->GetGlyphRangesCyrillic());

	ImGui_ImplWin32_Init(hwnd);
	ImGui_ImplDX11_Init(g_pd3dDevice, g_pd3dDeviceContext);

	bool show_demo_window = true;
	bool show_another_window = false;
	ImVec4 clear_color = ImColor(0, 0, 0, 255);

	D3DX11_IMAGE_LOAD_INFO info; ID3DX11ThreadPump* pump{ nullptr };
	if (texture::preview_slow == nullptr) D3DX11CreateShaderResourceViewFromMemory(g_pd3dDevice, preview_slow, sizeof(preview_slow), &info, pump, &texture::preview_slow, 0);

	if (texture::logotype_image == nullptr) D3DX11CreateShaderResourceViewFromMemory(g_pd3dDevice, logotype, sizeof(logotype), &info, pump, &texture::logotype_image, 0);

	ImGuiStyle& s = ImGui::GetStyle();
	s.FramePadding = ImVec2(18, 10);
	s.ItemSpacing = ImVec2(4, 10);
	s.FrameRounding = 2.f;
	s.WindowRounding = 20.f;
	s.WindowBorderSize = 0.f;
	s.PopupBorderSize = 0.f;
	s.WindowPadding = ImVec2(20, 20);
	s.ChildBorderSize = 1.f;
	s.Colors[ImGuiCol_Border] = ImVec4(0.f, 0.f, 0.f, 0.f);
	s.Colors[ImGuiCol_Separator] = ImVec4(1.f, 1.f, 1.f, 0.2f);
	s.Colors[ImGuiCol_BorderShadow] = ImVec4(0.f, 0.f, 0.f, 0.f);
	s.WindowShadowSize = 0;
	s.PopupRounding = 5.f;
	s.ScrollbarSize = 1;
	s.SeparatorTextPadding = ImVec2(10, 10);

	std::vector<s_tab> tabs_info;

	tabs_info.push_back({ "Combat", {"Aim Assistance", "Close Aim", "Weapon Config"} });
	tabs_info.push_back({ "Visuals", {"Players", "Radar", "World"} });
	tabs_info.push_back({ "Miscellaneous ", {"Misc", "Exploits", "Configuration"} });


	c_tabs p_tabs(tabs_info);
	c_animated_bg p_animated_bg;
	CNotifications p_notif;

	bool done = false;
	while (!done)
	{

		MSG msg;
		while (::PeekMessage(&msg, nullptr, 0U, 0U, PM_REMOVE))
		{
			::TranslateMessage(&msg);
			::DispatchMessage(&msg);
			if (msg.message == WM_QUIT)
				done = true;
		}
		if (done) break;

		if (g_ResizeWidth != 0 && g_ResizeHeight != 0)
		{
			CleanupRenderTarget();
			g_pSwapChain->ResizeBuffers(0, g_ResizeWidth, g_ResizeHeight, DXGI_FORMAT_UNKNOWN, 0);
			g_ResizeWidth = g_ResizeHeight = 0;
			CreateRenderTarget();
		}

		ImGui_ImplDX11_NewFrame();
		ImGui_ImplWin32_NewFrame();
		NewFrame();

		LoadImages();

		ImGui::GetBackgroundDrawList()->AddImage(texture::window_bg, ImVec2(0, 0), ImVec2(2560, 1440));

		ImGui::SetNextWindowSize(c::bg::size);
		Begin("M1LL3X", nullptr, ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoBringToFrontOnFocus | ImGuiWindowFlags_NoResize | ImGuiWindowFlags_AlwaysAutoResize | ImGuiWindowFlags_NoBackground);
		{
			if (ImGui::IsKeyPressed(ImGuiKey_Insert))
				menu_active = !menu_active;

			c::anim::speed = ImGui::GetIO().DeltaTime * 14.f;
			c::second_color = utils::GetDarkColor(c::main_color);

			const ImVec2& pos = ImGui::GetWindowPos();
			const ImVec2& region = ImGui::GetContentRegionMax();
			const ImVec2& spacing = s.ItemSpacing;


			menu_alpha = ImLerp(menu_alpha, menu_active ? 1.f : 0.1f, c::anim::speed);


			//s.Alpha = menu_alpha;

			static int current_frame = 0;

			static float frame_offset = 0.f;
			static float static_frame_offset = 0.01111111111f;

			frame_offset = current_frame * static_frame_offset;

			draw_background_blur(GetBackgroundDrawList(), g_pSwapChain, g_pd3dDevice, g_pd3dDeviceContext, pos, pos + c::bg::size, c::bg::rounding);

			GetBackgroundDrawList()->AddRectFilled(pos, pos + c::bg::size, utils::GetColorWithAlpha(c::window_bg_color, c::window_bg_color.Value.w * s.Alpha), c::bg::rounding);


			// left tab
			//GetBackgroundDrawList()->AddRectFilled(pos, pos + ImVec2(180, c::bg::size.y), GetColorU32(c::child::background), c::bg::rounding, ImDrawFlags_RoundCornersLeft);
			GetBackgroundDrawList()->AddText(pos + ImVec2(15, c::bg::size.y - 35), c::label::default, "dev build 24.03");
			// left tab

			//top block
			GetBackgroundDrawList()->AddRectFilled(pos, pos + ImVec2(c::bg::size.x, 70), GetColorU32(c::child::background), c::bg::rounding, ImDrawFlags_RoundCornersTopRight);

			PushFont(font::bold_font);
			GetBackgroundDrawList()->AddText(utils::center_text(pos, pos + ImVec2(70, 70), ICON_FIRE_FILL) + ImVec2(0, 4.5f), main_color, ICON_FIRE_FILL);
			GetBackgroundDrawList()->AddText(ImVec2(pos.x + 60, utils::center_text(pos, pos + ImVec2(70, 70), "LineFlow").y), c::label::active, "LineFlow");
			PopFont();

            		// Discord avatar (load + draw) - can be toggled in Misc
		if (g_showDiscordAvatar) {
			// Try to load Discord avatar (runs in background, checks for texture creation every frame)
			DiscordAvatar::LoadDiscordAvatar(); // This will only start loading once, but checks for texture creation every frame
			
			// Display Discord avatar with GIF animation support
			ID3D11ShaderResourceView* avatarTex = DiscordAvatar::GetAvatarTexture();
			if (avatarTex == nullptr) {
				avatarTex = texture::default_avatar_image; // Fallback to default
			}
			
            // Try get decoration texture (only show if Discord avatar is enabled)
            ID3D11ShaderResourceView* decoTex = DiscordAvatar::GetDecorationTexture();
			if (DiscordAvatar::IsGif() && avatarTex != nullptr) {
			// Animate GIF sprite sheet - use all frames dynamically
			const float gif_frameLength = 1.f / 10.f; // 10 FPS
			static float gif_frameTimer = gif_frameLength;
			
			// Get frame count and calculate grid size dynamically
			int total_frames = DiscordAvatar::GetGifFrameCount();
			if (total_frames <= 1) total_frames = 9; // Fallback if not set
			
			// Calculate grid dimensions (square-ish grid)
			int cols = static_cast<int>(ceil(sqrt(static_cast<float>(total_frames))));
			int rows = static_cast<int>(ceil(static_cast<float>(total_frames) / cols));
			
			// Get current frame index (0 to total_frames-1)
			int frame_idx = DiscordAvatar::gif_current_frame_index;
			if (frame_idx >= total_frames) frame_idx = 0; // Safety check
			
			// Calculate row and column - frames arranged row-first
			int row = frame_idx / cols;
			int col = frame_idx % cols;
			
			// UV coordinates for this specific frame
			float cell_width = 1.0f / cols;
			float cell_height = 1.0f / rows;
			float uv0_x = col * cell_width;
			float uv0_y = row * cell_height;
			float uv1_x = uv0_x + cell_width;
			float uv1_y = uv0_y + cell_height;
			
			// Advance to next frame smoothly
			gif_frameTimer -= ImGui::GetIO().DeltaTime;
			if (gif_frameTimer <= 0.f) {
				gif_frameTimer = gif_frameLength;
				DiscordAvatar::gif_current_frame_index = (DiscordAvatar::gif_current_frame_index + 1) % total_frames;
			}
			
            ImVec2 avatar_min(pos.x + c::bg::size.x - 55, pos.y + 15);
            ImVec2 avatar_max(pos.x + c::bg::size.x - 15, pos.y + 55);
            float avatar_rounding = (avatar_max.x - avatar_min.x) * 0.5f;
			ImGui::GetBackgroundDrawList()->AddImageRounded(
				avatarTex,
				avatar_min,
				avatar_max,
				ImVec2(uv0_x, uv0_y),
				ImVec2(uv1_x, uv1_y),
                IM_COL32_WHITE,
                avatar_rounding
			);
            // Overlay decoration if available (slightly larger, no rounding so edges aren't clipped)
            if (decoTex != nullptr) {
                ImVec2 deco_min = avatar_min - ImVec2(3.f, 3.f);
                ImVec2 deco_max = avatar_max + ImVec2(3.f, 3.f);
                ImGui::GetBackgroundDrawList()->AddImage(
                    decoTex,
                    deco_min,
                    deco_max,
                    ImVec2(0, 0),
                    ImVec2(1, 1),
                    IM_COL32_WHITE
                );
            }
			} else {
				// Static image (PNG or default)
				ImVec2 avatar_min(pos.x + c::bg::size.x - 55, pos.y + 15);
				ImVec2 avatar_max(pos.x + c::bg::size.x - 15, pos.y + 55);
				float avatar_rounding = (avatar_max.x - avatar_min.x) * 0.5f; // make it a circle
			ImGui::GetBackgroundDrawList()->AddImageRounded(
					avatarTex,
					avatar_min,
					avatar_max,
					ImVec2(0, 0),
					ImVec2(1, 1),
					IM_COL32_WHITE,
					avatar_rounding
				);
            // Overlay decoration if available (slightly larger, no rounding so edges aren't clipped)
            if (decoTex != nullptr) {
                ImVec2 deco_min = avatar_min - ImVec2(3.f, 3.f);
                ImVec2 deco_max = avatar_max + ImVec2(3.f, 3.f);
                ImGui::GetBackgroundDrawList()->AddImage(
                    decoTex,
                    deco_min,
                    deco_max,
                    ImVec2(0, 0),
                    ImVec2(1, 1),
                    IM_COL32_WHITE
                );
            }
			}
		} else {
			// Show default avatar when Discord avatar is disabled (no Discord avatar, no decoration)
			if (texture::default_avatar_image != nullptr) {
				ImVec2 avatar_min(pos.x + c::bg::size.x - 55, pos.y + 15);
				ImVec2 avatar_max(pos.x + c::bg::size.x - 15, pos.y + 55);
				float avatar_rounding = (avatar_max.x - avatar_min.x) * 0.5f; // make it a circle
				ImGui::GetBackgroundDrawList()->AddImageRounded(
					texture::default_avatar_image,
					avatar_min,
					avatar_max,
					ImVec2(0, 0),
					ImVec2(1, 1),
					IM_COL32_WHITE,
					avatar_rounding
				);
			}
		}


			GetBackgroundDrawList()->AddText(pos + ImVec2(c::bg::size.x - 70 - CalcTextSize(":D").x, 18), c::label::active, ":D");

			PushFont(font::esp_font);
			GetBackgroundDrawList()->AddText(pos + ImVec2(c::bg::size.x - 70 - CalcTextSize("Administrator").x, 37), c::label::default, "Administrator");
			PopFont();

			// top block


			p_tabs.DrawTabs();

			if (p_tabs.IsTabActive(0)) {
				ImGui::SetCursorPos(ImVec2(200.f, 85 + page_offset));
				float half_w = (ImGui::GetContentRegionAvail().x - ImGui::GetStyle().ItemSpacing.x) * 0.5f;
				float full_h = 450;

				custom::Child("Main Aim Config##L", ImVec2(half_w, full_h), true);
				custom::SliderInt("Distance", &slider_int[2], 0, 100);
				custom::SliderInt("FOV Size", &slider_int[1], 0, 100);
				custom::SliderInt("Smoothing", &slider_int[0], 0, 100);
				custom::Checkbox("Prediction", &checkboxes[4]);
				custom::Checkbox("Ignore Knocked", &checkboxes[3]);
				custom::Checkbox("Visible Check", &checkboxes[2]);
				custom::Checkbox("Auto Aim", &checkboxes[1]);
				custom::Checkbox("Enable Aimbot", &checkboxes[0]);
				custom::ColorEdit4("FOV Color", &col[0], picker_flags);
				custom::Combo("Aim Key", &combo[1], combo_list, IM_ARRAYSIZE(combo_list));
				custom::Combo("Aim Bone", &combo[0], combo_list, IM_ARRAYSIZE(combo_list));
				custom::BindBox("Draw FOV", &checkboxes[5], &keybind[2], &keybind_mode[2]);
				custom::EndChild();

				ImGui::SameLine(0, ImGui::GetStyle().ItemSpacing.x * 3);

				custom::Child("Backup Aim Config##R", ImVec2(half_w, full_h), true);
				custom::SliderInt("Distance", &slider_int[5], 0, 100);
				custom::SliderInt("FOV Size", &slider_int[4], 0, 100);
				custom::ColorEdit4("Main color", (float*)&c::main_color, picker_flags);
				custom::SliderInt("Smoothing", &slider_int[3], 0, 100);
				custom::Combo("Aim Key", &combo[3], combo_list, IM_ARRAYSIZE(combo_list));
				custom::Combo("Aim Bone", &combo[2], combo_list, IM_ARRAYSIZE(combo_list));
				custom::Checkbox("Prediction", &checkboxes[10]);
				custom::Checkbox("Ignore Knocked", &checkboxes[9]);
				custom::Checkbox("Visible Check", &checkboxes[8]);
				custom::Checkbox("Auto Aim", &checkboxes[7]);
				custom::Checkbox("Enable Aimbot", &checkboxes[6]);
				custom::BindBox("Draw FOV", &checkboxes[11], &keybind[3], &keybind_mode[3]);
				custom::EndChild();
			}

			if (p_tabs.IsTabActive(1)) {

				static const char* combo_list[] = {"Head", "Neck", "Chest", "Pelvis", "Legs" };

				static const char* color_mode_list[] = { "Static", "Gradient", "Rainbow", "Pulse" };

				static const char* team_filter_list[] = { "All", "Enemies", "Teammates", "Neutral" };

				static const char* glow_mode_list[] = { "Basic", "Rainbow", "Pulse", "Blink" };

				static const char* material_list[] = { "Flat", "Wireframe", "Shaded", "Metallic" };


				ImGui::SetCursorPos(ImVec2(200.f, 85 + page_offset));
				float half_w = (ImGui::GetContentRegionAvail().x - ImGui::GetStyle().ItemSpacing.x) * 0.5f;
				float full_h = 450;

				custom::Child("Visuals (General)##L2", ImVec2(half_w, full_h), true);
				custom::Checkbox("Show Player Box", &checkboxes[12]);
				custom::Checkbox("Show Health Bar", &checkboxes[13]);
				custom::Checkbox("Show Skeleton", &checkboxes[14]);
				custom::Checkbox("Show Names", &checkboxes[15]);
				custom::Checkbox("Show Distance", &checkboxes[16]);
				custom::SliderInt("Box Thickness", &slider_int[6], 1, 10);
				custom::SliderInt("Health Bar Width", &slider_int[7], 1, 20);
				custom::SliderInt("Name Font Size", &slider_int[8], 10, 30);
				custom::Combo("ESP Color Mode", &combo[4], color_mode_list, IM_ARRAYSIZE(color_mode_list));
				custom::Combo("Team Filter", &combo[5], team_filter_list, IM_ARRAYSIZE(team_filter_list));
				custom::BindBox("Toggle Visuals", &checkboxes[17], &keybind[4], &keybind_mode[4]);
				custom::EndChild();

				ImGui::SameLine(0, ImGui::GetStyle().ItemSpacing.x * 3);

				custom::Child("Visuals (Advanced)##R2", ImVec2(half_w, full_h), true);
				custom::Checkbox("Glow Effect", &checkboxes[18]);
				custom::Checkbox("Chams", &checkboxes[19]);
				custom::Checkbox("Offscreen Arrows", &checkboxes[20]);
				custom::Checkbox("Distance Circles", &checkboxes[21]);
				custom::Checkbox("Ammo Count", &checkboxes[22]);
				custom::SliderInt("Glow Intensity", &slider_int[9], 0, 100);
				custom::SliderInt("Chams Opacity", &slider_int[10], 0, 100);
				custom::SliderInt("Arrow Size", &slider_int[11], 5, 50);
				custom::Combo("Glow Color Mode", &combo[6], glow_mode_list, IM_ARRAYSIZE(glow_mode_list));
				custom::Combo("Chams Material", &combo[7], material_list, IM_ARRAYSIZE(material_list));
				custom::BindBox("Toggle Advanced ESP", &checkboxes[23], &keybind[5], &keybind_mode[5]);
				custom::EndChild();
			}

			if (p_tabs.IsTabActive(2)) {
				ImGui::SetCursorPos(ImVec2(200.f, 85 + page_offset));
				custom::Child("Weapon Config tab", ImVec2(ImGui::GetContentRegionAvail().x - 21, 460), true); {

					const char* combo_list[] = { "Option 1", "Option 2", "Option 3" };

					custom::Checkbox("Enable", &checkboxes[20]);
					custom::Combo("Aim bone for each weapon category", &combo[20], combo_list, IM_ARRAYSIZE(combo_list));
					custom::Combo("Smoothing each weapon category", &combo[21], combo_list, IM_ARRAYSIZE(combo_list));
					custom::Combo("Fov each weapon category", &combo[22], combo_list, IM_ARRAYSIZE(combo_list));
					custom::Checkbox("Triggerbot", &checkboxes[21]);
					custom::SliderInt("Triggerbot Distance ", &slider_int[20], 0, 100);
					custom::Keybind("Trigger Key", &keybind[20], &keybind_mode[20]);

				}
				custom::EndChild();
			}


			if (p_tabs.IsTabActive(3)) {


				ImGui::SetCursorPos(ImVec2(200.f, 85 + page_offset));
				custom::Child("ESP Player", ImVec2(ImGui::GetContentRegionAvail().x / 2, 460), true); {

					custom::Checkbox("Enable", &checkboxes[30]);
					custom::Checkbox("2D Box", &checkboxes[31]);
					custom::Checkbox("Cornered Box", &checkboxes[32]);
					custom::Checkbox("Skeleton", &checkboxes[33]);
					custom::Checkbox("Head Circle", &checkboxes[34]);
					custom::Checkbox("Name", &checkboxes[35]);
					custom::Checkbox("Distance", &checkboxes[36]);
					custom::Checkbox("Snaplines", &checkboxes[37]);
					custom::Checkbox("Show Bots", &checkboxes[38]);
					custom::Checkbox("Platform", &checkboxes[39]);
					custom::Checkbox("Rank", &checkboxes[40]);
					custom::Checkbox("Weapon", &checkboxes[41]);
					custom::Checkbox("Team Check", &checkboxes[42]);
					custom::SliderInt("Skeleton Thickness", &slider_int[30], 0, 192);
					custom::ColorEdit4("Visible", col, picker_flags);

					custom::Checkbox("Invisible", &checkboxes[43]);
					custom::Checkbox("Visible Skeleton", &checkboxes[44]);
					custom::Checkbox("Visible Text", &checkboxes[46]);
					custom::Checkbox("Invisible Text", &checkboxes[47]);
				}

				custom::EndChild();

				ImGui::SetCursorPos(ImVec2(540, 85));

				custom::Child("ESP Preview", ImVec2(ImGui::GetContentRegionAvail().x - 20, 460), true); {

					ImGui::SetCursorPos(ImVec2(0, 50));
				ImGui:BeginChild("Esp2"); {
					PushFont(font::esp_font);
					m_esp_draw.set_positions();
					m_esp_draw.on_draw();
					PopFont();
				} ImGui::EndChild();

				}
				custom::EndChild();
			}

			if (p_tabs.IsTabActive(4)) {
				ImGui::SetCursorPos(ImVec2(200.f, 85));
				custom::Child("Radar", ImVec2(ImGui::GetContentRegionAvail().x - 21, 460), true); {

					const char* combo_list[] = { "Option 1", "Option 2", "Option 3" };

					custom::Checkbox("Enable", &checkboxes[50]);

					custom::SliderInt("Size", &slider_int[50], 0, 100);
					custom::SliderInt("Position X", &slider_int[51], 0, 100);
					custom::SliderInt("Position Y", &slider_int[52], 0, 100);
					custom::SliderInt("Reneder Distance", &slider_int[53], 0, 100);
					custom::SliderInt("Enemy Distance", &slider_int[54], 0, 100);

				}
				custom::EndChild();
			}

			if (p_tabs.IsTabActive(5)) {
				ImGui::SetCursorPos(ImVec2(200.f, 85));
				custom::Child("World esp", ImVec2(ImGui::GetContentRegionAvail().x - 21, 460), true); {

					const char* combo_list[] = { "Option 1", "Option 2", "Option 3" };

					custom::Checkbox("Enable", &checkboxes[60]);
					custom::Checkbox("Vehicles", &checkboxes[61]);
					custom::Checkbox("Chests", &checkboxes[62]);
					custom::Checkbox("Ammo Boxes", &checkboxes[63]);
					custom::Checkbox("Floor Loot", &checkboxes[64]);

				}
				custom::EndChild();
			}

			if (p_tabs.IsTabActive(6)) {
				ImGui::SetCursorPos(ImVec2(200.f, 85));
				custom::Child("Misc", ImVec2(ImGui::GetContentRegionAvail().x - 21, 460), true); {

					const char* combo_list[] = { "Option 1", "Option 2", "Option 3" };

					custom::Checkbox("Crosshair", &checkboxes[70]);
					custom::Checkbox("Fps Counter", &checkboxes[71]);
					custom::Checkbox("Stream Proof", &checkboxes[72]);
					custom::Checkbox("Vehicles", &checkboxes[73]);
					custom::Checkbox("Chests", &checkboxes[74]);
					custom::Checkbox("Ammo Boxes", &checkboxes[75]);
					custom::Checkbox("Floor Loot", &checkboxes[76]);

				}
				custom::EndChild();
			}

			if (p_tabs.IsTabActive(7)) {
				ImGui::SetCursorPos(ImVec2(200.f, 85));
				custom::Child("Exploits", ImVec2(ImGui::GetContentRegionAvail().x - 21, 460), true); {

					const char* combo_list[] = { "Option 1", "Option 2", "Option 3" };

					custom::Checkbox("No Recoil", &checkboxes[80]);
					custom::Checkbox("No Bloom", &checkboxes[81]);
					custom::Checkbox("Wireframe", &checkboxes[82]);
					custom::Checkbox("First Person", &checkboxes[83]);
					custom::Keybind("Vehicle Speed Uncap (Hold key)", &keybind[84], &keybind_mode[84]);

				}
				custom::EndChild();
			}

			if (p_tabs.IsTabActive(8)) {
				ImGui::SetCursorPos(ImVec2(200.f, 85));
				custom::Child("Config", ImVec2(ImGui::GetContentRegionAvail().x - 21, 460), true); {

					const char* combo_list[] = { "Option 1", "Option 2", "Option 3" };
					custom::Button("Save", ImVec2(ImGui::GetContentRegionAvail().x, 50));
					custom::Button("Load", ImVec2(ImGui::GetContentRegionAvail().x, 50));

				}
				custom::EndChild();
			}

			p_notif.Render();
		}
		End();

		Render();
		const float clear_color_with_alpha[4] = { clear_color.x * clear_color.w, clear_color.y * clear_color.w, clear_color.z * clear_color.w, clear_color.w };
		g_pd3dDeviceContext->OMSetRenderTargets(1, &g_mainRenderTargetView, nullptr);
		g_pd3dDeviceContext->ClearRenderTargetView(g_mainRenderTargetView, clear_color_with_alpha);
		ImGui_ImplDX11_RenderDrawData(ImGui::GetDrawData());

		g_pSwapChain->Present(1, 0);

	}

	ImGui_ImplDX11_Shutdown();
	ImGui_ImplWin32_Shutdown();
	ImGui::DestroyContext();

	CleanupDeviceD3D();
	::DestroyWindow(hwnd);
	::UnregisterClassW(wc.lpszClassName, wc.hInstance);

	return 0;
}

bool CreateDeviceD3D(HWND hWnd)
{

	DXGI_SWAP_CHAIN_DESC sd;
	ZeroMemory(&sd, sizeof(sd));
	sd.BufferCount = 2;
	sd.BufferDesc.Width = 0;
	sd.BufferDesc.Height = 0;
	sd.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
	sd.BufferDesc.RefreshRate.Numerator = 60;
	sd.BufferDesc.RefreshRate.Denominator = 1;
	sd.Flags = DXGI_SWAP_CHAIN_FLAG_ALLOW_MODE_SWITCH;
	sd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
	sd.OutputWindow = hWnd;
	sd.SampleDesc.Count = 1;
	sd.SampleDesc.Quality = 0;
	sd.Windowed = TRUE;
	sd.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;

	UINT createDeviceFlags = 0;
	D3D_FEATURE_LEVEL featureLevel;
	const D3D_FEATURE_LEVEL featureLevelArray[2] = { D3D_FEATURE_LEVEL_11_0, D3D_FEATURE_LEVEL_10_0, };
	HRESULT res = D3D11CreateDeviceAndSwapChain(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, createDeviceFlags, featureLevelArray, 2, D3D11_SDK_VERSION, &sd, &g_pSwapChain, &g_pd3dDevice, &featureLevel, &g_pd3dDeviceContext);
	if (res == DXGI_ERROR_UNSUPPORTED)
		res = D3D11CreateDeviceAndSwapChain(nullptr, D3D_DRIVER_TYPE_WARP, nullptr, createDeviceFlags, featureLevelArray, 2, D3D11_SDK_VERSION, &sd, &g_pSwapChain, &g_pd3dDevice, &featureLevel, &g_pd3dDeviceContext);
	if (res != S_OK)
		return false;

	CreateRenderTarget();
	return true;
}

void CleanupDeviceD3D()
{
	CleanupRenderTarget();
	if (g_pSwapChain) { g_pSwapChain->Release(); g_pSwapChain = nullptr; }
	if (g_pd3dDeviceContext) { g_pd3dDeviceContext->Release(); g_pd3dDeviceContext = nullptr; }
	if (g_pd3dDevice) { g_pd3dDevice->Release(); g_pd3dDevice = nullptr; }
}

void CreateRenderTarget()
{
	ID3D11Texture2D* pBackBuffer;
	g_pSwapChain->GetBuffer(0, IID_PPV_ARGS(&pBackBuffer));
	g_pd3dDevice->CreateRenderTargetView(pBackBuffer, nullptr, &g_mainRenderTargetView);
	pBackBuffer->Release();
}

void CleanupRenderTarget()
{
	if (g_mainRenderTargetView) { g_mainRenderTargetView->Release(); g_mainRenderTargetView = nullptr; }
}

extern IMGUI_IMPL_API LRESULT ImGui_ImplWin32_WndProcHandler(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam);

LRESULT WINAPI WndProc(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam)
{
	if (ImGui_ImplWin32_WndProcHandler(hWnd, msg, wParam, lParam))
		return true;

	switch (msg)
	{
	case WM_SIZE:
		if (wParam == SIZE_MINIMIZED)
			return 0;
		g_ResizeWidth = (UINT)LOWORD(lParam);
		g_ResizeHeight = (UINT)HIWORD(lParam);
		return 0;
	case WM_SYSCOMMAND:
		if ((wParam & 0xfff0) == SC_KEYMENU)
			return 0;
		break;
	case WM_DESTROY:
		::PostQuitMessage(0);
		return 0;
	}
	return ::DefWindowProcW(hWnd, msg, wParam, lParam);
}
 