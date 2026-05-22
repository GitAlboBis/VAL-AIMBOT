#pragma once

enum class PluginError {
    None = 0,
    AlreadyInitialized = 1,
    NotInitialized = 2,
    InvalidArgument = 3,
    InternalError = 4
};
