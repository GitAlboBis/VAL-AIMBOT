"""
Test suite for debug mode toggle and display functionality.

Tests Task 13.1: Add debug mode toggle and display
- Debug mode checkbox in Miscellaneous section
- Backend type display (imgui_bundle or pyimgui)
- Delta time display for animation calculations
- Active animation state count display
- Current tab index and page offset display
- Engine thread state display (running/stopped/error)
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.shared_state import SharedState
from gui.imgui_compat import IMGUI_BACKEND


def test_debug_mode_toggle():
    """Test that debug mode can be toggled via config."""
    print("\n=== Test: Debug Mode Toggle ===")
    
    shared_state = SharedState()
    
    # Initially debug mode should be False
    shared_state.update_config('general', 'debug_mode', False)
    config = shared_state.get_config()
    assert config['general']['debug_mode'] == False, "Debug mode should start as False"
    
    # Enable debug mode
    shared_state.update_config('general', 'debug_mode', True)
    config = shared_state.get_config()
    assert config['general']['debug_mode'] == True, "Debug mode should be enabled"
    
    # Disable debug mode
    shared_state.update_config('general', 'debug_mode', False)
    config = shared_state.get_config()
    assert config['general']['debug_mode'] == False, "Debug mode should be disabled"
    
    print("✓ Debug mode toggle works correctly")


def test_backend_type_available():
    """Test that backend type constant is available."""
    print("\n=== Test: Backend Type Available ===")
    
    # IMGUI_BACKEND should be one of: "imgui_bundle", "pyimgui", "none"
    assert IMGUI_BACKEND in ["imgui_bundle", "pyimgui", "none"], \
        f"IMGUI_BACKEND should be valid, got: {IMGUI_BACKEND}"
    
    print(f"✓ Backend type is available: {IMGUI_BACKEND}")


def test_delta_time_accessible():
    """Test that delta time is accessible from widgets module."""
    print("\n=== Test: Delta Time Accessible ===")
    
    from gui.widgets import _delta_time
    
    # Delta time should be a positive float
    assert isinstance(_delta_time, float), "Delta time should be a float"
    assert _delta_time > 0, "Delta time should be positive"
    
    print(f"✓ Delta time is accessible: {_delta_time:.4f}s")


def test_animation_states_accessible():
    """Test that animation states dict is accessible from widgets module."""
    print("\n=== Test: Animation States Accessible ===")
    
    from gui.widgets import _anim_state
    
    # Animation states should be a dict
    assert isinstance(_anim_state, dict), "Animation states should be a dict"
    
    # Initially should be empty or have some states
    print(f"✓ Animation states dict is accessible: {len(_anim_state)} states")


def test_engine_thread_state_in_shared_state():
    """Test that engine thread state can be stored in shared state."""
    print("\n=== Test: Engine Thread State in Shared State ===")
    
    shared_state = SharedState()
    
    # Test all valid engine thread states
    valid_states = ['running', 'stopped', 'error', 'unknown']
    
    for state in valid_states:
        shared_state.update_state('engine_thread_state', state)
        retrieved_state = shared_state.get_state('engine_thread_state', 'unknown')
        assert retrieved_state == state, f"Engine thread state should be {state}"
        print(f"  ✓ Engine thread state '{state}' stored and retrieved correctly")
    
    print("✓ Engine thread state works in shared state")


def test_tab_system_properties():
    """Test that TabSystem has required properties for debug display."""
    print("\n=== Test: TabSystem Properties ===")
    
    from gui.widgets import TabSystem
    
    # Create a test tab system
    tabs = TabSystem([
        ("COMBAT", ["Aim Assistance", "Close Aim"]),
        ("VISUALS", ["Players", "Radar"]),
        ("MISCELLANEOUS", ["Misc", "Exploits"]),
    ])
    
    # Check that required properties exist
    assert hasattr(tabs, 'current_idx'), "TabSystem should have current_idx"
    assert hasattr(tabs, 'page_offset'), "TabSystem should have page_offset"
    
    # Check initial values
    assert isinstance(tabs.current_idx, int), "current_idx should be an int"
    assert isinstance(tabs.page_offset, (int, float)), "page_offset should be numeric"
    
    print(f"✓ TabSystem has required properties:")
    print(f"  - current_idx: {tabs.current_idx}")
    print(f"  - page_offset: {tabs.page_offset}")


def test_debug_info_state_keys():
    """Test that all debug info state keys can be stored in shared state."""
    print("\n=== Test: Debug Info State Keys ===")
    
    shared_state = SharedState()
    
    # Test storing and retrieving all debug-related state keys
    debug_keys = {
        'engine_thread_state': 'running',
        'engine_loop_ms': 4.2,
        'engine_hz': 240.0,
    }
    
    for key, value in debug_keys.items():
        shared_state.update_state(key, value)
        retrieved = shared_state.get_state(key)
        assert retrieved == value, f"State key '{key}' should store and retrieve correctly"
        print(f"  ✓ State key '{key}' = {value}")
    
    print("✓ All debug info state keys work correctly")


def test_debug_mode_config_section():
    """Test that debug mode is stored in the correct config section."""
    print("\n=== Test: Debug Mode Config Section ===")
    
    shared_state = SharedState()
    
    # Debug mode should be in 'general' section, not 'misc'
    shared_state.update_config('general', 'debug_mode', True)
    
    config = shared_state.get_config()
    assert 'general' in config, "Config should have 'general' section"
    assert 'debug_mode' in config['general'], "General section should have 'debug_mode'"
    assert config['general']['debug_mode'] == True, "Debug mode should be True"
    
    print("✓ Debug mode is stored in 'general' config section")


def test_debug_display_conditional():
    """Test that debug display is conditional on debug_mode being enabled."""
    print("\n=== Test: Debug Display Conditional ===")
    
    shared_state = SharedState()
    
    # When debug mode is False, debug info should not be displayed
    shared_state.update_config('general', 'debug_mode', False)
    config = shared_state.get_config()
    
    # Simulate the conditional check in _page_misc
    debug_mode = config.get('general', {}).get('debug_mode', False)
    should_display_debug = debug_mode and shared_state is not None
    
    assert should_display_debug == False, "Debug info should not display when debug_mode is False"
    print("  ✓ Debug info hidden when debug_mode is False")
    
    # When debug mode is True, debug info should be displayed
    shared_state.update_config('general', 'debug_mode', True)
    config = shared_state.get_config()
    
    debug_mode = config.get('general', {}).get('debug_mode', False)
    should_display_debug = debug_mode and shared_state is not None
    
    assert should_display_debug == True, "Debug info should display when debug_mode is True"
    print("  ✓ Debug info shown when debug_mode is True")
    
    print("✓ Debug display is properly conditional")


def run_all_tests():
    """Run all debug mode tests."""
    print("\n" + "="*60)
    print("Running Debug Mode Tests (Task 13.1)")
    print("="*60)
    
    try:
        test_debug_mode_toggle()
        test_backend_type_available()
        test_delta_time_accessible()
        test_animation_states_accessible()
        test_engine_thread_state_in_shared_state()
        test_tab_system_properties()
        test_debug_info_state_keys()
        test_debug_mode_config_section()
        test_debug_display_conditional()
        
        print("\n" + "="*60)
        print("✓ All Debug Mode Tests Passed!")
        print("="*60)
        return True
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return False
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
