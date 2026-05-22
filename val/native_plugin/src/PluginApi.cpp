#include "PluginApi.h"

#include "Engine.h"

#include <memory>
#include <mutex>

namespace {
std::mutex g_mutex;
std::unique_ptr<Engine> g_engine;
PluginStatus g_statusSnapshot{};

Engine* GetOrCreateEngine() {
    if (!g_engine) {
        g_engine = std::make_unique<Engine>();
    }
    return g_engine.get();
}
}

bool __stdcall Initialize(const PluginInitInfo* init) {
    std::lock_guard<std::mutex> guard(g_mutex);
    return GetOrCreateEngine()->Initialize(init);
}

bool __stdcall Run() {
    std::lock_guard<std::mutex> guard(g_mutex);
    return GetOrCreateEngine()->Run();
}

bool __stdcall Tick() {
    std::lock_guard<std::mutex> guard(g_mutex);
    return GetOrCreateEngine()->Tick();
}

const PluginStatus* __stdcall GetStatus() {
    std::lock_guard<std::mutex> guard(g_mutex);
    if (g_engine) {
        g_statusSnapshot = g_engine->GetStatus();
    } else {
        g_statusSnapshot = {};
        g_statusSnapshot.structSize = sizeof(PluginStatus);
    }
    return &g_statusSnapshot;
}

void __stdcall Shutdown() {
    std::lock_guard<std::mutex> guard(g_mutex);
    if (g_engine) {
        g_engine->Shutdown();
        g_engine.reset();
    }
    g_statusSnapshot = {};
}
