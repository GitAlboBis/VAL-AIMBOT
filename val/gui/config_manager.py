"""
Tuborg Config Manager — Save/Load config presets as YAML files.

Ports the Givenchy configs.cpp save/load pattern to Python YAML.
Configs stored in ./configs/ directory alongside config.yaml.
"""

import os
import yaml
import shutil
import time
from typing import Optional, Dict, Any

CONFIGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "configs")
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
MAX_BACKUPS = 3  # Keep last 3 timestamped backups


def ensure_configs_dir():
    """Create configs directory if it doesn't exist."""
    os.makedirs(CONFIGS_DIR, exist_ok=True)


def list_configs() -> list:
    """
    List all saved config presets.
    Returns list of config names (without .yaml extension).
    
    Also aliased as list_presets() for consistency with save_preset/load_preset.
    """
    ensure_configs_dir()
    configs = []
    for f in os.listdir(CONFIGS_DIR):
        if f.endswith(".yaml") or f.endswith(".yml"):
            configs.append(os.path.splitext(f)[0])
    configs.sort()
    return configs


# Alias for consistency with save_preset/load_preset naming
list_presets = list_configs


def save_config(name: str, config_dict: dict) -> bool:
    """
    Save a config preset to ./configs/<name>.yaml.
    Returns True on success.
    
    DEPRECATED: Use save_preset() with shared_state parameter instead.
    This function is kept for backward compatibility.
    """
    ensure_configs_dir()
    filepath = os.path.join(CONFIGS_DIR, f"{name}.yaml")
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            yaml.dump(config_dict, f, default_flow_style=False, allow_unicode=True)
        return True
    except Exception as e:
        print(f"[Config] Save failed: {e}")
        return False


def save_preset(name: str, shared_state) -> bool:
    """
    Save current config from shared state as a preset to ./configs/<name>.yaml.
    
    Args:
        name: Preset name (without .yaml extension)
        shared_state: SharedState instance to read config from
    
    Returns:
        True on success, False on failure
    
    Example:
        save_preset("my_preset", shared_state)
    """
    from gui.widgets import notifications
    
    ensure_configs_dir()
    filepath = os.path.join(CONFIGS_DIR, f"{name}.yaml")
    
    try:
        # Read current config from shared state
        config_dict = shared_state.get_config()
        
        if not config_dict:
            print(f"[Config] No config data in shared state")
            notifications.add(f"Failed to save preset: No config data", color=(1.0, 0.3, 0.3, 1.0))
            return False
        
        # Validate config before saving
        if not validate_config(config_dict):
            print(f"[Config] Invalid config structure, cannot save preset")
            notifications.add(f"Failed to save preset: Invalid config", color=(1.0, 0.3, 0.3, 1.0))
            return False
        
        # Save to preset file
        with open(filepath, 'w', encoding='utf-8') as f:
            yaml.dump(config_dict, f, default_flow_style=False, allow_unicode=True)
        
        print(f"[Config] Saved preset: {name}")
        notifications.add(f"Preset '{name}' saved", color=(0.3, 1.0, 0.3, 1.0))
        return True
        
    except Exception as e:
        print(f"[Config] Save preset failed: {e}")
        notifications.add(f"Failed to save preset: {str(e)}", color=(1.0, 0.3, 0.3, 1.0))
        return False


def load_config(name: str) -> Optional[dict]:
    """
    Load a config preset from ./configs/<name>.yaml.
    Returns dict on success, None on failure.
    
    DEPRECATED: Use load_preset() with shared_state parameter instead.
    This function is kept for backward compatibility.
    """
    ensure_configs_dir()
    filepath = os.path.join(CONFIGS_DIR, f"{name}.yaml")
    if not os.path.exists(filepath):
        # Try .yml extension
        filepath = os.path.join(CONFIGS_DIR, f"{name}.yml")
        if not os.path.exists(filepath):
            print(f"[Config] Not found: {name}")
            return None

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else None
    except Exception as e:
        print(f"[Config] Load failed: {e}")
        return None


