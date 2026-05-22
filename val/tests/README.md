# Test Suite Documentation

This document provides comprehensive instructions for running and managing the test suite for the Python-based detection framework.

## Overview

The test suite contains **538 tests** organized into two main categories:
- **Unit Tests** (`tests/unit/`): Fast, isolated tests with no external dependencies
- **Integration Tests** (`tests/integration/`): Slower tests that may require hardware or real components

## Quick Start

### Run All Tests
```bash
pytest
```

### Run Only Unit Tests (Fast)
```bash
pytest -m unit
```

### Run Only Integration Tests
```bash
pytest -m integration
```

### Run with Coverage Report
```bash
pytest --cov=. --cov-report=html
```

This generates an HTML coverage report in `htmlcov/index.html`.

## Test Execution Commands

### Basic Commands

| Command | Description |
|---------|-------------|
| `pytest` | Run all tests |
| `pytest -v` | Run with verbose output |
| `pytest -q` | Run with quiet output |
| `pytest --tb=short` | Show short traceback format |

### Filtering Tests

| Command | Description |
|---------|-------------|
| `pytest -m unit` | Run only unit tests |
| `pytest -m integration` | Run only integration tests |
| `pytest -m "not slow"` | Skip slow tests |
| `pytest -k "test_ai_engine"` | Run tests matching pattern |
| `pytest tests/unit/test_ai_engine.py` | Run specific test file |
| `pytest tests/unit/test_ai_engine.py::TestAIEngine::test_process_frame_with_none_frame` | Run specific test |

### Coverage Commands

| Command | Description |
|---------|-------------|
| `pytest --cov=.` | Run with coverage |
| `pytest --cov=. --cov-report=html` | Generate HTML coverage report |
| `pytest --cov=. --cov-report=term-missing` | Show missing lines in terminal |
| `pytest --cov=engines --cov-report=html` | Coverage for specific module |

### Performance and Debugging

| Command | Description |
|---------|-------------|
| `pytest --durations=10` | Show 10 slowest tests |
| `pytest --pdb` | Drop into debugger on failures |
| `pytest --lf` | Run only last failed tests |
| `pytest --ff` | Run failures first, then rest |
| `pytest -x` | Stop on first failure |

## Test Markers

The test suite uses pytest markers to categorize tests:

### Available Markers

- **`@pytest.mark.unit`**: Unit tests (fast, no external dependencies)
- **`@pytest.mark.integration`**: Integration tests (slower, may require hardware)
- **`@pytest.mark.slow`**: Slow tests (can be skipped with `-m "not slow"`)

### Using Markers

```python
import pytest

@pytest.mark.unit
def test_fast_function():
    """Fast unit test."""
    pass

@pytest.mark.integration
def test_engine_coordination():
    """Integration test requiring real components."""
    pass

@pytest.mark.slow
def test_performance_benchmark():
    """Slow performance test."""
    pass
```

## Test Structure

### Directory Layout

```
tests/
├── conftest.py              # Pytest fixtures and configuration
├── unit/                    # Unit tests (fast, isolated)
│   ├── test_ai_engine.py
│   ├── test_hsv_engine.py
│   ├── test_aim_controller.py
│   ├── test_target_tracker.py
│   ├── test_memory_esp.py
│   ├── test_shared_state.py
│   ├── test_config_manager.py
│   └── test_error_handler.py
├── integration/             # Integration tests (slower)
│   ├── test_engine_coordinator.py
│   ├── test_gui_integration.py
│   ├── test_error_recovery.py
│   ├── test_full_integration.py
│   └── test_config_hotreload.py
└── README.md               # This file
```

### Test Categories

#### Unit Tests (42 test files)
- **Engine Tests**: AI engine, HSV engine, aim controller, target tracker, memory ESP
- **State Management**: Shared state, config manager
- **Error Handling**: Error handler, validation
- **GUI Components**: Status indicators, keybind capture
- **Utilities**: Debug logging, conflict detection

