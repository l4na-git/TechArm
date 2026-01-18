#!/usr/bin/env python3
"""Test script to verify TeachArm system integrity."""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

print("=" * 60)
print("TeachArm System Verification Test")
print("=" * 60)

# Test 1: Import core modules
print("\n[Test 1] Importing core modules...")
try:
    from teacharm.config import Settings, load_settings
    from teacharm.logger import get_logger
    from teacharm.materials import load_materials
    from teacharm.scripts import load_scripts
    print("✓ Core modules imported successfully")
except Exception as e:
    print(f"✗ Failed to import core modules: {e}")
    sys.exit(1)

# Test 2: Import service modules
print("\n[Test 2] Importing service modules...")
try:
    from teacharm.services.router import RouterService
    from teacharm.services.deepseek import DeepSeekService
    from teacharm.services.dialogue import DialogueService
    from teacharm.services.tts import VoiceVoxService
    from teacharm.services.arm import ArmService
    print("✓ Service modules imported successfully")
except Exception as e:
    print(f"✗ Failed to import service modules: {e}")
    sys.exit(1)

# Test 3: Load settings
print("\n[Test 3] Loading settings...")
try:
    settings = load_settings()
    print("✓ Settings loaded successfully")
    print(f"  - Materials dir: {settings.materials_dir}")
    print(f"  - Scripts dir: {settings.scripts_dir}")
    print(f"  - Config dir: {settings.config_dir}")
    print(f"  - DeepSeek URL: {settings.deepseek_base_url}")
    print(f"  - DeepSeek Model: {settings.deepseek_model}")
except Exception as e:
    print(f"✗ Failed to load settings: {e}")
    sys.exit(1)

# Test 4: Load materials
print("\n[Test 4] Loading materials...")
try:
    materials = load_materials(settings.materials_dir)
    print(f"✓ Loaded {len(materials)} materials")
    for mat_id, mat in materials.items():
        print(f"  - {mat_id}: {len(mat.regions)} regions")
except Exception as e:
    print(f"✗ Failed to load materials: {e}")
    sys.exit(1)

# Test 5: Load scripts
print("\n[Test 5] Loading scripts...")
try:
    scripts_path = settings.scripts_dir / "common.yaml"
    scripts = load_scripts(scripts_path)
    print("✓ Scripts loaded successfully")
    print(f"  - Role: {scripts.role.name}")
    print(f"  - Commands: {len(scripts.commands)}")
    print(f"  - Greeting reply: {scripts.intent.greeting_reply[:50]}...")
except Exception as e:
    print(f"✗ Failed to load scripts: {e}")
    sys.exit(1)

# Test 6: Initialize services
print("\n[Test 6] Initializing services...")
try:
    router = RouterService(settings)
    deepseek = DeepSeekService(settings)
    dialogue = DialogueService(settings, scripts, router, deepseek)
    print("✓ Services initialized successfully")
    print(f"  - Router stats: {router.get_stats()}")
    print(f"  - DeepSeek stats: {deepseek.get_stats()}")
except Exception as e:
    print(f"✗ Failed to initialize services: {e}")
    sys.exit(1)

# Test 7: Create FastAPI app
print("\n[Test 7] Creating FastAPI application...")
try:
    from teacharm.server import create_app
    app = create_app(settings)
    print("✓ FastAPI application created successfully")
    routes = [route.path for route in app.routes if hasattr(route, 'path')]
    print(f"  - Total routes: {len(routes)}")
    print("  - Key endpoints:")
    for route in ["/health", "/api/stats", "/api/materials", "/api/dialogue"]:
        if route in routes:
            print(f"    ✓ {route}")
except Exception as e:
    print(f"✗ Failed to create FastAPI app: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("✓ All tests passed! TeachArm system is ready.")
print("=" * 60)
print("\nTo start the server, run:")
print("  python -m teacharm.main")
print("  or")
print("  uvicorn teacharm.main:app --host 0.0.0.0 --port 8000")
