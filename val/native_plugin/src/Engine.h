#pragma once

#include "AimController.h"
#include "Config.h"
#include "OutputScheduler.h"
#include "PluginApi.h"
#include "Status.h"
#include "TargetTypes.h"

#include <mutex>
#include <string>

class Engine {
public:
    Engine();

    bool Initialize(const PluginInitInfo* init);
    bool Run();
    bool Tick();
    void Shutdown();
    PluginStatus GetStatus() const;

private:
    void SetError(PluginError error, const char* message);
    void Log(int level, const char* message) const;

    mutable std::mutex mutex_;
    Config config_;
    AimController aim_;
    OutputScheduler output_;
    PluginInitInfo initInfo_{};
    PluginStatus status_{};
};
