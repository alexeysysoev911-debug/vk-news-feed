"""
Compliance-фильтр для РФ.

Два механизма, конфиг — в /data/compliance.json (редактируется без пересборки):

  block   — список терминов; если встречается в заголовке/тексте, пост НЕ публикуется
  mark    — словарь {термин: пометка}; если встречается, рядом дописывается пометка
            (например, "(внесён в реестр иноагентов в РФ)")

Сопоставление регистронезависимое, по границам слов (чтобы "ЯБ" не ловило "ЯБлоко").

ВАЖНО: это снижение риска, а не юридическая гарантия. Реестры Минюста/РКН
меняются ежедневно — список нужно пополнять вручную. Главный щит — жёсткий
LLM safety_check, отсекающий политику и экстремизм на уровне смысла.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from ..core.logging import get_logger

log = get_logger("compliance")

CONFIG_PATH = Path("/data/compliance.json")

# Стартовый конфиг, если файла ещё нет. Пополняй block/mark по мере новостей.
_DEFAULT_CONFIG = {
    "block": [
        # Явная запрещёнка/экстремизм — упоминать нельзя.
        # Примеры-плейсхолдеры, замени/дополни актуальным списком Минюста:
        "АУЕ",
        "Колумбайн",
        "М.К.У.",
    ],
    "mark": {
        # термин : пометка, которая будет дописана после него
        # Примеры — приведи в соответствие с актуальным реестром:
        # "ИмяФамилия": "(внесён в реестр иноагентов в РФ)",
    },
}


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text("utf-8"))
            cfg.setdefault("block", [])
            cfg.setdefault("mark", {})
            return cfg
        except Exception as e:  # noqa: BLE001
            log.error("compliance_config_corrupt", error=str(e))
            return {"block": [], "mark": {}}
    # первого запуска — создаём дефолт, чтобы было что редактировать
    try:
        CONFIG_PATH.write_text(
            json.dumps(_DEFAULT_CONFIG, ensure_ascii=False, indent=2), "utf-8"
        )
        log.info("compliance_config_created", path=str(CONFIG_PATH))
    except OSError as e:
        log.warning("compliance_config_write_failed", error=str(e))
    return json.loads(json.dumps(_DEFAULT_CONFIG))


def _word_re(term: str) -> re.Pattern:
    # границы по не-буквенно-цифровым; работает и для кириллицы
    return re.compile(
        rf"(?<![0-9A-Za-zА-Яа-яЁё]){re.escape(term)}(?![0-9A-Za-zА-Яа-яЁё])",
        re.IGNORECASE,
    )


def check_blocklist(title: str, text: str) -> Optional[str]:
    """Вернёт сработавший термин, если пост нужно ЗАБЛОКИРОВАТЬ, иначе None."""
    cfg = _load_config()
    haystack = f"{title}\n{text}"
    for term in cfg.get("block", []):
        term = (term or "").strip()
        if term and _word_re(term).search(haystack):
            return term
    return None


def apply_marks(title: str, text: str) -> tuple[str, str, list[str]]:
    """
    Дописывает пометки к маркируемым терминам.
    Вернёт (title, text, applied) — applied: какие пометки проставлены.
    Пометка ставится один раз на первое вхождение в каждом поле.
    """
    cfg = _load_config()
    applied: list[str] = []

    def mark_field(s: str) -> str:
        for term, note in cfg.get("mark", {}).items():
            term = (term or "").strip()
            note = (note or "").strip()
            if not term or not note:
                continue
            pat = _word_re(term)
            m = pat.search(s)
            if m and note not in s:  # не дублируем, если пометка уже есть
                s = s[: m.end()] + f" {note}" + s[m.end():]
                applied.append(term)
        return s

    return mark_field(title), mark_field(text), applied
