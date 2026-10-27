"""网关配置加载：model_config.toml + 环境变量；pytest 默认走 mock。"""
import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

from .schemas import GatewayConfig, ModelPolicy, ModelPolicyConfig

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_POLICIES: dict[ModelPolicy, dict[str, Any]] = {
    'FAST': {'provider': 'mock', 'model': 'fast-model-v1', 'temperature': 0.1,
             'max_tokens': 512, 'timeout_seconds': 8.0},
    'BALANCED': {'provider': 'mock', 'model': 'balanced-model-v1', 'temperature': 0.2,
                 'max_tokens': 3584, 'timeout_seconds': 60.0},
    'STRONG': {'provider': 'mock', 'model': 'strong-model-v1', 'temperature': 0.2,
               'max_tokens': 2048, 'timeout_seconds': 30.0},
}

DEFAULT_TASK_MAP: dict[str, ModelPolicy] = {
    'tutor_hint': 'FAST',
    'tutor_explanation': 'BALANCED',
    'chat': 'BALANCED',
    'grading': 'BALANCED',
    'question_generation': 'STRONG',
}


def load_gateway_config(config_path: Path | None = None) -> GatewayConfig:
    root = Path(__file__).resolve().parents[3]
    loaded: dict[str, Any] = {}
    for p in (config_path, root / 'model_config.toml', root / 'model_config.json'):
        if p and Path(p).is_file():
            try:
                text = Path(p).read_text(encoding='utf-8')
                loaded = tomllib.loads(text) if str(p).endswith('.toml') else json.loads(text)
                break
            except Exception:
                continue

    global_base_url = os.environ.get('AI_BASE_URL') or os.environ.get('OPENAI_BASE_URL')
    global_api_key = os.environ.get('AI_API_KEY') or os.environ.get('OPENAI_API_KEY')
    is_pytest = bool(os.environ.get('PYTEST_CURRENT_TEST') or 'pytest' in sys.modules)
    default_provider = 'mock' if (is_pytest and os.environ.get('USE_REAL_AI') != '1') else (
        os.environ.get('AI_PROVIDER', 'openai_compatible' if global_api_key else 'mock'))

    policies: dict[ModelPolicy, ModelPolicyConfig] = {}
    raw_policies = loaded.get('policies', {})
    for pol_name, defaults in DEFAULT_POLICIES.items():
        pol_raw = raw_policies.get(pol_name, {})
        if is_pytest and os.environ.get('USE_REAL_AI') != '1':
            provider, model = 'mock', defaults['model']
        else:
            provider = os.environ.get(f'AI_{pol_name}_PROVIDER') or pol_raw.get('provider') or default_provider
            model = pol_raw.get('model') or os.environ.get(f'AI_{pol_name}_MODEL') or defaults['model']
        policies[pol_name] = ModelPolicyConfig(
            provider=provider, model=model,
            base_url=pol_raw.get('base_url') or global_base_url,
            api_key=pol_raw.get('api_key') or global_api_key,
            temperature=float(pol_raw.get('temperature', defaults['temperature'])),
            max_tokens=int(pol_raw.get('max_tokens', defaults['max_tokens'])),
            timeout_seconds=float(pol_raw.get('timeout_seconds', defaults['timeout_seconds'])),
        )

    task_map: dict[str, ModelPolicy] = dict(DEFAULT_TASK_MAP)
    for task_name, pol in (loaded.get('task_policy_map') or {}).items():
        if pol in ('FAST', 'BALANCED', 'STRONG'):
            task_map[task_name] = pol
    return GatewayConfig(policies=policies, task_policy_map=task_map)