def load_preset(name: str, shared_state) -> bool:
    """
    Load a config preset from ./configs/<name>.yaml into shared state.
    
    Validates the preset before loading to ensure it has valid structure.
    Updates all config sections in shared state with preset values.
    
    Args:
        name: Preset name (without .yaml extension)
        shared_state: SharedState instance to write config to
    
    Returns:
        True on success, False on failure
    
    Example:
        load_preset("my_preset", shared_state)
    """
    from gui.widgets import notifications
    
    ensure_configs_dir()
    filepath = os.path.join(CONFIGS_DIR, f"{name}.yaml")
    
    # Try .yaml extension first
    if not os.path.exists(filepath):
        # Try .yml extension
        filepath = os.path.join(CONFIGS_DIR, f"{name}.yml")
        if not os.path.exists(filepath):
            print(f"[Config] Preset not found: {name}")
            notifications.add(f"Preset '{name}' not found", color=(1.0, 0.5, 0.3, 1.0))
            return False
    
    try:
        # Load preset file
        with open(filepath, 'r', encoding='utf-8') as f:
            preset_dict = yaml.safe_load(f)
        
        # Validate preset structure
        if not isinstance(preset_dict, dict):
            print(f"[Config] Invalid preset format: {name}")
            notifications.add(f"Invalid preset format: {name}", color=(1.0, 0.3, 0.3, 1.0))
            return False
        
        if not validate_config(preset_dict):
            print(f"[Config] Invalid preset structure: {name}")
            notifications.add(f"Invalid preset structure: {name}", color=(1.0, 0.3, 0.3, 1.0))
            return False
        
        # Load preset into shared state
        for section, values in preset_dict.items():
            if isinstance(values, dict):
                # Use update_config_section for efficiency
                shared_state.update_config_section(section, values)
            else:
                # Handle non-dict top-level values
                shared_state.update_config('general', section, values)
        
        print(f"[Config] Loaded preset: {name}")
        notifications.add(f"Preset '{name}' loaded", color=(0.3, 1.0, 0.3, 1.0))
        return True
        
    except yaml.YAMLError as e:
        print(f"[Config] YAML parsing error in preset {name}: {e}")
        notifications.add(f"YAML error in preset: {name}", color=(1.0, 0.3, 0.3, 1.0))
        return False
        
    except Exception as e:
        print(f"[Config] Failed to load preset {name}: {e}")
        notifications.add(f"Failed to load preset: {str(e)}", color=(1.0, 0.3, 0.3, 1.0))
        return False


def delete_config(name: str) -> bool:
    """
    Delete a config preset.
    
    Also aliased as delete_preset() for consistency with save_preset/load_preset.
    
    Args:
        name: Preset name (without .yaml extension)
    
    Returns:
        True if preset was deleted, False if not found
    
    Note: This function does not require confirmation - caller should
    implement confirmation dialog if needed.
    """
    ensure_configs_dir()
    filepath = os.path.join(CONFIGS_DIR, f"{name}.yaml")
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            print(f"[Config] Deleted preset: {name}")
            return True
        except Exception as e:
            print(f"[Config] Failed to delete preset {name}: {e}")
            return False
    
    filepath = os.path.join(CONFIGS_DIR, f"{name}.yml")
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            print(f"[Config] Deleted preset: {name}")
            return True
        except Exception as e:
            print(f"[Config] Failed to delete preset {name}: {e}")
            return False
    
    print(f"[Config] Preset not found: {name}")
    return False


# Alias for consistency with save_preset/load_preset naming
delete_preset = delete_config


def apply_preset_to_live(preset: dict, live: dict) -> dict:
    """
    Deep-merge a preset dict into the live config dict.
    Preset values override live values. Missing keys in preset
    are preserved from live.
    """
    result = live.copy()
    for key, value in preset.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = apply_preset_to_live(value, result[key])
        else:
            result[key] = value
    return result


def save_live_config(config_dict: dict) -> bool:
    """
    Save the live config back to the main config.yaml.
    Creates a backup first.
    """
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "config.yaml"
    )
    backup_path = config_path + ".bak"

    try:
        # Backup current
        if os.path.exists(config_path):
            shutil.copy2(config_path, backup_path)

        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_dict, f, default_flow_style=False, allow_unicode=True)
        return True
    except Exception as e:
        print(f"[Config] Save live config failed: {e}")
        return False


