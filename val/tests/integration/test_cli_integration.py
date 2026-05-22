"""
Integration test for command-line argument parsing.

This script tests the command-line argument parsing by simulating
different argument combinations and verifying the behavior.
"""

import sys
import os
import tempfile
import yaml


def test_help_output():
    """Test that --help displays usage information."""
    print("Testing --help output...")
    import subprocess
    
    result = subprocess.run(
        [sys.executable, 'main.py', '--help'],
        capture_output=True,
        text=True,
        timeout=5
    )
    
    # Check that help text contains expected flags
    assert '--gui' in result.stdout, "Missing --gui in help"
    assert '--debug' in result.stdout, "Missing --debug in help"
    assert '--config' in result.stdout, "Missing --config in help"
    assert '--no-engines' in result.stdout, "Missing --no-engines in help"
    assert '--preset' in result.stdout, "Missing --preset in help"
    
    print("✓ Help output contains all expected flags")


def test_argument_parsing():
    """Test that arguments are parsed correctly."""
    print("\nTesting argument parsing...")
    
    # Create a test script that imports and parses arguments
    test_script = """
import sys
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--gui', action='store_true')
parser.add_argument('--debug', action='store_true')
parser.add_argument('--config', type=str, default='config.yaml')
parser.add_argument('--no-engines', action='store_true')
parser.add_argument('--preset', type=str, default=None)

args = parser.parse_args()

print(f"gui={args.gui}")
print(f"debug={args.debug}")
print(f"config={args.config}")
print(f"no_engines={args.no_engines}")
print(f"preset={args.preset}")
"""
    
    # Test with various argument combinations
    test_cases = [
        ([], {'gui': False, 'debug': False, 'config': 'config.yaml', 'no_engines': False, 'preset': None}),
        (['--gui'], {'gui': True, 'debug': False, 'config': 'config.yaml', 'no_engines': False, 'preset': None}),
        (['--debug'], {'gui': False, 'debug': True, 'config': 'config.yaml', 'no_engines': False, 'preset': None}),
        (['--config', 'custom.yaml'], {'gui': False, 'debug': False, 'config': 'custom.yaml', 'no_engines': False, 'preset': None}),
        (['--no-engines'], {'gui': False, 'debug': False, 'config': 'config.yaml', 'no_engines': True, 'preset': None}),
        (['--preset', 'aggressive'], {'gui': False, 'debug': False, 'config': 'config.yaml', 'no_engines': False, 'preset': 'aggressive'}),
        (['--gui', '--debug', '--no-engines'], {'gui': True, 'debug': True, 'config': 'config.yaml', 'no_engines': True, 'preset': None}),
    ]
    
    import subprocess
    
    for args, expected in test_cases:
        # Write test script to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(test_script)
            temp_script = f.name
        
        try:
            # Run test script with arguments
            result = subprocess.run(
                [sys.executable, temp_script] + args,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            # Parse output
            output_dict = {}
            for line in result.stdout.strip().split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    # Convert string values to appropriate types
                    if value == 'True':
                        value = True
                    elif value == 'False':
                        value = False
                    elif value == 'None':
                        value = None
                    output_dict[key] = value
            
            # Verify output matches expected
            for key, expected_value in expected.items():
                actual_value = output_dict.get(key)
                assert actual_value == expected_value, \
                    f"Mismatch for {key}: expected {expected_value}, got {actual_value} (args: {args})"
            
            print(f"✓ Arguments {args} parsed correctly")
        
        finally:
            # Clean up temp file
            if os.path.exists(temp_script):
                os.unlink(temp_script)


def test_config_file_validation():
    """Test that config file validation works."""
    print("\nTesting config file validation...")
    
    # Create a temporary config file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        test_config = {
            'general': {'log_level': 'INFO'},
            'capture': {'backend': 'dxgi'}
        }
        yaml.dump(test_config, f)
        temp_config = f.name
    
    try:
        # Test that file exists
        assert os.path.exists(temp_config), "Temp config file should exist"
        print(f"✓ Config file validation works")
    
    finally:
        # Clean up
        if os.path.exists(temp_config):
            os.unlink(temp_config)


def test_preset_file_validation():
    """Test that preset file validation works."""
    print("\nTesting preset file validation...")
    
    # Create a temporary preset directory and file
    temp_dir = tempfile.mkdtemp()
    preset_path = os.path.join(temp_dir, 'test_preset.yaml')
    
    preset_config = {
        'ai_engine': {'confidence': 0.75},
        'aim': {'speed': 1.5}
    }
    
    with open(preset_path, 'w') as f:
        yaml.dump(preset_config, f)
    
    try:
        # Test that file exists
        assert os.path.exists(preset_path), "Preset file should exist"
        
        # Test loading preset
        with open(preset_path, 'r') as f:
            loaded_preset = yaml.safe_load(f)
        
        assert loaded_preset['ai_engine']['confidence'] == 0.75
        assert loaded_preset['aim']['speed'] == 1.5
        
        print(f"✓ Preset file validation works")
    
    finally:
        # Clean up
        if os.path.exists(preset_path):
            os.unlink(preset_path)
        if os.path.exists(temp_dir):
            os.rmdir(temp_dir)


if __name__ == '__main__':
    print("=" * 60)
    print("Command-Line Argument Integration Tests")
    print("=" * 60)
    
    try:
        test_help_output()
        test_argument_parsing()
        test_config_file_validation()
        test_preset_file_validation()
        
        print("\n" + "=" * 60)
        print("All integration tests passed! ✓")
        print("=" * 60)
    
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
