"""DeepSeek text generation service for explanations and hints."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Dict, List, Optional

import httpx

from ..config import Settings
from ..logger import get_logger
from ..materials import Region

logger = get_logger(__name__)


@dataclass
class GenerationRequest:
    """Request structure for DeepSeek generation."""

    task: str = "generate_explanation"
    style: str = "hint"  # "hint" or "explain"
    material_id: str = ""
    region_id: str = ""
    region_label: str = ""
    region_type: str = ""
    region_text: Optional[str] = None
    script_on_help: Optional[str] = None
    script_on_point: Optional[str] = None
    max_sentences: int = 2
    audience: str = "小学3年生"
    # 座標とコンテキスト強化
    pointer_coords: Optional[Dict[str, float]] = None  # {"x": 0.59, "y": 0.05}
    region_bbox: Optional[Dict[str, float]] = None  # 領域範囲
    pdf_full_text: Optional[str] = None  # PDF全文
    user_speech: Optional[str] = None  # ユーザー発話テキスト
    # 参照先情報
    reference_region: Optional[Region] = None  # 参照先レジオン


@dataclass
class GenerationResponse:
    """Response structure from DeepSeek."""

    text: str
    request_time_ms: int
    rejected: bool = False
    rejection_reason: Optional[str] = None


class DeepSeekService:
    """DeepSeek text generation service for educational content."""

    def __init__(self, settings: Settings):
        self._base_url = settings.ollama_base_url
        self._model = settings.ollama_model
        self._timeout = 15.0
        self._total_requests = 0
        self._total_time_ms = 0

    async def generate_explanation(
        self,
        region: Region,
        material_id: str,
        style: str = "hint",
        pointer_coords: Optional[Dict[str, float]] = None,
        pdf_full_text: Optional[str] = None,
        user_speech: Optional[str] = None,
        reference_region: Optional[Region] = None,
    ) -> GenerationResponse:
        """
        Generate a short explanation or hint for a region.
        Returns 1-2 sentences suitable for elementary students.
        
        Args:
            region: 指定された領域情報
            material_id: 教材ID
            style: 生成スタイル ("hint" or "explain")
            pointer_coords: ポインター座標 {"x": 0.5, "y": 0.3}
            pdf_full_text: PDF全文テキスト（コンテキスト強化用）
            user_speech: ユーザー音声認識テキスト
            reference_region: 参照先レジオン（参考文献）
        """
        import time

        start_time = time.time()
        self._total_requests += 1

        request = GenerationRequest(
            style=style,
            material_id=material_id,
            region_id=region.id,
            region_label=region.label or region.id,
            region_type=region.type,
            region_text=region.extracted_text or getattr(region, "text", None),
            script_on_help=self._get_script_text(region, "on_help"),
            script_on_point=self._get_script_text(region, "on_point"),
            pointer_coords=pointer_coords,
            region_bbox=region.bbox.dict() if region.bbox else None,
            pdf_full_text=pdf_full_text,
            user_speech=user_speech,
            reference_region=reference_region,
        )

        try:
            text = await self._call_deepseek(request)
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._total_time_ms += elapsed_ms

            return GenerationResponse(
                text=text,
                request_time_ms=elapsed_ms,
                rejected=False,
            )
        except Exception as e:
            logger.error("DeepSeek generation failed: %s", e, exc_info=True)
            elapsed_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)
            # Return more informative error for debugging
            if "Connection refused" in error_msg or "cannot connect" in error_msg.lower():
                debug_text = f"[DeepSeek接続エラー: {self._base_url}に接続できません]"
            elif "timeout" in error_msg.lower():
                debug_text = f"[DeepSeek タイムアウト: {self._base_url}からの応答がありません]"
            else:
                debug_text = f"[DeepSeekエラー: {error_msg[:50]}...]"
            
            return GenerationResponse(
                text=debug_text,
                request_time_ms=elapsed_ms,
                rejected=True,
                rejection_reason=error_msg,
            )

    async def _call_deepseek(self, request: GenerationRequest) -> str:
        """Call DeepSeek API and return generated text."""
        system_prompt = self._build_system_prompt(request)
        user_message = self._build_user_message(request)

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.7,
            "max_tokens": 150,
        }

        logger.debug("Calling DeepSeek at %s with model %s", self._base_url, self._model)
        logger.debug("System prompt length: %d chars", len(system_prompt))
        logger.debug("User message length: %d chars", len(user_message))

        import os
        # Development mode: if TEACHARM_DEV_MODE is set, return mock response
        if os.getenv("TEACHARM_DEV_MODE"):
            logger.info("Using mock DeepSeek response (DEV_MODE)")
            label = request.region_label or request.region_id
            return f"{label}を見てみよう。ここをよく読んで、大事な言葉を探してみてください。"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            cleaned = self._sanitize_output(content)
            return cleaned.strip()

    def _build_system_prompt(self, request: GenerationRequest) -> str:
        """Build system prompt for DeepSeek."""
        base_prompt = f"""あなたは小学生向けの学習支援AIです。

