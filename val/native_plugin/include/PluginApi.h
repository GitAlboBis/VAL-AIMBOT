#pragma once

#include <cstdint>

#if defined(_WIN32)
  #if defined(UNIBOTPLUGIN_EXPORTS)
    #define UNIBOT_API extern "C" __declspec(dllexport)
  #else
    #define UNIBOT_API extern "C" __declspec(dllimport)
  #endif
#else
  #define UNIBOT_API extern "C"
#endif

using UnibotLogCallback = void(__stdcall *)(int level, const char* message);

struct PluginInitInfo {
    uint32_t structSize;
    void* hostContext;
    UnibotLogCallback log;
};

struct PluginStatus {
    uint32_t structSize;
    bool initialized;
    bool running;
    bool lastFrameOk;
    float targetX;
    float targetY;
    float moveX;
    float moveY;
    int lastErrorCode;
    char lastError[256];
};

UNIBOT_API bool __stdcall Initialize(const PluginInitInfo* init);
UNIBOT_API bool __stdcall Run();
UNIBOT_API bool __stdcall Tick();
UNIBOT_API const PluginStatus* __stdcall GetStatus();
UNIBOT_API void __stdcall Shutdown();
