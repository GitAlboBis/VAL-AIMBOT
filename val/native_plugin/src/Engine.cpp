#include "Engine.h"

#include <cstring>

Engine::Engine()
    : config_(MakeDefaultConfig()),
      aim_(config_),
      output_(config_) {
    status_.structSize = sizeof(PluginStatus);
    status_.lastError[0] = '\0';
}

bool Engine::Initialize(const PluginInitInfo* init) {
    std::lock_guard<std::mutex> guard(mutex_);
    if (status_.initialized) {
        SetError(PluginError::AlreadyInitialized, "Plugin is already initialized.");
        return false;
    }

    if (init != nullptr) {
        initInfo_ = *init;
    } else {
        initInfo_.structSize = sizeof(PluginInitInfo);
        initInfo_.hostContext = nullptr;
        initInfo_.log = nullptr;
    }

    status_ = {};
    status_.structSize = sizeof(PluginStatus);
    status_.initialized = true;
    status_.running = false;
    status_.lastFrameOk = false;
    status_.lastErrorCode = static_cast<int>(PluginError::None);
    status_.lastError[0] = '\0';

    Log(1, "UnibotPlugin initialized with embedded defaults.");
    return true;
}

bool Engine::Run() {
    std::lock_guard<std::mutex> guard(mutex_);
    if (!status_.initialized) {
        SetError(PluginError::NotInitialized, "Plugin must be initialized before Run.");
        return false;
    }

    // The first migration slice is intentionally passive: Run marks the plugin
    // as active but does not capture the screen or emit input yet.
    status_.running = true;
    Log(1, "UnibotPlugin run state enabled.");
    return true;
}

bool Engine::Tick() {
    std::lock_guard<std::mutex> guard(mutex_);
    if (!status_.initialized) {
        SetError(PluginError::NotInitialized, "Plugin must be initialized before Tick.");
        return false;
    }
    if (!status_.running) {
        SetError(PluginError::NotInitialized, "Plugin must be running before Tick.");
        return false;
    }

    TargetMeasurement target;
    target.valid = false;

    AimMove move = aim_.Calculate(false, target);
    output_.SetMove(move);
    AimMove scheduled = output_.TakeNextMove();

    status_.lastFrameOk = true;
    status_.targetX = 0.0f;
    status_.targetY = 0.0f;
    status_.moveX = scheduled.x;
    status_.moveY = scheduled.y;
    status_.lastErrorCode = static_cast<int>(PluginError::None);
    status_.lastError[0] = '\0';
    return true;
}

void Engine::Shutdown() {
    std::lock_guard<std::mutex> guard(mutex_);
    output_.Clear();
    aim_.Reset();
    status_ = {};
    status_.structSize = sizeof(PluginStatus);
    initInfo_ = {};
}

PluginStatus Engine::GetStatus() const {
    std::lock_guard<std::mutex> guard(mutex_);
    return status_;
}

void Engine::SetError(PluginError error, const char* message) {
    status_.lastErrorCode = static_cast<int>(error);
    strcpy_s(status_.lastError, sizeof(status_.lastError), message);
    Log(3, message);
}

void Engine::Log(int level, const char* message) const {
    if (initInfo_.log != nullptr) {
        initInfo_.log(level, message);
    }
}
