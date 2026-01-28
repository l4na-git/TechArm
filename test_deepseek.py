#!/usr/bin/env python
"""Test DeepSeek service to diagnose connection issues."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from teacharm.config import Settings
from teacharm.services.deepseek import DeepSeekService
from teacharm.materials import Region


async def main():
    settings = Settings()
    print(f"DeepSeek URL: {settings.ollama_base_url}")
    print(f"DeepSeek Model: {settings.ollama_model}")
    
    service = DeepSeekService(settings)
    
    # Create a test region
    region = Region(
        id="test",
        label="Test Region",
        type="text",
        extracted_text="This is test content",
    )
    
    print("\nCalling DeepSeekService.generate_explanation()...")
    response = await service.generate_explanation(
        region=region,
        material_id="test",
        style="explain",
        user_speech="これについて教えて",
    )
    
    print(f"Response text: {response.text}")
    print(f"Rejected: {response.rejected}")
    if response.rejection_reason:
        print(f"Rejection reason: {response.rejection_reason}")


if __name__ == "__main__":
    asyncio.run(main())