役割:
- 教材内容について、相手にわかりやすく説明する
- 1〜2文で簡潔に答える
- 次に何を見ればいいか、具体的なヒントを含める

制約:
- 教材の範囲内のみ回答する
- 教材外の質問は丁寧に断り、学習に戻す
- 個人情報は聞かない、答えない
- 答えを直接言わず、考え方や手がかりを示す
- 思考過程や内部判断は出力せず、自然な回答のみを返す
- 最初の一文で対象を明示し、「{request.region_label}を見てみよう。」のように案内する
- 相手の年齢や属性を決めつける呼びかけは禁止
- 呼びかけは中立にする（例: 「いっしょに見てみよう」「ここを確認しよう」「順番に見ていこう」）
- 口調はやさしく
- 教材内の根拠が乏しい場合は、確認の質問を1つだけ返してよい

スタイル: {request.style}
- hint: ヒントや手がかりを示す（答えは言わない）
- explain: 言い換えや別の表現で説明する"""
        
        # PDF全文がある場合はコンテキストとして追加
        if request.pdf_full_text:
            context_section = f"""

【教材全文】
以下は教材PDF全体の内容です。回答の際の背景情報として参照してください。

{request.pdf_full_text[:3000]}"""  # 最大3000文字まで
            base_prompt += context_section
        
        return base_prompt

    @staticmethod
    def _normalize_ranges(text: str) -> str:
        """Normalize range expressions like 'ア～ウ' to 'アからウ'."""
        return re.sub(
            r"([A-Za-z0-9０-９ぁ-んァ-ン一-龥]+)\s*[〜～~]\s*([A-Za-z0-9０-９ぁ-んァ-ン一-龥]+)",
            r"\1から\2",
            text,
        )

    def _build_user_message(self, request: GenerationRequest) -> str:
        """Build user message for DeepSeek."""
        parts = [
            f"教材ID: {request.material_id}",
            f"対象: {request.region_label} ({request.region_type})",
        ]
        
        # ポインター座標情報
        if request.pointer_coords:
            x = request.pointer_coords.get("x", 0)
            y = request.pointer_coords.get("y", 0)
            parts.append(f"ポインター座標: (x={x:.3f}, y={y:.3f})")
        
        # 領域範囲情報（type情報を強調）
        if request.region_bbox:
            bbox = request.region_bbox
            parts.append(
                f"領域範囲: x={bbox['x']:.3f}〜{bbox['x']+bbox['w']:.3f}, "
                f"y={bbox['y']:.3f}〜{bbox['y']+bbox['h']:.3f}"
            )
            parts.append(f"領域タイプ: {request.region_type}")

        # PDFから抽出したテキスト
        if request.region_text:
            parts.append(f"\n【この領域の内容】\n{request.region_text}")

        # 既存スクリプト（参考情報）
        if request.script_on_point:
            parts.append(f"\n【参考: 既存の説明】\n{request.script_on_point}")
        
        # 参照先情報（オプション。参考になる場合は活用してよい）
        if request.reference_region:
            ref = request.reference_region
            ref_label = ref.label or ref.id
            ref_text = ref.extracted_text or ""
            # テキストは最大200-400文字に短縮
            if ref_text:
                ref_text = ref_text[:300]
            parts.append("\n【参考: 参照するとよい場所（オプション）】")
            parts.append(f"タイトル: {ref_label}")
            parts.append(f"タイプ: {ref.type}")
            if ref_text:
                parts.append(f"内容: {ref_text}")
            parts.append("※ この情報は補助的です。見つからなくても、教材から説明してください。")
        
        # ユーザー発話
        if request.user_speech:
            parts.append(f"\n【ユーザーの質問】\n{request.user_speech}")
            parts.append("\n上記の質問に対して、教材内容を踏まえて1〜2文で答えてください。")
        elif request.style == "hint":
            parts.append(
                "\nこの問題について、考え方のヒントを1〜2文で教えてください。"
            )
        else:
            parts.append("\nこの内容を別の言い方で説明してください。")

        return "\n".join(parts)

    @staticmethod
    def _get_script_text(region: Region, event: str) -> Optional[str]:
        """Extract script text from region if it exists."""
        script = getattr(region, "script", None)
        if not script:
            return None
        event_commands = script.get(event, [])
        if not event_commands:
            return None
        # Find SAY command
        for cmd in event_commands:
            if isinstance(cmd, dict) and "SAY" in cmd:
                return cmd["SAY"]
        return None

    async def select_region_id(
        self,
        material_id: str,
        user_speech: str,
        candidates: List[Dict[str, str]],
    ) -> Optional[str]:
        """Select the most relevant region id from candidates."""
        if not user_speech or not candidates:
            return None

        system_prompt = (
            "You are a classifier. Choose the most relevant region id "
            "for the user's request. Return JSON only."
        )
        candidate_lines = []
        for candidate in candidates:
            text = candidate.get("text", "")
            candidate_lines.append(
                f"- id: {candidate['id']}, label: {candidate['label']}, "
                f"type: {candidate['type']}, text: {text}"
            )
        user_message = (
            f"material_id: {material_id}\n"
            f"user: {user_speech}\n"
            "candidates:\n"
            + "\n".join(candidate_lines)
            + "\n\n"
            "Return JSON only in this format:\n"
            '{"region_id": "..." } or {"region_id": null}'
        )

        try:
            content = await self._call_deepseek_raw(
                system_prompt,
                user_message,
                temperature=0.0,
                max_tokens=80,
            )
        except Exception as exc:
            logger.error("DeepSeek region selection failed: %s", exc)
            return None

        return self._parse_region_id(content, candidates)

    async def select_paragraph_id(
        self,
        material_id: str,
        user_speech: str,
        problem_label: str,
        problem_text: str,
        candidates: List[Dict[str, str]],
    ) -> Optional[str]:
        """Select the most relevant paragraph id for a given problem."""
        if not user_speech or not candidates:
            return None

        system_prompt = (
            "You are a classifier. Choose the most relevant paragraph id "
            "to read for the given problem. Return JSON only."
        )
        candidate_lines = []
        for candidate in candidates:
            text = candidate.get("text", "")
            candidate_lines.append(
                f"- id: {candidate['id']}, label: {candidate['label']}, "
                f"type: {candidate['type']}, text: {text}"
            )
        user_message = (
            f"material_id: {material_id}\n"
            f"problem_label: {problem_label}\n"
            f"problem_text: {problem_text}\n"
            f"user: {user_speech}\n"
            "paragraph_candidates:\n"
            + "\n".join(candidate_lines)
            + "\n\n"
            "Return JSON only in this format:\n"
            '{"region_id": "..." } or {"region_id": null}'
        )

        try:
            content = await self._call_deepseek_raw(
                system_prompt,
                user_message,
                temperature=0.0,
                max_tokens=80,
            )
        except Exception as exc:
            logger.error("DeepSeek paragraph selection failed: %s", exc)
            return None

        return self._parse_region_id(content, candidates)

    async def _call_deepseek_raw(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return self._sanitize_output(content)

    @staticmethod
    def _parse_region_id(
        content: str, candidates: List[Dict[str, str]]
    ) -> Optional[str]:
        cleaned = content.strip()
        candidate_ids = {c["id"] for c in candidates}
        label_to_id = {c["label"]: c["id"] for c in candidates}

        try:
            data = json.loads(cleaned)
            region_id = data.get("region_id")
            if region_id in candidate_ids:
                return region_id
            if isinstance(region_id, str) and region_id in label_to_id:
                return label_to_id[region_id]
        except json.JSONDecodeError:
            pass

        for candidate_id in candidate_ids:
            if candidate_id in cleaned:
                return candidate_id
        for label, region_id in label_to_id.items():
            if label in cleaned:
                return region_id
        return None

    @staticmethod
    def _sanitize_output(content: str) -> str:
        """Strip tags and normalize range/symbol expressions."""
        cleaned = re.sub(r"<[^>]+>", "", content)
        cleaned = DeepSeekService._normalize_ranges(cleaned)
        cleaned = DeepSeekService._normalize_symbols(cleaned)
        return cleaned.strip()

    @staticmethod
    def _normalize_symbols(text: str) -> str:
        """Normalize common symbols to their spoken Japanese forms."""
        replacements = {
            "〇": "まる",
            "○": "まる",
            "△": "さんかく",
            "▲": "さんかく",
            "□": "しかく",
            "■": "しかく",
            "×": "ばつ",
            "✕": "ばつ",
            "✖": "ばつ",
        }
        return "".join(replacements.get(ch, ch) for ch in text)

    def get_stats(self) -> Dict[str, Any]:
        """Return statistics for monitoring."""
        avg_time = (
            self._total_time_ms // self._total_requests
            if self._total_requests > 0
            else 0
        )
        return {
            "total_requests": self._total_requests,
            "total_time_ms": self._total_time_ms,
            "avg_time_ms": avg_time,
        }