#### Integration Tests (26 test files)
- **Full Application**: End-to-end integration, startup/shutdown
- **Engine Coordination**: Multi-engine coordination, error recovery
- **GUI Integration**: App integration, live data, performance metrics
- **Configuration**: Hot-reload, preset management
- **Theme Verification**: Colors, layout, animations, styling

## Common Test Scenarios

### Running Tests During Development

```bash
# Quick unit test run (fast feedback)
pytest -m unit -q

# Run tests for specific component you're working on
pytest -k "ai_engine" -v

# Run with coverage to see what you're testing
pytest --cov=engines/ai_engine.py --cov-report=term-missing
```

### Pre-Commit Testing

```bash
# Run all unit tests (should be fast)
pytest -m unit

# Run integration tests if you changed core functionality
pytest -m integration

# Full test suite with coverage
pytest --cov=. --cov-report=html
```

### Performance Testing

```bash
# Find slow tests
pytest --durations=10

# Skip slow tests for quick feedback
pytest -m "not slow"

# Run only performance-related tests
pytest -k "performance"
```

## Troubleshooting

### Common Issues and Solutions

#### 1. Import Errors

**Problem**: `ModuleNotFoundError` when running tests
```
ImportError: No module named 'engines'
```

**Solution**: Ensure you're running pytest from the project root directory:
```bash
cd /path/to/project/root
pytest
```

#### 2. Missing Dependencies

**Problem**: Tests fail due to missing packages
```
ImportError: No module named 'numpy'
```

**Solution**: Install test dependencies:
```bash
pip install -r requirements.txt
# or if you have a test-specific requirements file:
pip install -r requirements-test.txt
```

#### 3. Hardware-Dependent Test Failures

**Problem**: Integration tests fail on systems without GPU/hardware
```
DirectML device not found
```

**Solution**: Skip integration tests or hardware-specific tests:
```bash
pytest -m unit  # Run only unit tests
pytest -m "not integration"  # Skip integration tests
```

#### 4. Slow Test Execution

**Problem**: Tests take too long to run

**Solution**: Use filtering and parallel execution:
```bash
pytest -m unit  # Run only fast unit tests
pytest -n auto  # Run tests in parallel (requires pytest-xdist)
pytest --durations=10  # Identify slow tests
```

#### 5. Configuration Issues

**Problem**: Tests fail due to missing config.yaml
```
FileNotFoundError: config.yaml not found
```

**Solution**: Tests should use mock configurations from `conftest.py`. If they don't:
```python
# In your test
def test_something(mock_config):
    # Use mock_config instead of loading real config.yaml
    pass
```

#### 6. Shared State Issues

**Problem**: Tests interfere with each other
```
AssertionError: Expected state to be clean
```

**Solution**: Use fresh fixtures and proper cleanup:
```python
def test_something(mock_shared_state):
    # Each test gets a fresh shared state
    pass
```

#### 7. GUI Tests on Headless Systems

**Problem**: GUI tests fail on servers without display
```
Cannot initialize ImGui context
```

**Solution**: Skip GUI tests on headless systems:
```bash
pytest -m "not gui"  # If you add gui marker
# or run only unit tests:
pytest -m unit
```

### Debugging Test Failures

#### 1. Get Detailed Output
```bash
pytest -v --tb=long  # Verbose output with full tracebacks
pytest -s  # Don't capture output (see print statements)
```

#### 2. Run Single Test with Debugger
```bash
pytest tests/unit/test_ai_engine.py::TestAIEngine::test_process_frame_with_none_frame -v --pdb
```

#### 3. Check Test Coverage
```bash
pytest --cov=engines/ai_engine.py --cov-report=term-missing -v
```

#### 4. Run Only Failed Tests
```bash
pytest --lf  # Last failed
pytest --ff  # Failed first
```

### Performance Optimization

#### 1. Identify Slow Tests
```bash
pytest --durations=10
```