def validate_config(config_dict: dict) -> bool:
    """
    Validate that a config dict has the required structure.
    
    Checks for presence of critical sections and basic structure validity.
    
    Args:
        config_dict: Configuration dictionary to validate
    
    Returns:
        True if config is valid, False otherwise
    """
    if not isinstance(config_dict, dict):
        return False
    
    # Define required top-level sections
    required_sections = ['capture', 'ai_engine', 'aim', 'input', 'general']
    
    # Check that at least some required sections exist
    # (Allow partial configs for flexibility)
    has_any_section = any(section in config_dict for section in required_sections)
    
    if not has_any_section:
        return False
    
    # Validate that sections are dicts (not primitives)
    for section in config_dict:
        if section in required_sections:
            if not isinstance(config_dict[section], dict):
                return False
    
    return True


def create_timestamped_backup(config_path: str = CONFIG_PATH) -> Optional[str]:
    """
    Create a timestamped backup of the config file.
    
    Maintains up to MAX_BACKUPS timestamped backups, removing oldest when exceeded.
    
    Args:
        config_path: Path to config file to backup
    
    Returns:
        Path to created backup file, or None on failure
    """
    if not os.path.exists(config_path):
        return None
    
    try:
        # Create timestamped backup with microseconds for uniqueness
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        microseconds = int(time.time() * 1000000) % 1000000
        backup_path = f"{config_path}.bak.{timestamp}_{microseconds:06d}"
        shutil.copy2(config_path, backup_path)
        
        # Clean up old backups
        backup_dir = os.path.dirname(config_path)
        if not backup_dir:
            backup_dir = '.'
        backup_prefix = os.path.basename(config_path) + ".bak."
        
        # Find all timestamped backups
        backups = []
        for f in os.listdir(backup_dir):
            if f.startswith(backup_prefix):
                full_path = os.path.join(backup_dir, f)
                backups.append((os.path.getmtime(full_path), full_path))
        
        # Sort by modification time (oldest first)
        backups.sort()
        
        # Remove oldest backups if we exceed MAX_BACKUPS
        while len(backups) > MAX_BACKUPS:
            _, old_backup = backups.pop(0)
            try:
                os.remove(old_backup)
            except Exception as e:
                print(f"[Config] Failed to remove old backup {old_backup}: {e}")
        
        return backup_path
        
    except Exception as e:
        print(f"[Config] Failed to create timestamped backup: {e}")
        return None


def restore_from_backup(config_path: str = CONFIG_PATH) -> bool:
    """
    Restore config from the most recent backup file.
    
    Tries in order:
    1. Most recent timestamped backup (config.yaml.bak.TIMESTAMP)
    2. Simple backup (config.yaml.bak)
    
    Args:
        config_path: Path to config file to restore
    
    Returns:
        True if restoration successful, False otherwise
    """
    backup_dir = os.path.dirname(config_path)
    backup_prefix = os.path.basename(config_path) + ".bak."
    simple_backup = config_path + ".bak"
    
    try:
        # Find all timestamped backups
        backups = []
        for f in os.listdir(backup_dir):
            if f.startswith(backup_prefix):
                full_path = os.path.join(backup_dir, f)
                backups.append((os.path.getmtime(full_path), full_path))
        
        # Sort by modification time (newest first)
        backups.sort(reverse=True)
        
        # Try most recent timestamped backup first
        if backups:
            _, most_recent = backups[0]
            shutil.copy2(most_recent, config_path)
            print(f"[Config] Restored from timestamped backup: {most_recent}")
            return True
        
        # Fall back to simple backup
        if os.path.exists(simple_backup):
            shutil.copy2(simple_backup, config_path)
            print(f"[Config] Restored from simple backup: {simple_backup}")
            return True
        
        print("[Config] No backup files found")
        return False
        
    except Exception as e:
        print(f"[Config] Failed to restore from backup: {e}")
        return False


