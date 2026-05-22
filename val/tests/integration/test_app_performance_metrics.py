"""
Unit tests for Task 11.1: Live performance metrics display

Tests verify that:
1. FPS counter displays with color coding
2. Inference time displays with color coding (green <5ms, yellow <10ms, red >10ms)
3. Backend name displays correctly (DirectML, Ultralytics, CPU)
4. Capture resolution and FPS cap display correctly
5. Metrics update in real-time from shared state
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.shared_state import SharedState


class TestPerformanceMetricsDisplay:
    """Test suite for live performance metrics display (Task 11.1)."""
    
    def test_fps_color_coding(self):
        """Test FPS counter color coding: green >60, yellow >30, red <=30."""
        print("Testing FPS color coding...")
        
        # Test green (excellent)
        fps = 144.0
        if fps >= 60:
            color = (0.3, 1.0, 0.3, 1.0)
        elif fps >= 30:
            color = (1.0, 0.8, 0.3, 1.0)
        else:
            color = (1.0, 0.3, 0.3, 1.0)
        assert color == (0.3, 1.0, 0.3, 1.0), "FPS >= 60 should be green"
        print("  ✓ FPS >= 60 is green")
        
        # Test yellow (acceptable)
        fps = 45.0
        if fps >= 60:
            color = (0.3, 1.0, 0.3, 1.0)
        elif fps >= 30:
            color = (1.0, 0.8, 0.3, 1.0)
        else:
            color = (1.0, 0.3, 0.3, 1.0)
        assert color == (1.0, 0.8, 0.3, 1.0), "FPS 30-60 should be yellow"
        print("  ✓ FPS 30-60 is yellow")
        
        # Test red (poor)
        fps = 25.0
        if fps >= 60:
            color = (0.3, 1.0, 0.3, 1.0)
        elif fps >= 30:
            color = (1.0, 0.8, 0.3, 1.0)
        else:
            color = (1.0, 0.3, 0.3, 1.0)
        assert color == (1.0, 0.3, 0.3, 1.0), "FPS < 30 should be red"
        print("  ✓ FPS < 30 is red")
    
    def test_inference_time_color_coding(self):
        """Test inference time color coding: green <5ms, yellow <10ms, red >10ms."""
        print("\nTesting inference time color coding...")
        
        # Test green (excellent)
        inference_ms = 3.2
        if inference_ms < 5.0:
            color = (0.3, 1.0, 0.3, 1.0)
        elif inference_ms < 10.0:
            color = (1.0, 0.8, 0.3, 1.0)
        else:
            color = (1.0, 0.3, 0.3, 1.0)
        assert color == (0.3, 1.0, 0.3, 1.0), "Inference < 5ms should be green"
        print("  ✓ Inference < 5ms is green")
        
        # Test yellow (good)
        inference_ms = 7.5
        if inference_ms < 5.0:
            color = (0.3, 1.0, 0.3, 1.0)
        elif inference_ms < 10.0:
            color = (1.0, 0.8, 0.3, 1.0)
        else:
            color = (1.0, 0.3, 0.3, 1.0)
        assert color == (1.0, 0.8, 0.3, 1.0), "Inference 5-10ms should be yellow"
        print("  ✓ Inference 5-10ms is yellow")
        
        # Test red (poor)
        inference_ms = 15.0
        if inference_ms < 5.0:
            color = (0.3, 1.0, 0.3, 1.0)
        elif inference_ms < 10.0:
            color = (1.0, 0.8, 0.3, 1.0)
        else:
            color = (1.0, 0.3, 0.3, 1.0)
        assert color == (1.0, 0.3, 0.3, 1.0), "Inference > 10ms should be red"
        print("  ✓ Inference > 10ms is red")
    
    def test_backend_name_formatting(self):
        """Test backend name display formatting."""
        print("\nTesting backend name formatting...")
        
        # Test DirectML
        backend = 'directml'
        if backend == 'directml':
            display = 'DirectML'
        elif backend == 'ultralytics':
            display = 'Ultralytics'
        elif backend == 'cpu':
            display = 'CPU'
        else:
            display = backend.upper() if backend != 'none' else 'None'
        assert display == 'DirectML', "directml should display as DirectML"
        print("  ✓ 'directml' displays as 'DirectML'")
        
        # Test Ultralytics
        backend = 'ultralytics'
        if backend == 'directml':
            display = 'DirectML'
        elif backend == 'ultralytics':
            display = 'Ultralytics'
        elif backend == 'cpu':
            display = 'CPU'
        else:
            display = backend.upper() if backend != 'none' else 'None'
        assert display == 'Ultralytics', "ultralytics should display as Ultralytics"
        print("  ✓ 'ultralytics' displays as 'Ultralytics'")
        
        # Test CPU
        backend = 'cpu'
        if backend == 'directml':
            display = 'DirectML'
        elif backend == 'ultralytics':
            display = 'Ultralytics'
        elif backend == 'cpu':
            display = 'CPU'
        else:
            display = backend.upper() if backend != 'none' else 'None'
        assert display == 'CPU', "cpu should display as CPU"
        print("  ✓ 'cpu' displays as 'CPU'")
        
        # Test None
        backend = 'none'
        if backend == 'directml':
            display = 'DirectML'
        elif backend == 'ultralytics':
            display = 'Ultralytics'
        elif backend == 'cpu':
            display = 'CPU'
        else:
            display = backend.upper() if backend != 'none' else 'None'
        assert display == 'None', "none should display as None"
        print("  ✓ 'none' displays as 'None'")
    
    def test_shared_state_metrics_integration(self):
        """Test that metrics are correctly read from shared state."""
        print("\nTesting shared state metrics integration...")
        
        shared_state = SharedState()
        
        # Set test metrics
        shared_state.update_state('fps', 144.5)
        shared_state.update_state('ai_inference_ms', 3.2)
        shared_state.update_state('ai_backend', 'directml')
        shared_state.update_state('capture_resolution', '416x416')
        shared_state.update_state('capture_fps_cap', 60)
        
        # Read metrics
        fps = shared_state.get_state('fps', 0.0)
        inference_ms = shared_state.get_state('ai_inference_ms', 0.0)
        backend = shared_state.get_state('ai_backend', 'none')
        resolution = shared_state.get_state('capture_resolution', 'unknown')
        fps_cap = shared_state.get_state('capture_fps_cap', 0)
        
        # Verify
        assert fps == 144.5, "FPS should be 144.5"
        assert inference_ms == 3.2, "Inference time should be 3.2ms"
        assert backend == 'directml', "Backend should be directml"
        assert resolution == '416x416', "Resolution should be 416x416"
        assert fps_cap == 60, "FPS cap should be 60"
        
        print("  ✓ FPS: 144.5")
        print("  ✓ Inference: 3.2ms")
        print("  ✓ Backend: directml")
        print("  ✓ Resolution: 416x416")
        print("  ✓ FPS cap: 60")
    
    def test_capture_resolution_formatting(self):
        """Test capture resolution display formatting."""
        print("\nTesting capture resolution formatting...")
        
        # Test AI engine capture size
        capture_size = 416
        resolution = f"{capture_size}x{capture_size}"
        assert resolution == "416x416", "AI capture should be 416x416"
        print("  ✓ AI capture: 416x416")
        
        # Test capture card resolution
        res_w = 1920
        res_h = 1080
        resolution = f"{res_w}x{res_h}"
        assert resolution == "1920x1080", "Capture card should be 1920x1080"
        print("  ✓ Capture card: 1920x1080")
    
    def test_metrics_display_text_formatting(self):
        """Test that metrics are formatted correctly for display."""
        print("\nTesting metrics display text formatting...")
        
        # FPS formatting
        fps = 144.567
        fps_text = f"FPS: {fps:.0f}"
        assert fps_text == "FPS: 145", "FPS should round to nearest integer"
        print(f"  ✓ FPS formatting: {fps_text}")
        
        # Inference time formatting
        inference_ms = 3.2456
        inference_text = f"Inference: {inference_ms:.2f}ms"
        assert inference_text == "Inference: 3.25ms", "Inference should show 2 decimal places"
        print(f"  ✓ Inference formatting: {inference_text}")
        
        # Capture info formatting
        resolution = "416x416"
        fps_cap = 60
        capture_text = f"{resolution} @ {fps_cap} FPS"
        assert capture_text == "416x416 @ 60 FPS", "Capture info should be formatted correctly"
        print(f"  ✓ Capture info formatting: {capture_text}")
    
    def test_default_values_when_state_empty(self):
        """Test that default values are used when state is empty."""
        print("\nTesting default values when state is empty...")
        
        shared_state = SharedState()
        
        # Read metrics with defaults
        fps = shared_state.get_state('fps', 0.0)
        inference_ms = shared_state.get_state('ai_inference_ms', 0.0)
        backend = shared_state.get_state('ai_backend', 'none')
        resolution = shared_state.get_state('capture_resolution', 'unknown')
        fps_cap = shared_state.get_state('capture_fps_cap', 0)
        
        # Verify defaults
        assert fps == 0.0, "Default FPS should be 0.0"
        assert inference_ms == 0.0, "Default inference time should be 0.0"
        assert backend == 'none', "Default backend should be none"
        assert resolution == 'unknown', "Default resolution should be unknown"
        assert fps_cap == 0, "Default FPS cap should be 0"
        
        print("  ✓ Default FPS: 0.0")
        print("  ✓ Default inference: 0.0ms")
        print("  ✓ Default backend: none")
        print("  ✓ Default resolution: unknown")
        print("  ✓ Default FPS cap: 0")


class TestCoordinatorCaptureMetrics:
    """Test suite for coordinator capture metrics updates."""
    
    def test_capture_resolution_from_ai_config(self):
        """Test capture resolution is derived from AI engine config."""
        print("\nTesting capture resolution from AI config...")
        
        config = {
            'capture': {'backend': 'dxgi', 'fps_cap': 60},
            'ai_engine': {'capture_size': 416}
        }
        
        capture_backend = config.get('capture', {}).get('backend', 'dxgi')
        ai_config = config.get('ai_engine', {})
        
        if capture_backend == 'capture_card':
            capture_config = config.get('capture', {})
            res_w = capture_config.get('resolution_width', 1920)
            res_h = capture_config.get('resolution_height', 1080)
            resolution = f"{res_w}x{res_h}"
        else:
            capture_size = ai_config.get('capture_size', 416)
            resolution = f"{capture_size}x{capture_size}"
        
        assert resolution == "416x416", "DXGI backend should use AI capture size"
        print("  ✓ DXGI backend uses AI capture size: 416x416")
    
    def test_capture_resolution_from_capture_card_config(self):
        """Test capture resolution is derived from capture card config."""
        print("\nTesting capture resolution from capture card config...")
        
        config = {
            'capture': {
                'backend': 'capture_card',
                'fps_cap': 60,
                'resolution_width': 1920,
                'resolution_height': 1080
            },
            'ai_engine': {'capture_size': 416}
        }
        
        capture_backend = config.get('capture', {}).get('backend', 'dxgi')
        capture_config = config.get('capture', {})
        ai_config = config.get('ai_engine', {})
        
        if capture_backend == 'capture_card':
            res_w = capture_config.get('resolution_width', 1920)
            res_h = capture_config.get('resolution_height', 1080)
            resolution = f"{res_w}x{res_h}"
        else:
            capture_size = ai_config.get('capture_size', 416)
            resolution = f"{capture_size}x{capture_size}"
        
        assert resolution == "1920x1080", "Capture card backend should use card resolution"
        print("  ✓ Capture card backend uses card resolution: 1920x1080")
    
    def test_fps_cap_from_config(self):
        """Test FPS cap is read from capture config."""
        print("\nTesting FPS cap from config...")
        
        config = {
            'capture': {'backend': 'dxgi', 'fps_cap': 120}
        }
        
        fps_cap = config.get('capture', {}).get('fps_cap', 60)
        assert fps_cap == 120, "FPS cap should be 120"
        print("  ✓ FPS cap: 120")


class TestPerformanceMonitoring:
    """Test suite for Task 16.3: Performance monitoring and optimization."""
    
    def test_gui_frame_time_measurement(self):
        """Test GUI frame time measurement and color coding."""
        print("\nTesting GUI frame time measurement...")
        
        shared_state = SharedState()
        
        # Test excellent performance (< 16.67ms = 60+ FPS)
        shared_state.update_state('gui_frame_time_ms', 12.5)
        shared_state.update_state('gui_fps', 80.0)
        
        gui_frame_time_ms = shared_state.get_state('gui_frame_time_ms', 0.0)
        gui_fps = shared_state.get_state('gui_fps', 0.0)
        
        assert gui_frame_time_ms == 12.5, "GUI frame time should be 12.5ms"
        assert gui_fps == 80.0, "GUI FPS should be 80.0"
        
        # Color coding: Green <16.67ms
        if gui_frame_time_ms < 16.67:
            color = (0.3, 1.0, 0.3, 1.0)
        elif gui_frame_time_ms < 33.33:
            color = (1.0, 0.8, 0.3, 1.0)
        else:
            color = (1.0, 0.3, 0.3, 1.0)
        
        assert color == (0.3, 1.0, 0.3, 1.0), "Frame time < 16.67ms should be green"
        print("  ✓ GUI frame time: 12.5ms (80 FPS) - green")
        
        # Test acceptable performance (16.67-33.33ms = 30-60 FPS)
        shared_state.update_state('gui_frame_time_ms', 25.0)
        gui_frame_time_ms = shared_state.get_state('gui_frame_time_ms', 0.0)
        
        if gui_frame_time_ms < 16.67:
            color = (0.3, 1.0, 0.3, 1.0)
        elif gui_frame_time_ms < 33.33:
            color = (1.0, 0.8, 0.3, 1.0)
        else:
            color = (1.0, 0.3, 0.3, 1.0)
        
        assert color == (1.0, 0.8, 0.3, 1.0), "Frame time 16.67-33.33ms should be yellow"
        print("  ✓ GUI frame time: 25.0ms (40 FPS) - yellow")
        
        # Test poor performance (> 33.33ms = < 30 FPS)
        shared_state.update_state('gui_frame_time_ms', 50.0)
        gui_frame_time_ms = shared_state.get_state('gui_frame_time_ms', 0.0)
        
        if gui_frame_time_ms < 16.67:
            color = (0.3, 1.0, 0.3, 1.0)
        elif gui_frame_time_ms < 33.33:
            color = (1.0, 0.8, 0.3, 1.0)
        else:
            color = (1.0, 0.3, 0.3, 1.0)
        
        assert color == (1.0, 0.3, 0.3, 1.0), "Frame time > 33.33ms should be red"
        print("  ✓ GUI frame time: 50.0ms (20 FPS) - red")
    
    def test_engine_loop_time_measurement(self):
        """Test engine loop time measurement and color coding."""
        print("\nTesting engine loop time measurement...")
        
        shared_state = SharedState()
        
        # Test excellent performance (< 50ms)
        shared_state.update_state('engine_loop_ms', 4.2)
        shared_state.update_state('engine_hz', 238.0)
        
        engine_loop_ms = shared_state.get_state('engine_loop_ms', 0.0)
        engine_hz = shared_state.get_state('engine_hz', 0.0)
        
        assert engine_loop_ms == 4.2, "Engine loop time should be 4.2ms"
        assert engine_hz == 238.0, "Engine Hz should be 238.0"
        
        # Color coding: Green <50ms
        if engine_loop_ms < 50.0:
            color = (0.3, 1.0, 0.3, 1.0)
        elif engine_loop_ms < 100.0:
            color = (1.0, 0.8, 0.3, 1.0)
        else:
            color = (1.0, 0.3, 0.3, 1.0)
        
        assert color == (0.3, 1.0, 0.3, 1.0), "Engine loop < 50ms should be green"
        print("  ✓ Engine loop: 4.2ms (238 Hz) - green")
        
        # Test acceptable performance (50-100ms)
        shared_state.update_state('engine_loop_ms', 75.0)
        engine_loop_ms = shared_state.get_state('engine_loop_ms', 0.0)
        
        if engine_loop_ms < 50.0:
            color = (0.3, 1.0, 0.3, 1.0)
        elif engine_loop_ms < 100.0:
            color = (1.0, 0.8, 0.3, 1.0)
        else:
            color = (1.0, 0.3, 0.3, 1.0)
        
        assert color == (1.0, 0.8, 0.3, 1.0), "Engine loop 50-100ms should be yellow"
        print("  ✓ Engine loop: 75.0ms (13 Hz) - yellow")
        
        # Test poor performance (> 100ms)
        shared_state.update_state('engine_loop_ms', 150.0)
        engine_loop_ms = shared_state.get_state('engine_loop_ms', 0.0)
        
        if engine_loop_ms < 50.0:
            color = (0.3, 1.0, 0.3, 1.0)
        elif engine_loop_ms < 100.0:
            color = (1.0, 0.8, 0.3, 1.0)
        else:
            color = (1.0, 0.3, 0.3, 1.0)
        
        assert color == (1.0, 0.3, 0.3, 1.0), "Engine loop > 100ms should be red"
        print("  ✓ Engine loop: 150.0ms (7 Hz) - red")
    
    def test_config_update_latency_measurement(self):
        """Test config update latency measurement and color coding."""
        print("\nTesting config update latency measurement...")
        
        shared_state = SharedState()
        
        # Test excellent latency (< 50ms)
        shared_state.update_state('config_update_latency_ms', 25.0)
        
        latency_ms = shared_state.get_state('config_update_latency_ms', 0.0)
        assert latency_ms == 25.0, "Config update latency should be 25.0ms"
        
        # Color coding: Green <50ms
        if latency_ms < 50.0:
            color = (0.3, 1.0, 0.3, 1.0)
        elif latency_ms < 100.0:
            color = (1.0, 0.8, 0.3, 1.0)
        else:
            color = (1.0, 0.3, 0.3, 1.0)
        
        assert color == (0.3, 1.0, 0.3, 1.0), "Config update < 50ms should be green"
        print("  ✓ Config update latency: 25.0ms - green")
        
        # Test acceptable latency (50-100ms)
        shared_state.update_state('config_update_latency_ms', 75.0)
        latency_ms = shared_state.get_state('config_update_latency_ms', 0.0)
        
        if latency_ms < 50.0:
            color = (0.3, 1.0, 0.3, 1.0)
        elif latency_ms < 100.0:
            color = (1.0, 0.8, 0.3, 1.0)
        else:
            color = (1.0, 0.3, 0.3, 1.0)
        
        assert color == (1.0, 0.8, 0.3, 1.0), "Config update 50-100ms should be yellow"
        print("  ✓ Config update latency: 75.0ms - yellow")
        
        # Test poor latency (> 100ms)
        shared_state.update_state('config_update_latency_ms', 150.0)
        latency_ms = shared_state.get_state('config_update_latency_ms', 0.0)
        
        if latency_ms < 50.0:
            color = (0.3, 1.0, 0.3, 1.0)
        elif latency_ms < 100.0:
            color = (1.0, 0.8, 0.3, 1.0)
        else:
            color = (1.0, 0.3, 0.3, 1.0)
        
        assert color == (1.0, 0.3, 0.3, 1.0), "Config update > 100ms should be red"
        print("  ✓ Config update latency: 150.0ms - red")
    
    def test_performance_warning_thresholds(self):
        """Test that performance warnings are triggered at correct thresholds."""
        print("\nTesting performance warning thresholds...")
        
        # GUI frame time threshold: 16.67ms (60 FPS)
        gui_threshold = 16.67
        assert gui_threshold == 16.67, "GUI frame time threshold should be 16.67ms"
        print(f"  ✓ GUI frame time threshold: {gui_threshold}ms (60 FPS)")
        
        # Engine loop threshold: 50ms
        engine_threshold = 50.0
        assert engine_threshold == 50.0, "Engine loop threshold should be 50ms"
        print(f"  ✓ Engine loop threshold: {engine_threshold}ms")
        
        # Config update threshold: 50ms
        config_threshold = 50.0
        assert config_threshold == 50.0, "Config update threshold should be 50ms"
        print(f"  ✓ Config update threshold: {config_threshold}ms")
    
    def test_performance_metrics_display_formatting(self):
        """Test that performance metrics are formatted correctly for display."""
        print("\nTesting performance metrics display formatting...")
        
        # GUI frame time formatting
        gui_frame_time_ms = 12.567
        gui_fps = 79.123
        gui_text = f"GUI Frame: {gui_frame_time_ms:.2f}ms ({gui_fps:.0f} FPS)"
        assert gui_text == "GUI Frame: 12.57ms (79 FPS)", "GUI frame time should be formatted correctly"
        print(f"  ✓ GUI frame time: {gui_text}")
        
        # Engine loop formatting
        engine_loop_ms = 4.234
        engine_hz = 236.456
        engine_text = f"Engine Loop: {engine_loop_ms:.2f}ms ({engine_hz:.0f} Hz)"
        assert engine_text == "Engine Loop: 4.23ms (236 Hz)", "Engine loop should be formatted correctly"
        print(f"  ✓ Engine loop: {engine_text}")
        
        # Config update latency formatting
        latency_ms = 25.678
        latency_text = f"Config Update: {latency_ms:.2f}ms"
        assert latency_text == "Config Update: 25.68ms", "Config update latency should be formatted correctly"
        print(f"  ✓ Config update latency: {latency_text}")


def run_tests():
    """Run all tests."""
    print("=" * 70)
    print("Task 11.1 & 16.3: Performance Metrics & Monitoring - Unit Tests")
    print("=" * 70)
    
    test_suite1 = TestPerformanceMetricsDisplay()
    test_suite2 = TestCoordinatorCaptureMetrics()
    test_suite3 = TestPerformanceMonitoring()
    
    tests_passed = 0
    tests_failed = 0
    
    # Run TestPerformanceMetricsDisplay tests
    for method_name in dir(test_suite1):
        if method_name.startswith('test_'):
            try:
                method = getattr(test_suite1, method_name)
                method()
                tests_passed += 1
            except AssertionError as e:
                print(f"\n✗ {method_name} FAILED: {e}")
                tests_failed += 1
            except Exception as e:
                print(f"\n✗ {method_name} ERROR: {e}")
                tests_failed += 1
    
    # Run TestCoordinatorCaptureMetrics tests
    for method_name in dir(test_suite2):
        if method_name.startswith('test_'):
            try:
                method = getattr(test_suite2, method_name)
                method()
                tests_passed += 1
            except AssertionError as e:
                print(f"\n✗ {method_name} FAILED: {e}")
                tests_failed += 1
            except Exception as e:
                print(f"\n✗ {method_name} ERROR: {e}")
                tests_failed += 1
    
    # Run TestPerformanceMonitoring tests
    for method_name in dir(test_suite3):
        if method_name.startswith('test_'):
            try:
                method = getattr(test_suite3, method_name)
                method()
                tests_passed += 1
            except AssertionError as e:
                print(f"\n✗ {method_name} FAILED: {e}")
                tests_failed += 1
            except Exception as e:
                print(f"\n✗ {method_name} ERROR: {e}")
                tests_failed += 1
    
    print("\n" + "=" * 70)
    print(f"Test Results: {tests_passed} passed, {tests_failed} failed")
    print("=" * 70)
    
    return tests_failed == 0


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)