#### 2. Run Tests in Parallel
```bash
pip install pytest-xdist
pytest -n auto  # Use all CPU cores
pytest -n 4     # Use 4 processes
```

#### 3. Skip Slow Tests During Development
```bash
pytest -m "not slow"
```

## Test Configuration

### pytest.ini Configuration

The test suite is configured via `pytest.ini`:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short --strict-markers
markers =
    unit: Unit tests (fast, no external dependencies)
    integration: Integration tests (slower, may require hardware)
    slow: Slow tests (skip with -m "not slow")
```

### Available Fixtures

From `tests/conftest.py`:

- **`mock_config`**: Provides a mock configuration dictionary
- **`mock_shared_state`**: Provides a mock SharedState instance

### Adding New Tests

#### 1. Unit Test Template
```python
import pytest
from engines.ai_engine import AIEngine

@pytest.mark.unit
class TestAIEngine:
    """Test cases for AI Engine functionality."""
    
    def test_initialization(self, mock_config):
        """Test AI engine initializes correctly."""
        engine = AIEngine(mock_config)
        assert engine is not None
    
    def test_process_frame_validation(self, mock_config):
        """Test frame validation in process_frame."""
        engine = AIEngine(mock_config)
        result = engine.process_frame(None)
        assert result is None
```

#### 2. Integration Test Template
```python
import pytest
from engines.coordinator import EngineCoordinator

@pytest.mark.integration
class TestEngineCoordinator:
    """Integration test cases for Engine Coordinator."""
    
    def test_full_startup_shutdown(self, mock_shared_state):
        """Test complete coordinator lifecycle."""
        coordinator = EngineCoordinator(config, mock_shared_state)
        coordinator.start()
        assert coordinator.is_running()
        coordinator.stop()
        assert not coordinator.is_running()
```

## Continuous Integration

### GitHub Actions Example

```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v2
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: 3.8
    - name: Install dependencies
      run: pip install -r requirements.txt
    - name: Run unit tests
      run: pytest -m unit --cov=. --cov-report=xml
    - name: Run integration tests
      run: pytest -m integration
```

## Best Practices

### 1. Test Organization
- Keep unit tests fast (< 1 second each)
- Use appropriate markers (`@pytest.mark.unit`, `@pytest.mark.integration`)
- Group related tests in classes
- Use descriptive test names

### 2. Test Isolation
- Each test should be independent
- Use fixtures for setup/teardown
- Don't rely on test execution order
- Clean up resources after tests

### 3. Mocking
- Mock external dependencies in unit tests
- Use real components in integration tests
- Mock hardware-dependent functionality
- Provide realistic mock data

### 4. Assertions
- Use specific assertions (`assert x == 5` not `assert x`)
- Test both positive and negative cases
- Include edge cases and error conditions
- Verify expected exceptions are raised

### 5. Documentation
- Add docstrings to test classes and methods
- Document complex test scenarios
- Explain why tests exist, not just what they do
- Keep test code clean and readable

## Getting Help

### Resources
- **pytest Documentation**: https://docs.pytest.org/
- **Coverage.py Documentation**: https://coverage.readthedocs.io/
- **Project Issues**: Check the project's issue tracker for known test issues

### Common Commands Reference

```bash
# Basic test runs
pytest                          # All tests
pytest -m unit                  # Unit tests only
pytest -m integration           # Integration tests only
pytest -k "test_ai"            # Tests matching pattern

# Coverage
pytest --cov=.                 # Basic coverage
pytest --cov=. --cov-report=html  # HTML coverage report

# Debugging
pytest -v                      # Verbose output
pytest -s                      # Show print statements
pytest --pdb                   # Drop to debugger on failure
pytest --lf                    # Run last failed tests

# Performance
pytest --durations=10          # Show 10 slowest tests
pytest -n auto                 # Parallel execution (with pytest-xdist)
```

For additional help, consult the project documentation or reach out to the development team.