def load_config_into_shared_state(shared_state, config_path: str = CONFIG_PATH) -> bool:
    """
    Load config from YAML file into shared state.
    
    Handles corrupted file detection and automatic recovery from backups.
    
    Args:
        shared_state: SharedState instance to load config into
        config_path: Path to config file (defaults to main config.yaml)
    
    Returns:
        True if config loaded successfully, False otherwise
    """
    try:
        # Try to load the main config file
        if not os.path.exists(config_path):
            print(f"[Config] Config file not found: {config_path}")
            return False
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config_dict = yaml.safe_load(f)
        
        # Validate config structure
        if not validate_config(config_dict):
            print("[Config] Config file is corrupted or invalid, attempting recovery...")
            
            # Try to restore from backup
            if restore_from_backup(config_path):
                # Retry loading after restoration
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_dict = yaml.safe_load(f)
                
                if not validate_config(config_dict):
                    print("[Config] Backup is also corrupted")
                    return False
                
                print("[Config] Successfully recovered from backup")
            else:
                print("[Config] No valid backup found")
                return False
        
        # Load config into shared state
        for section, values in config_dict.items():
            if isinstance(values, dict):
                # Use update_config_section for efficiency
                shared_state.update_config_section(section, values)
            else:
                # Handle non-dict top-level values
                shared_state.update_config('general', section, values)
        
        print(f"[Config] Loaded config from {config_path}")
        return True
        
    except yaml.YAMLError as e:
        print(f"[Config] YAML parsing error: {e}")
        print("[Config] Attempting recovery from backup...")
        
        # Try to restore from backup
        if restore_from_backup(config_path):
            # Retry loading after restoration
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_dict = yaml.safe_load(f)
                
                if validate_config(config_dict):
                    for section, values in config_dict.items():
                        if isinstance(values, dict):
                            shared_state.update_config_section(section, values)
                        else:
                            shared_state.update_config('general', section, values)
                    
                    print("[Config] Successfully recovered from backup")
                    return True
            except Exception as retry_error:
                print(f"[Config] Retry after backup restoration failed: {retry_error}")
        
        return False
        
    except Exception as e:
        print(f"[Config] Failed to load config: {e}")
        return False


def save_live_config_auto(shared_state, config_path: str = CONFIG_PATH) -> bool:
    """
    Save live config from shared state to YAML file.
    
    Creates timestamped backup before overwriting. Restores backup on failure.
    
    Args:
        shared_state: SharedState instance to read config from
        config_path: Path to config file (defaults to main config.yaml)
    
    Returns:
        True if config saved successfully, False otherwise
    """
    from gui.widgets import notifications
    
    try:
        # Read current config from shared state
        config_dict = shared_state.get_config()
        
        if not config_dict:
            print("[Config] No config data in shared state")
            notifications.add("Failed to save config: No data", color=(1.0, 0.3, 0.3, 1.0))
            return False
        
        # Create timestamped backup before overwriting
        backup_path = create_timestamped_backup(config_path)
        if backup_path:
            print(f"[Config] Created backup: {backup_path}")
        
        # Save to config file
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_dict, f, default_flow_style=False, allow_unicode=True)
        
        print(f"[Config] Saved config to {config_path}")
        notifications.add("Config saved successfully", color=(0.3, 1.0, 0.3, 1.0))
        return True
        
    except Exception as e:
        print(f"[Config] Failed to save config: {e}")
        
        # Attempt to restore from backup on failure
        if os.path.exists(config_path + ".bak"):
            try:
                shutil.copy2(config_path + ".bak", config_path)
                print("[Config] Restored backup after save failure")
                notifications.add("Config save failed - backup restored", color=(1.0, 0.5, 0.3, 1.0))
            except Exception as restore_error:
                print(f"[Config] Failed to restore backup: {restore_error}")
                notifications.add("Config save failed - backup restore failed", color=(1.0, 0.3, 0.3, 1.0))
        else:
            notifications.add(f"Config save failed: {str(e)}", color=(1.0, 0.3, 0.3, 1.0))
        
        return False
